"""Application entry point for the HSE NN matching Telegram bot."""
from aiogram.client.session.aiohttp import AiohttpSession
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name(".env"))
print(os.environ["EMAIL_HASH_SECRET"])

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram import BaseMiddleware
from app.core.keyboards import current_user_id

from app.features.admin.access_middleware import AccessMiddleware
from app.features.admin.admin_db import get_admin_role, init_admin_db, sync_admins_from_env
from app.features.admin.admin_handlers import admin_router
from app.features.admin.ads import ads_router
from app.core.db import init_db
from app.dev.dev_reset import dev_reset_router, is_enabled as dev_reset_enabled
from app.features.events.events_handlers import events_router
from app.features.profile.handlers import router as profile_router
from app.features.admin.report_handlers import report_router
from app.features.temp_profile.temp_profile_handlers import temp_profile_router

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
    from app.features.verification.verification_handlers import verification_router
    dispatcher = Dispatcher()
    # Запоминаем id пользователя на время обработки апдейта (персональное меню).
    dispatcher.update.outer_middleware(CurrentUserMiddleware())
    # Bans, temporary restrictions and spam limits apply to every message/callback.
    access = AccessMiddleware()
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)
    # Order matters: test-only reset first, then admin panel and complaints,
    # then profile/menu commands, then task and event flows.
    if dev_reset_enabled():
        dispatcher.include_router(dev_reset_router)  # только для тестов, подключается первым
    dispatcher.include_router(admin_router)
    dispatcher.include_router(report_router)
    dispatcher.include_router(ads_router)
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
