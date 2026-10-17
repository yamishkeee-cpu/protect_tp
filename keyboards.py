"""Telegram keyboards used by the bot's registration and discovery flows."""
from contextvars import ContextVar
from typing import Optional

from verification_db import get_user_status, was_ever_verified

# Кто сейчас пишет боту (заполняется в bot.py, нужно для персонального меню).
current_user_id: ContextVar[Optional[int]] = ContextVar("current_user_id", default=None)
VERIFY_MENU_TEXT = "✉️ Подтвердить почту"

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

FACULTY_LIST = [
    "Дизайн",
    "Иностранные языки и межкультурная бизнес-коммуникация",
    "Компьютерные науки и технологии",
    "Международная программа по бизнесу и экономике",
    "Программная инженерия (очно-заочное обучение)",
    "Технологии искусственного и дополненного интеллекта",
    "Филология",
    "Фундаментальная и прикладная лингвистика",
    "Фундаментальная и прикладная математика",
    "Цифровой маркетинг",
    "Экономика и бизнес (очно-заочное обучение)",
    "Юриспруденция",
]


def get_main_menu():
    rows = [
        [KeyboardButton(text="🔍 Поиск людей для общения")],
        [KeyboardButton(text="🎯 Поиск для задач/проектов")],
        [KeyboardButton(text="📅 Поиск мероприятий")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📝 Заполнить заново")],
    ]
    user_id = current_user_id.get()
    if user_id is not None:
        status = get_user_status(user_id)
        if status == "guest" or (status == "banned" and not was_ever_verified(user_id)):
            rows.append([KeyboardButton(text=VERIFY_MENU_TEXT)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def get_faculty_keyboard(page=0):
    page_size = 8
    page_count = (len(FACULTY_LIST) + page_size - 1) // page_size
    page = max(0, min(int(page), page_count - 1))
    start = page * page_size
    end = start + page_size
    buttons = [
        [InlineKeyboardButton(text=item, callback_data=f"faculty_{idx}")]
        for idx, item in enumerate(FACULTY_LIST[start:end], start=start)
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"facultypage_{page - 1}"))
    if end < len(FACULTY_LIST):
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"facultypage_{page + 1}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_temp_profile_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Смотреть анкеты для задач", callback_data="search_temp_profiles")],
        [InlineKeyboardButton(text="➕ Создать временную анкету", callback_data="create_temp_profile")],
        [InlineKeyboardButton(text="📋 Мои временные анкеты", callback_data="my_temp_profiles")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_menu")],
    ])


def get_temp_profile_keyboard():
    """Goal selection used when creating a temporary profile."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Ищу людей для задачи", callback_data="goal_seek")],
        [InlineKeyboardButton(text="🙋 Предлагаю себя для задачи", callback_data="goal_offer")],
    ])


def get_confirm_temp_profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить анкету", callback_data="confirm_temp_profile_yes")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="confirm_temp_profile_no")],
    ])
def get_duration_keyboard():
    """Выбор срока размещения временной анкеты."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 день",  callback_data="dur_1"),
            InlineKeyboardButton(text="3 дня",   callback_data="dur_3"),
            InlineKeyboardButton(text="7 дней",  callback_data="dur_7"),
        ],
        [
            InlineKeyboardButton(text="14 дней", callback_data="dur_14"),
            InlineKeyboardButton(text="30 дней", callback_data="dur_30"),
        ],
        [
            InlineKeyboardButton(text="✏️ Своё число", callback_data="dur_custom"),
        ],
    ])

def get_field_choice_keyboard(field_name):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Взять из постоянного профиля", callback_data=f"{field_name}_from_profile")],
        [InlineKeyboardButton(text="✏️ Ввести вручную", callback_data=f"{field_name}_manual")],
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data=f"{field_name}_skip")],
    ])


def get_search_keyboard(profile_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Нравится", callback_data=f"like_{profile_id}"),
         InlineKeyboardButton(text="⏭️ Дальше", callback_data=f"next_profile_{profile_id}")],
        [InlineKeyboardButton(text="🚩 Пожаловаться", callback_data=f"rp:{profile_id}")],
        [InlineKeyboardButton(text="🛑 Остановить поиск", callback_data="stop_search")],
    ])


def get_temp_search_keyboard(temp_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋 Интересно", callback_data=f"temp_interest_{temp_id}"),
         InlineKeyboardButton(text="⏭️ Дальше", callback_data=f"temp_next_{temp_id}")],
        [InlineKeyboardButton(text="🛑 Остановить поиск", callback_data="temp_stop_search")],
    ])


def get_profile_view_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Заполнить профиль заново", callback_data="edit_profile")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")],
    ])


def get_event_category_keyboard(categories):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"event_category_{category_id}")]
        for category_id, name, *_ in categories
    ])


def get_event_confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать событие", callback_data="confirm_event_creation")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_event_creation")],
    ])


def get_event_search_keyboard(event_id, already_responded=False):
    button = InlineKeyboardButton(
        text="✅ Вы уже откликнулись" if already_responded else "🙋 Откликнуться",
        callback_data="already_responded" if already_responded else f"event_respond_{event_id}",
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [button],
        [InlineKeyboardButton(text="⏭️ Следующее", callback_data=f"event_next_{event_id}")],
        [InlineKeyboardButton(text="🛑 Остановить поиск", callback_data="stop_event_search")],
    ])


def get_event_management_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Искать события", callback_data="search_events")],
        [InlineKeyboardButton(text="➕ Создать событие", callback_data="create_event")],
        [InlineKeyboardButton(text="📋 Мои события", callback_data="my_events")],
        [InlineKeyboardButton(text="💬 Отклики на мои события", callback_data="my_event_responses")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_menu")],
    ])


def get_my_events_keyboard():
    return get_event_management_keyboard()
