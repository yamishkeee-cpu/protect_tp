"""Permanent profile registration, profile browsing, and mutual likes."""
import html
import logging

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from app.core.db import (
    add_like,
    clear_interaction,
    remove_like,
    get_random_stranger,
    get_user,
    get_user_bio,
    get_user_profile,
    has_like,
    mark_stranger_viewed,
    reset_all_viewed,
    save_user,
    is_profile_active,
    set_profile_active,
)
from app.features.admin.ads import maybe_show_ad
from app.core.keyboards import FACULTY_LIST, get_faculty_keyboard, get_main_menu, get_search_keyboard
from app.features.profile.states import Anketa
from app.features.verification.verification_db import get_user_status
from app.features.verification.verification_keyboards import get_verify_keyboard
from aiogram.types import LinkPreviewOptions
logger = logging.getLogger(__name__)
router = Router()
PROFILE_DELAY = 0.2

POLICY_URL = "https://telegra.ph/Politika-konfidencialnosti-10-14-105"


def _profile_manage_keyboard(active: bool) -> InlineKeyboardMarkup:
    if active:
        btn = InlineKeyboardButton(text="🙈 Деактивировать анкету", callback_data="profile_toggle_off")
    else:
        btn = InlineKeyboardButton(text="👁 Активировать анкету", callback_data="profile_toggle_on")
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


async def _offer_verification(message: Message) -> None:
    """Кнопка подтверждения почты, если она ещё не подтверждена."""
    if get_user_status(message.from_user.id) != "verified":
        await message.answer(
            "📧 Почта ВШЭ пока не подтверждена. Подтверди её, чтобы получить статус проверенного участника.",
            reply_markup=get_verify_keyboard(),
        )
async def begin_registration(message: Message, state: FSMContext, first_time: bool = False) -> None:
    await state.clear()
    text = (
        "👋 Привет! Это бот знакомств ВШЭ НН.\n\n"
        "Давай заполним постоянный профиль. Как тебя зовут?"
    )
    # Ссылку на политику показываем только при первом запуске
    if first_time:
        text += (
            "\n\nПри дальнейшем использовании бота вы соглашаетесь с "
            f'<a href="{POLICY_URL}">политикой конфиденциальности</a>'
        )
    await message.answer(
        text,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Anketa.name)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    existing = get_user_profile(message.from_user.id)
    if existing:
        await state.clear()
        await message.answer(
            f"С возвращением, {html.escape(existing[0] or 'пользователь')}! "
            f'Напоминаем тебе о <a href="{POLICY_URL}">политике конфиденциальности</a>.\n'
            "Выбери действие в меню.",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            reply_markup=get_main_menu(),
        )
        return
    await begin_registration(message, state, first_time=True)


@router.message(Command("cancel"))
async def cancel_current_flow(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Текущее действие отменено.", reply_markup=get_main_menu())


@router.message(F.text == "📝 Заполнить заново")
async def restart_registration(message: Message, state: FSMContext):
    await begin_registration(message, state)


@router.message(Anketa.name)
async def process_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name or len(name) > 50:
        await message.answer("Введите имя длиной от 1 до 50 символов.")
        return
    await state.update_data(name=name)
    await message.answer("Введи год поступления (например, 2024):")
    await state.set_state(Anketa.start_year)


@router.message(Anketa.start_year)
async def process_year(message: Message, state: FSMContext):
    year_text = (message.text or "").strip()
    if not year_text.isdecimal():
        await message.answer("Введите год цифрами, например 2024.")
        return
    year = int(year_text)
    if not 2000 <= year <= 2035:
        await message.answer("Проверь год поступления и введи год от 2000 до 2035.")
        return
    await state.update_data(start_year=str(year))
    await message.answer("Напиши номер группы")
    await state.set_state(Anketa.group_num)


@router.message(Anketa.group_num)
async def process_group(message: Message, state: FSMContext):
    group = (message.text or "").strip()
    if not group or len(group) > 30:
        await message.answer("Введите номер группы длиной от 1 до 30 символов.")
        return
    await state.update_data(group_num=group)
    await message.answer("Выбери направление подготовки:", reply_markup=get_faculty_keyboard())
    await state.set_state(Anketa.faculty)


@router.callback_query(F.data.startswith("facultypage_"))
async def faculty_page_callback(call: types.CallbackQuery):
    try:
        page = int(call.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректная страница", show_alert=True)
        return
    await call.message.edit_reply_markup(reply_markup=get_faculty_keyboard(page))
    await call.answer()


@router.callback_query(Anketa.faculty, F.data.startswith("faculty_"))
async def faculty_callback(call: types.CallbackQuery, state: FSMContext):
    try:
        index = int(call.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректное направление", show_alert=True)
        return
    if not 0 <= index < len(FACULTY_LIST):
        await call.answer("Это направление недоступно. Выбери из списка.", show_alert=True)
        return
    await state.update_data(faculty=FACULTY_LIST[index])
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Расскажи немного о себе: интересы, увлечения, кого хочешь найти (до 300 символов).")
    await state.set_state(Anketa.bio)
    await call.answer()


@router.message(Anketa.faculty)
async def process_faculty_direct(message: Message):
    await message.answer("Пожалуйста, выбери направление кнопкой ниже:", reply_markup=get_faculty_keyboard())


@router.message(Anketa.bio)
async def process_bio(message: Message, state: FSMContext):
    bio = (message.text or "").strip()
    if not bio or len(bio) > 300:
        await message.answer("Введи био текстом длиной от 1 до 300 символов.")
        return
    await state.update_data(bio=bio)
    await message.answer("Отправь одну свою фотографию:")
    await state.set_state(Anketa.photo)


@router.message(Anketa.photo)
async def process_photo(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Пожалуйста, отправь именно фотографию.")
        return
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    try:
        save_user(
            user_id=message.from_user.id,
            name=data["name"],
            start_year=data["start_year"],
            group_num=data["group_num"],
            faculty=data["faculty"],
            photo=photo_id,
            bio=data["bio"],
        )
    except Exception:
        logger.exception("Failed to save permanent profile for user %s", message.from_user.id)
        await message.answer("Не удалось сохранить профиль. Попробуй ещё раз позже.")
        return
    await state.clear()
    await message.answer("🎉 Профиль сохранён! Теперь можно искать людей.", reply_markup=get_main_menu())
    await _offer_verification(message)


@router.message(F.text == "👤 Мой профиль")
async def show_my_profile(message: Message, state: FSMContext):
    await state.clear()
    user = get_user_profile(message.from_user.id) or get_user(message.from_user.id)
    if not user:
        await message.answer("Ты ещё не заполнил анкету. Нажми «📝 Заполнить заново».", reply_markup=get_main_menu())
        await _offer_verification(message)
        return
    name, start_year, group_num, faculty, photo = user
    active = is_profile_active(message.from_user.id)
    status_line = "🟢 Анкета активна" if active else "🔴 Анкета скрыта из поиска"
    manage_kb = _profile_manage_keyboard(active)
    caption = (
        "📝 <b>Твой профиль</b>\n"
        f"{status_line}\n"
        f"👤 Имя: {html.escape(name or 'Не указано')}\n"
        f"📅 Год поступления: {html.escape(start_year or 'Не указан')}\n"
        f"👥 Группа: {html.escape(group_num or 'Не указана')}\n"
        f"🎓 Направление: {html.escape(faculty or 'Не указано')}\n"
        f"📝 О себе: {html.escape(get_user_bio(message.from_user.id) or 'Не указано')}"
    )
    if photo:
        try:
            await message.answer_photo(photo=photo, caption=caption, reply_markup=manage_kb)
            return
        except TelegramBadRequest:
            # Фото устарело (например, сменился бот): просим загрузить заново, остальные данные оставляем
            logger.warning("Broken photo file_id for user %s", message.from_user.id)
            await state.update_data(name=name, start_year=start_year, group_num=group_num, faculty=faculty,
                                    bio=get_user_bio(message.from_user.id))
            await state.set_state(Anketa.photo)
            await message.answer("Твоё фото больше не открывается. Отправь, пожалуйста, новую фотографию:",
                                 reply_markup=ReplyKeyboardRemove())
            await _offer_verification(message)
            return
    await message.answer(caption, reply_markup=manage_kb)


@router.callback_query(F.data == "profile_toggle_off")
async def deactivate_profile_callback(call: types.CallbackQuery):
    if not set_profile_active(call.from_user.id, False):
        await call.answer("Анкета не найдена", show_alert=True)
        return
    await call.answer("Анкета скрыта")
    try:
        await call.message.edit_reply_markup(reply_markup=_profile_manage_keyboard(False))
    except TelegramAPIError:
        pass
    await call.message.answer(
        "🙈 Анкета скрыта из поиска. Другие пользователи её больше не увидят.\n"
        "В любой момент можно активировать снова в «👤 Мой профиль»."
    )


@router.callback_query(F.data == "profile_toggle_on")
async def activate_profile_callback(call: types.CallbackQuery):
    if not set_profile_active(call.from_user.id, True):
        await call.answer("Анкета не найдена", show_alert=True)
        return
    await call.answer("Анкета активирована")
    try:
        await call.message.edit_reply_markup(reply_markup=_profile_manage_keyboard(True))
    except TelegramAPIError:
        pass
    await call.message.answer(
        "👁 Анкета снова активна и будет показываться в поиске."
    )


async def send_random_profile(message_or_call, user_id: int):
    target = message_or_call.message if isinstance(message_or_call, types.CallbackQuery) else message_or_call
    for _ in range(20):  # анкеты с нерабочим фото пропускаем
        stranger = get_random_stranger(user_id)
        if not stranger:
            # Exhaustion is per-user, not global. Clear this user's history so that
            # the next search begins a new cycle without disturbing other users.
            reset_all_viewed(user_id)
            await target.answer(
                "🎉 Пока больше нет новых анкет. История просмотра сброшена — можешь начать поиск снова.",
                reply_markup=get_main_menu(),
            )
            return

        profile_id, name, year, group_num, faculty, photo = stranger
        mark_stranger_viewed(user_id, profile_id)
        caption = (
            "🔍 <b>Анкета</b>\n"
            f"👤 Имя: {html.escape(name or 'Не указано')}\n"
            f"📅 Год поступления: {html.escape(year or 'Не указан')}\n"
            f"👥 Группа: {html.escape(group_num or 'Не указана')}\n"
            f"🎓 Направление: {html.escape(faculty or 'Не указано')}\n"
            f"📝 О себе: {html.escape(get_user_bio(profile_id) or 'Не указано')}"
        )
        keyboard = get_search_keyboard(profile_id)
        if not photo:
            continue
        await maybe_show_ad(target, user_id)  # ad card between profiles
        try:
            await target.answer_photo(photo=photo, caption=caption, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            logger.warning("Skipping profile %s: photo is not available", profile_id)
    await target.answer("Не удалось подобрать анкету. Попробуй позже.", reply_markup=get_main_menu())


@router.message(F.text == "🔍 Поиск людей для общения")
async def start_search(message: Message, state: FSMContext):
    await state.clear()
    if not get_user_profile(message.from_user.id):
        await message.answer("Сначала заполни постоянный профиль: нажми «📝 Заполнить заново».", reply_markup=get_main_menu())
        return
    await send_random_profile(message, message.from_user.id)


async def _get_username(bot, user_id: int) -> str | None:
    try:
        chat = await bot.get_chat(user_id)
    except TelegramAPIError:
        return None
    return chat.username


async def _send_profile_card(bot, receiver_id: int, profile_id: int, intro: str,
                             contact: bool = False, reply_markup=None) -> None:
    """Отправляет receiver_id анкету profile_id. contact=True добавляет @username."""
    profile = get_user_profile(profile_id) or get_user(profile_id)
    if not profile:
        await bot.send_message(receiver_id, "Профиль этого пользователя уже недоступен.")
        return
    name, year, group_num, faculty, photo = profile
    caption = (
        f"{intro}\n\n"
        f"👤 Имя: {html.escape(name or 'Не указано')}\n"
        f"📅 Год поступления: {html.escape(year or 'Не указан')}\n"
        f"👥 Группа: {html.escape(group_num or 'Не указана')}\n"
        f"🎓 Направление: {html.escape(faculty or 'Не указано')}\n"
        f"📝 О себе: {html.escape(get_user_bio(profile_id) or 'Не указано')}"
    )
    if contact:
        username = await _get_username(bot, profile_id)
        if username:
            caption += f"\n\n✉️ Написать: @{username}"
        else:
            caption += (
                "\n\n✉️ У пользователя не задан username. "
                f'<a href="tg://user?id={profile_id}">Попробовать открыть профиль</a>'
            )
    if photo:
        try:
            await bot.send_photo(receiver_id, photo=photo, caption=caption, reply_markup=reply_markup)
            return
        except TelegramBadRequest:
            logger.warning("Broken photo for profile %s, sending text only", profile_id)
    await bot.send_message(receiver_id, caption, reply_markup=reply_markup)


def _reply_keyboard(liker_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❤️ Лайк в ответ", callback_data=f"likeback_{liker_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{liker_id}"),
    ]])


async def _notify_match(bot, liker_id: int, responder_id: int) -> None:
    """Взаимная симпатия: обе стороны получают анкету и @username друг друга.
    После успешной отправки информация о матче (лайки в обе стороны) удаляется из базы."""
    delivered = True
    try:
        await _send_profile_card(bot, responder_id, liker_id, "💞 <b>Взаимная симпатия!</b>", contact=True)
    except TelegramAPIError:
        delivered = False
        logger.info("Could not send contact to the responder %s", responder_id)
    try:
        await _send_profile_card(
            bot, liker_id, responder_id,
            "💞 <b>Ты понравился этому человеку в ответ!</b>\nУ вас взаимная симпатия.",
            contact=True,
        )
    except TelegramAPIError:
        delivered = False
        logger.info("Could not notify the first liker %s", liker_id)
    if delivered:
        remove_like(liker_id, responder_id)
        remove_like(responder_id, liker_id)
    # если кому-то не дошло (например, заблокировал бота), лайки остаются,
    # и следующий лайк повторит отправку


async def _remove_buttons(call: types.CallbackQuery) -> None:
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass


@router.callback_query(F.data.startswith("like_"))
async def like_callback(call: types.CallbackQuery):
    try:
        stranger_id = int(call.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректная анкета", show_alert=True)
        return
    me = call.from_user.id
    if stranger_id == me or not get_user_profile(stranger_id) or not is_profile_active(stranger_id):
        await call.answer("Эта анкета уже недоступна", show_alert=True)
        return
    already = has_like(me, stranger_id)
    reciprocal = has_like(stranger_id, me)
    add_like(me, stranger_id)  # если лайк уже есть, ничего не меняется
    await _remove_buttons(call)

    if reciprocal:
        # Этот человек лайкал нас раньше: взаимная симпатия, данные о матче удаляются из базы
        await call.answer("Взаимная симпатия!")
        await _notify_match(call.bot, stranger_id, me)
    else:
        # Первый лайк или повторный (на прошлый не ответили): человеку приходит запрос
        await call.answer("Лайк отправлен снова" if already else "Лайк отправлен")
        try:
            await _send_profile_card(
                call.bot, stranger_id, me,
                "❤️ <b>Ты понравился этому человеку!</b>\n"
                "Лайкни в ответ, чтобы получить его контакт, или отклони.",
                reply_markup=_reply_keyboard(me),
            )
        except TelegramAPIError:
            logger.info("Could not notify the liked user about a like")
    await call.message.answer("❤️ Лайк обработан. Показываю следующую анкету…")
    await send_random_profile(call, me)


@router.callback_query(F.data.startswith("likeback_"))
async def likeback_callback(call: types.CallbackQuery):
    try:
        liker_id = int(call.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректная анкета", show_alert=True)
        return
    me = call.from_user.id
    await _remove_buttons(call)
    if not has_like(liker_id, me) or not get_user_profile(liker_id) or not is_profile_active(liker_id):
        await call.answer("Этот лайк уже недоступен", show_alert=True)
        return
    if not add_like(me, liker_id):
        await call.answer("Ты уже ответил на этот лайк")
        return
    await call.answer("Взаимная симпатия!")
    await _notify_match(call.bot, liker_id, me)


@router.callback_query(F.data.startswith("reject_"))
async def reject_callback(call: types.CallbackQuery):
    # Отказ: из базы стирается всё, что связывает двоих (лайки и просмотры),
    # как будто они не взаимодействовали. Тому, кто лайкнул, ничего не отправляется.
    try:
        liker_id = int(call.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer()
        return
    clear_interaction(call.from_user.id, liker_id)
    await _remove_buttons(call)
    await call.answer("Анкета отклонена")


@router.callback_query(F.data.startswith("dislike_"))
@router.callback_query(F.data.startswith("next_profile_"))
async def next_profile_callback(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await send_random_profile(call, call.from_user.id)


@router.callback_query(F.data == "stop_search")
async def stop_search_callback(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await call.message.answer("Поиск остановлен. Что делаем дальше?", reply_markup=get_main_menu())


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    try:
        await call.message.edit_text(
            "Главное меню 👇", 
            reply_markup=get_main_menu()
        )
    except TelegramAPIError:
        try:
            await call.message.delete()
        except TelegramAPIError:
            pass
        await call.message.answer("Главное меню 👇", reply_markup=get_main_menu())


@router.callback_query(F.data == "edit_profile")
async def edit_profile_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await begin_registration(call.message, state)