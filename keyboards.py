from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

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

def get_main_menu():
    """Главное меню с новыми вкладками."""
    buttons = [
        [KeyboardButton(text="🔍 Поиск людей для общения")],
        [KeyboardButton(text="🎯 Поиск для задач/проектов")],
        [KeyboardButton(text="📅 Поиск мероприятий")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📝 Заполнить заново")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_temp_profile_keyboard():
    """Клавиатура для выбора цели поиска временной анкеты."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Ищу людей для поиска", callback_data="goal_iscu_ludei"),
             InlineKeyboardButton(text="🙋 Предлагаю себя для поиска", callback_data="goal_predlagayu_sebya")],
        ]
    )

def get_confirm_temp_profile_keyboard():
    """Клавиатура для подтверждения создания временной анкеты."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтверждаю создание", callback_data="confirm_temp_profile_yes")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="confirm_temp_profile_no")],
        ]
    )

def get_faculty_keyboard(page=0):
    """Клавиатура с выбором факультета (со страничной навигацией)."""
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

def get_temp_profile_confirm_keyboard():
    """Клавиатура для подтверждения создания временной анкеты."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтверждаю создание", callback_data="confirm_temp_profile_yes")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="confirm_temp_profile_no")],
        ]
    )

def get_search_keyboard():
    """Клавиатура для поиска анкет (для общения)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👍 Нравится", callback_data="like"),
             InlineKeyboardButton(text="👎 Не нравится", callback_data="dislike")],
            [InlineKeyboardButton(text="🛑 Остановить поиск", callback_data="stop_search")],
        ]
    )

def get_profile_view_keyboard():
    """Клавиатура для просмотра своего профиля."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать профиль", callback_data="edit_profile")],
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")],
        ]
    )

def get_field_choice_keyboard(field_name):
    """Клавиатура для выбора способа заполнения поля (из профиля / вручную / пропустить)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📥 Взять из профиля", callback_data=f"{field_name}_from_profile")],
            [InlineKeyboardButton(text=f"✏️ Ввести вручную", callback_data=f"{field_name}_manual")],
            [InlineKeyboardButton(text=f"⏭️ Пропустить", callback_data=f"{field_name}_skip")],
        ]
    )

def get_event_category_keyboard():
    """Клавиатура для выбора категории события."""
    categories = [
        ("📚 Учебные", "cat_Учебные"),
        ("🎨 Внеучебные", "cat_Внеучебные"),
        ("🏠 Жизненные", "cat_Жизненные"),
        ("🏛️ Официальные (только админы)", "cat_Официальные"),
    ]
    buttons = []
    for name, callback in categories:
        buttons.append([InlineKeyboardButton(text=name, callback_data=callback)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_event_confirm_keyboard():
    """Клавиатура для подтверждения создания события."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать событие", callback_data="confirm_event_yes")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="confirm_event_no")],
        ]
    )

def get_event_search_keyboard():
    """Клавиатура для поиска событий."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🙋 Откликнуться", callback_data="respond_event")],
            [InlineKeyboardButton(text="⏭️ Следующее", callback_data="next_event")],
            [InlineKeyboardButton(text="🛑 Остановить поиск", callback_data="stop_event_search")],
        ]
    )

def get_my_events_keyboard():
    """Клавиатура для управления своими событиями."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Мои события", callback_data="my_events")],
            [InlineKeyboardButton(text="➕ Создать событие", callback_data="create_event")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")],
        ]
    )