from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.markdown import hbold
import html
from datetime import datetime, timedelta

from db import get_user, get_user_profile
from keyboards import get_main_menu
from events_db import (
    create_event_full,
    get_active_events_for_search,
    get_event_detail,
    add_event_response,
    get_event_responses_list,
    has_user_responded,
    mark_event_viewed,
    reset_events_viewed,
    close_event_by_owner,
    extend_event_by_owner,
    get_user_events_full,
    get_event_category_name,
    get_event_categories_by_type
)
from temp_profile_db import get_user_temp_profiles
from events_states import EventCreation

router = Router()
events_router = router  # Экспортируем роутер для bot.py

# ==================== СОЗДАНИЕ АНКЕТЫ СОБЫТИЯ ====================

@router.message(F.text == "📅 Поиск мероприятий")
async def event_search_start(message: Message, state: FSMContext):
    """Начинает процесс создания анкеты события."""
    await message.answer(
        "📅 <b>Создание анкеты мероприятия</b>\n\n"
        "Введите название события (обязательно):",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(EventCreation.title)

@router.message(EventCreation.title)
async def process_event_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if not title:
        await message.answer("Название события не может быть пустым. Пожалуйста, введите название:")
        return

    await state.update_data(title=title)
    await message.answer(
        "Выберите тип даты события:\n"
        "• Конкретная дата (например, 20.10.2026)\n"
        "• Диапазон дат (например, с 20 по 23 октября)"
    )
    await state.set_state(EventCreation.date_choice)

@router.message(EventCreation.date_choice)
async def process_event_date_choice(message: Message, state: FSMContext):
    choice = message.text.strip().lower()
    if choice in ["конкретная дата", "конкретная", "одна дата"]:
        await state.update_data(date_type="specific")
        await message.answer(
            "Введите дату события в формате ДД.ММ.ГГГГ (например, 20.10.2026):"
        )
        await state.set_state(EventCreation.date_input)
    elif choice in ["диапазон дат", "диапазон", "с ... по"]:
        await state.update_data(date_type="range")
        await message.answer(
            "Введите начальную дату диапазона в формате ДД.ММ.ГГГГ (например, 20.10.2026):"
        )
        await state.set_state(EventCreation.date_input)
    else:
        await message.answer("Пожалуйста, выберите: 'конкретная дата' или 'диапазон дат':")

@router.message(EventCreation.date_input)
async def process_event_date_input(message: Message, state: FSMContext):
    date_str = message.text.strip()
    # Простая проверка формата ДД.ММ.ГГГГ
    parts = date_str.split('.')
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        await message.answer(
            "Неверный формат даты. Пожалуйста, введите дату в формате ДД.ММ.ГГГГ (например, 20.10.2026):"
        )
        return

    day, month, year = parts
    if len(day) != 2 or len(month) != 2 or len(year) != 4:
        await message.answer(
            "Неверный формат даты. Используйте ДД.ММ.ГГГГ (например, 20.10.2026):"
        )
        return

    # Проверяем корректность даты
    try:
        datetime(int(year), int(month), int(day))
    except ValueError:
        await message.answer("Пожалуйста, введите корректную дату:")
        return

    data = await state.get_data()
    if data.get('date_type') == "specific":
        await state.update_data(date_start=date_str, date_end=date_str)
        await message.answer(
            "Указывать время начала события? (например, 14:30) или напишите 'пропустить':"
        )
        await state.set_state(EventCreation.time_choice)
    else:  # диапазон
        await state.update_data(date_start=date_str)
        await message.answer(
            "Введите конечную дату диапазона в формате ДД.ММ.ГГГГ (например, 23.10.2026):"
        )
        await state.set_state(EventCreation.date_end_input)

@router.message(EventCreation.date_end_input)
async def process_event_date_end_input(message: Message, state: FSMContext):
    date_str = message.text.strip()
    parts = date_str.split('.')
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        await message.answer(
            "Неверный формат даты. Пожалуйста, введите дату в формате ДД.ММ.ГГГГ (например, 23.10.2026):"
        )
        return

    day, month, year = parts
    if len(day) != 2 or len(month) != 2 or len(year) != 4:
        await message.answer(
            "Неверный формат даты. Используйте ДД.ММ.ГГГГ (например, 23.10.2026):"
        )
        return

    try:
        datetime(int(year), int(month), int(day))
    except ValueError:
        await message.answer("Пожалуйста, введите корректную дату:")
        return

    await state.update_data(date_end=date_str)
    await message.answer(
        "Указывать время начала события? (например, 14:30) или напишите 'пропустить':"
    )
    await state.set_state(EventCreation.time_choice)

@router.message(EventCreation.time_choice)
async def process_event_time_choice(message: Message, state: FSMContext):
    time_input = message.text.strip()
    if time_input.lower() in ["пропустить", "нет", "не указывать"]:
        await state.update_data(time_start=None)
        await message.answer("Выберите категорию события:")
        await state.set_state(EventCreation.category_choice)
    else:
        # Простая проверка формата ЧЧ:ММ
        parts = time_input.split(':')
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            await message.answer(
                "Неверный формат времени. Используйте ЧЧ:ММ (например, 14:30) или напишите 'пропустить':"
            )
            return

        hour, minute = parts
        if len(hour) != 2 or len(minute) != 2:
            await message.answer(
                "Неверный формат времени. Используйте ЧЧ:ММ (например, 14:30) или напишите 'пропустить':"
            )
            return

        try:
            hour_int = int(hour)
            minute_int = int(minute)
            if hour_int < 0 or hour_int > 23 or minute_int < 0 or minute_int > 59:
                await message.answer("Время должно быть в диапазоне 00:00 - 23:59:")
                return
        except ValueError:
            await message.answer("Пожалуйста, введите корректное время:")
            return

        await state.update_data(time_start=time_input)
        await message.answer("Выберите категорию события:")
        await state.set_state(EventCreation.category_choice)

@router.callback_query(EventCreation.category_choice)
async def process_event_category_choice(call: types.CallbackQuery, state: FSMContext):
    # Получаем список категорий для отображения
    from keyboards import InlineKeyboardButton, InlineKeyboardMarkup
    categories = get_event_categories_by_type()

    if not categories:
        await call.message.edit_text("Категории событий не найдены. Обратитесь к администратору.")
        await state.clear()
        await call.answer()
        return

    buttons = []
    for cat_id, cat_name in categories:
        buttons.append([InlineKeyboardButton(text=cat_name, callback_data=f"event_category_{cat_id}")])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    await call.message.edit_reply_markup(reply_markup=reply_markup)
    await call.answer()

@router.callback_query(F.data.startswith("event_category_"))
async def process_event_category_selected(call: types.CallbackQuery, state: FSMContext):
    category_id = int(call.data.split("_")[2])
    category_name = get_event_category_name(category_id)
    await state.update_data(category_id=category_id, category_name=category_name)

    await call.message.edit_text(
        f"Выбрана категория: {hbold(category_name)}\n\n"
        "Указывать ожидаемое количество участников? (например, 5) или напишите 'пропустить':"
    )
    await state.set_state(EventCreation.people_needed_choice)

@router.message(EventCreation.people_needed_choice)
async def process_event_people_needed_choice(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() in ["пропустить", "нет", "не указывать"]:
        await state.update_data(people_needed=None)
        await message.answer("Введите описание события (опционально):")
        await state.set_state(EventCreation.description)
    else:
        if not text.isdigit():
            await message.answer("Пожалуйста, введите число или 'пропустить':")
            return

        count = int(text)
        if count < 1:
            await message.answer("Количество участников должно быть положительным числом:")
            return

        await state.update_data(people_needed=count)
        await message.answer("Введите описание события (опционально):")
        await state.set_state(EventCreation.description)

@router.message(EventCreation.description)
async def process_event_description(message: Message, state: FSMContext):
    description = message.text.strip() if message.text else ""
    await state.update_data(description=description)
    await message.answer("Введите место проведения события (опционально):")
    await state.set_state(EventCreation.location)

@router.message(EventCreation.location)
async def process_event_location(message: Message, state: FSMContext):
    location = message.text.strip() if message.text else ""
    await state.update_data(location=location)

    # Показываем предварительный просмотр и запрашиваем подтверждение
    data = await state.get_data()

    # Формируем дату для отображения
    date_display = data['date_start']
    if data.get('date_end') and data['date_end'] != data['date_start']:
        date_display = f"{data['date_start']} - {data['date_end']}"

    time_display = data.get('time_start', 'Не указано')
    people_display = str(data.get('people_needed', 'Не указано'))
    category_display = data.get('category_name', 'Не выбрана')

    preview_text = (
        f"📅 <b>Предварительный просмотр анкеты события</b>\n\n"
        f"📝 <b>Название:</b> {html.escape(data.get('title', ''))}\n"
        f"📅 <b>Дата:</b> {html.escape(date_display)}\n"
        f"🕐 <b>Время:</b> {html.escape(time_display)}\n"
        f"🏷️ <b>Категория:</b> {html.escape(category_display)}\n"
        f"👥 <b>Ожидается участников:</b> {html.escape(people_display)}\n"
        f"📄 <b>Описание:</b> {html.escape(data.get('description', '')[:100])}{'...' if len(data.get('description', '')) > 100 else ''}\n"
        f"📍 <b>Место:</b> {html.escape(location)}"
    )

    from keyboards import InlineKeyboardButton, InlineKeyboardMarkup
    confirm_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать событие", callback_data="confirm_event_creation")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_event_creation")],
        ]
    )

    await call.message.edit_text(preview_text, reply_markup=confirm_keyboard)
    await state.set_state(EventCreation.confirm)

@router.callback_query(EventCreation.confirm)
async def confirm_event_creation(call: types.CallbackQuery, state: FSMContext):
    action = call.data
    if action == "cancel_event_creation":
        await call.message.edit_text("Создание события отменено.")
        await state.clear()
        await call.answer()
        return

    if action != "confirm_event_creation":
        await call.answer()
        return

    user_id = call.from_user.id
    data = await state.get_data()

    # Создаем событие
    event_id = create_event_full(
        user_id=user_id,
        title=data.get('title', ''),
        date_start=data.get('date_start', ''),
        date_end=data.get('date_end', ''),
        time_start=data.get('time_start'),
        category_id=data.get('category_id'),
        people_needed=data.get('people_needed'),
        description=data.get('description', ''),
        location=data.get('location', '')
    )

    if event_id:
        await call.message.edit_text(
            f"✅ <b>Событие успешно создано!</b>\n\n"
            f"Ваше событие получило ID: {event_id}\n"
            f"Оно будет активно до истечения срока действия.\n"
            f"Вы можете управлять им в своем профиле."
        )
    else:
        await call.message.edit_text("❌ Ошибка при создании события. Пожалуйста, попробуйте позже.")

    await state.clear()
    await call.answer()

# ==================== ПОИСК И ОТКЛИК НА СОБЫТИЯ ====================

@router.message(F.text == "📅 Поиск мероприятий")
async def event_search_or_create(message: Message, state: FSMContext):
    """Меню: создать событие или искать события."""
    from keyboards import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать событие", callback_data="create_event")],
            [InlineKeyboardButton(text="🔍 Искать события", callback_data="search_events")],
        ]
    )
    await message.answer(
        "📅 <b>Управление мероприятий:</b>\n\n"
        "Выберите действие:",
        reply_markup=keyboard
    )
    await state.clear()

@router.callback_query(F.data == "search_events")
async def start_event_search(call: types.CallbackQuery):
    """Начинает поиск событий."""
    user_id = call.from_user.id
    user_profile = get_user_profile(user_id)
    if not user_profile:
        await call.message.answer(
            "Сначала заполните свой постоянный профиль, чтобы искать события!\n"
            "Нажмите '📝 Заполнить заново'"
        )
        await call.answer()
        return

    reset_events_viewed(user_id)
    await send_random_event(call, user_id)
    await call.answer()

@router.callback_query(F.data == "create_event")
async def start_event_creation(call: types.CallbackQuery, state: FSMContext):
    """Начинает создание события."""
    await call.message.edit_text(
        "📅 <b>Создание анкеты мероприятия</b>\n\n"
        "Введите название события (обязательно):",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(EventCreation.title)
    await call.answer()

async def send_random_event(message_or_call, user_id):
    """Отправляет случайное событие для просмотра."""
    is_callback = isinstance(message_or_call, types.CallbackQuery)
    target = message_or_call.message if is_callback else message_or_call

    event = get_active_events_for_search(user_id)
    if not event:
        # Все события просмотрены или нет активных
        reset_events_viewed(user_id)
        await target.answer(
            "🎉 <b>Все события просмотрены или нет активных событий!</b>\n\n"
            "Теперь вы можете начать сначала или создать свое событие.",
            reply_markup=get_main_menu()
        )
        return

    e_id, e_title, e_date_start, e_date_end, e_time_start, e_people_needed, e_description, e_location, \
    e_category_name, e_category_type, e_creator_name, e_creator_photo = event

    # Помечаем событие как просмотренное
    mark_event_viewed(user_id, e_id)

    # Формируем дату для отображения
    date_display = e_date_start
    if e_date_end and e_date_end != e_date_start:
        date_display = f"{e_date_start} - {e_date_end}"

    time_display = e_time_start or "Не указано"
    people_display = str(e_people_needed) if e_people_needed else "Не указано"

    caption = (
        f"📅 <b>Найдено событие:</b>\n\n"
        f"📝 <b>Название:</b> {html.escape(e_title)}\n"
        f"📅 <b>Дата:</b> {html.escape(date_display)}\n"
        f"🕐 <b>Время:</b> {html.escape(time_display)}\n"
        f"🏷️ <b>Категория:</b> {html.escape(e_category_name)}\n"
        f"👥 <b>Ожидается участников:</b> {html.escape(people_display)}\n"
        f"📄 <b>Описание:</b> {html.escape(e_description[:100])}{'...' if len(e_description) > 100 else ''}\n"
        f"📍 <b>Место:</b> {html.escape(e_location)}\n"
        f"👤 <b>Создатель:</b> {html.escape(e_creator_name)}"
    )

    from keyboards import InlineKeyboardButton, InlineKeyboardMarkup
    # Проверяем, не откликался ли уже пользователь
    has_responded = has_user_responded(e_id, user_id)

    buttons = [
        [InlineKeyboardButton(text="👍 Откликнуться", callback_data=f"event_respond_{e_id}")],
        [InlineKeyboardButton(text="➡️ Дальше", callback_data="event_next_profile")]
    ]
    if has_responded:
        buttons[0][0] = InlineKeyboardButton(text="✅ Вы уже откликнулись", callback_data="already_responded")

    reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    await target.answer_photo(
        photo=e_creator_photo,
        caption=caption,
        reply_markup=reply_markup
    )

@router.message(F.text == "🔍 Найти анкеты")
async def start_event_search(message: Message):
    user_profile = get_user_profile(message.from_user.id)
    if not user_profile:
        await message.answer(
            "Сначала заполните свой постоянный профиль, чтобы искать события!\n"
            "Нажмите '📝 Заполнить заново'"
        )
        return

    reset_events_viewed(message.from_user.id)
    await send_random_event(message, message.from_user.id)

@router.callback_query(F.data == "event_next_profile")
async def next_event_callback(call: types.CallbackQuery):
    await call.message.edit_reply_markup(reply_markup=None)
    await send_random_event(call, call.from_user.id)
    await call.answer()

@router.callback_query(F.data.startswith("event_respond_"))
async def event_respond_callback(call: types.CallbackQuery):
    event_id = int(call.data.split("_")[2])
    user_id = call.from_user.id

    # Добавляем отклик
    response_id = add_event_response(event_id, user_id)

    if response_id:
        await call.message.edit_text("✅ Ваш отклик отправлен создателю события!")
        await call.message.answer("Ищем следующее событие...", reply_markup=get_main_menu())

        # Уведомляем создателя события
        event_detail = get_event_detail(event_id)
        if event_detail:
            creator_id = event_detail[1]  # user_id создателя
            creator_name = event_detail[14]  # creator_name
            responder_name = call.from_user.full_name or call.from_user.username or f"Пользователь {user_id}"

            try:
                await bot.send_message(
                    chat_id=creator_id,
                    text=f"🔔 <b>Новый отклик на ваше событие!</b>\n\n"
                         f"📝 Событие: {html.escape(event_detail[2])}\n"
                         f"👤 Откликнулся: {html.escape(responder_name)}\n"
                         f"💬 Вы можете посмотреть все отклики в разделе '💬 Отклики'",
                    parse_mode="HTML"
                )
            except Exception:
                pass  # Пользователь мог заблокировать бота
    else:
        await call.message.edit_text("❌ Вы уже откликнулись на это событие.")

    await call.answer()

# ==================== УПРАВЛЕНИЕ СОБЫТИЯМИ ====================

@router.message(F.text == "💬 Отклики")
async def show_my_responses(message: Message):
    """Показывает отклики на события пользователя."""
    user_id = message.from_user.id
    user_events = get_user_events_full(user_id)

    if not user_events:
        await message.answer(
            "У вас пока нет созданных событий.\n"
            "Создайте первое событие через '📅 Поиск мероприятий'",
            reply_markup=get_main_menu()
        )
        return

    text = "💬 <b>Отклики на ваши события</b>\n\n"
    for event in user_events:
        e_id, e_title, e_date_start, e_date_end, e_people_needed, e_status, e_created_at = event[0], event[1], event[2], event[3], event[5], event[9], event[10]

        responses_count = get_responses_count(e_id)
        people_needed_display = f" / {e_people_needed}" if e_people_needed else ""

        date_display = e_date_start
        if e_date_end and e_date_end != e_date_start:
            date_display = f"{e_date_start} - {e_date_end}"

        status_emoji = "🟢" if e_status == "active" else "🔴"
        status_text = "Активно" if e_status == "active" else "Закрыто"

        text += (
            f"{status_emoji} <b>{html.escape(e_title)}</b>\n"
            f"📅 {html.escape(date_display)}\n"
            f"👥 Откликов: {responses_count}{people_needed_display}\n"
            f"📊 Статус: {status_text}\n\n"
        )

    await message.answer(text, reply_markup=get_main_menu())

@router.message(F.text == "👤 Мой профиль")
async def show_my_profile_with_events(message: Message):
    """Расширенный профиль с информацией о событиях."""
    user_id = message.from_user.id
    user_profile = get_user_profile(user_id)
    user_events = get_user_events_full(user_id)
    user_temp_profiles = get_user_temp_profiles(user_id)  # из temp_profile_db

    if not user_profile:
        await message.answer("Вы еще не заполнили постоянный профиль. Нажмите '📝 Заполнить заново'")
        return

    name, start_year, group_num, faculty, photo = user_profile

    caption = (
        f"👤 <b>Ваш постоянный профиль:</b>\n"
        f"👤 Имя: {html.escape(name)}\n"
        f"📅 Год: {html.escape(start_year)}\n"
        f"👥 Группа: {html.escape(group_num)}\n"
        f"🎓 Факультет: {html.escape(faculty)}\n\n"
        f"📋 <b>Ваши временные анкеты:</b> {len(user_temp_profiles)} активных\n"
        f"📅 <b>Ваши события:</b> {len(user_events)} (активных/закрытых)\n"
    )

    await message.answer_photo(photo=photo, caption=caption, reply_markup=get_main_menu())
