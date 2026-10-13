import asyncio
import sqlite3
import random
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
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
        "👋 Привет! Это бот знакомств ВШЭ ННГУ.\n"
        "Давай заполним профиль. **Как тебя зовут?**",
        reply_markup=types.ReplyKeyboardRemove() # Прячем главное меню на время заполнения
    )
    await state.set_state(Anketa.name)

@router.message(Anketa.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введи **год твоего поступления** (например, 2024):")
    await state.set_state(Anketa.start_year)

@router.message(Anketa.start_year)
async def process_year(message: Message, state: FSMContext):
    await state.update_data(start_year=message.text)
    await message.answer("Напиши **номер твоей группы**:")
    await state.set_state(Anketa.group_num)

@router.message(Anketa.group_num)
async def process_group(message: Message, state: FSMContext):
    await state.update_data(group_num=message.text)
    await message.answer("Укажи свое **направление/факультет**:")
    await state.set_state(Anketa.faculty)

@router.message(Anketa.faculty)
async def process_faculty(message: Message, state: FSMContext):
    await state.update_data(faculty=message.text)
    await message.answer("Отправь **одну свою фотографию**:")
    await state.set_state(Anketa.photo)

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
@router.callback_query(F.data == "next_profile")
async def next_profile_callback(call: types.CallbackQuery):
    # Удаляем старые кнопки под прошлой анкетой, чтобы не кликали дважды
    await call.message.edit_reply_markup(reply_markup=None)
    await send_random_profile(call, call.from_user.id)
    await call.answer()

@router.callback_query(F.data.startswith("like_"))
async def like_callback(call: types.CallbackQuery):
    await call.message.edit_reply_markup(reply_markup=None)

    # Узнаем ID того, кого лайкнули
    stranger_id = int(call.data.split("_")[1])

    # Отправляем уведомление тому, кого лайкнули
    my_profile = get_user(call.from_user.id)
    if my_profile:
        my_name = my_profile[0]
        # Отправляем ссылку на аккаунт лайкнувшего юзера
        username_link = f"@{call.from_user.username}" if call.from_user.username else f"tg://user?id={call.from_user.id}"

        try:
            await bot.send_message(
                chat_id=stranger_id,
                text=f"❤️ Ты понравился пользователю **{my_name}**! Ссылка для связи: {username_link}"
            )
        except Exception:
            # Если пользователь заблокировал бота, сообщение не уйдет
            pass

    await call.message.answer("Лайк отправлен! Ищем следующую анкету...")
    await send_random_profile(call, call.from_user.id)
    await call.answer()

# ==================== ЗАПУСК БОТА ====================
async def main():
    dp.include_router(router)
    print("Бот запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
