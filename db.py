import sqlite3
from datetime import datetime, timedelta

# ==================== РАБОТА С БАЗОЙ ДАННЫХ (SQLite) ====================
def init_db():
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    # --- Существующая таблица пользователей (для обратной совместимости) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            start_year TEXT,
            group_num TEXT,
            faculty TEXT,
            photo TEXT,
            viewed INTEGER DEFAULT 0
        )
    """)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN viewed INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # --- Постоянные профили (внутренние аккаунты) ---
    # Хранит основную информацию владельца, доступ только у него.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            start_year TEXT,
            group_num TEXT,
            faculty TEXT,
            photo TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    # --- Временные анкеты (для задач/проектов с целью поиска) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS temp_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            start_year TEXT,
            group_num TEXT,
            faculty TEXT,
            photo TEXT,
            goal TEXT, -- 'ищу_людей' или 'предлагаю_себя'
            description TEXT,
            created_at TIMESTAMP,
            expires_at TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
    """)
    # --- Категории событий ---
    # type: 'учебные', 'внеучебные', 'связанные_с_жизнью', 'официальные'
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            type TEXT
        )
    """)
    # --- Анкеты событий ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            date_start TEXT, -- YYYY-MM-DD
            date_end TEXT,   -- YYYY-MM-DD (опционально для диапазона)
            time_start TEXT, -- HH:MM (опционально)
            category_id INTEGER,
            people_needed INTEGER, -- может быть NULL
            description TEXT,
            location TEXT,
            status TEXT DEFAULT 'active', -- 'active', 'closed', 'expired'
            created_at TIMESTAMP,
            expires_at TIMESTAMP
        )
    """)
    # --- Отклики на события ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            user_id INTEGER,
            created_at TIMESTAMP
        )
    """)
    # --- Отслеживание просмотра временных анкет ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viewed_temp (
            user_id INTEGER,
            temp_id INTEGER,
            PRIMARY KEY (user_id, temp_id)
        )
    """)
    # --- Отслеживание просмотра анкет событий ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viewed_events (
            user_id INTEGER,
            event_id INTEGER,
            PRIMARY KEY (user_id, event_id)
        )
    """)
    # --- Заполнение категорий по умолчанию ---
    default_categories = [
        ("Учебные проекты", "учебные"),
        ("Внеучебные проекты", "внеучебные"),
        ("События не связанные с учебой", "связанные_с_жизнью"),
    ]
    for name, cat_type in default_categories:
        cursor.execute("INSERT OR IGNORE INTO event_categories (name, type) VALUES (?, ?)", (name, cat_type))
    conn.commit()
    conn.close()

# ==================== Постоянный профиль ====================
def save_user_profile(user_id, name, start_year, group_num, faculty, photo):
    """Создает или обновляет постоянный профиль пользователя."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("""
        INSERT INTO user_profiles (user_id, name, start_year, group_num, faculty, photo, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name, start_year=excluded.start_year, group_num=excluded.group_num,
            faculty=excluded.faculty, photo=excluded.photo, updated_at=excluded.updated_at
    """, (user_id, name, start_year, group_num, faculty, photo, now, now))
    conn.commit()
    conn.close()

def get_user_profile(user_id):
    """Возвращает постоянный профиль пользователя или None."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, start_year, group_num, faculty, photo FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

# ==================== Старые функции (совместимость) ====================
def save_user(user_id, name, start_year, group_num, faculty, photo):
    """Сохраняет пользователя в старую таблицу для обратной совместимости."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, name, start_year, group_num, faculty, photo, viewed)
        VALUES (?, ?, ?, ?, ?, ?, 0)
    """, (user_id, name, start_year, group_num, faculty, photo))
    conn.commit()
    conn.close()

def get_user(user_id):
    """Возвращает данные пользователя из старой таблицы."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, start_year, group_num, faculty, photo FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_random_stranger(user_id):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, name, start_year, group_num, faculty, photo
        FROM users
        WHERE user_id != ? AND viewed = 0
        ORDER BY RANDOM() LIMIT 1
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def mark_stranger_viewed(stranger_id):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET viewed = 1 WHERE user_id = ?", (stranger_id,))
    conn.commit()
    conn.close()

def reset_all_viewed():
    """Сбрасываем статус просмотра для всех."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET viewed = 0")
    conn.commit()
    conn.close()

# ==================== Временные анкеты ====================
def create_temp_profile(user_id, name, start_year, group_num, faculty, photo, goal, description=None, expires_at=None):
    """Создает временную анкету."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    now = datetime.now()
    if expires_at is None:
        expires_at = now + timedelta(days=3)
    cursor.execute("""
        INSERT INTO temp_profiles (user_id, name, start_year, group_num, faculty, photo, goal, description, created_at, expires_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (user_id, name, start_year, group_num, faculty, photo, goal, description, now, expires_at))
    profile_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return profile_id

def get_active_temp_profiles_for_search(user_id, goal_preference=None):
    """Возвращает активные временные анкеты для поиска.
    user_id - кто ищет.
    goal_preference - если 'ищу_людей', показывает анкеты с 'предлагаю_себя' и наоборот.
    """
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    now = datetime.now()
    # Если пользователь ищет людей, показываем анкеты "кто предлагает себя"
    if goal_preference == 'ищу_людей':
        target_goal = 'предлагаю_себя'
    elif goal_preference == 'предлагаю_себя':
        target_goal = 'ищу_людей'
    else:
        target_goal = None
    query = """
        SELECT tp.id, tp.name, tp.start_year, tp.group_num, tp.faculty, tp.photo, tp.goal, tp.description
        FROM temp_profiles tp
        JOIN user_profiles up ON tp.user_id = up.user_id
        WHERE tp.user_id != ? AND tp.is_active = 1 AND tp.expires_at > ?
    """
    params = [user_id, now]
    if target_goal:
        query += " AND tp.goal = ?"
        params.append(target_goal)
    query += " AND tp.id NOT IN (SELECT temp_id FROM viewed_temp WHERE user_id = ?) ORDER BY RANDOM() LIMIT 1"
    params.append(user_id)
    cursor.execute(query, params)
    row = cursor.fetchone()
    conn.close()
    return row

def mark_temp_viewed(user_id, temp_id):
    """Помечает временную анкету как просмотренную пользователем."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO viewed_temp (user_id, temp_id) VALUES (?, ?)", (user_id, temp_id))
    conn.commit()
    conn.close()

def reset_temp_viewed(user_id):
    """Сбрасывает просмотренные временные анкеты для пользователя."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM viewed_temp WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_user_temp_profiles(user_id):
    """Возвращает все активные временные анкеты пользователя."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, start_year, group_num, faculty, photo, goal, description, created_at, expires_at
        FROM temp_profiles
        WHERE user_id = ? AND is_active = 1
        ORDER BY created_at DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def close_temp_profile(temp_id, user_id):
    """Деактивирует временную анкету (только для владельца)."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE temp_profiles SET is_active = 0 WHERE id = ? AND user_id = ?", (temp_id, user_id))
    conn.commit()
    conn.close()

# ==================== События ====================
def get_event_categories(category_type=None):
    """Возвращает категории событий. Если category_type задан, фильтрует по типу."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    if category_type:
        cursor.execute("SELECT id, name FROM event_categories WHERE type = ?", (category_type,))
    else:
        cursor.execute("SELECT id, name, type FROM event_categories ORDER BY type, name")
    rows = cursor.fetchall()
    conn.close()
    return rows

def add_event_category(name, category_type):
    """Добавляет новую категорию события."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO event_categories (name, type) VALUES (?, ?)", (name, category_type))
    conn.commit()
    conn.close()

def get_category_by_id(category_id):
    """Возвращает категорию по ID."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM event_categories WHERE id = ?", (category_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def create_event(user_id, title, date_start, date_end, time_start, category_id, people_needed, description, location):
    """Создает анкету события."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    now = datetime.now()
    # Срок действия: 1 день после конца события
    end_date = datetime.strptime(date_end if date_end else date_start, "%Y-%m-%d")
    expires_at = end_date + timedelta(days=1)
    cursor.execute("""
        INSERT INTO events (user_id, title, date_start, date_end, time_start, category_id, people_needed, description, location, status, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
    """, (user_id, title, date_start, date_end, time_start, category_id, people_needed, description, location, now, expires_at))
    event_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return event_id

def get_active_events(user_id, limit=10):
    """Возвращает активные события от других пользователей."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("""
        SELECT e.id, e.title, e.date_start, e.date_end, e.time_start, e.people_needed, e.description, e.location,
               ec.name as category_name, up.name as creator_name, up.photo as creator_photo
        FROM events e
        JOIN event_categories ec ON e.category_id = ec.id
        JOIN user_profiles up ON e.user_id = up.user_id
        WHERE e.user_id != ? AND e.status = 'active' AND e.expires_at > ?
        AND e.id NOT IN (SELECT event_id FROM viewed_events WHERE user_id = ?)
        ORDER BY e.created_at DESC LIMIT ?
    """, (user_id, now, user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_event_by_id(event_id):
    """Возвращает полную информацию о событии."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.id, e.user_id, e.title, e.date_start, e.date_end, e.time_start, e.category_id, e.people_needed,
               e.description, e.location, e.status, e.created_at, e.expires_at, ec.name as category_name,
               up.name as creator_name, up.photo as creator_photo
        FROM events e
        JOIN event_categories ec ON e.category_id = ec.id
        JOIN user_profiles up ON e.user_id = up.user_id
        WHERE e.id = ?
    """, (event_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_event_responses(event_id, user_id):
    """Возвращает отклики на событие (только для владельца)."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT er.id, er.user_id, er.created_at, up.name, up.photo
        FROM event_responses er
        JOIN user_profiles up ON er.user_id = up.user_id
        WHERE er.event_id = ? AND e.user_id = ?
    """, (event_id, user_id))
    rows = cursor.fetchall()
    conn.close()
    return rows

def add_event_response(event_id, user_id):
    """Добавляет отклик на событие."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("INSERT OR IGNORE INTO event_responses (event_id, user_id, created_at) VALUES (?, ?, ?)", (event_id, user_id, now))
    response_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return response_id

def mark_event_viewed(user_id, event_id):
    """Помечает событие как просмотренное."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO viewed_events (user_id, event_id) VALUES (?, ?)", (user_id, event_id))
    conn.commit()
    conn.close()

def reset_events_viewed(user_id):
    """Сбрасывает просмотренные события."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM viewed_events WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def close_event(event_id, user_id):
    """Закрывает событие (только для владельца)."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE events SET status = 'closed' WHERE id = ? AND user_id = ?", (event_id, user_id))
    conn.commit()
    conn.close()

def extend_event(event_id, user_id, new_expires_at):
    """Продлевает срок действия события."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE events SET expires_at = ? WHERE id = ? AND user_id = ?", (new_expires_at, event_id, user_id))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

def get_user_events(user_id):
    """Возвращает события созданные пользователем."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, title, date_start, date_end, time_start, people_needed, category_id, status, created_at, expires_at
        FROM events
        WHERE user_id = ? AND status IN ('active', 'closed')
        ORDER BY created_at DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

# Инициализируем БД при старте скрипта
init_db()
