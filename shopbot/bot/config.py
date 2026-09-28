"""Настройки из окружения. Падаем на старте, а не на первом платеже."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    pass


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"не задана переменная {name} (см. .env.example)")
    return value


def _admin_ids(raw: str) -> frozenset[int]:
    ids = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        if not part.lstrip("-").isdigit():
            raise ConfigError(f"ADMIN_IDS: {part!r} не похоже на Telegram ID")
        ids.add(int(part))
    if not ids:
        raise ConfigError("ADMIN_IDS пуст — подтверждать заказы будет некому")
    return frozenset(ids)


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    panel_base_url: str
    panel_api_token: str
    panel_verify_tls: bool
    sub_base_url: str
    payment_details: str
    db_path: Path
    order_ttl_minutes: int

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Config":
        _load_dotenv(env_file or Path(__file__).resolve().parent.parent / ".env")
        ttl_raw = os.environ.get("ORDER_TTL_MINUTES", "120").strip()
        if not ttl_raw.isdigit() or int(ttl_raw) <= 0:
            raise ConfigError("ORDER_TTL_MINUTES должен быть положительным числом")
        return cls(
            bot_token=_required("BOT_TOKEN"),
            admin_ids=_admin_ids(_required("ADMIN_IDS")),
            panel_base_url=_required("PANEL_BASE_URL").rstrip("/"),
            panel_api_token=_required("PANEL_API_TOKEN"),
            panel_verify_tls=os.environ.get("PANEL_VERIFY_TLS", "false").lower()
            in ("1", "true", "yes"),
            sub_base_url=_required("SUB_BASE_URL").rstrip("/"),
            payment_details=_required("PAYMENT_DETAILS"),
            db_path=Path(os.environ.get("DB_PATH", "shop.db")),
            order_ttl_minutes=int(ttl_raw),
        )
