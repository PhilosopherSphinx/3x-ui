"""Покупательская часть: тарифы, заказ, выдача, статус."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..db import STATUS_AWAITING, STATUS_EXPIRED, STATUS_PENDING, Database
from ..panel import PanelError
from ..service import Provisioner
from ..tariffs import TRIAL, by_code

log = logging.getLogger(__name__)
router = Router(name="user")


def _username(message_from) -> str:
    return message_from.username or ""


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database) -> None:
    await db.upsert_user(message.from_user.id, _username(message.from_user))
    await message.answer(texts.START, reply_markup=kb.main_menu())


@router.message(Command("help"))
@router.message(F.text == kb.BTN_HELP)
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP)


@router.message(Command("tariffs"))
@router.message(F.text == kb.BTN_TARIFFS)
async def show_tariffs(message: Message, db: Database) -> None:
    await db.upsert_user(message.from_user.id, _username(message.from_user))
    offer_trial = not await db.trial_used(message.from_user.id)
    await message.answer(
        texts.CHOOSE_TARIFF, reply_markup=kb.tariff_list(offer_trial)
    )


@router.message(Command("my"))
@router.message(F.text == kb.BTN_MY)
async def show_subscription(message: Message, provisioner: Provisioner) -> None:
    try:
        info = await provisioner.status(message.from_user.id)
    except PanelError:
        await message.answer("Панель сейчас не отвечает, попробуйте через минуту.")
        return
    if info is None:
        await message.answer(texts.NO_SUBSCRIPTION)
        return
    await message.answer(texts.subscription_status(info))


@router.callback_query(F.data.startswith(f"{kb.CB_BUY}:"))
async def on_buy(
    callback: CallbackQuery,
    db: Database,
    config: Config,
    provisioner: Provisioner,
) -> None:
    _, code = kb.parse_callback(callback.data)
    tariff = by_code(code)
    if tariff is None:
        await callback.answer("Тариф больше не доступен", show_alert=True)
        return

    user = callback.from_user
    await db.upsert_user(user.id, _username(user))

    if tariff.code == TRIAL.code:
        await _grant_trial(callback, db, provisioner)
        return

    order = await db.create_order(
        user.id, _username(user), tariff.code, tariff.price_kopecks
    )
    await callback.message.answer(
        texts.payment_request(
            order, tariff, config.payment_details, config.order_ttl_minutes
        ),
        reply_markup=kb.payment_actions(order.id),
    )
    await callback.answer()


async def _grant_trial(
    callback: CallbackQuery, db: Database, provisioner: Provisioner
) -> None:
    """Отметка ставится до выдачи — двойное нажатие не даст второй пробный."""
    if not await db.mark_trial_used(callback.from_user.id):
        await callback.answer(texts.TRIAL_ALREADY_USED, show_alert=True)
        return
    try:
        link = await provisioner.grant(
            callback.from_user.id, TRIAL, comment="trial"
        )
    except PanelError:
        await db.clear_trial(callback.from_user.id)
        log.exception("пробный для %s не выдан", callback.from_user.id)
        await callback.answer(
            "Не получилось выдать доступ, попробуйте позже", show_alert=True
        )
        return
    await callback.message.answer(texts.trial_granted(link, TRIAL))
    await callback.answer()


@router.callback_query(F.data.startswith(f"{kb.CB_PAID}:"))
async def on_paid(callback: CallbackQuery, db: Database, config: Config, bot: Bot) -> None:
    _, raw_id = kb.parse_callback(callback.data)
    order = await db.get_order(int(raw_id)) if raw_id.isdigit() else None
    if order is None or order.tg_id != callback.from_user.id:
        await callback.answer(texts.ORDER_GONE, show_alert=True)
        return
    if order.status == STATUS_PENDING:
        await callback.answer(texts.ALREADY_PENDING, show_alert=True)
        return
    if not await db.transition(order.id, STATUS_AWAITING, STATUS_PENDING):
        await callback.answer(texts.ORDER_GONE, show_alert=True)
        return

    tariff = by_code(order.tariff_code)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(texts.payment_sent())
    await callback.answer()

    if tariff is not None:
        await _notify_admins(bot, config, order, tariff)


async def _notify_admins(bot: Bot, config: Config, order, tariff) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                texts.admin_new_order(order, tariff),
                reply_markup=kb.admin_actions(order.id),
            )
        except Exception:
            log.exception("не доставлено уведомление админу %s", admin_id)


@router.callback_query(F.data.startswith(f"{kb.CB_CANCEL}:"))
async def on_cancel(callback: CallbackQuery, db: Database) -> None:
    _, raw_id = kb.parse_callback(callback.data)
    order = await db.get_order(int(raw_id)) if raw_id.isdigit() else None
    if order is None or order.tg_id != callback.from_user.id:
        await callback.answer(texts.ORDER_GONE, show_alert=True)
        return
    if await db.transition(order.id, STATUS_AWAITING, STATUS_EXPIRED):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Заказ отменён")
    else:
        await callback.answer(texts.ORDER_GONE, show_alert=True)
