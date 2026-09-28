"""Все тексты в одном месте — чтобы править формулировки, не трогая логику."""

from __future__ import annotations

import datetime as dt

from .db import Order
from .tariffs import Tariff

START = (
    "Привет. Здесь оформляется доступ.\n\n"
    "«Тарифы» — выбрать срок и оплатить.\n"
    "«Моя подписка» — ссылка, остаток трафика и до какого числа всё работает."
)

HELP = (
    "<b>Как это работает</b>\n\n"
    "1. Выбираете тариф — бот выдаёт сумму и реквизиты.\n"
    "2. Переводите <b>ровно указанную сумму, вместе с копейками</b>. "
    "Копейки у каждого заказа свои — по ним платёж находят.\n"
    "3. Нажимаете «Я оплатил».\n"
    "4. Платёж сверяют вручную, обычно в течение часа. "
    "Как только подтвердят — бот пришлёт ссылку подписки.\n\n"
    "Ссылка постоянная: при продлении она не меняется, "
    "заново настраивать приложение не нужно.\n\n"
    "Проблемы с подключением — пишите, разберёмся."
)

CHOOSE_TARIFF = "Выберите тариф:"
NO_SUBSCRIPTION = "Активной подписки нет. Загляните в «Тарифы»."
TRIAL_ALREADY_USED = "Пробный период уже был использован на этом аккаунте."
ORDER_GONE = "Заказ не найден или уже обработан."
ALREADY_PENDING = "Этот заказ уже отправлен на проверку. Ожидайте подтверждения."
PANEL_FAILED = (
    "Не получилось выдать доступ — панель не ответила. "
    "Платёж зафиксирован, с вами свяжутся. Ничего повторно платить не нужно."
)


def payment_request(order: Order, tariff: Tariff, details: str, ttl_minutes: int) -> str:
    return (
        f"<b>Заказ №{order.id}</b> — {tariff.title}\n\n"
        f"Сумма к переводу: <b>{order.amount_display} ₽</b>\n"
        f"Реквизиты: {details}\n\n"
        f"⚠️ Переведите сумму <b>ровно до копейки</b>. "
        f"Копейки — это номер вашего заказа, без них платёж не найдётся.\n\n"
        f"После перевода нажмите «Я оплатил». "
        f"Заказ действует {ttl_minutes} мин."
    )


def payment_sent() -> str:
    return (
        "Принято. Платёж проверят вручную — обычно в течение часа.\n"
        "Как только подтвердят, сюда придёт ссылка подписки."
    )


def access_granted(link: str, tariff: Tariff) -> str:
    return (
        f"Оплата подтверждена. Тариф: <b>{tariff.title}</b>, {tariff.days} дн.\n\n"
        f"Ваша ссылка подписки:\n<code>{link}</code>\n\n"
        "Скопируйте её и добавьте в приложение. "
        "Ссылка постоянная — при продлении останется прежней."
    )


def trial_granted(link: str, tariff: Tariff) -> str:
    return (
        f"Пробный доступ на {tariff.days} дн. открыт.\n\n"
        f"Ваша ссылка подписки:\n<code>{link}</code>\n\n"
        "Скопируйте её и добавьте в приложение."
    )


def order_rejected(order_id: int) -> str:
    return (
        f"Заказ №{order_id} отклонён — платёж не нашёлся.\n"
        "Если вы точно переводили, напишите и приложите чек."
    )


def subscription_status(info: dict) -> str:
    lines = ["<b>Ваша подписка</b>", ""]
    if not info["enable"]:
        lines.append("Статус: <b>отключена</b>")
    elif info["expiry_ms"] > 0:
        until = dt.datetime.fromtimestamp(info["expiry_ms"] / 1000)
        left = until - dt.datetime.now()
        if left.total_seconds() <= 0:
            lines.append("Статус: <b>срок истёк</b>")
        else:
            lines.append(
                f"Действует до: <b>{until:%d.%m.%Y}</b> (осталось {left.days} дн.)"
            )
    else:
        lines.append("Срок: <b>без ограничения</b>")

    if info["limit_gb"]:
        lines.append(
            f"Трафик: {info['used_gb']:.1f} из {info['limit_gb']:.0f} ГБ"
        )
    else:
        lines.append(f"Трафик: {info['used_gb']:.1f} ГБ (без лимита)")

    lines += ["", "Ссылка подписки:", f"<code>{info['link']}</code>"]
    return "\n".join(lines)


def admin_new_order(order: Order, tariff: Tariff) -> str:
    who = f"@{order.username}" if order.username else "без username"
    return (
        f"<b>Заказ №{order.id}</b>\n"
        f"Покупатель: {who} (<code>{order.tg_id}</code>)\n"
        f"Тариф: {tariff.title}, {tariff.days} дн.\n"
        f"Ждём перевод: <b>{order.amount_display} ₽</b>\n\n"
        f"Проверьте поступление и подтвердите."
    )


def admin_resolved(order: Order, tariff: Tariff, approved: bool, admin: str) -> str:
    verdict = "✅ подтверждён" if approved else "❌ отклонён"
    who = f"@{order.username}" if order.username else "без username"
    return (
        f"<b>Заказ №{order.id}</b> {verdict}\n"
        f"{who} · {tariff.title} · {order.amount_display} ₽\n"
        f"Решение: {admin}"
    )
