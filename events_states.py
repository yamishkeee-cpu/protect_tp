from aiogram.fsm.state import State, StatesGroup

# ==================== СОСТОЯНИЯ АНКЕТ СОБЫТИЙ ====================
class EventCreation(StatesGroup):
    """Состояния для создания анкеты события."""
    # Основные поля
    title = State()          # Название события (обязательно)
    date_choice = State()    # Выбор типа даты: конкретная / диапазон
    date_input = State()     # Ввод даты (YYYY-MM-DD) или начала диапазона
    date_end_input = State() # Ввод конца диапазона (опционально)
    time_choice = State()    # Нужно ли указывать время (опционально)
    time_input = State()     # Ввод времени (HH:MM)
    # Категория события
    category_choice = State()
    # Количество людей (обязательно)
    people_needed_choice = State()
    people_needed_input = State()
    # Описание (опционально)
    description = State()
    # Местоположение (опционально)
    location = State()
    # Конфирмация
    confirm = State()
