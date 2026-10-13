import asyncio
import sqlite3
import random
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# 1. Токен вашего бота
BOT_TOKEN = "8803078943:AAF3RdQmYCeZqP_Z_kIYsGEBIk-IKoauQVc"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# ==================== РАБОТА С БАЗОЙ ДАННЫХ (SQLite) ====================
def init_db():
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            start_year TEXT,
            group_num TEXT,
            faculty TEXT,
            photo TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user(user_id, name, start_year, group_num, faculty, photo):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, name, start_year, group_num, faculty, photo)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, name, start_year, group_num, faculty, photo))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, start_year, group_num, faculty, photo FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_random_stranger(user_id):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    # Ищем случайного пользователя, чей ID не равен ID текущего юзера
    cursor.execute("SELECT user_id, name, start_year, group_num, faculty, photo FROM users WHERE user_id != ? ORDER BY RANDOM() LIMIT 1", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

# Инициализируем БД при старте скрипта
init_db()

# ==================== СПИСОК НАПРАВЛЕНИЙ ====================
# Сформировано из страницы ВШЭ НН: https://www.hse.ru/n/education/bachelor?campus=51999664
FACULTY_LIST = [
    "Дизайн",
    "Иностранные языки и межкультурная бизнес-коммуникация",
    "Компьютерные науки и технологии (Бизнес-информатика)",
    "Компьютерные науки и технологии (Программная инженерия, очная)",
    "Компьютерные науки и технологии (Прикладная математика и информатика)",
    "Международная программа по бизнесу и экономике (Менеджмент)",
    "Международная программа по бизнесу и экономике (Экономика)",
    "Программная инженерия (очно-заочное обучение)",
    "Технологии искусственного и дополненного интеллекта",
    "Филология",
    "Фундаментальная и прикладная лингвистика",
    "Фундаментальная и прикладная математика (Математика)",
    "Фундаментальная и прикладная математика (Прикладная математика)",
    "Цифровой маркетинг",
    "Экономика и бизнес (очно-заочное обучение)",
    "Юриспруденция",
]

# ==================== КЛАВИАТУРЫ (КНОПКИ) ====================
def get_main_menu():
    buttons = [
        [KeyboardButton(text="🔍 Найти анкеты")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📝 Заполнить заново")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_search_keyboard(stranger_id):
    buttons = [
        [
            InlineKeyboardButton(text="❤️ Лайк", callback_data=f"like_{stranger_id}"),
            InlineKeyboardButton(text="➡️ Дальше", callback_data="next_profile")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_faculty_keyboard():
    """Клавиатура с направлениями, разбитыми на страницы."""
    return _get_faculty_keyboard_page(0)

def _get_faculty_keyboard_page(page):
    PAGE_SIZE = 8
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = FACULTY_LIST[start:end]

    buttons = []
    for item in page_items:
        buttons.append([InlineKeyboardButton(text=item, callback_data=f"faculty_{item}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"facultypage_{page - 1}"))
    if end < len(FACULTY_LIST):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"facultypage_{page + 1}"))
    if nav:
        buttons.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== СОСТОЯНИЯ (FSM) ====================
class Anketa(StatesGroup):
    name = State()
    start_year = State()
    group_num = State()
    faculty = State()
    photo = State()

# ==================== ЛОГИКА АНКЕТЫ ====================
@router.message(Command("start"))
@router.message(F.text == "📝 Заполнить заново")
async def cmd_start(message: Message, state: FSMContext):
    await message.answer(
        "👋 Привет! Это бот знакомств ВШЭ НН.\n"
        "Давай заполним профиль. **Как тебя зовут?**",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Anketa.name)

@router.message(Anketa.name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    # Проверка адекватности: непустое, длина не более 50 символов
    if not name or len(name) > 50:
        await message.answer("Введите корректное имя (не более 50 символов, не пустое).")
        return
    await state.update_data(name=name)
    await message.answer("Введи **год твоего поступления** (например, 2024):")
    await state.set_state(Anketa.start_year)

@router.message(Anketa.start_year)
async def process_year(message: Message, state: FSMContext):
    year_str = message.text.strip()
    # Проверка: должно быть целым числом и минимум 2020
    if not year_str.isdigit():
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
    await message.answer("Напиши **номер твоей группы** (например, БИ-201):")
    await state.set_state(Anketa.group_num)

@router.message(Anketa.group_num)
async def process_group(message: Message, state: FSMContext):
    group = message.text.strip()
    # Проверка адекватности: непустое, длина не более 20 символов
    if not group or len(group) > 20:
        await message.answer("Введите корректный номер группы (не более 20 символов, не пустое).")
        return

    await state.update_data(group_num=group)
    await message.answer(
        "Выбери **направление подготовки** из списка:",
        reply_markup=get_faculty_keyboard()
    )
    await state.set_state(Anketa.faculty)

@router.callback_query(F.data.startswith("facultypage_"))
async def faculty_page_callback(call: types.CallbackQuery):
    page = int(call.data.split("_")[1])
    await call.message.edit_reply_markup(reply_markup=_get_faculty_keyboard_page(page))
    await call.answer()

@router.callback_query(F.data.startswith("faculty_") & ~F.data.startswith("facultypage_"))
async def faculty_callback(call: types.CallbackQuery, state: FSMContext):
    faculty = call.data.split("faculty_")[1]
    await state.update_data(faculty=faculty)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Отправь **одну свою фотографию**:")
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
    caption = f"📝 **Твой профиль:**\n👤 Имя: {name}\n📅 Год: {start_year}\n👥 Группа: {group_num}\n🎓 Направление: {faculty}"
    await message.answer_photo(photo=photo, caption=caption)

# ==================== МЕХАНИКА ПОИСКА ЧУЖИХ АНКЕТ ====================
async def send_random_profile(message_or_call, user_id):
    # Метод может вызываться как из текстового сообщения, так и из инлайн-кнопки
    is_callback = isinstance(message_or_call, types.CallbackQuery)
    target = message_or_call.message if is_callback else message_or_call

    stranger = get_random_stranger(user_id)
    if not stranger:
        await target.answer("В базе пока нет других анкет, кроме твоей. Пригласи друзей!")
        return

    s_id, s_name, s_year, s_group, s_faculty, s_photo = stranger
    caption = f"🔍 **Найдена анкета:**\n👤 Имя: {s_name}\n📅 Год: {s_year}\n👥 Группа: {s_group}\n🎓 Направление: {s_faculty}"

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
            username_text = f"🔗 Ссылка: [Профиль](tg://user?id={call.from_user.id})"

        # Формируем красивый текст анкеты лайкнувшего
        notification_caption = (
            f"❤️ **Ты понравился этому человеку!**\n\n"
            f"👤 Имя: {my_name}\n"
            f"📅 Год: {my_year}\n"
            f"👥 Группа: {my_group}\n"
            f"🎓 Направление: {my_faculty}\n\n"
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

    # Пишем текущему пользователю, что лайк отправлен, и сразу показываем следующую анкету
    await call.message.answer("Лайк отправлен! Ищем следующую анкету...")
    await send_random_profile(call, call.from_user.id)
    await call.answer()

@router.callback_query(F.data == "next_profile")
async def next_profile_callback(call: types.CallbackQuery):
    await call.message.edit_reply_markup(reply_markup=None)
    await send_random_profile(call, call.from_user.id)
    await call.answer()

# ==================== ЗАПУСК БОТА ====================
async def main():
    dp.include_router(router)
    print("Бот запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
