"""Выдача и продление доступа. Между заказом и панелью."""

from __future__ import annotations

import logging
import secrets
import string
import time
import uuid as uuid_lib

from .panel import Panel, PanelError
from .tariffs import Tariff

log = logging.getLogger(__name__)

GIB = 1024**3
_SUB_ID_ALPHABET = string.ascii_lowercase + string.digits


def client_email(tg_id: int) -> str:
    """Стабильный и уникальный идентификатор клиента в панели."""
    return f"tg{tg_id}"


def _new_sub_id() -> str:
    """Ссылка подписки защищена только неугадываемостью subId — нужен secrets."""
    return "".join(secrets.choice(_SUB_ID_ALPHABET) for _ in range(16))


def _now_ms() -> int:
    return int(time.time() * 1000)


def next_expiry(current_ms: int, days: int) -> int:
    """Продление добавляется к остатку, а не обнуляет его.

    Истёкший или не выставленный срок (<= 0) отсчитывается от сейчас.
    """
    base = current_ms if current_ms > _now_ms() else _now_ms()
    return base + days * 86_400_000


class Provisioner:
    def __init__(self, panel: Panel, sub_base_url: str) -> None:
        self._panel = panel
        self._sub_base_url = sub_base_url.rstrip("/")

    def sub_link(self, sub_id: str) -> str:
        return f"{self._sub_base_url}/{sub_id}"

    async def grant(self, tg_id: int, tariff: Tariff, comment: str = "") -> str:
        """Создаёт или продлевает клиента. Возвращает ссылку подписки.

        Повторный вызов с тем же заказом продлит второй раз, поэтому
        защита от двойной выдачи живёт на уровне статуса заказа.
        """
        email = client_email(tg_id)
        total_bytes = tariff.total_gb * GIB
        existing = await self._panel.get_client(email)

        if existing is None:
            sub_id = _new_sub_id()
            await self._panel.create_client(
                email=email,
                sub_id=sub_id,
                uuid=str(uuid_lib.uuid4()),
                tg_id=tg_id,
                expiry_time=next_expiry(0, tariff.days),
                total_bytes=total_bytes,
                inbound_ids=tariff.inbound_ids,
                comment=comment,
            )
            log.info("создан клиент %s по тарифу %s", email, tariff.code)
            return self.sub_link(sub_id)

        await self._panel.update_client(
            current=existing,
            expiry_time=next_expiry(existing.expiry_time, tariff.days),
            total_bytes=total_bytes,
            enable=True,
        )
        # Тариф мог смениться — набор входящих приводим к оплаченному.
        if tuple(sorted(existing.inbound_ids)) != tuple(sorted(tariff.inbound_ids)):
            await self._panel.attach(email, tariff.inbound_ids)
        # Квотный тариф продлевают ради нового объёма, значит счётчик обнуляем.
        if total_bytes > 0:
            await self._panel.reset_traffic(email)

        log.info("продлён клиент %s по тарифу %s", email, tariff.code)
        if not existing.sub_id:
            # Новый subId здесь дал бы покупателю мёртвую ссылку: в панели его нет.
            raise PanelError(f"у клиента {email} пустой subId — выдать ссылку нечем")
        return self.sub_link(existing.sub_id)

    async def status(self, tg_id: int) -> dict | None:
        """Текущее состояние подписки для команды /my."""
        try:
            client = await self._panel.get_client(client_email(tg_id))
        except PanelError:
            log.exception("не удалось прочитать клиента %s", tg_id)
            raise
        if client is None:
            return None
        return {
            "link": self.sub_link(client.sub_id),
            "expiry_ms": client.expiry_time,
            "used_gb": client.used_traffic / GIB,
            "limit_gb": client.total_bytes / GIB if client.total_bytes else 0,
            "enable": client.enable,
        }
