import sqlite3
from datetime import datetime, timedelta

# ==================== СОБЫТИЯ ====================
def get_event_categories_by_type(category_type=None):
    """Возвращает категории событий, сгруппированные по типу."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    if category_type:
        cursor.execute("SELECT id, name FROM event_categories WHERE type = ? ORDER BY name", (category_type,))
    else:
        cursor.execute("SELECT id, name, type FROM event_categories ORDER BY type, name")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_category_type_by_id(category_id):
    """Возвращает тип категории по ID."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT type FROM event_categories WHERE id = ?", (category_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_responses_count(event_id):
    """Возвращает количество откликов на событие."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM event_responses WHERE event_id = ?", (event_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def create_event_full(user_id, title, date_start, date_end, time_start, category_id, people_needed, description, location):
    """Создает анкету события с полной валидацией."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    now = datetime.now()

    # Парсим дату окончания для расчета срока действия
    end_date_str = date_end if date_end else date_start
    try:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    except ValueError:
        end_date = datetime.strptime(date_start, "%Y-%m-%d")

    # Срок действия: 1 день после окончания события
    expires_at = end_date + timedelta(days=1)

    cursor.execute("""
        INSERT INTO events (user_id, title, date_start, date_end, time_start, category_id, people_needed, description, location, status, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
    """, (user_id, title, date_start, date_end, time_start, category_id, people_needed, description, location, now, expires_at))

    event_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return event_id

def get_active_events_for_search(user_id, limit=5):
    """Возвращает активные события для поиска (исключая просмотренные)."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("""
        SELECT e.id, e.title, e.date_start, e.date_end, e.time_start, e.people_needed, e.description, e.location,
               ec.name as category_name, ec.type as category_type, up.name as creator_name, up.photo as creator_photo
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

def get_event_detail(event_id):
    """Возвращает детальную информацию о событии."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.id, e.user_id, e.title, e.date_start, e.date_end, e.time_start, e.category_id, e.people_needed,
               e.description, e.location, e.status, e.created_at, e.expires_at,
               ec.name as category_name, ec.type as category_type,
               up.name as creator_name, up.photo as creator_photo
        FROM events e
        JOIN event_categories ec ON e.category_id = ec.id
        JOIN user_profiles up ON e.user_id = up.user_id
        WHERE e.id = ?
    """, (event_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def add_event_response(event_id, user_id):
    """Добавляет отклик на событие."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    now = datetime.now()
    try:
        cursor.execute("INSERT INTO event_responses (event_id, user_id, created_at) VALUES (?, ?, ?)", (event_id, user_id, now))
        response_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return response_id
    except sqlite3.IntegrityError:
        # Уже откликался
        conn.close()
        return None

def has_user_responded(event_id, user_id):
    """Проверяет, откликался ли пользователь на событие."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM event_responses WHERE event_id = ? AND user_id = ?", (event_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def get_event_responses_list(event_id, user_id):
    """Возвращает список откликов на событие (для владельца)."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT er.id, er.user_id, er.created_at, up.name, up.photo, up.start_year, up.group_num, up.faculty
        FROM event_responses er
        JOIN user_profiles up ON er.user_id = up.user_id
        WHERE er.event_id = ?
        ORDER BY er.created_at ASC
    """, (event_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_responses_count(event_id):
    """Возвращает количество откликов на событие."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM event_responses WHERE event_id = ?", (event_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def should_auto_close_event(event_id):
    """Проверяет, нужно ли автоматически закрыть событие по количеству откликов."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT people_needed FROM events WHERE id = ?", (event_id,))
    row = cursor.fetchone()
    if not row or row[0] is None:
        conn.close()
        return False
    people_needed = row[0]
    count = get_responses_count(event_id)
    conn.close()
    return count >= people_needed

def mark_event_viewed(user_id, event_id):
    """Помечает событие как просмотренное."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO viewed_events (user_id, event_id) VALUES (?, ?)", (user_id, event_id))
    conn.commit()
    conn.close()

def reset_events_viewed(user_id):
    """Сбрасывает просмотренные события для пользователя."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM viewed_events WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def close_event_by_owner(event_id, user_id):
    """Закрывает событие владельцем."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE events SET status = 'closed' WHERE id = ? AND user_id = ?", (event_id, user_id))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

def extend_event_by_owner(event_id, user_id, new_expires_at):
    """Продлевает срок действия события владельцем."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE events SET expires_at = ?, status = 'active' WHERE id = ? AND user_id = ?", (new_expires_at, event_id, user_id))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

def get_user_events_full(user_id):
    """Возвращает все события пользователя с деталями."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.id, e.title, e.date_start, e.date_end, e.time_start, e.people_needed, e.description, e.location,
               e.category_id, e.status, e.created_at, e.expires_at,
               ec.name as category_name
        FROM events e
        JOIN event_categories ec ON e.category_id = ec.id
        WHERE e.user_id = ? AND e.status IN ('active', 'closed')
        ORDER BY e.created_at DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_event_category_name(category_id):
    """Возвращает название категории по ID."""
    conn = sqlite3.connect("dating_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM event_categories WHERE id = ?", (category_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""