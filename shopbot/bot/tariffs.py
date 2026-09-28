"""Тарифы. Единственный файл, который правишь при смене цен.

inbound_ids — это и есть содержимое тарифа: какие входящие привязываются
клиенту. Посмотреть номера: в панели «Входящие», столбец ID.
"""

from __future__ import annotations

from dataclasses import dataclass

# TODO: подставить реальные ID входящих из панели.
# Набор, который сейчас получает тестовая подписка:
# Основной, Запасной, Мобильный, WhiteList-Selectel, WhiteList_PQC.
STANDARD_INBOUNDS: tuple[int, ...] = (1, 2, 3, 4, 5)


@dataclass(frozen=True)
class Tariff:
    code: str
    title: str
    days: int
    price_rub: int
    total_gb: int  # 0 — без лимита трафика
    inbound_ids: tuple[int, ...] = STANDARD_INBOUNDS

    @property
    def price_kopecks(self) -> int:
        return self.price_rub * 100

    def describe(self) -> str:
        limit = "без лимита трафика" if self.total_gb == 0 else f"{self.total_gb} ГБ"
        return f"{self.title} — {self.price_rub} ₽ · {self.days} дн. · {limit}"


TARIFFS: tuple[Tariff, ...] = (
    Tariff(code="m1", title="1 месяц", days=30, price_rub=200, total_gb=0),
    Tariff(code="m3", title="3 месяца", days=90, price_rub=500, total_gb=0),
    Tariff(code="m12", title="1 год", days=365, price_rub=1800, total_gb=0),
)

# Пробный период. Выдаётся один раз на Telegram-аккаунт, без оплаты.
TRIAL = Tariff(code="trial", title="Пробный период", days=5, price_rub=0, total_gb=0)


def by_code(code: str) -> Tariff | None:
    if code == TRIAL.code:
        return TRIAL
    for tariff in TARIFFS:
        if tariff.code == code:
            return tariff
    return None
