"""Клиент API панели 3x-ui v3.x.

ЕДИНСТВЕННЫЙ модуль, зависящий от версии панели. Формы запросов сверены по
исходникам v3.8.5 (internal/web/controller/client.go, internal/web/service/
client.go, client_crud.go), а не угаданы.

Три ловушки этого API, из-за которых наивный клиент молча ломается:

1. /clients/add принимает ВЛОЖЕННЫЙ payload {"client": {...}, "inboundIds": []},
   а /clients/update/:email — ПЛОСКИЙ model.Client. Формы разные.
2. При чтении UUID лежит в поле "uuid", а при записи его ждут в поле "id".
   Поле "id" в ответе — это целочисленный ключ строки БД, не UUID.
3. Update ЗАМЕНЯЕТ запись целиком и требует непустой email
   (client_crud.go:585). Разреженный payload стирает subId и UUID, поэтому
   обновление здесь всегда read-modify-write.

totalGB вопреки названию хранится в байтах (ldap_sync_job.go:218).
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
    uuid: str
    expiry_time: int  # мс от эпохи; 0 — бессрочно
    total_bytes: int  # 0 — без лимита
    used_traffic: int
    enable: bool
    inbound_ids: tuple[int, ...]
    raw: dict  # исходная запись — основа для read-modify-write


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
            # Отсутствие клиента панель отдаёт как success:false, а не как 404.
            if "not found" in str(exc).lower() or "record" in str(exc).lower():
                return None
            raise
        if not obj:
            return None
        record = obj.get("client") or {}
        return PanelClient(
            email=record.get("email", email),
            sub_id=record.get("subId", ""),
            uuid=record.get("uuid", ""),
            expiry_time=int(record.get("expiryTime") or 0),
            total_bytes=int(record.get("totalGB") or 0),
            used_traffic=int(obj.get("usedTraffic") or 0),
            enable=bool(record.get("enable", True)),
            inbound_ids=tuple(obj.get("inboundIds") or ()),
            raw=record,
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
        flow: str = "",
        comment: str = "",
        limit_hwid: int = 0,
    ) -> None:
        client = {
            "id": uuid,  # именно "id": на запись UUID идёт сюда
            "email": email,
            "subId": sub_id,
            "tgId": tg_id,
            "expiryTime": expiry_time,
            "totalGB": total_bytes,
            "enable": True,
            "comment": comment,
            "limitIp": 0,
            "limitHwid": limit_hwid,
        }
        if flow:
            client["flow"] = flow
        await self._call(
            "POST", "/clients/add", {"client": client, "inboundIds": list(inbound_ids)}
        )

    async def update_client(
        self,
        current: PanelClient,
        expiry_time: int,
        total_bytes: int,
        enable: bool = True,
        limit_hwid: int | None = None,
    ) -> None:
        """Read-modify-write: Update заменяет запись, а не дополняет её."""
        record = current.raw
        payload = {
            "id": current.uuid,
            "email": current.email,
            "subId": current.sub_id,
            "tgId": int(record.get("tgId") or 0),
            "expiryTime": expiry_time,
            "totalGB": total_bytes,
            "enable": enable,
            "comment": record.get("comment") or "",
            "limitIp": int(record.get("limitIp") or 0),
            "limitHwid": (
                limit_hwid
                if limit_hwid is not None
                else int(record.get("limitHwid") or 0)
            ),
            "reset": int(record.get("reset") or 0),
            "resetDay": int(record.get("resetDay") or 0),
            "resetMax": int(record.get("resetMax") or 0),
        }
        for optional in ("flow", "security", "password", "auth", "group"):
            value = record.get(optional)
            if value:
                payload[optional] = value
        await self._call("POST", f"/clients/update/{current.email}", payload)

    async def attach(self, email: str, inbound_ids: tuple[int, ...]) -> None:
        await self._call(
            "POST", f"/clients/{email}/attach", {"inboundIds": list(inbound_ids)}
        )

    async def reset_traffic(self, email: str) -> None:
        await self._call("POST", f"/clients/resetTraffic/{email}")
