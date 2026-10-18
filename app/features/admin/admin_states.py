from aiogram.fsm.state import State, StatesGroup


class AdminFlow(StatesGroup):
    """Одношаговые диалоги админ-панели."""
    user_search = State()        # ввод Telegram ID / внутреннего ID
    sanction_comment = State()   # комментарий к санкции / решению по жалобе
    sanction_confirm = State()   # подтверждение перманентного бана
    setting_value = State()      # новое числовое значение настройки
    journal_value = State()      # значение фильтра журнала


class AdCreate(StatesGroup):
    """Создание рекламной вставки."""
    text = State()
    image = State()
    url = State()
    button = State()
    every_n = State()
    max_per_user = State()
    start_date = State()
    end_date = State()
    confirm = State()


class AdEdit(StatesGroup):
    value = State()


class ReportFlow(StatesGroup):
    """Жалоба пользователя: комментарий для причины «Другое»."""
    comment = State()
