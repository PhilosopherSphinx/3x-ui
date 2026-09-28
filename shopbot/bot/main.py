"""Точка входа. Запуск: python -m bot.main"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import Config, ConfigError
from .db import Database
from .handlers import admin, user
from .panel import Panel
from .service import Provisioner

log = logging.getLogger(__name__)

EXPIRE_SWEEP_SECONDS = 300


async def _expire_loop(db: Database, ttl_minutes: int) -> None:
    while True:
        await asyncio.sleep(EXPIRE_SWEEP_SECONDS)
        try:
            count = await db.expire_stale(ttl_minutes)
            if count:
                log.info("протухло неоплаченных заказов: %s", count)
        except Exception:
            log.exception("сбой в подчистке заказов")


async def run() -> None:
    config = Config.load()

    db = Database(config.db_path)
    await db.connect()

    panel = Panel(
        config.panel_base_url, config.panel_api_token, config.panel_verify_tls
    )
    provisioner = Provisioner(panel, config.sub_base_url)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher["db"] = db
    dispatcher["config"] = config
    dispatcher["provisioner"] = provisioner

    # Админский роутер первым: его фильтры пропускают чужие апдейты дальше.
    dispatcher.include_router(admin.setup(config.admin_ids))
    dispatcher.include_router(user.router)

    sweeper = asyncio.create_task(_expire_loop(db, config.order_ttl_minutes))
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        await panel.close()
        await db.close()
        await bot.session.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run())
    except ConfigError as exc:
        raise SystemExit(f"ошибка конфигурации: {exc}") from exc
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
