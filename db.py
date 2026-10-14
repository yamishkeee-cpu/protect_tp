import sqlite3

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
            photo TEXT,
            viewed INTEGER DEFAULT 0
        )
    """)
    # Добавим колонку viewed, если её ещё нет (для старых БД)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN viewed INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def save_user(user_id, name, start_year, group_num, faculty, photo):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, name, start_year, group_num, faculty, photo, viewed)
        VALUES (?, ?, ?, ?, ?, ?, 0)
    """, (user_id, name, start_year, group_num, faculty, photo))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, start_year, group_num, faculty, photo FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_random_stranger(user_id):
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    # Ищем случайного пользователя, чей ID не равен ID текущего юзера И которого ещё не просмотрели
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
    """Сбрасываем статус просмотра для всех — вызывается при завершении просмотра."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET viewed = 0")
    conn.commit()
    conn.close()

# Инициализируем БД при старте скрипта
init_db()
