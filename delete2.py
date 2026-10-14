import asyncio
import html
import os
import sqlite3
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# 1. Токен бота берём из переменной окружения BOT_TOKEN (не храним в коде)
BOT_TOKEN = "8425058319:AAGxEM1f7-PvsFVI5JsQRjMd3CD8BZoYBOU"
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Не задан BOT_TOKEN. Запуск: BOT_TOKEN=<токен> python bot.py")

# Все сообщения отправляются с HTML-разметкой (<b>жирный</b>)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
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
    # +++ НОВОЕ: добавляем колонки is_active и is_deleted, если их ещё нет.
    # Это безопасная "миграция" — существующие данные не теряются.
    cursor.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}

    if "is_active" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
    if "is_deleted" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_deleted INTEGER DEFAULT 0")

    conn.commit()
    conn.close()

def save_user(user_id, name, start_year, group_num, faculty, photo):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    # +++ НОВОЕ: при сохранении анкеты сразу ставим is_active=1, is_deleted=0
    # (если пользователь заполняет заново после деактивации — снова активен)
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, name, start_year, group_num, faculty, photo, is_active, is_deleted)
        VALUES (?, ?, ?, ?, ?, ?, 1, 0)
    """, (user_id, name, start_year, group_num, faculty, photo))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, start_year, group_num, faculty, photo, is_active, is_deleted FROM users WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return row

def get_random_stranger(user_id):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    # +++ ИЗМЕНЕНО: ищем только активные и не удалённые анкеты
    cursor.execute("""
        SELECT user_id, name, start_year, group_num, faculty, photo
        FROM users
        WHERE user_id != ?
          AND is_active = 1
          AND is_deleted = 0
        ORDER BY RANDOM() LIMIT 1
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

# +++ НОВОЕ: деактивация анкеты
def deactivate_user(user_id):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# +++ НОВОЕ: реактивация анкеты
def reactivate_user(user_id):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# +++ НОВОЕ: полное удаление анкеты из БД
def delete_user(user_id):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# Инициализируем БД при старте скрипта
init_db()

# ==================== СПИСОК НАПРАВЛЕНИЙ ====================
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
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📝 Заполнить заново")],
        # +++ НОВОЕ: отдельная кнопка для управления анкетой
        [KeyboardButton(text="⚙️ Управление анкетой")]
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
    return _get_faculty_keyboard_page(0)

def _get_faculty_keyboard_page(page):
    PAGE_SIZE = 8
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = FACULTY_LIST[start:end]

    buttons = []
    for offset, item in enumerate(page_items):
        buttons.append([InlineKeyboardButton(text=item, callback_data=f"faculty_{start + offset}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"facultypage_{page - 1}"))
    if end < len(FACULTY_LIST):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"facultypage_{page + 1}"))
    if nav:
        buttons.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=buttons)

# +++ НОВОЕ: клавиатура управления анкетой (зависит от текущего статуса)
def get_manage_keyboard(is_active):
    if is_active:
        buttons = [
            [InlineKeyboardButton(text="⏸ Деактивировать анкету", callback_data="profile_deactivate")],
            [InlineKeyboardButton(text="🗑 Удалить анкету", callback_data="profile_delete")],
        ]
    else:
        buttons = [
            [InlineKeyboardButton(text="✅ Активировать анкету", callback_data="profile_reactivate")],
            [InlineKeyboardButton(text="🗑 Удалить анкету", callback_data="profile_delete")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# +++ НОВОЕ: подтверждение удаления
def get_delete_confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ Да, удалить навсегда", callback_data="profile_delete_confirm")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data="profile_manage")],
    ])

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
        "Давай заполним профиль. <b>Как тебя зовут?</b>",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Anketa.name)

@router.message(Anketa.name)
async def process_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name or len(name) > 50:
        await message.answer("Введите корректное имя (не более 50 символов, не пустое).")
        return
    await state.update_data(name=name)
    await message.answer("Введи <b>год твоего поступления</b> (например, 2024):")
    await state.set_state(Anketa.start_year)

@router.message(Anketa.start_year)
async def process_year(message: Message, state: FSMContext):
    year_str = (message.text or "").strip()
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

    # +++ ИЗМЕНЕНО: распаковка теперь включает is_active и is_deleted
    name, start_year, group_num, faculty, photo, is_active, is_deleted = user

    status = "🟢 Активна" if is_active else "🔴 Деактивирована"
    caption = (
        f"📝 <b>Твой профиль:</b>\n"
        f"👤 Имя: {html.escape(name)}\n"
        f"📅 Год: {html.escape(start_year)}\n"
        f"👥 Группа: {html.escape(group_num)}\n"
        f"🎓 Направление: {html.escape(faculty)}\n"
        f"📊 Статус: {status}"
    )
    await message.answer_photo(photo=photo, caption=caption)

# ==================== +++ НОВОЕ: УПРАВЛЕНИЕ АНКЕТОЙ ====================
@router.message(F.text == "⚙️ Управление анкетой")
async def manage_profile(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("У тебя ещё нет анкеты. Нажми '📝 Заполнить заново', чтобы создать.")
        return

    name, start_year, group_num, faculty, photo, is_active, is_deleted = user
    status = "🟢 Активна" if is_active else "🔴 Деактивирована"

    text = (
        f"⚙️ <b>Управление анкетой</b>\n\n"
        f"Текущий статус: {status}\n\n"
        f"⏸ <b>Деактивировать</b> — анкета скроется из поиска, но данные сохранятся. "
        f"Ты сможешь вернуть её в любой момент.\n\n"
        f"🗑 <b>Удалить</b> — анкета и все данные будут удалены безвозвратно."
    )
    await message.answer(text, reply_markup=get_manage_keyboard(is_active))

@router.callback_query(F.data == "profile_manage")
async def manage_profile_callback(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.message.edit_text("У тебя ещё нет анкеты.")
        await call.answer()
        return

    name, start_year, group_num, faculty, photo, is_active, is_deleted = user
    status = "🟢 Активна" if is_active else "🔴 Деактивирована"
    text = (
        f"⚙️ <b>Управление анкетой</b>\n\n"
        f"Текущий статус: {status}\n\n"
        f"⏸ <b>Деактивировать</b> — анкета скроется из поиска, но данные сохранятся.\n\n"
        f"🗑 <b>Удалить</b> — анкета и все данные будут удалены безвозвратно."
    )
    await call.message.edit_text(text, reply_markup=get_manage_keyboard(is_active))
    await call.answer()

# --- Деактивация ---
@router.callback_query(F.data == "profile_deactivate")
async def deactivate_profile(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Анкета не найдена", show_alert=True)
        return

    deactivate_user(call.from_user.id)
    await call.message.edit_text(
        "⏸ <b>Анкета деактивирована.</b>\n\n"
        "Ты больше не показываешься в поиске у других пользователей. "
        "Данные сохранены — вернуть анкету можно в любой момент.",
        reply_markup=get_manage_keyboard(is_active=False)
    )
    await call.answer("Анкета деактивирована")

# --- Реактивация ---
@router.callback_query(F.data == "profile_reactivate")
async def reactivate_profile(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Анкета не найдена", show_alert=True)
        return

    reactivate_user(call.from_user.id)
    await call.message.edit_text(
        "✅ <b>Анкета снова активна!</b>\n\n"
        "Тебя снова видят другие пользователи.",
        reply_markup=get_manage_keyboard(is_active=True)
    )
    await call.answer("Анкета активирована")

# --- Удаление: шаг 1 (подтверждение) ---
@router.callback_query(F.data == "profile_delete")
async def ask_delete_profile(call: types.CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.answer("Анкета не найдена", show_alert=True)
        return

    await call.message.edit_text(
        "🗑 <b>Удалить анкету?</b>\n\n"
        "⚠️ Это действие <b>необратимо</b>: фото, имя, группа и направление "
        "будут удалены из базы навсегда. Совпадения и лайки тоже пропадут.\n\n"
        "Если хочешь просто скрыть анкету — используй деактивацию.",
        reply_markup=get_delete_confirm_keyboard()
    )
    await call.answer()

# --- Удаление: шаг 2 (подтверждено) ---
@router.callback_query(F.data == "profile_delete_confirm")
async def confirm_delete_profile(call: types.CallbackQuery):
    delete_user(call.from_user.id)
    await call.message.edit_text(
        "✅ Анкета удалена.\n\n"
        "Чтобы создать новую — нажми '📝 Заполнить заново'."
    )
    await call.answer("Анкета удалена")

# ==================== МЕХАНИКА ПОИСКА ЧУЖИХ АНКЕТ ====================
async def send_random_profile(message_or_call, user_id):
    is_callback = isinstance(message_or_call, types.CallbackQuery)
    target = message_or_call.message if is_callback else message_or_call

    stranger = get_random_stranger(user_id)
    if not stranger:
        await target.answer("В базе пока нет других анкет, кроме твоей. Пригласи друзей!")
        return

    s_id, s_name, s_year, s_group, s_faculty, s_photo = stranger
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
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала заполни свою анкету, чтобы искать других!")
        return

    # +++ НОВОЕ: если анкета деактивирована — предлагаем активировать перед поиском
    _, _, _, _, _, is_active, is_deleted = user
    if not is_active:
        await message.answer(
            "⚠️ Твоя анкета сейчас <b>деактивирована</b> — тебя не видят другие.\n"
            "Активируй её через '⚙️ Управление анкетой', чтобы участвовать в поиске."
        )
        return

    await send_random_profile(message, message.from_user.id)

# ОБРАБОТКА ИНЛАЙН-КНОПОК (ЛАЙК И ДАЛЬШЕ)
@router.callback_query(F.data.startswith("like_"))
async def like_callback(call: types.CallbackQuery):
    await call.message.edit_reply_markup(reply_markup=None)

    stranger_id = int(call.data.split("_")[1])

    # +++ НОВОЕ: проверяем, что целевая анкета ещё активна и не удалена
    target_user = get_user(stranger_id)
    if not target_user or not target_user[5] or target_user[6]:
        # target_user[5] = is_active, target_user[6] = is_deleted
        await call.answer("Эта анкета больше недоступна", show_alert=True)
        await send_random_profile(call, call.from_user.id)
        return

    my_profile = get_user(call.from_user.id)

    if my_profile:
        my_name, my_year, my_group, my_faculty, my_photo = my_profile[:5]

        if call.from_user.username:
            username_text = f"🔗 Ссылка: @{call.from_user.username}"
        else:
            username_text = f'🔗 Ссылка: <a href="tg://user?id={call.from_user.id}">Профиль</a>'

        notification_caption = (
            f"❤️ <b>Ты понравился этому человеку!</b>\n\n"
            f"👤 Имя: {html.escape(my_name)}\n"
            f"📅 Год: {html.escape(my_year)}\n"
            f"👥 Группа: {html.escape(my_group)}\n"
            f"🎓 Направление: {html.escape(my_faculty)}\n\n"
            f"{username_text}"
        )

        try:
            await bot.send_photo(
                chat_id=stranger_id,
                photo=my_photo,
                caption=notification_caption
            )
        except Exception:
            pass

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