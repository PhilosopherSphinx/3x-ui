"""Хранилище заказов. SQLite: нагрузка здесь — десятки записей в день."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

# Жизненный цикл заказа. Переходы делаются только через UPDATE ... WHERE status=?,
# поэтому двойное нажатие кнопки не может провести один заказ дважды.
STATUS_AWAITING = "awaiting_payment"
STATUS_PENDING = "pending_confirm"
STATUS_PAID = "paid"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"

LIVE_STATUSES = (STATUS_AWAITING, STATUS_PENDING)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id      INTEGER PRIMARY KEY,
    username   TEXT    NOT NULL DEFAULT '',
    trial_used INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id          INTEGER NOT NULL,
    username       TEXT    NOT NULL DEFAULT '',
    tariff_code    TEXT    NOT NULL,
    amount_kopecks INTEGER NOT NULL,
    status         TEXT    NOT NULL,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL,
    admin_id       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_tg_id  ON orders(tg_id);
"""


@dataclass(frozen=True)
class Order:
    id: int
    tg_id: int
    username: str
    tariff_code: str
    amount_kopecks: int
    status: str
    created_at: int
    updated_at: int
    admin_id: int

    @property
    def amount_display(self) -> str:
        return f"{self.amount_kopecks // 100}.{self.amount_kopecks % 100:02d}"


def _row_to_order(row: aiosqlite.Row) -> Order:
    return Order(
        id=row["id"],
        tg_id=row["tg_id"],
        username=row["username"],
        tariff_code=row["tariff_code"],
        amount_kopecks=row["amount_kopecks"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        admin_id=row["admin_id"],
    )


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._create_lock = asyncio.Lock()

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() не вызывался")
        return self._conn

    # --- пользователи ---

    async def upsert_user(self, tg_id: int, username: str) -> None:
        await self.conn.execute(
            "INSERT INTO users (tg_id, username, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username",
            (tg_id, username, int(time.time())),
        )
        await self.conn.commit()

    async def trial_used(self, tg_id: int) -> bool:
        async with self.conn.execute(
            "SELECT trial_used FROM users WHERE tg_id=?", (tg_id,)
        ) as cur:
            row = await cur.fetchone()
        return bool(row and row["trial_used"])

    async def mark_trial_used(self, tg_id: int) -> bool:
        """True, если пробный засчитан именно этим вызовом."""
        cur = await self.conn.execute(
            "UPDATE users SET trial_used=1 WHERE tg_id=? AND trial_used=0", (tg_id,)
        )
        await self.conn.commit()
        return cur.rowcount == 1

    async def clear_trial(self, tg_id: int) -> None:
        """Откат отметки, если выдача пробного не дошла до панели."""
        await self.conn.execute(
            "UPDATE users SET trial_used=0 WHERE tg_id=?", (tg_id,)
        )
        await self.conn.commit()

    # --- заказы ---

    async def create_order(
        self, tg_id: int, username: str, tariff_code: str, base_kopecks: int
    ) -> Order:
        """Сумма получает уникальные копейки, чтобы перевод сходился с заказом.

        Занятые копейки берутся только у живых заказов, так что диапазон
        переиспользуется и 100 одновременных заказов на один тариф — предел.
        """
        async with self._create_lock:
            base = (base_kopecks // 100) * 100
            placeholders = ",".join("?" * len(LIVE_STATUSES))
            async with self.conn.execute(
                f"SELECT amount_kopecks FROM orders "
                f"WHERE status IN ({placeholders}) AND amount_kopecks BETWEEN ? AND ?",
                (*LIVE_STATUSES, base, base + 99),
            ) as cur:
                taken = {row["amount_kopecks"] for row in await cur.fetchall()}

            amount = next(
                (base + n for n in range(100) if base + n not in taken), base
            )
            now = int(time.time())
            cur = await self.conn.execute(
                "INSERT INTO orders (tg_id, username, tariff_code, amount_kopecks, "
                "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tg_id, username, tariff_code, amount, STATUS_AWAITING, now, now),
            )
            await self.conn.commit()
            order_id = cur.lastrowid

        order = await self.get_order(order_id)
        assert order is not None
        return order

    async def get_order(self, order_id: int) -> Order | None:
        async with self.conn.execute(
            "SELECT * FROM orders WHERE id=?", (order_id,)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_order(row) if row else None

    async def transition(
        self, order_id: int, from_status: str, to_status: str, admin_id: int = 0
    ) -> bool:
        """Атомарная смена статуса. False — заказ уже обработан кем-то другим."""
        cur = await self.conn.execute(
            "UPDATE orders SET status=?, updated_at=?, admin_id=? "
            "WHERE id=? AND status=?",
            (to_status, int(time.time()), admin_id, order_id, from_status),
        )
        await self.conn.commit()
        return cur.rowcount == 1

    async def orders_by_status(self, status: str, limit: int = 50) -> list[Order]:
        async with self.conn.execute(
            "SELECT * FROM orders WHERE status=? ORDER BY id DESC LIMIT ?",
            (status, limit),
        ) as cur:
            return [_row_to_order(row) for row in await cur.fetchall()]

    async def expire_stale(self, ttl_minutes: int) -> int:
        cutoff = int(time.time()) - ttl_minutes * 60
        cur = await self.conn.execute(
            "UPDATE orders SET status=?, updated_at=? "
            "WHERE status=? AND created_at < ?",
            (STATUS_EXPIRED, int(time.time()), STATUS_AWAITING, cutoff),
        )
        await self.conn.commit()
        return cur.rowcount
