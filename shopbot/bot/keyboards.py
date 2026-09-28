"""Клавиатуры. Все callback_data собираются и разбираются здесь."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .tariffs import TARIFFS, TRIAL

BTN_TARIFFS = "Тарифы"
BTN_MY = "Моя подписка"
BTN_HELP = "Помощь"

CB_BUY = "buy"
CB_PAID = "paid"
CB_CANCEL = "cancel"
CB_ADMIN_OK = "adm_ok"
CB_ADMIN_NO = "adm_no"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_TARIFFS), KeyboardButton(text=BTN_MY)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
    )


def tariff_list(offer_trial: bool) -> InlineKeyboardMarkup:
    rows = []
    if offer_trial:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🎁 {TRIAL.title} — бесплатно, {TRIAL.days} дн.",
                    callback_data=f"{CB_BUY}:{TRIAL.code}",
                )
            ]
        )
    for tariff in TARIFFS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{tariff.title} — {tariff.price_rub} ₽",
                    callback_data=f"{CB_BUY}:{tariff.code}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_actions(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Я оплатил", callback_data=f"{CB_PAID}:{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отменить заказ", callback_data=f"{CB_CANCEL}:{order_id}"
                )
            ],
        ]
    )


def admin_actions(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить", callback_data=f"{CB_ADMIN_OK}:{order_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data=f"{CB_ADMIN_NO}:{order_id}"
                ),
            ]
        ]
    )


def parse_callback(data: str) -> tuple[str, str]:
    action, _, payload = data.partition(":")
    return action, payload
