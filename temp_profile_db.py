import sqlite3
from datetime import datetime, timedelta
from db import init_db  # Чтобы гарантировать инициализацию БД

# ==================== ВРЕМЕННЫЕ АНКЕТЫ ====================
def get_temp_profile_fields_from_user(user_id):
    """Получает данные из постоянного профиля для предложения в анкете."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, start_year, group_num, faculty, photo FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row  # (name, start_year, group_num, faculty, photo) или None

def save_temp_profile_with_partial_fill(user_id, field_data):
    """Сохраняет временную анкету с частичным заполнением из профиля.
    field_data: dict с ключами: name, start_year, group_num, faculty, photo, goal, description
    Значения могут быть None (значит пропущено) или строка/булево.
    Для photo и других полей: если None, берется из профиля, если False/пустая строка - пропускается.
    """
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    now = datetime.now()

    # Сначала получаем данные из профиля
    profile_data = get_temp_profile_fields_from_user(user_id)
    profile_dict = None
    if profile_data:
        profile_dict = {
            'name': profile_data[0],
            'start_year': profile_data[1],
            'group_num': profile_data[2],
            'faculty': profile_data[3],
            'photo': profile_data[4]
        }

    # Формируем итоговые данные
    name = field_data.get('name')
    if name is None and profile_dict:
        name = profile_dict['name']
    elif name is None:
        name = ""

    start_year = field_data.get('start_year')
    if start_year is None and profile_dict:
        start_year = profile_dict['start_year']
    elif start_year is None:
        start_year = ""

    group_num = field_data.get('group_num')
    if group_num is None and profile_dict:
        group_num = profile_dict['group_num']
    elif group_num is None:
        group_num = ""

    faculty = field_data.get('faculty')
    if faculty is None and profile_dict:
        faculty = profile_dict['faculty']
    elif faculty is None:
        faculty = ""

    photo = field_data.get('photo')
    if photo is None and profile_dict:
        photo = profile_dict['photo']
    elif photo is None:
        photo = ""

    goal = field_data.get('goal', '')
    description = field_data.get('description', '')

    # Срок действия: 3 дня по умолчанию
    expires_at = now + timedelta(days=3)

    cursor.execute("""
        INSERT INTO temp_profiles (user_id, name, start_year, group_num, faculty, photo, goal, description, created_at, expires_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (user_id, name, start_year, group_num, faculty, photo, goal, description, now, expires_at))

    temp_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return temp_id

# Оставляем остальные функции из db.py, но импортируем оттуда для избежания дублирования
# В реальном коде эти функции будут в основном db.py, но здесь для полноты:
def get_active_temp_profiles_for_search(user_id, goal_preference=None):
    from db import get_active_temp_profiles_for_search as base_func
    return base_func(user_id, goal_preference)

def mark_temp_viewed(user_id, temp_id):
    from db import mark_temp_viewed as base_func
    base_func(user_id, temp_id)

def reset_temp_viewed(user_id):
    from db import reset_temp_viewed as base_func
    base_func(user_id)

def get_user_temp_profiles(user_id):
    from db import get_user_temp_profiles as base_func
    return base_func(user_id)

def close_temp_profile(temp_id, user_id):
    from db import close_temp_profile as base_func
    base_func(temp_id, user_id)
