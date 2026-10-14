from aiogram.fsm.state import State, StatesGroup

# ==================== СОСТОЯНИЯ (FSM) ====================
class Anketa(StatesGroup):
    name = State()
    start_year = State()
    group_num = State()
    faculty = State()
    photo = State()

# Включаем состояния из других файлов для удобства импорта
# (Фактически состояния будут импортироваться из отдельных файлов в handlers)
