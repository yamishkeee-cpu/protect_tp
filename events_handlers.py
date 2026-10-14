"""Event creation, event discovery, responses and owner management."""
import html
import logging
from datetime import date, datetime, time, timedelta

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from db import get_user, get_user_profile
from events_db import (
    add_event_response,
    close_event_by_owner,
    create_event_full,
    get_active_events_for_search,
    get_event_category_name,
    get_event_detail,
    get_event_responses_list,
    get_responses_count,
    get_user_events_full,
    has_user_responded,
    mark_event_viewed,
    reset_events_viewed,
)
from events_states import EventCreation
from keyboards import (
    get_event_category_keyboard,
    get_event_confirm_keyboard,
    get_event_management_keyboard,
    get_event_search_keyboard,
    get_main_menu,
)
from events_db import get_event_categories_by_type

logger = logging.getLogger(__name__)
router = Router()
events_router = router


def _parse_date(text: str):
    try:
        parsed = datetime.strptime(text.strip(), "%d.%m.%Y").date()
    except (TypeError, ValueError):
        return None
    return parsed


def _display_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return value or "Не указана"


async def _ask_date_choice(message: Message, state: FSMContext):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📅 Одна дата", callback_data="event_date_specific")],
        [types.InlineKeyboardButton(text="🗓️ Диапазон дат", callback_data="event_date_range")],
        [types.InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_event_creation")],
    ])
    await message.answer("Выбери тип даты события:", reply_markup=keyboard)
    await state.set_state(EventCreation.date_choice)


async def _ask_time(message: Message, state: FSMContext):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Без времени", callback_data="event_time_skip")],
    ])
    await message.answer("Введи время начала в формате ЧЧ:ММ или нажми «Без времени»:", reply_markup=keyboard)
    await state.set_state(EventCreation.time_choice)


async def _ask_categories(message: Message, state: FSMContext):
    categories = get_event_categories_by_type()
    if not categories:
        await message.answer("Категории событий не найдены. Обратись к администратору.")
        await state.clear()
        return
    await message.answer("Выбери категорию события:", reply_markup=get_event_category_keyboard(categories))
    await state.set_state(EventCreation.category_choice)


@router.message(F.text == "📅 Поиск мероприятий")
async def event_search_or_create(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📅 <b>Мероприятия</b>\n\nВыбери действие:", reply_markup=get_event_management_keyboard())


@router.callback_query(F.data == "create_event")
async def start_event_creation(call: types.CallbackQuery, state: FSMContext):
    if not get_user_profile(call.from_user.id):
        await call.answer("Сначала заполни постоянный профиль", show_alert=True)
        return
    await state.clear()
    await state.set_state(EventCreation.title)
    await call.message.edit_text(
        "📅 <b>Создание мероприятия</b>\n\nВведи название события (до 100 символов):",
        reply_markup=None,
    )
    await call.answer()


@router.message(EventCreation.title)
async def process_event_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title or len(title) > 100:
        await message.answer("Название должно содержать от 1 до 100 символов. Попробуй ещё раз:")
        return
    await state.update_data(title=title)
    await _ask_date_choice(message, state)


@router.callback_query(EventCreation.date_choice, F.data.in_({"event_date_specific", "event_date_range"}))
async def process_event_date_choice(call: types.CallbackQuery, state: FSMContext):
    date_type = "specific" if call.data == "event_date_specific" else "range"
    await state.update_data(date_type=date_type)
    await call.message.edit_text("Введи дату в формате ДД.ММ.ГГГГ (например, 20.10.2026):", reply_markup=None)
    await state.set_state(EventCreation.date_input)
    await call.answer()


@router.callback_query(EventCreation.date_choice, F.data == "cancel_event_creation")
async def cancel_event_from_date_choice(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Создание мероприятия отменено.", reply_markup=None)
    await call.message.answer("Главное меню:", reply_markup=get_main_menu())
    await call.answer()


@router.message(EventCreation.date_input)
async def process_event_date_input(message: Message, state: FSMContext):
    parsed = _parse_date(message.text or "")
    if not parsed:
        await message.answer("Неверная дата. Используй формат ДД.ММ.ГГГГ, например 20.10.2026:")
        return
    if parsed < date.today():
        await message.answer("Дата события не может быть в прошлом. Введи дату ещё раз:")
        return
    data = await state.get_data()
    await state.update_data(date_start=parsed.isoformat())
    if data.get("date_type") == "range":
        await message.answer("Введи конечную дату диапазона в формате ДД.ММ.ГГГГ:")
        await state.set_state(EventCreation.date_end_input)
    else:
        await state.update_data(date_end=parsed.isoformat())
        await _ask_time(message, state)


@router.message(EventCreation.date_end_input)
async def process_event_date_end_input(message: Message, state: FSMContext):
    parsed = _parse_date(message.text or "")
    data = await state.get_data()
    start = date.fromisoformat(data["date_start"])
    if not parsed:
        await message.answer("Неверная дата. Используй формат ДД.ММ.ГГГГ:")
        return
    if parsed < start:
        await message.answer("Конечная дата не может быть раньше начальной. Введи её ещё раз:")
        return
    await state.update_data(date_end=parsed.isoformat())
    await _ask_time(message, state)


@router.callback_query(EventCreation.time_choice, F.data == "event_time_skip")
async def skip_event_time(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(time_start=None)
    await call.message.edit_text("Время не указано.", reply_markup=None)
    await _ask_categories(call.message, state)
    await call.answer()


@router.message(EventCreation.time_choice)
async def process_event_time_choice(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    try:
        parsed_time = datetime.strptime(value, "%H:%M").time()
    except ValueError:
        await message.answer("Введи время в формате ЧЧ:ММ, например 14:30, или нажми «Без времени».")
        return
    await state.update_data(time_start=parsed_time.strftime("%H:%M"))
    await _ask_categories(message, state)


@router.callback_query(EventCreation.category_choice, F.data.startswith("event_category_"))
async def process_event_category_selected(call: types.CallbackQuery, state: FSMContext):
    try:
        category_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректная категория", show_alert=True)
        return
    category_name = get_event_category_name(category_id)
    if not category_name:
        await call.answer("Категория не найдена", show_alert=True)
        return
    await state.update_data(category_id=category_id, category_name=category_name)
    await call.message.edit_text(
        f"Выбрана категория: <b>{html.escape(category_name)}</b>\n\n"
        "Сколько участников нужно для этого мероприятия? Введи число от 1 до 1000:",
        reply_markup=None,
    )
    await state.set_state(EventCreation.people_needed_choice)
    await call.answer()


@router.message(EventCreation.people_needed_choice)
async def process_event_people_needed_choice(message: Message, state: FSMContext):
    value = (message.text or "").strip().lower()
    if not value.isdecimal() or int(value) < 1 or int(value) > 1000:
        await message.answer("Введи целое число от 1 до 1000.")
        return
    await state.update_data(people_needed=int(value))
    await message.answer("Напиши описание события или отправь «пропустить»:")
    await state.set_state(EventCreation.description)


@router.message(EventCreation.description)
async def process_event_description(message: Message, state: FSMContext):
    description = (message.text or "").strip()
    if description.lower() in {"пропустить", "нет", "skip"}:
        description = ""
    if len(description) > 1500:
        await message.answer("Описание слишком длинное. Максимум — 1500 символов.")
        return
    await state.update_data(description=description)
    await message.answer("Укажи место проведения или отправь «пропустить»:")
    await state.set_state(EventCreation.location)


@router.message(EventCreation.location)
async def process_event_location(message: Message, state: FSMContext):
    location = (message.text or "").strip()
    if location.lower() in {"пропустить", "нет", "skip"}:
        location = ""
    if len(location) > 250:
        await message.answer("Место должно быть не длиннее 250 символов.")
        return
    await state.update_data(location=location)
    data = await state.get_data()
    start_display = _display_date(data["date_start"])
    end_display = _display_date(data.get("date_end") or data["date_start"])
    date_display = start_display if start_display == end_display else f"{start_display} — {end_display}"
    people = str(data["people_needed"]) if data.get("people_needed") else "Не указано"
    text = (
        "📅 <b>Проверь мероприятие</b>\n\n"
        f"📝 <b>Название:</b> {html.escape(data['title'])}\n"
        f"📅 <b>Дата:</b> {html.escape(date_display)}\n"
        f"🕐 <b>Время:</b> {html.escape(data.get('time_start') or 'Не указано')}\n"
        f"🏷️ <b>Категория:</b> {html.escape(data.get('category_name') or 'Не выбрана')}\n"
        f"👥 <b>Нужно участников:</b> {html.escape(people)}\n"
        f"📄 <b>Описание:</b> {html.escape(data.get('description') or 'Не указано')}\n"
        f"📍 <b>Место:</b> {html.escape(location or 'Не указано')}\n\nСоздать событие?"
    )
    await message.answer(text, reply_markup=get_event_confirm_keyboard())
    await state.set_state(EventCreation.confirm)


@router.callback_query(EventCreation.confirm, F.data == "cancel_event_creation")
async def cancel_event_creation(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Создание мероприятия отменено.", reply_markup=None)
    await call.message.answer("Главное меню:", reply_markup=get_main_menu())
    await call.answer()


@router.callback_query(EventCreation.confirm, F.data == "confirm_event_creation")
async def confirm_event_creation(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    try:
        event_id = create_event_full(
            user_id=call.from_user.id,
            title=data["title"],
            date_start=data["date_start"],
            date_end=data.get("date_end") or data["date_start"],
            time_start=data.get("time_start"),
            category_id=data.get("category_id"),
            people_needed=data.get("people_needed"),
            description=data.get("description", ""),
            location=data.get("location", ""),
        )
    except (ValueError, KeyError):
        logger.exception("Invalid event creation data for user %s", call.from_user.id)
        await call.answer("Не удалось создать событие. Проверь данные и попробуй ещё раз.", show_alert=True)
        return
    except Exception:
        logger.exception("Failed to create event for user %s", call.from_user.id)
        await call.answer("Ошибка базы данных при создании события", show_alert=True)
        return
    await state.clear()
    await call.message.edit_text(
        f"✅ <b>Мероприятие создано!</b>\nНомер анкеты: #{event_id}.\n"
        "Оно будет доступно для поиска до дня после окончания события.",
        reply_markup=None,
    )
    await call.message.answer("Главное меню:", reply_markup=get_main_menu())
    await call.answer("Событие сохранено")


@router.callback_query(F.data == "search_events")
async def start_event_search(call: types.CallbackQuery):
    if not get_user_profile(call.from_user.id):
        await call.answer("Сначала заполни постоянный профиль", show_alert=True)
        return
    await call.answer()
    await send_random_event(call, call.from_user.id)


async def send_random_event(message_or_call, user_id: int):
    target = message_or_call.message if isinstance(message_or_call, types.CallbackQuery) else message_or_call
    events = get_active_events_for_search(user_id)
    if not events:
        reset_events_viewed(user_id)
        await target.answer(
            "🎉 Сейчас нет новых доступных мероприятий. История просмотра сброшена — попробуй поиск позже.",
            reply_markup=get_main_menu(),
        )
        return
    event = events[0]
    (event_id, title, date_start, date_end, time_start, people_needed,
     description, location, category_name, category_type, creator_name, creator_photo, participant_profile_id) = event
    mark_event_viewed(user_id, event_id)
    date_display = _display_date(date_start)
    if date_end and date_end != date_start:
        date_display += f" — {_display_date(date_end)}"
    text = (
        "📅 <b>Мероприятие</b>\n\n"
        f"📝 <b>Название:</b> {html.escape(title or '')}\n"
        f"📅 <b>Дата:</b> {html.escape(date_display)}\n"
        f"🕐 <b>Время:</b> {html.escape(time_start or 'Не указано')}\n"
        f"🏷️ <b>Категория:</b> {html.escape(category_name or 'Не указана')}\n"
        f"👥 <b>Нужно участников:</b> {html.escape(str(people_needed) if people_needed else 'Не указано')}\n"
        f"📄 <b>Описание:</b> {html.escape((description or 'Не указано')[:800])}\n"
        f"📍 <b>Место:</b> {html.escape(location or 'Не указано')}\n"
        f"👤 <b>Организатор:</b> {html.escape(creator_name or 'Не указан')}\n"
        f"🧩 <b>Анкета события:</b> #{participant_profile_id}"
    )
    keyboard = get_event_search_keyboard(event_id, has_user_responded(event_id, user_id))
    if creator_photo and len(text) <= 950:
        await target.answer_photo(photo=creator_photo, caption=text, reply_markup=keyboard)
    elif creator_photo:
        # Telegram captions are shorter than normal messages. Keep the controls
        # attached to the image and deliver the complete details separately.
        await target.answer_photo(
            photo=creator_photo,
            caption="📅 <b>Мероприятие</b>",
            reply_markup=keyboard,
        )
        await target.answer(text)
    else:
        await target.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("event_next_"))
async def next_event_callback(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await send_random_event(call, call.from_user.id)


@router.callback_query(F.data == "already_responded")
async def already_responded_callback(call: types.CallbackQuery):
    await call.answer("Ты уже откликнулся на это мероприятие")


@router.callback_query(F.data == "stop_event_search")
async def stop_event_search(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await call.message.answer("Поиск мероприятий остановлен.", reply_markup=get_main_menu())


@router.callback_query(F.data.startswith("event_respond_"))
async def event_respond_callback(call: types.CallbackQuery):
    try:
        event_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректное событие", show_alert=True)
        return
    event = get_event_detail(event_id)
    if not event:
        await call.answer("Событие уже недоступно", show_alert=True)
        return
    response_id = add_event_response(event_id, call.from_user.id)
    await call.answer("Отклик отправлен" if response_id else "Вы уже откликались или событие недоступно",
                      show_alert=not bool(response_id))
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    if response_id:
        creator_id = event[1]
        responder = get_user_profile(call.from_user.id) or get_user(call.from_user.id)
        responder_name = responder[0] if responder else (call.from_user.full_name or "Пользователь")
        link = f'<a href="tg://user?id={call.from_user.id}">Открыть профиль в Telegram</a>'
        try:
            await call.bot.send_message(
                creator_id,
                "🔔 <b>Новый отклик на мероприятие!</b>\n\n"
                f"📝 Событие: {html.escape(event[2] or '')}\n"
                f"👤 Откликнулся: {html.escape(responder_name or 'Пользователь')}\n{link}",
            )
        except TelegramAPIError:
            logger.info("Could not notify event owner %s", creator_id)
        await call.message.answer("✅ Отклик отправлен организатору.")
        await send_random_event(call, call.from_user.id)


@router.callback_query(F.data == "my_events")
async def show_my_events(call: types.CallbackQuery):
    events = get_user_events_full(call.from_user.id)
    if not events:
        await call.message.edit_text("У тебя пока нет созданных мероприятий.", reply_markup=None)
        await call.answer()
        return
    lines = ["📋 <b>Твои мероприятия</b>\n"]
    buttons = []
    for row in events:
        event_id, title, date_start, date_end, time_start, people_needed, description, location, category_id, status = row[:10]
        date_display = _display_date(date_start)
        if date_end and date_end != date_start:
            date_display += f" — {_display_date(date_end)}"
        status_text = {"active": "Активно", "closed": "Закрыто", "expired": "Истекло"}.get(status, status)
        count = get_responses_count(event_id)
        lines.append(
            f"<b>#{event_id} {html.escape(title)}</b>\n"
            f"📅 {html.escape(date_display)} · {html.escape(status_text)}\n"
            f"🙋 Откликов: {count}{f' / {people_needed}' if people_needed else ''}\n"
        )
        if status == "active":
            buttons.append([types.InlineKeyboardButton(text=f"Закрыть #{event_id}", callback_data=f"close_event_{event_id}")])
        buttons.append([types.InlineKeyboardButton(text=f"Отклики #{event_id}", callback_data=f"event_responses_{event_id}")])
    buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    await call.message.edit_text("\n".join(lines), reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@router.callback_query(F.data.startswith("close_event_"))
async def close_my_event(call: types.CallbackQuery):
    try:
        event_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректный номер", show_alert=True)
        return
    close_event_by_owner(event_id, call.from_user.id)
    await show_my_events(call)


@router.callback_query(F.data.startswith("event_responses_"))
async def show_event_responses(call: types.CallbackQuery):
    try:
        event_id = int(call.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await call.answer("Некорректный номер", show_alert=True)
        return
    responses = get_event_responses_list(event_id, call.from_user.id)
    if not responses:
        await call.message.edit_text("На это мероприятие пока нет откликов или оно не принадлежит тебе.", reply_markup=None)
        await call.answer()
        return
    lines = [f"💬 <b>Отклики на мероприятие #{event_id}</b>\n"]
    for row in responses:
        _, user_id, created_at, name, photo, year, group, faculty = row
        lines.append(
            f"👤 {html.escape(name or 'Без имени')} — "
            f"{html.escape(group or 'группа не указана')}\n"
            f"<a href=\"tg://user?id={user_id}\">Связаться в Telegram</a>\n"
        )
    back = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔙 К моим мероприятиям", callback_data="my_events")]
    ])
    await call.message.edit_text("\n".join(lines), reply_markup=back)
    await call.answer()


@router.callback_query(F.data == "my_event_responses")
async def show_my_responses(call: types.CallbackQuery):
    events = get_user_events_full(call.from_user.id)
    if not events:
        await call.message.edit_text("У тебя пока нет созданных мероприятий.", reply_markup=None)
        await call.answer()
        return
    lines = ["💬 <b>Отклики на твои мероприятия</b>\n"]
    buttons = []
    for row in events:
        event_id, title, start_date, end_date, _, people_needed, *_ = row
        count = get_responses_count(event_id)
        lines.append(f"<b>#{event_id} {html.escape(title)}</b> — откликов: {count}\n")
        if count:
            buttons.append([types.InlineKeyboardButton(text=f"Посмотреть #{event_id}", callback_data=f"event_responses_{event_id}")])
    buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    await call.message.edit_text("\n".join(lines), reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()
