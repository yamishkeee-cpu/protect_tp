"""Application entry point for the HSE NN matching Telegram bot."""
import asyncio
import logging
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # Environment variables still work without python-dotenv.
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(Path(__file__).with_name(".env"))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from access_middleware import AccessMiddleware
from admin_db import get_admin_role, init_admin_db, sync_admins_from_env
from admin_handlers import admin_router
from ads import ads_router
from db import init_db
from events_handlers import events_router
from handlers import router as profile_router
from report_handlers import report_router
from temp_profile_handlers import temp_profile_router


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    # Bans, temporary restrictions and spam limits apply to every message/callback.
    access = AccessMiddleware()
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)
    # Order matters: admin panel and complaints first, then profile/menu commands,
    # then task and event flows.
    dispatcher.include_router(admin_router)
    dispatcher.include_router(report_router)
    dispatcher.include_router(ads_router)
    dispatcher.include_router(profile_router)
    dispatcher.include_router(temp_profile_router)
    dispatcher.include_router(events_router)
    return dispatcher


async def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Не задан BOT_TOKEN. Получи/обнови токен у @BotFather и задай переменную окружения.\n"
            "macOS/Linux: export BOT_TOKEN='твой_токен'\n"
            "PowerShell: $env:BOT_TOKEN='твой_токен'"
        )

    init_db()
    init_admin_db()
    sync_admins_from_env()  # ADMIN_IDS / MODERATOR_IDS -> admins table
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not any(os.getenv(name, "").strip() for name in
               ("ADMIN_USERNAMES", "MODERATOR_USERNAMES", "ADMIN_IDS", "MODERATOR_IDS")):
        logging.getLogger(__name__).warning(
            "Админы не заданы: укажи ADMIN_USERNAMES (или ADMIN_IDS) в .env, иначе /admin недоступен")
    dispatcher = build_dispatcher()
    async with Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    ) as bot:
        logging.getLogger(__name__).info("Бот запускается")
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        logging.getLogger(__name__).exception("Критическая ошибка во время работы бота")
        raise
