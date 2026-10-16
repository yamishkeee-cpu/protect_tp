"""ТОЛЬКО ДЛЯ ТЕСТОВ. Команда /reset_me полностью стирает данные вызвавшего пользователя.

Включается переменными окружения:
    TEST_MODE=1
    TEST_USER_IDS=123456789,987654321
Перед деплоем: убрать переменные из .env и удалить этот файл вместе с подключением в bot.py.
"""
import logging
import os

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

from db import db_connection

logger = logging.getLogger(__name__)
dev_reset_router = Router()

CONFIRM_YES = "dev_reset_yes"
CONFIRM_NO = "dev_reset_no"


def is_enabled() -> bool:
    return os.getenv("TEST_MODE", "").strip() == "1"


def _allowed_ids() -> set[int]:
    result = set()
    for part in os.getenv("TEST_USER_IDS", "").split(","):
        part = part.strip()
        if part.isdecimal():
            result.add(int(part))
    return result


def _is_allowed(user_id: int) -> bool:
    return is_enabled() and user_id in _allowed_ids()


# Порядок важен: сначала зависимые записи, потом сами анкеты и события.
_RESET_STATEMENTS = (
    "DELETE FROM temp_profile_responses WHERE user_id = :u "
    "OR temp_id IN (SELECT id FROM temp_profiles WHERE user_id = :u)",
    "DELETE FROM viewed_temp WHERE user_id = :u "
    "OR temp_id IN (SELECT id FROM temp_profiles WHERE user_id = :u)",
    "DELETE FROM event_responses WHERE user_id = :u "
    "OR event_id IN (SELECT id FROM events WHERE user_id = :u) "
    "OR temp_profile_id IN (SELECT id FROM temp_profiles WHERE user_id = :u)",
    "DELETE FROM viewed_events WHERE user_id = :u "
    "OR event_id IN (SELECT id FROM events WHERE user_id = :u)",
    "DELETE FROM temp_profiles WHERE user_id = :u",
    "DELETE FROM events WHERE user_id = :u",
    "DELETE FROM viewed_profiles WHERE user_id = :u OR profile_user_id = :u",
    "DELETE FROM user_likes WHERE user_id = :u OR liked_user_id = :u",
    "DELETE FROM email_verifications WHERE user_id = :u",
    "DELETE FROM verified_emails WHERE user_id = :u",
    "DELETE FROM user_profiles WHERE user_id = :u",
    "DELETE FROM users WHERE user_id = :u",
)


def wipe_user(user_id: int) -> None:
    """Всё в одной транзакции: при любой ошибке откатывается целиком."""
    with db_connection() as conn:
        for statement in _RESET_STATEMENTS:
            conn.execute(statement, {"u": user_id})


@dev_reset_router.message(Command("reset_me"))
async def reset_me(message: Message, state: FSMContext):
    if not _is_allowed(message.from_user.id):
        return  # молча игнорируем
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Да, удалить", callback_data=CONFIRM_YES),
        InlineKeyboardButton(text="Отмена", callback_data=CONFIRM_NO),
    ]])
    await message.answer(
        "⚠️ <b>Тестовый сброс.</b> Будут удалены твой профиль, статус, привязка почты, "
        "коды, лайки, анкеты и события. Продолжить?",
        reply_markup=keyboard,
    )


@dev_reset_router.callback_query(F.data == CONFIRM_NO)
async def reset_cancel(call: CallbackQuery):
    if not _is_allowed(call.from_user.id):
        await call.answer()
        return
    await call.answer()
    await call.message.edit_text("Сброс отменён.", reply_markup=None)


@dev_reset_router.callback_query(F.data == CONFIRM_YES)
async def reset_confirm(call: CallbackQuery, state: FSMContext):
    if not _is_allowed(call.from_user.id):
        await call.answer()
        return
    await call.answer()
    await state.clear()
    try:
        wipe_user(call.from_user.id)
    except Exception:
        logger.exception("Тестовый сброс не удался (user %s)", call.from_user.id)
        await call.message.edit_text("Не удалось удалить данные, подробности в логе.", reply_markup=None)
        return
    logger.warning("TEST RESET: данные пользователя %s удалены", call.from_user.id)
    await call.message.edit_text("✅ Данные удалены.", reply_markup=None)
    await call.message.answer("Нажми /start, чтобы пройти регистрацию заново.",
                              reply_markup=ReplyKeyboardRemove())