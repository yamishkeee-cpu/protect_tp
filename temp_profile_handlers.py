from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.markdown import hbold
import html

from db import get_user
from keyboards import get_main_menu, get_temp_profile_keyboard, get_confirm_temp_profile_keyboard
from temp_profile_db import save_temp_profile_with_partial_fill, get_temp_profile_fields_from_user
from temp_profile_states import TempProfile

router = Router()
temp_profile_router = router  # Экспортируем роутер для bot.py

# ==================== СОЗДАНИЕ ВРЕМЕННОЙ АНКЕТЫ ====================

@router.message(F.text == "📋 Поиск для задач")
async def temp_profile_start(message: Message, state: FSMContext):
    """Начинает процесс создания временной анкеты."""
    # Сначала показываем выбор цели поиска
    await message.answer(
        "📋 <b>Создание временной анкеты</b>\n\n"
        "Выберите цель поиска анкеты:",
        reply_markup=get_temp_profile_keyboard()
    )
    await state.set_state(TempProfile.goal_choice)

# Обработчик выбора цели поиска
@router.callback_query(TempProfile.goal_choice)
async def process_goal_choice(call: types.CallbackQuery, state: FSMContext):
    goal = call.data
    await state.update_data(goal=goal)

    await call.message.edit_text(
        "👤 <b>Имя</b>\n"
        "Выберите способ указания имени:\n"
        "• Взять из постоянного профиля\n"
        "• Ввести вручную\n"
        "• Пропустить"
    )
    await state.set_state(TempProfile.name_choice)

# Обработчик выбора имени
@router.callback_query(TempProfile.name_choice)
async def process_name_choice(call: types.CallbackQuery, state: FSMContext):
    choice = call.data
    await state.update_data(name_choice=choice)

    if choice == "from_profile":
        await call.message.edit_text("✅ Имя будет взято из постоянного профиля.")
        await state.set_state(TempProfile.year_choice)
    elif choice == "manual":
        await call.message.edit_text("Введите ваше имя (или nickname):")
        await state.set_state(TempProfile.name_input)
    elif choice == "skip":
        await call.message.edit_text("✅ Имя будет пропущено.")
        await state.set_state(TempProfile.year_choice)

    await call.answer()

# Обработчик ввода имени вручную
@router.message(TempProfile.name_input)
async def process_name_input(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым. Введите ваше имя:")
        return

    await state.update_data(name=name)
    await message.answer("✅ Имя сохранено: " + hbold(name))
    await state.set_state(TempProfile.year_choice)

# Обработчик выбора года
@router.callback_query(TempProfile.year_choice)
async def process_year_choice(call: types.CallbackQuery, state: FSMContext):
    choice = call.data
    await state.update_data(year_choice=choice)

    if choice == "from_profile":
        await call.message.edit_text("✅ Год поступления будет взят из постоянного профиля.")
        await state.set_state(TempProfile.group_choice)
    elif choice == "manual":
        await call.message.edit_text("Введите год поступления (например, 2024):")
        await state.set_state(TempProfile.year_input)
    elif choice == "skip":
        await call.message.edit_text("✅ Год поступления будет пропущен.")
        await state.set_state(TempProfile.group_choice)

    await call.answer()

# Обработчик ввода года вручную
@router.message(TempProfile.year_input)
async def process_year_input(message: Message, state: FSMContext):
    year_str = message.text.strip()
    if not year_str.isdigit():
        await message.answer("Пожалуйста, введите корректный год (только цифры):")
        return

    year = int(year_str)
    if year < 2020 or year > 2030:
        await message.answer("Год должен быть между 2020 и 2030:")
        return

    await state.update_data(start_year=str(year))
    await message.answer("✅ Год поступления сохранен: " + hbold(str(year)))
    await state.set_state(TempProfile.group_choice)

# Обработчик выбора группы
@router.callback_query(TempProfile.group_choice)
async def process_group_choice(call: types.CallbackQuery, state: FSMContext):
    choice = call.data
    await state.update_data(group_choice=choice)

    if choice == "from_profile":
        await call.message.edit_text("✅ Номер группы будет взят из постоянного профиля.")
        await state.set_state(TempProfile.faculty_choice)
    elif choice == "manual":
        await call.message.edit_text("Введите номер вашей группы (например, БИ-201):")
        await state.set_state(TempProfile.group_input)
    elif choice == "skip":
        await call.message.edit_text("✅ Номер группы будет пропущен.")
        await state.set_state(TempProfile.faculty_choice)

    await call.answer()

# Обработчик ввода группы вручную
@router.message(TempProfile.group_input)
async def process_group_input(message: Message, state: FSMContext):
    group = message.text.strip()
    if not group:
        await message.answer("Номер группы не может быть пустым. Введите номер группы:")
        return

    await state.update_data(group_num=group)
    await message.answer("✅ Номер группы сохранен: " + hbold(group))
    await state.set_state(TempProfile.faculty_choice)

# Обработчик выбора факультета
@router.callback_query(TempProfile.faculty_choice)
async def process_faculty_choice(call: types.CallbackQuery, state: FSMContext):
    choice = call.data
    await state.update_data(faculty_choice=choice)

    if choice == "from_profile":
        await call.message.edit_text("✅ Факультет будет взят из постоянного профиля.")
        await state.set_state(TempProfile.photo_choice)
    elif choice == "manual":
        from keyboards import get_faculty_keyboard
        await call.message.edit_text("Выберите факультет из списка:", reply_markup=get_faculty_keyboard())
        await state.set_state(TempProfile.faculty)
    elif choice == "skip":
        await call.message.edit_text("✅ Факультет будет пропущен.")
        await state.set_state(TempProfile.photo_choice)

    await call.answer()

# Обработчик выбора факультета вручную
@router.callback_query(TempProfile.faculty_choice)
async def process_faculty_manual(call: types.CallbackQuery, state: FSMContext):
    index = int(call.data.split("_")[1])
    from keyboards import FACULTY_LIST
    if 0 <= index < len(FACULTY_LIST):
        faculty = FACULTY_LIST[index]
        await call.message.edit_text("✅ Факультет сохранен: " + hbold(faculty))
        await state.update_data(faculty=faculty)
    else:
        await call.message.edit_text("Неверный факультет. Пожалуйста, выберите из списка снова.")

    await state.set_state(TempProfile.photo_choice)
    await call.answer()

# Обработчик выбора фото
@router.callback_query(TempProfile.photo_choice)
async def process_photo_choice(call: types.CallbackQuery, state: FSMContext):
    choice = call.data
    await state.update_data(photo_choice=choice)

    if choice == "from_profile":
        await call.message.edit_text("✅ Фото будет взято из постоянного профиля.")
        await state.set_state(TempProfile.description)
    elif choice == "manual":
        await call.message.edit_text("Отправьте одну фотографию (фото будет использовано в анкете):")
        await state.set_state(TempProfile.photo)
    elif choice == "skip":
        await call.message.edit_text("✅ Фото будет пропущено.")
        await state.set_state(TempProfile.description)

    await call.answer()

# Обработчик фото
@router.message(TempProfile.photo)
async def process_photo(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Пожалуйста, отправьте именно фотографию.")
        return

    photo_id = message.photo[-1].file_id
    await state.update_data(photo=photo_id)
    await message.answer("✅ Фото сохранено.")
    await state.set_state(TempProfile.description)

# ==================== ОПИСАНИЕ И ПОДТВЕРЖДЕНИЕ ====================

# Обработчик описания
@router.message(TempProfile.description)
async def process_description(message: Message, state: FSMContext):
    description = message.text.strip() if message.text else ""
    await state.update_data(description=description)
    await message.answer("✅ Описание сохранено: " + (hbold(description) if description else "Не указано"))
    await state.set_state(TempProfile.confirm)

# Обработчик подтверждения
@router.callback_query(TempProfile.confirm)
async def confirm_temp_profile(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    data = await state.get_data()

    # Подготовка данных для сохранения
    field_data = {
        'name': data.get('name'),
        'start_year': data.get('start_year'),
        'group_num': data.get('group_num'),
        'faculty': data.get('faculty'),
        'photo': data.get('photo'),
        'goal': data.get('goal'),
        'description': data.get('description', '')
    }

    # Сохранение анкеты
    temp_id = save_temp_profile_with_partial_fill(user_id, field_data)

    # Создаем красивый текст анкеты
    name = field_data['name'] or "Не указано"
    year = field_data['start_year'] or "Не указан"
    group = field_data['group_num'] or "Не указана"
    faculty = field_data['faculty'] or "Не указан"
    photo_text = "Не указано" if not field_data['photo'] else "✅"
    goal_text = "ищу людей" if field_data['goal'] == 'ищу_людей' else "предлагаю себя"
    description_text = field_data['description'] or "Не указано"

    caption = (
        f"📋 <b>Временная анкета создана</b>\n\n"
        f"👤 <b>Имя:</b> {html.escape(name)}\n"
        f"📅 <b>Год:</b> {html.escape(year)}\n"
        f"👥 <b>Группа:</b> {html.escape(group)}\n"
        f"🎓 <b>Факультет:</b> {html.escape(faculty)}\n"
        f"📸 <b>Фото:</b> {photo_text}\n"
        f"🎯 <b>Цель:</b> {html.escape(goal_text)}\n"
        f"📝 <b>Описание:</b> {html.escape(description_text[:100])}{'...' if len(description_text) > 100 else ''}"
    )

    # Показываем превью анкеты
    if field_data['photo']:
        await call.message.edit_text(f"✅ Временная анкета успешно создана!\n\nПревью анкеты:")
        # Отправляем фото в личку к пользователю, если нужно, или показываем превью
        await call.message.answer_photo(
            photo=field_data['photo'],
            caption=caption,
            reply_markup=get_main_menu()
        )
    else:
        await call.message.edit_text(f"✅ Временная анкета успешно создана!\n\nПревью анкеты:")
        await call.message.answer(caption, reply_markup=get_main_menu())

    # Очищаем состояние FSM
    await state.clear()

    await call.answer("Временная анкета создана!")