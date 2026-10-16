"""Application entry point for the HSE NN matching Telegram bot."""
from aiogram.client.session.aiohttp import AiohttpSession
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
from aiogram import BaseMiddleware
from keyboards import current_user_id

from db import init_db
from dev_reset import dev_reset_router, is_enabled as dev_reset_enabled
from events_handlers import events_router
from handlers import router as profile_router
from temp_profile_handlers import temp_profile_router

class CurrentUserMiddleware(BaseMiddleware):
    """Запоминает id пользователя на время обработки апдейта (для персонального меню)."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        token = current_user_id.set(user.id if user else None)
        try:
            return await handler(event, data)
        finally:
            current_user_id.reset(token)

def build_dispatcher() -> Dispatcher:
    from verification_handlers import verification_router   # NEW (к остальным импортам)
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(CurrentUserMiddleware())
    # Order matters: profile/menu commands first, then task and event flows.
    if dev_reset_enabled():
        dispatcher.include_router(dev_reset_router)  # только для тестов, подключается первым
    dispatcher.include_router(profile_router)
    dispatcher.include_router(verification_router)
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
    proxy = os.getenv("PROXY_URL", "").strip() or None
    session = AiohttpSession(proxy=proxy) if proxy else AiohttpSession()
    async with Bot(
        token=token,
        session=session,
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
