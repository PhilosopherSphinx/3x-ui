"""Клиент API панели 3x-ui.

ЕДИНСТВЕННЫЙ модуль, зависящий от версии панели. Написан под форк v3.x
(унифицированная таблица клиентов, маршруты /panel/api/clients/*).
Апстрим 2.x держит клиентов JSON-строкой внутри инбаунда и использует
/panel/api/inbounds/addClient — там нужен другой файл, не правки здесь.

Формы запросов выведены из модели ClientRecord. Сверить с живой панелью:
    GET /panel/api/openapi.json
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)


class PanelError(RuntimeError):
    """Панель ответила отказом или недоступна."""


@dataclass(frozen=True)
class PanelClient:
    email: str
    sub_id: str
    expiry_time: int  # мс от эпохи; 0 — бессрочно
    total_gb: int  # байты; 0 — без лимита
    used_traffic: int
    enable: bool
    inbound_ids: tuple[int, ...]


class Panel:
    def __init__(self, base_url: str, token: str, verify_tls: bool) -> None:
        self._client = httpx.AsyncClient(
            base_url=f"{base_url}/panel/api",
            headers={"Authorization": f"Bearer {token}"},
            verify=verify_tls,
            timeout=httpx.Timeout(20.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, payload: dict | None = None):
        try:
            response = await self._client.request(method, path, json=payload)
        except httpx.HTTPError as exc:
            raise PanelError(f"панель недоступна: {exc}") from exc

        if response.status_code == 401:
            raise PanelError("панель не приняла токен (401)")
        if response.status_code == 403:
            raise PanelError("токену не хватает прав — нужна область admin (403)")
        if response.status_code >= 400:
            raise PanelError(f"панель вернула HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError as exc:
            raise PanelError("панель вернула не JSON — проверь webBasePath") from exc

        if not body.get("success"):
            raise PanelError(body.get("msg") or "панель отклонила запрос")
        return body.get("obj")

    async def get_client(self, email: str) -> PanelClient | None:
        try:
            obj = await self._call("GET", f"/clients/get/{email}")
        except PanelError as exc:
            # Панель отвечает success:false и на «нет такого клиента».
            if "not found" in str(exc).lower() or "не найден" in str(exc).lower():
                return None
            raise
        if not obj:
            return None
        record = obj.get("client") or {}
        return PanelClient(
            email=record.get("email", email),
            sub_id=record.get("subId", ""),
            expiry_time=int(record.get("expiryTime") or 0),
            total_gb=int(record.get("totalGB") or 0),
            used_traffic=int(obj.get("usedTraffic") or 0),
            enable=bool(record.get("enable", True)),
            inbound_ids=tuple(obj.get("inboundIds") or ()),
        )

    async def create_client(
        self,
        email: str,
        sub_id: str,
        uuid: str,
        tg_id: int,
        expiry_time: int,
        total_bytes: int,
        inbound_ids: tuple[int, ...],
        comment: str = "",
    ) -> None:
        await self._call(
            "POST",
            "/clients/add",
            {
                "email": email,
                "subId": sub_id,
                "uuid": uuid,
                "tgId": tg_id,
                "expiryTime": expiry_time,
                "totalGB": total_bytes,
                "enable": True,
                "comment": comment,
                "inboundIds": list(inbound_ids),
            },
        )

    async def update_client(
        self,
        email: str,
        expiry_time: int,
        total_bytes: int,
        enable: bool = True,
    ) -> None:
        await self._call(
            "POST",
            f"/clients/update/{email}",
            {
                "expiryTime": expiry_time,
                "totalGB": total_bytes,
                "enable": enable,
            },
        )

    async def attach(self, email: str, inbound_ids: tuple[int, ...]) -> None:
        await self._call(
            "POST", f"/clients/{email}/attach", {"inboundIds": list(inbound_ids)}
        )

    async def reset_traffic(self, email: str) -> None:
        await self._call("POST", f"/clients/resetTraffic/{email}")
