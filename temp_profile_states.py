from aiogram.fsm.state import State, StatesGroup

# ==================== СОСТОЯНИЯ ВРЕМЕННЫХ АНКЕТ ====================
class TempProfile(StatesGroup):
    """Состояния для создания временной анкеты."""
    # Выбор цели поиска
    goal_choice = State()
    # Заполнение имени (из профиля / вручную / пропустить)
    name_choice = State()
    name_input = State()
    # Заполнение года (из профиля / вручную / пропустить)
    year_choice = State()
    year_input = State()
    # Заполнение группы (из профиля / вручную / пропустить)
    group_choice = State()
    group_input = State()
    # Заполнение факультета (из профиля / вручную / пропустить)
    faculty_choice = State()
    faculty = State()
    # Фото (из профиля / вручную / пропустить)
    photo_choice = State()
    photo = State()
    # Описание (необязательно)
    description = State()
    #выбор срока кнопкой
    duration_choice = State()
    # ввод числа
    duration_input = State()
    # Конфирмация создания
    confirm = State()
