"""Permanent profile registration, profile browsing, and mutual likes."""
import html
import logging

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from db import (
    add_like,
    get_random_stranger,
    get_user,
    get_user_profile,
    has_like,
    mark_stranger_viewed,
    reset_all_viewed,
    save_user,
)
from keyboards import FACULTY_LIST, get_faculty_keyboard, get_main_menu, get_search_keyboard
from states import Anketa
from aiogram.types import LinkPreviewOptions
logger = logging.getLogger(__name__)
router = Router()
PROFILE_DELAY = 0.2

POLICY_URL = "https://telegra.ph/Politika-konfidencialnosti-10-14-105"
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
    await call.message.answer("Отправь одну свою фотографию:")
    await state.set_state(Anketa.photo)
    await call.answer()


@router.message(Anketa.faculty)
async def process_faculty_direct(message: Message):
    await message.answer("Пожалуйста, выбери направление кнопкой ниже:", reply_markup=get_faculty_keyboard())


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
        )
    except Exception:
        logger.exception("Failed to save permanent profile for user %s", message.from_user.id)
        await message.answer("Не удалось сохранить профиль. Попробуй ещё раз позже.")
        return
    await state.clear()
    await message.answer("🎉 Профиль сохранён! Теперь можно искать людей.", reply_markup=get_main_menu())


@router.message(F.text == "👤 Мой профиль")
async def show_my_profile(message: Message, state: FSMContext):
    user = get_user_profile(message.from_user.id) or get_user(message.from_user.id)
    if not user:
        await message.answer("Ты ещё не заполнил анкету. Нажми «📝 Заполнить заново».", reply_markup=get_main_menu())
        return
    name, start_year, group_num, faculty, photo = user
    caption = (
        "📝 <b>Твой профиль</b>\n"
        f"👤 Имя: {html.escape(name or 'Не указано')}\n"
        f"📅 Год поступления: {html.escape(start_year or 'Не указан')}\n"
        f"👥 Группа: {html.escape(group_num or 'Не указана')}\n"
        f"🎓 Направление: {html.escape(faculty or 'Не указано')}"
    )
    if photo:
        try:
            await message.answer_photo(photo=photo, caption=caption, reply_markup=get_main_menu())
            return
        except TelegramBadRequest:
            # Фото устарело (например, сменился бот): просим загрузить заново, остальные данные оставляем
            logger.warning("Broken photo file_id for user %s", message.from_user.id)
            await state.update_data(name=name, start_year=start_year, group_num=group_num, faculty=faculty)
            await state.set_state(Anketa.photo)
            await message.answer("Твоё фото больше не открывается. Отправь, пожалуйста, новую фотографию:",
                                 reply_markup=ReplyKeyboardRemove())
            return
    await message.answer(caption, reply_markup=get_main_menu())


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
            f"🎓 Направление: {html.escape(faculty or 'Не указано')}"
        )
        keyboard = get_search_keyboard(profile_id)
        if not photo:
            continue
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


async def _send_liker_profile(bot, receiver_id: int, liker_id: int, mutual: bool) -> None:
    profile = get_user_profile(liker_id) or get_user(liker_id)
    if not profile:
        await bot.send_message(receiver_id, "Кто-то поставил тебе лайк, но его профиль уже недоступен.")
        return
    name, year, group_num, faculty, photo = profile
    link = f'<a href="tg://user?id={liker_id}">Открыть профиль в Telegram</a>'
    intro = "💞 <b>У вас взаимная симпатия!</b>" if mutual else "❤️ <b>Кому-то понравилась твоя анкета!</b>"
    caption = (
        f"{intro}\n\n"
        f"👤 Имя: {html.escape(name or 'Не указано')}\n"
        f"📅 Год поступления: {html.escape(year or 'Не указан')}\n"
        f"👥 Группа: {html.escape(group_num or 'Не указана')}\n"
        f"🎓 Направление: {html.escape(faculty or 'Не указано')}\n\n{link}"
    )
    if photo:
        try:
            await bot.send_photo(receiver_id, photo=photo, caption=caption)
            return
        except TelegramBadRequest:
            logger.warning("Broken photo for liker %s, sending text only", liker_id)
    await bot.send_message(receiver_id, caption)


@router.callback_query(F.data.startswith("like_"))
async def like_callback(call: types.CallbackQuery):
    try:
        stranger_id = int(call.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректная анкета", show_alert=True)
        return
    if stranger_id == call.from_user.id or not get_user_profile(stranger_id):
        await call.answer("Эта анкета уже недоступна", show_alert=True)
        return
    reciprocal = has_like(stranger_id, call.from_user.id)
    is_new_like = add_like(call.from_user.id, stranger_id)
    await call.answer("Лайк отправлен" if is_new_like else "Ты уже ставил лайк этой анкете")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    if is_new_like:
        try:
            await _send_liker_profile(call.bot, stranger_id, call.from_user.id, reciprocal)
        except TelegramAPIError:
            logger.info("Could not notify the liked user about a like")
        if reciprocal:
            try:
                await _send_liker_profile(call.bot, call.from_user.id, stranger_id, True)
            except TelegramAPIError:
                logger.info("Could not notify the current user about a mutual like")
    await call.message.answer("❤️ Лайк обработан. Показываю следующую анкету…")
    await send_random_profile(call, call.from_user.id)


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
    await call.message.answer("Главное меню:", reply_markup=get_main_menu())


@router.callback_query(F.data == "edit_profile")
async def edit_profile_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await begin_registration(call.message, state)