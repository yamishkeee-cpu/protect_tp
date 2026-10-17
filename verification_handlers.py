"""Диалог подтверждения почты: «введи почту → введи код»."""
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message


from db import get_user_profile
from keyboards import VERIFY_MENU_TEXT, get_main_menu
from verification_db import get_user_status, was_ever_verified
from verification_keyboards import (
    BACK_CALLBACK,
    SKIP_VERIFY_CALLBACK,
    VERIFY_CALLBACK,
    get_back_keyboard,
    get_skip_keyboard,
    get_verify_keyboard,
)
from verification_service import (
    CODE_LENGTH,
    CODE_TTL_MINUTES,
    MAX_REQUESTS_PER_DAY,
    request_code,
    verify_code,
)
from verification_states import Verification

logger = logging.getLogger(__name__)
verification_router = Router()

RETRY_TEXT = "🔁 Запросить новый код"

EMAIL_PROMPT = (
    "Введи свою университетскую почту ВШЭ (…@edu.hse.ru или …@hse.ru).\n"
    "На неё придёт код подтверждения."
)
def _mask_email(raw: str) -> str:
    local, _, domain = raw.strip().lower().rpartition("@")
    return f"{local[:2]}***@{domain}"

MENU_BUTTONS = {
    "🔍 Поиск людей для общения",
    "🎯 Поиск для задач/проектов",
    "📅 Поиск мероприятий",
    "👤 Мой профиль",
    "📝 Заполнить заново",
}


async def _begin_verification(target: Message, user_id: int, state: FSMContext):
    if not get_user_profile(user_id):
        await target.answer(
            "Сначала заполни профиль: нажми «📝 Заполнить заново».",
            reply_markup=get_main_menu(),
        )
        return
    if get_user_status(user_id) == "verified":
        await target.answer("✅ Твоя почта уже подтверждена.", reply_markup=get_main_menu())
        return
    if get_user_status(user_id) == "banned" and was_ever_verified(user_id):
        await target.answer("Доступ ограничен. Обратись к администраторам.",
                            reply_markup=get_main_menu())
        return
    await state.clear()
    await state.set_state(Verification.email)
    await target.answer(EMAIL_PROMPT, reply_markup=get_skip_keyboard())


@verification_router.callback_query(F.data == VERIFY_CALLBACK)
async def verify_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await _begin_verification(call.message, call.from_user.id, state)


@verification_router.message(F.text == VERIFY_MENU_TEXT)
async def verify_start_from_menu(message: Message, state: FSMContext):
    await _begin_verification(message, message.from_user.id, state)


@verification_router.callback_query(Verification.email, F.data == SKIP_VERIFY_CALLBACK)
async def verify_skip(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await call.message.answer(
        "Хорошо, продолжаем без верификации. Подтвердить почту можно позже.",
        reply_markup=get_main_menu(),
    )
@verification_router.callback_query(F.data == SKIP_VERIFY_CALLBACK)
async def verify_skip_stale(call: CallbackQuery):
    await call.answer("Это действие уже недоступно.", show_alert=True)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass

@verification_router.callback_query(Verification.code, F.data == BACK_CALLBACK)
async def verify_back(call: CallbackQuery, state: FSMContext):
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await state.set_state(Verification.email)
    await call.message.answer(EMAIL_PROMPT, reply_markup=get_skip_keyboard())

@verification_router.callback_query(F.data == BACK_CALLBACK)
async def verify_back_stale(call: CallbackQuery):
    # Кнопка осталась в старом сообщении, а диалог уже завершён или перешёл дальше.
    await call.answer("Это действие уже недоступно.", show_alert=True)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass

@verification_router.message(Verification.email, ~F.text.in_(MENU_BUTTONS))
async def process_email(message: Message, state: FSMContext):
    result = await request_code(message.from_user.id, message.text or "")
    status = result.status

    if status == "sent":
        await state.set_state(Verification.code)
        await message.answer(
            f"📨 Код отправлен на {_mask_email(message.text or '')}. "
            f"Он действует {CODE_TTL_MINUTES} минут.\n"
            f"Введи {CODE_LENGTH} цифр из письма (загляни и в «Спам»).",
            reply_markup=get_back_keyboard(),
        )
        return
    if status == "invalid_domain":
        await message.answer(
            "Подходят только адреса вида …@edu.hse.ru и …@hse.ru. "
            "Проверь адрес и отправь ещё раз."
        )
        return
    if status == "email_taken":
        await message.answer(
            "Эта почта уже привязана к другому аккаунту. "
            "Если это твоя почта, обратись к администраторам."
        )
        return
    if status == "cooldown":
        await message.answer(
            f"Код можно запрашивать не чаще раза в минуту. Подожди {result.retry_after} сек. "
            "и отправь почту ещё раз."
        )
        return

    # Остальные исходы завершают диалог.
    await state.clear()
    texts = {
        "email_limit": "На эту почту сегодня уже отправлено слишком много кодов. Попробуй завтра.",
        "daily_limit": f"Достигнут суточный лимит ({MAX_REQUESTS_PER_DAY} запросов кода). Попробуй завтра.",
        "banned": "Доступ ограничен. Обратись к администраторам.",
        "no_profile": "Сначала заполни профиль: нажми «📝 Заполнить заново».",
        "send_failed": "Не удалось отправить письмо. Попробуй чуть позже.",
        "config_error": "Подтверждение почты временно недоступно. Попробуй позже.",
    }
    await message.answer(texts.get(status, "Что-то пошло не так. Попробуй позже."),
                         reply_markup=get_main_menu())


@verification_router.message(Verification.code, ~F.text.in_(MENU_BUTTONS))
async def process_code(message: Message, state: FSMContext):
    result = await verify_code(message.from_user.id, message.text or "")
    status = result.status

    if status == "verified":
        await state.clear()
        await message.answer("✅ Почта подтверждена! Спасибо.", reply_markup=get_main_menu())
        return
    if status == "bad_format":
        await message.answer(f"Код состоит из {CODE_LENGTH} цифр. Попробуй ещё раз.")
        return
    if status == "wrong_code":
        await message.answer(f"Неверный код. Осталось попыток: {result.attempts_left}.")
        return

    # Код больше не действует: диалог закрываем, предлагаем запросить новый.
    await state.clear()
    if status in ("expired", "too_many_attempts", "no_code"):
        reasons = {
            "expired": "Срок действия кода истёк.",
            "too_many_attempts": "Слишком много неверных попыток.",
            "no_code": "Активного кода нет.",
        }
        await message.answer(reasons[status], reply_markup=get_verify_keyboard(RETRY_TEXT))
        return
    texts = {
        "email_taken": "Эта почта уже привязана к другому аккаунту. Обратись к администраторам.",
        "no_profile": "Сначала заполни профиль: нажми «📝 Заполнить заново».",
        "config_error": "Подтверждение почты временно недоступно. Попробуй позже.",
    }
    await message.answer(texts.get(status, "Что-то пошло не так. Попробуй позже."),
                         reply_markup=get_main_menu())