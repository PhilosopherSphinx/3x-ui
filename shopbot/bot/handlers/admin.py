"""Админская часть: подтверждение и отклонение заказов."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..db import STATUS_PAID, STATUS_PENDING, STATUS_REJECTED, Database
from ..panel import PanelError
from ..service import Provisioner
from ..tariffs import by_code

log = logging.getLogger(__name__)
router = Router(name="admin")


def setup(admin_ids: frozenset[int]) -> Router:
    """Вешает проверку прав на весь роутер, а не на каждый обработчик."""
    router.message.filter(F.from_user.id.in_(admin_ids))
    router.callback_query.filter(F.from_user.id.in_(admin_ids))
    return router


def _admin_name(user) -> str:
    return f"@{user.username}" if user.username else str(user.id)


@router.message(Command("orders"))
async def list_orders(message: Message, db: Database) -> None:
    orders = await db.orders_by_status(STATUS_PENDING)
    if not orders:
        await message.answer("Заказов на проверке нет.")
        return
    for order in orders:
        tariff = by_code(order.tariff_code)
        if tariff is None:
            continue
        await message.answer(
            texts.admin_new_order(order, tariff),
            reply_markup=kb.admin_actions(order.id),
        )


@router.callback_query(F.data.startswith(f"{kb.CB_ADMIN_OK}:"))
async def approve(
    callback: CallbackQuery, db: Database, provisioner: Provisioner, bot: Bot
) -> None:
    _, raw_id = kb.parse_callback(callback.data)
    order = await db.get_order(int(raw_id)) if raw_id.isdigit() else None
    if order is None:
        await callback.answer(texts.ORDER_GONE, show_alert=True)
        return
    tariff = by_code(order.tariff_code)
    if tariff is None:
        await callback.answer("Тариф заказа больше не существует", show_alert=True)
        return

    admin_id = callback.from_user.id
    if not await db.transition(order.id, STATUS_PENDING, STATUS_PAID, admin_id):
        await callback.answer("Заказ уже обработан", show_alert=True)
        return

    try:
        link = await provisioner.grant(
            order.tg_id, tariff, comment=f"order#{order.id}"
        )
    except PanelError as exc:
        # Возврат в очередь: деньги получены, кнопка должна остаться рабочей.
        await db.transition(order.id, STATUS_PAID, STATUS_PENDING, admin_id)
        log.exception("выдача по заказу %s не прошла", order.id)
        await callback.answer(f"Панель отказала: {exc}", show_alert=True)
        await bot.send_message(order.tg_id, texts.PANEL_FAILED)
        return

    await bot.send_message(order.tg_id, texts.access_granted(link, tariff))
    await callback.message.edit_text(
        texts.admin_resolved(order, tariff, True, _admin_name(callback.from_user))
    )
    await callback.answer("Выдано")


@router.callback_query(F.data.startswith(f"{kb.CB_ADMIN_NO}:"))
async def reject(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    _, raw_id = kb.parse_callback(callback.data)
    order = await db.get_order(int(raw_id)) if raw_id.isdigit() else None
    if order is None:
        await callback.answer(texts.ORDER_GONE, show_alert=True)
        return
    tariff = by_code(order.tariff_code)
    if not await db.transition(
        order.id, STATUS_PENDING, STATUS_REJECTED, callback.from_user.id
    ):
        await callback.answer("Заказ уже обработан", show_alert=True)
        return

    await bot.send_message(order.tg_id, texts.order_rejected(order.id))
    if tariff is not None:
        await callback.message.edit_text(
            texts.admin_resolved(
                order, tariff, False, _admin_name(callback.from_user)
            )
        )
    await callback.answer("Отклонён")
