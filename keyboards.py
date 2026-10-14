from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

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
    for offset, item in enumerate(page_items):
        # В callback_data кладём индекс: название длиннее лимита Telegram в 64 байта
        buttons.append([InlineKeyboardButton(text=item, callback_data=f"faculty_{start + offset}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"facultypage_{page - 1}"))
    if end < len(FACULTY_LIST):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"facultypage_{page + 1}"))
    if nav:
        buttons.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=buttons)
