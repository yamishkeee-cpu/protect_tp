"""User-side complaints: the «🚩 Пожаловаться» button under a feed profile."""
import logging

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.features.admin import admin_db
from app.features.admin.admin_states import ReportFlow
from app.core.db import get_user_profile
from app.features.profile.handlers import send_random_profile
from app.core.keyboards import get_main_menu, get_search_keyboard

logger = logging.getLogger(__name__)
report_router = Router()

RESULT_TEXT = {
    "queued": "🚩 Спасибо, жалоба передана модераторам.",
    "auto_banned": "🚩 Спасибо, жалоба принята. Анкета скрыта.",
    "duplicate": "Ты уже отправлял жалобу на эту анкету.",
    "limit": "Достигнут дневной лимит жалоб. Попробуй завтра.",
    "not_allowed": "Жалобы доступны только зарегистрированным пользователям.",
    "already_banned": "🚩 Эта анкета уже заблокирована. Спасибо!",
    "invalid": "Не удалось отправить жалобу: анкета недоступна.",
}


def _reasons_kb(target_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title, callback_data=f"rpr:{target_id}:{code}")]
            for code, title in admin_db.REPORT_REASONS.items()]
    rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data=f"rpb:{target_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _finish(call_or_message, reporter_id: int, target_id: int, reason: str, comment: str = "") -> None:
    result = admin_db.create_report(reporter_id, target_id, reason, comment)
    target = call_or_message.message if isinstance(call_or_message, types.CallbackQuery) else call_or_message
    await target.answer(RESULT_TEXT.get(result, RESULT_TEXT["invalid"]))
    await send_random_profile(call_or_message, reporter_id)


@report_router.callback_query(F.data.startswith("rp:"))
async def report_open(call: types.CallbackQuery):
    try:
        target_id = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        await call.answer("Некорректная анкета", show_alert=True)
        return
    if not get_user_profile(call.from_user.id):
        await call.answer("Сначала заполни профиль", show_alert=True)
        return
    try:
        await call.message.edit_reply_markup(reply_markup=_reasons_kb(target_id))
    except TelegramAPIError:
        pass
    await call.answer("Выбери причину жалобы")


@report_router.callback_query(F.data.startswith("rpb:"))
async def report_back(call: types.CallbackQuery):
    try:
        target_id = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        await call.answer()
        return
    try:
        await call.message.edit_reply_markup(reply_markup=get_search_keyboard(target_id))
    except TelegramAPIError:
        pass
    await call.answer()


@report_router.callback_query(F.data.startswith("rpr:"))
async def report_reason(call: types.CallbackQuery, state: FSMContext):
    try:
        _, target_raw, reason = call.data.split(":")
        target_id = int(target_raw)
    except (ValueError, IndexError):
        await call.answer("Некорректная жалоба", show_alert=True)
        return
    if reason not in admin_db.REPORT_REASONS:
        await call.answer("Неизвестная причина", show_alert=True)
        return
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    if reason == "other":
        await state.set_state(ReportFlow.comment)
        await state.update_data(report_target=target_id)
        await call.message.answer("Опиши проблему в одном сообщении (до 500 символов). /cancel — отменить.")
        return
    await _finish(call, call.from_user.id, target_id, reason)


@report_router.message(StateFilter(ReportFlow.comment))
async def report_comment(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Напиши причину текстом или нажми /cancel.")
        return
    data = await state.get_data()
    target_id = data.get("report_target")
    await state.clear()
    if not target_id:
        await message.answer("Жалоба устарела.", reply_markup=get_main_menu())
        return
    await _finish(message, message.from_user.id, int(target_id), "other", text[:500])
