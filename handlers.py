import asyncio
import html

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from db import (
    save_user,
    get_user,
    get_random_stranger,
    mark_stranger_viewed,
    reset_all_viewed,
)
from keyboards import (
    get_main_menu,
    get_search_keyboard,
    get_faculty_keyboard,
    FACULTY_LIST,
)
from states import Anketa

# Задержка (в секундах) между показом анкет для подгрузки новых
PROFILE_DELAY = 1.5

router = Router()

# ==================== ЛОГИКА АНКЕТЫ ====================
@router.message(Command("start"))
@router.message(F.text == "📝 Заполнить заново")
async def cmd_start(message: Message, state: FSMContext):
    await message.answer(
        "👋 Привет! Это бот знакомств ВШЭ НН.\n"
        "Давай заполним профиль. <b>Как тебя зовут?</b>",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Anketa.name)

@router.message(Anketa.name)
async def process_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    # Проверка адекватности: непустое, длина не более 50 символов
    if not name or len(name) > 50:
        await message.answer("Введите корректное имя (не более 50 символов, не пустое).")
        return
    await state.update_data(name=name)
    await message.answer("Введи <b>год твоего поступления</b> (например, 2024):")
    await state.set_state(Anketa.start_year)

@router.message(Anketa.start_year)
async def process_year(message: Message, state: FSMContext):
    year_str = (message.text or "").strip()
    # Проверка: должно быть целым числом и минимум 2020
    if not year_str.isdecimal():
        await message.answer("Введите корректный год (только цифры).")
        return
    year = int(year_str)
    if year < 2020:
        await message.answer("Год поступления должен быть не меньше 2020.")
        return
    if year > 2030:
        await message.answer("Год поступления не может быть больше 2030.")
        return
    await state.update_data(start_year=str(year))
    await message.answer("Напиши <b>номер твоей группы</b> (например, БИ-201):")
    await state.set_state(Anketa.group_num)

@router.message(Anketa.group_num)
async def process_group(message: Message, state: FSMContext):
    group = (message.text or "").strip()
    # Проверка адекватности: непустое, длина не более 20 символов
    if not group or len(group) > 20:
        await message.answer("Введите корректный номер группы (не более 20 символов, не пустое).")
        return

    await state.update_data(group_num=group)
    await message.answer(
        "Выбери <b>направление подготовки</b> из списка:",
        reply_markup=get_faculty_keyboard()
    )
    await state.set_state(Anketa.faculty)

@router.callback_query(F.data.startswith("facultypage_"))
async def faculty_page_callback(call: types.CallbackQuery):
    page = int(call.data.split("_")[1])
    await call.message.edit_reply_markup(reply_markup=_get_faculty_keyboard_page(page))
    await call.answer()

@router.callback_query(Anketa.faculty, F.data.startswith("faculty_"))
async def faculty_callback(call: types.CallbackQuery, state: FSMContext):
    index = int(call.data.split("_")[1])
    if not 0 <= index < len(FACULTY_LIST):
        await call.answer("Это направление недоступно, выбери из списка.", show_alert=True)
        return
    faculty = FACULTY_LIST[index]
    await state.update_data(faculty=faculty)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Отправь <b>одну свою фотографию</b>:")
    await state.set_state(Anketa.photo)
    await call.answer()

@router.message(Anketa.faculty)
async def process_faculty_direct(message: Message):
    # Пользователь ввёл текст вместо выбора из списка — просим выбрать
    await message.answer(
        "Пожалуйста, выбери направление из списка кнопок.",
        reply_markup=get_faculty_keyboard()
    )

@router.message(Anketa.photo)
async def process_photo(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Пожалуйста, отправь именно фото.")
        return

    photo_id = message.photo[-1].file_id
    user_data = await state.get_data()

    # СОХРАНЯЕМ В БАЗУ ДАННЫХ
    save_user(
        user_id=message.from_user.id,
        name=user_data['name'],
        start_year=user_data['start_year'],
        group_num=user_data['group_num'],
        faculty=user_data['faculty'],
        photo=photo_id
    )

    await message.answer("🎉 Профиль успешно сохранен!", reply_markup=get_main_menu())
    await state.clear()

# ==================== ПРОСМОТР СВОЕГО ПРОФИЛЯ ====================
@router.message(F.text == "👤 Мой профиль")
async def show_my_profile(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Ты еще не заполнил анкету. Нажми '📝 Заполнить заново'")
        return

    name, start_year, group_num, faculty, photo = user
    caption = (
        f"📝 <b>Твой профиль:</b>\n"
        f"👤 Имя: {html.escape(name)}\n"
        f"📅 Год: {html.escape(start_year)}\n"
        f"👥 Группа: {html.escape(group_num)}\n"
        f"🎓 Направление: {html.escape(faculty)}"
    )
    await message.answer_photo(photo=photo, caption=caption)

# ==================== МЕХАНИКА ПОИСКА ЧУЖИХ АНКЕТ ====================
async def send_random_profile(message_or_call, user_id):
    # Метод может вызываться как из текстового сообщения, так и из инлайн-кнопки
    is_callback = isinstance(message_or_call, types.CallbackQuery)
    target = message_or_call.message if is_callback else message_or_call

    stranger = get_random_stranger(user_id)
    if not stranger:
        # Все анкеты просмотрены — сбрасываем и сообщаем
        reset_all_viewed()
        await target.answer("🎉 <b>Все анкеты просмотрены!</b>\n\nТеперь ты можешь начать сначала.", reply_markup=get_main_menu())
        return

    s_id, s_name, s_year, s_group, s_faculty, s_photo = stranger

    # Помечаем анкету как просмотренную
    mark_stranger_viewed(s_id)

    caption = (
        f"🔍 <b>Найдена анкета:</b>\n"
        f"👤 Имя: {html.escape(s_name)}\n"
        f"📅 Год: {html.escape(s_year)}\n"
        f"👥 Группа: {html.escape(s_group)}\n"
        f"🎓 Направление: {html.escape(s_faculty)}"
    )

    await target.answer_photo(
        photo=s_photo,
        caption=caption,
        reply_markup=get_search_keyboard(s_id)
    )

@router.message(F.text == "🔍 Найти анкеты")
async def start_search(message: Message):
    # Проверяем, заполнил ли сам пользователь анкету перед поиском
    if not get_user(message.from_user.id):
        await message.answer("Сначала заполни свою анкету, чтобы искать других!")
        return
    # Сбрасываем просмотренные при новом поиске
    reset_all_viewed()
    await send_random_profile(message, message.from_user.id)

# ОБРАБОТКА ИНЛАЙН-КНОПОК (ЛАЙК И ДАЛЬШЕ)
@router.callback_query(F.data.startswith("like_"))
async def like_callback(call: types.CallbackQuery):
    # Удаляем старые кнопки под текущей анкетой, чтобы не кликали дважды
    await call.message.edit_reply_markup(reply_markup=None)

    # Узнаем ID того, кого лайкнули (stranger_id)
    stranger_id = int(call.data.split("_")[1])

    # Достаем анкету текущего пользователя (того, кто ставит лайк) из базы данных
    my_profile = get_user(call.from_user.id)

    if my_profile:
        my_name, my_year, my_group, my_faculty, my_photo = my_profile

        # Формируем ссылку на аккаунт или юзернейм
        if call.from_user.username:
            username_text = f"🔗 Ссылка: @{call.from_user.username}"
        else:
            username_text = f'🔗 Ссылка: <a href="tg://user?id={call.from_user.id}">Профиль</a>'

        # Формируем красивый текст анкеты лайкнувшего
        notification_caption = (
            f"❤️ <b>Ты понравился этому человеку!</b>\n\n"
            f"👤 Имя: {html.escape(my_name)}\n"
            f"📅 Год: {html.escape(my_year)}\n"
            f"👥 Группа: {html.escape(my_group)}\n"
            f"🎓 Направление: {html.escape(my_faculty)}\n\n"
            f"{username_text}"
        )

        try:
            # Отправляем полную анкету с фото тому, кого лайкнули
            await bot.send_photo(
                chat_id=stranger_id,
                photo=my_photo,
                caption=notification_caption
            )
        except Exception:
            # Защита на случай, если пользователь заблокировал бота
            pass

    # Пишем текущему пользователю, что лайк отправлен, с задержкой показываем следующую анкету
    await call.message.answer("Лайк отправлен! Ищем следующую анкету...")
    # Задержка для подгрузки новых анкет
    await asyncio.sleep(PROFILE_DELAY)
    await send_random_profile(call, call.from_user.id)
    await call.answer()

@router.callback_query(F.data == "next_profile")
async def next_profile_callback(call: types.CallbackQuery):
    await call.message.edit_reply_markup(reply_markup=None)
    # Задержка для подгрузки новых анкет
    await asyncio.sleep(PROFILE_DELAY)
    await send_random_profile(call, call.from_user.id)
    await call.answer()
