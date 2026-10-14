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

from db import init_db
from events_handlers import events_router
from handlers import router as profile_router
from temp_profile_handlers import temp_profile_router


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    # Order matters: profile/menu commands first, then task and event flows.
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
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
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
