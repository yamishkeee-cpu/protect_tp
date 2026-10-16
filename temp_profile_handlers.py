"""Temporary profiles: creation, browsing, interest and owner management."""
import html
import logging
from datetime import datetime

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from db import get_user, get_user_profile
from keyboards import (
    FACULTY_LIST,
    get_duration_keyboard,
    get_field_choice_keyboard,
    get_main_menu,
    get_temp_profile_keyboard,
    get_temp_profile_menu_keyboard,
    get_temp_search_keyboard,
)
from temp_profile_db import (
    add_temp_profile_response,
    close_temp_profile,
    get_active_temp_profiles_for_search,
    get_temp_profile_by_id,
    get_user_temp_profiles,
    mark_temp_viewed,
    reset_temp_viewed,
    save_temp_profile_with_partial_fill,
)
from temp_profile_states import TempProfile

logger = logging.getLogger(__name__)
router = Router()
temp_profile_router = router

FIELD_PROMPTS = {
    "name": "👤 <b>Имя</b>\nКак указать имя во временной анкете?",
    "start_year": "📅 <b>Год поступления</b>\nКак указать год?",
    "group_num": "👥 <b>Группа</b>\nКак указать номер группы?",
    "faculty": "🎓 <b>Направление</b>\nКак указать направление?",
    "photo": "📸 <b>Фотография</b>\nКак указать фото?",
}
FIELD_INPUTS = {
    "name": TempProfile.name_input,
    "start_year": TempProfile.year_input,
    "group_num": TempProfile.group_input,
    "photo": TempProfile.photo,
}
FIELD_STATES = {
    "name": TempProfile.name_choice,
    "start_year": TempProfile.year_choice,
    "group_num": TempProfile.group_choice,
    "faculty": TempProfile.faculty_choice,
    "photo": TempProfile.photo_choice,
}
NEXT_FIELD = {
    "name": "start_year",
    "start_year": "group_num",
    "group_num": "faculty",
    "faculty": "photo",
    "photo": "description",
}


async def _show_field_choice(target: Message, field_name: str, state: FSMContext, edit=False):
    text = FIELD_PROMPTS[field_name]
    markup = get_field_choice_keyboard(field_name)
    if edit:
        await target.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)
    await state.set_state(FIELD_STATES[field_name])


async def _show_description_prompt(target: Message, state: FSMContext, edit=False):
    text = "📝 Напиши короткое описание задачи или команды. Можно отправить «пропустить»."
    if edit:
        await target.edit_text(text)
    else:
        await target.answer(text)
    await state.set_state(TempProfile.description)


async def _after_field_choice(call: types.CallbackQuery, state: FSMContext, field_name: str, choice: str):
    next_field = NEXT_FIELD[field_name]
    if choice == "manual":
        if field_name == "faculty":
            await call.message.edit_text(
                "Выбери направление для временной анкеты:",
                reply_markup=__import__("keyboards").get_faculty_keyboard(),
            )
            await state.set_state(TempProfile.faculty)
        else:
            labels = {
                "name": "Введите имя или никнейм (до 50 символов):",
                "start_year": "Введите год поступления (например, 2024):",
                "group_num": "Введите номер группы (например, БИ-201):",
                "photo": "Отправьте одну фотографию для временной анкеты:",
            }
            await call.message.edit_text(labels[field_name], reply_markup=None)
            await state.set_state(FIELD_INPUTS[field_name])
        return

    # None means inherit from the permanent profile; empty string means skip.
    await state.update_data(**{field_name: None if choice == "from_profile" else ""})
    if next_field == "description":
        await _show_description_prompt(call.message, state, edit=True)
    else:
        await _show_field_choice(call.message, next_field, state, edit=True)


@router.message(F.text == "🎯 Поиск для задач/проектов")
async def temp_profile_menu(message: Message, state: FSMContext):
    await state.clear()
    if not get_user_profile(message.from_user.id):
        await message.answer(
            "Сначала заполни постоянный профиль, чтобы создавать и просматривать временные анкеты.",
            reply_markup=get_main_menu(),
        )
        return
    await message.answer("🎯 <b>Поиск для задач и проектов</b>\n\nВыбери действие:",
                         reply_markup=get_temp_profile_menu_keyboard())


@router.callback_query(F.data == "create_temp_profile")
async def temp_profile_start(call: types.CallbackQuery, state: FSMContext):
    if not get_user_profile(call.from_user.id):
        await call.answer("Сначала заполни постоянный профиль", show_alert=True)
        return
    await state.clear()
    await state.set_state(TempProfile.goal_choice)
    await call.message.edit_text(
        "📋 <b>Создание временной анкеты</b>\n\nВыбери цель поиска:",
        reply_markup=get_temp_profile_keyboard(),
    )
    await call.answer()


@router.callback_query(TempProfile.goal_choice, F.data.in_({"goal_seek", "goal_offer"}))
async def process_goal_choice(call: types.CallbackQuery, state: FSMContext):
    goal = "ищу_людей" if call.data == "goal_seek" else "предлагаю_себя"
    await state.update_data(goal=goal)
    await _show_field_choice(call.message, "name", state, edit=True)
    await call.answer()


@router.callback_query(TempProfile.name_choice, F.data.startswith("name_"))
async def process_name_choice(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await _after_field_choice(call, state, "name", call.data.removeprefix("name_"))


@router.message(TempProfile.name_input)
async def process_name_input(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name or len(name) > 50:
        await message.answer("Введите имя длиной от 1 до 50 символов.")
        return
    await state.update_data(name=name)
    await _show_field_choice(message, "start_year", state)


@router.callback_query(TempProfile.year_choice, F.data.startswith("start_year_"))
async def process_year_choice(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await _after_field_choice(call, state, "start_year", call.data.removeprefix("start_year_"))


@router.message(TempProfile.year_input)
async def process_year_input(message: Message, state: FSMContext):
    year_text = (message.text or "").strip()
    if not year_text.isdecimal() or not 2000 <= int(year_text) <= 2035:
        await message.answer("Введите корректный год цифрами (от 2000 до 2035).")
        return
    await state.update_data(start_year=year_text)
    await _show_field_choice(message, "group_num", state)


@router.callback_query(TempProfile.group_choice, F.data.startswith("group_num_"))
async def process_group_choice(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await _after_field_choice(call, state, "group_num", call.data.removeprefix("group_num_"))


@router.message(TempProfile.group_input)
async def process_group_input(message: Message, state: FSMContext):
    group = (message.text or "").strip()
    if not group or len(group) > 30:
        await message.answer("Введите номер группы длиной от 1 до 30 символов.")
        return
    await state.update_data(group_num=group)
    await _show_field_choice(message, "faculty", state)


@router.callback_query(TempProfile.faculty_choice, F.data.startswith("faculty_"))
async def process_faculty_choice(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await _after_field_choice(call, state, "faculty", call.data.removeprefix("faculty_"))


@router.callback_query(TempProfile.faculty, F.data.startswith("faculty_"))
async def process_faculty_manual(call: types.CallbackQuery, state: FSMContext):
    try:
        index = int(call.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректное направление", show_alert=True)
        return
    if not 0 <= index < len(FACULTY_LIST):
        await call.answer("Такого направления нет", show_alert=True)
        return
    await state.update_data(faculty=FACULTY_LIST[index])
    await call.message.edit_reply_markup(reply_markup=None)
    await _show_field_choice(call.message, "photo", state, edit=True)
    await call.answer()


@router.callback_query(TempProfile.photo_choice, F.data.startswith("photo_"))
async def process_photo_choice(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await _after_field_choice(call, state, "photo", call.data.removeprefix("photo_"))


@router.message(TempProfile.photo)
async def process_photo(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Пожалуйста, отправьте именно фотографию или отмените действие командой /cancel.")
        return
    await state.update_data(photo=message.photo[-1].file_id)
    await _show_description_prompt(message, state)


@router.message(TempProfile.description)
async def process_description(message: Message, state: FSMContext):
    description = (message.text or "").strip()
    if description.lower() in {"пропустить", "нет", "skip"}:
        description = ""
    if len(description) > 1000:
        await message.answer("Описание слишком длинное. Максимум — 1000 символов.")
        return
    await state.update_data(description=description)
    data = await state.get_data()
    def value(key, fallback):
        item = data.get(key)
        if item is None:
            return fallback
        return item or "Не указано"
    profile = get_user_profile(message.from_user.id) or (None, None, None, None, None)
    name = value("name", profile[0] or "Не указано")
    year = value("start_year", profile[1] or "Не указан")
    group = value("group_num", profile[2] or "Не указана")
    faculty = value("faculty", profile[3] or "Не указано")
    photo = data.get("photo") if data.get("photo") is not None else profile[4]
    goal = "Ищу людей" if data.get("goal") == "ищу_людей" else "Предлагаю себя"
     text = (
        "📋 <b>Проверь временную анкету</b>\n\n"
        f"👤 <b>Имя:</b> {html.escape(str(name))}\n"
        f"📅 <b>Год:</b> {html.escape(str(year))}\n"
        f"👥 <b>Группа:</b> {html.escape(str(group))}\n"
        f"🎓 <b>Направление:</b> {html.escape(str(faculty))}\n"
        f"📸 <b>Фото:</b> {'есть' if photo else 'не указано'}\n"
        f"🎯 <b>Цель:</b> {goal}\n"
        f"📝 <b>Описание:</b> {html.escape(description or 'Не указано')}\n\n"
        "⏳ <b>На сколько дней разместить анкету?</b>"
    )
    await message.answer(text, reply_markup=get_duration_keyboard())
    await state.set_state(TempProfile.duration_choice)


@router.callback_query(TempProfile.confirm, F.data == "confirm_temp_profile_no")
async def cancel_temp_profile(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Создание временной анкеты отменено.", reply_markup=None)
    await call.message.answer("Главное меню:", reply_markup=get_main_menu())
    await call.answer()


@router.callback_query(TempProfile.confirm, F.data == "confirm_temp_profile_yes")
async def confirm_temp_profile(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    field_data = {
        "name": data.get("name"),
        "start_year": data.get("start_year"),
        "group_num": data.get("group_num"),
        "faculty": data.get("faculty"),
        "photo": data.get("photo"),
        "goal": data.get("goal"),
        "description": data.get("description", ""),
    }
    try:
        temp_id = save_temp_profile_with_partial_fill(call.from_user.id, field_data)
    except Exception:
        logger.exception("Failed to save temporary profile for user %s", call.from_user.id)
        await call.answer("Не удалось сохранить анкету", show_alert=True)
        return
    await state.clear()
    await call.message.edit_text(f"✅ Временная анкета создана! Её номер: {temp_id}. Она будет активна 3 дня.", reply_markup=None)
    await call.message.answer("Главное меню:", reply_markup=get_main_menu())
    await call.answer("Анкета сохранена")


async def send_next_temp_profile(message_or_call, user_id: int):
    target = message_or_call.message if isinstance(message_or_call, types.CallbackQuery) else message_or_call
    profile = get_active_temp_profiles_for_search(user_id)
    if not profile:
        # Begin a new personal cycle only after all currently active profiles have
        # been seen. This does not clear anyone else's view history.
        reset_temp_viewed(user_id)
        await target.answer(
            "🎉 Новых временных анкет пока нет. История просмотра сброшена — попробуй позже.",
            reply_markup=get_main_menu(),
        )
        return
    temp_id, name, year, group, faculty, photo, goal, description, owner_id, event_id, event_title, event_date_start, event_date_end, event_people_needed = profile
    mark_temp_viewed(user_id, temp_id)
    goal_text = "Ищу людей" if goal == "ищу_людей" else "Предлагаю себя"
    event_line = ""
    if event_id and event_title:
        event_date = event_date_start or ""
        if event_date_end and event_date_end != event_date_start:
            event_date += f" — {event_date_end}"
        event_line = (
            f"\n📅 <b>Мероприятие:</b> {html.escape(event_title)}"
            f"\n🗓️ <b>Дата:</b> {html.escape(event_date)}"
            f"\n👥 <b>Нужно участников:</b> {html.escape(str(event_people_needed or '—'))}"
            f"\n🔗 <b>Анкета события:</b> #{event_id}"
        )
    caption = (
        ("📅 <b>Анкета участника мероприятия</b>\n" if event_id else "🎯 <b>Анкета для задачи или проекта</b>\n") +
        f"👤 Имя: {html.escape(name or 'Не указано')}\n"
        f"📅 Год поступления: {html.escape(year or 'Не указан')}\n"
        f"👥 Группа: {html.escape(group or 'Не указана')}\n"
        f"🎓 Направление: {html.escape(faculty or 'Не указано')}\n"
        f"🎯 Цель: {goal_text}\n"
        f"📝 Описание: {html.escape((description or 'Не указано')[:700])}"
        f"{event_line}"
    )
    keyboard = get_temp_search_keyboard(temp_id)
    if photo and len(caption) <= 950:
        await target.answer_photo(photo=photo, caption=caption, reply_markup=keyboard)
    elif photo:
        # Telegram limits photo captions to 1024 characters; longer cards must
        # keep their buttons on the photo and send the full details separately.
        await target.answer_photo(
            photo=photo,
            caption="🎯 <b>Анкета для задачи или проекта</b>",
            reply_markup=keyboard,
        )
        await target.answer(caption)
    else:
        await target.answer(caption, reply_markup=keyboard)


@router.callback_query(F.data == "search_temp_profiles")
async def start_temp_profile_search(call: types.CallbackQuery):
    if not get_user_profile(call.from_user.id):
        await call.answer("Сначала заполни постоянный профиль", show_alert=True)
        return
    await call.answer()
    await send_next_temp_profile(call, call.from_user.id)


@router.callback_query(F.data.startswith("temp_next_"))
async def next_temp_profile_callback(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await send_next_temp_profile(call, call.from_user.id)


@router.callback_query(F.data.startswith("temp_interest_"))
async def temp_profile_interest_callback(call: types.CallbackQuery):
    try:
        temp_id = int(call.data.split("_", 2)[2])
    except (ValueError, IndexError):
        await call.answer("Некорректная анкета", show_alert=True)
        return
    profile = get_temp_profile_by_id(temp_id)
    if not profile:
        await call.answer("Анкета уже недоступна", show_alert=True)
        return
    owner_id = profile[1]
    success = add_temp_profile_response(temp_id, call.from_user.id)
    await call.answer("Отклик отправлен" if success else "Вы уже откликались или анкета недоступна")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    if success:
        sender = get_user_profile(call.from_user.id) or get_user(call.from_user.id)
        sender_name = sender[0] if sender else (call.from_user.full_name or "Пользователь")
        link = f'<a href="tg://user?id={call.from_user.id}">Открыть профиль в Telegram</a>'
        try:
            await call.bot.send_message(
                owner_id,
                "🙋 <b>Новый отклик на временную анкету!</b>\n\n"
                f"Анкета: {html.escape(profile[2] or 'Без имени')}\n"
                f"Откликнулся: {html.escape(sender_name or 'Пользователь')}\n{link}",
            )
        except TelegramAPIError:
            logger.info("Could not notify temporary-profile owner %s", owner_id)
        await call.message.answer("✅ Отклик отправлен автору анкеты.")
    await send_next_temp_profile(call, call.from_user.id)


@router.callback_query(F.data == "temp_stop_search")
async def stop_temp_search_callback(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await call.message.answer("Поиск временных анкет остановлен.", reply_markup=get_main_menu())


@router.callback_query(F.data == "my_temp_profiles")
async def show_my_temp_profiles(call: types.CallbackQuery):
    profiles = get_user_temp_profiles(call.from_user.id)
    if not profiles:
        await call.message.edit_text("У тебя пока нет активных временных анкет.", reply_markup=None)
        await call.answer()
        return
    buttons = []
    lines = ["📋 <b>Твои активные временные анкеты</b>\n"]
    now = datetime.now()
    for row in profiles:
        temp_id, name, year, group, faculty, photo, goal, description, created_at, expires_at = row
        lines.append(
            f"<b>#{temp_id} {html.escape(name or 'Без имени')}</b> — "
            f"{html.escape(goal or 'цель не указана')}\n"
            f"Истекает: {html.escape(str(expires_at))}\n"
        )
        buttons.append([types.InlineKeyboardButton(text=f"Закрыть #{temp_id}", callback_data=f"close_temp_{temp_id}")])
    buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    await call.message.edit_text("\n".join(lines), reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@router.callback_query(F.data.startswith("close_temp_"))
async def close_my_temp_profile(call: types.CallbackQuery):
    try:
        temp_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректный номер", show_alert=True)
        return
    success = close_temp_profile(temp_id, call.from_user.id)
    await call.answer("Анкета закрыта" if success else "Не удалось закрыть анкету", show_alert=not success)
    profiles = get_user_temp_profiles(call.from_user.id)
    if not profiles:
        await call.message.edit_text("Активных временных анкет больше нет.", reply_markup=None)
        return
    lines = ["📋 <b>Твои активные временные анкеты</b>\n"]
    buttons = []
    for row in profiles:
        pid, name, year, group, faculty, photo, goal, description, created_at, expires_at = row
        lines.append(f"<b>#{pid} {html.escape(name or 'Без имени')}</b> — {html.escape(goal or '')}\nИстекает: {html.escape(str(expires_at))}\n")
        buttons.append([types.InlineKeyboardButton(text=f"Закрыть #{pid}", callback_data=f"close_temp_{pid}")])
    buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    await call.message.edit_text("\n".join(lines), reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
