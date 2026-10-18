"""Database operations for events and event responses."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from app.core.db import db_connection
from app.features.temp_profile.temp_profile_db import save_temp_profile_with_partial_fill


def get_event_categories_by_type(category_type=None):
    with db_connection() as conn:
        if category_type:
            return conn.execute(
                "SELECT id, name, type FROM event_categories WHERE type = ? ORDER BY name",
                (category_type,),
            ).fetchall()
        return conn.execute(
            "SELECT id, name, type FROM event_categories ORDER BY type, name"
        ).fetchall()


def get_category_type_by_id(category_id):
    with db_connection() as conn:
        row = conn.execute("SELECT type FROM event_categories WHERE id = ?", (category_id,)).fetchone()
        return row[0] if row else None


def get_event_category_name(category_id):
    with db_connection() as conn:
        row = conn.execute("SELECT name FROM event_categories WHERE id = ?", (category_id,)).fetchone()
        return row[0] if row else ""


def get_responses_count(event_id):
    with db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM event_responses WHERE event_id = ?", (event_id,)
        ).fetchone()
        return int(row[0]) if row else 0


def create_event_full(user_id, title, date_start, date_end, time_start,
                      category_id, people_needed, description, location):
    """Create an event and its event-specific participant-search profile."""
    if not title or not title.strip():
        raise ValueError("Название события не может быть пустым")
    start_date = datetime.strptime(date_start, "%Y-%m-%d").date()
    end_date = datetime.strptime(date_end or date_start, "%Y-%m-%d").date()
    if end_date < start_date:
        raise ValueError("Дата окончания не может быть раньше даты начала")
    if people_needed is None:
        raise ValueError("Количество участников обязательно")
    if int(people_needed) < 1:
        raise ValueError("Количество участников должно быть положительным")
    expires_at = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    now = datetime.now().isoformat(sep=" ", timespec="seconds")

    with db_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO events
               (user_id, title, date_start, date_end, time_start, category_id,
                people_needed, description, location, status, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (user_id, title.strip(), start_date.isoformat(), end_date.isoformat(), time_start,
             category_id, int(people_needed), (description or "").strip(), (location or "").strip(),
             now, expires_at.isoformat(sep=" ", timespec="seconds")),
        )
        event_id = cursor.lastrowid

    # Link the event to a dedicated temporary profile. This profile is the
    # searchable "I am looking for people for this exact event" card.
    profile_id = save_temp_profile_with_partial_fill(
        user_id,
        {"goal": "ищу_людей", "description": (description or "").strip(), "expires_at": expires_at},
        event_id=event_id,
    )
    with db_connection() as conn:
        conn.execute("UPDATE events SET participant_profile_id = ? WHERE id = ?", (profile_id, event_id))
    return event_id


def ensure_event_participant_profile(user_id, event_id):
    """Return/create the user's event-specific profile used by event responses."""
    with db_connection() as conn:
        row = conn.execute(
            "SELECT id FROM temp_profiles WHERE user_id = ? AND event_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
            (user_id, event_id),
        ).fetchone()
    if row:
        return row[0]
    with db_connection() as conn:
        event_row = conn.execute("SELECT expires_at FROM events WHERE id = ?", (event_id,)).fetchone()
    event_expiry = datetime.fromisoformat(event_row[0]) if event_row and event_row[0] else datetime.now() + timedelta(days=3)
    return save_temp_profile_with_partial_fill(
        user_id,
        {"goal": "предлагаю_себя", "description": "Отклик на мероприятие", "expires_at": event_expiry},
        event_id=event_id,
    )


def get_active_events_for_search(user_id, limit=5):
    """Return unviewed active events from other users, newest first."""
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    with db_connection() as conn:
        return conn.execute(
            """SELECT e.id, e.title, e.date_start, e.date_end, e.time_start,
                      e.people_needed, e.description, e.location,
                      ec.name AS category_name, ec.type AS category_type,
                      up.name AS creator_name, up.photo AS creator_photo,
                      e.participant_profile_id
               FROM events e
               JOIN event_categories ec ON e.category_id = ec.id
               JOIN user_profiles up ON e.user_id = up.user_id
               WHERE e.user_id <> ? AND e.status = 'active' AND e.expires_at > ?
                 AND NOT EXISTS (
                     SELECT 1 FROM viewed_events v
                     WHERE v.user_id = ? AND v.event_id = e.id
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM accounts a
                     WHERE a.user_id = e.user_id AND a.banned_until > datetime('now', 'localtime')
                 )
                 AND (e.people_needed IS NULL OR (
                     SELECT COUNT(*) FROM event_responses er WHERE er.event_id = e.id
                 ) < e.people_needed)
               ORDER BY RANDOM() LIMIT ?""",
            (user_id, now, user_id, max(1, int(limit))),
        ).fetchall()


def get_event_detail(event_id):
    with db_connection() as conn:
        return conn.execute(
            """SELECT e.id, e.user_id, e.title, e.date_start, e.date_end, e.time_start,
                      e.category_id, e.people_needed, e.description, e.location, e.status,
                      e.created_at, e.expires_at, ec.name AS category_name,
                      ec.type AS category_type, up.name AS creator_name, up.photo AS creator_photo
               FROM events e
               LEFT JOIN event_categories ec ON e.category_id = ec.id
               LEFT JOIN user_profiles up ON e.user_id = up.user_id
               WHERE e.id = ?""",
            (event_id,),
        ).fetchone()


def add_event_response(event_id, user_id):
    """Register a response and attach the responder's event-specific profile."""
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    # Validate the event first, then create the linked profile outside the write transaction.
    with db_connection() as conn:
        event = conn.execute(
            "SELECT user_id, status, expires_at, people_needed FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if not event:
            return None
        owner_id, status, expires_at, people_needed = event
        if owner_id == user_id or status != "active":
            return None
        if expires_at and expires_at <= now:
            conn.execute("UPDATE events SET status = 'expired' WHERE id = ?", (event_id,))
            return None
        count = conn.execute(
            "SELECT COUNT(*) FROM event_responses WHERE event_id = ?", (event_id,)
        ).fetchone()[0]
        if people_needed is not None and count >= int(people_needed):
            conn.execute("UPDATE events SET status = 'closed' WHERE id = ?", (event_id,))
            return None
        duplicate = conn.execute(
            "SELECT 1 FROM event_responses WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        ).fetchone()
        if duplicate:
            return None

    participant_profile_id = ensure_event_participant_profile(user_id, event_id)
    with db_connection() as conn:
        # Re-check capacity and duplicate after profile creation to avoid stale writes.
        event = conn.execute(
            "SELECT status, people_needed FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if not event or event[0] != "active":
            return None
        count = conn.execute(
            "SELECT COUNT(*) FROM event_responses WHERE event_id = ?", (event_id,)
        ).fetchone()[0]
        if event[1] is not None and count >= int(event[1]):
            conn.execute("UPDATE events SET status = 'closed' WHERE id = ?", (event_id,))
            return None
        try:
            cursor = conn.execute(
                "INSERT INTO event_responses (event_id, user_id, created_at, temp_profile_id) VALUES (?, ?, ?, ?)",
                (event_id, user_id, now, participant_profile_id),
            )
        except sqlite3.IntegrityError:
            return None
        if event[1] is not None and count + 1 >= int(event[1]):
            conn.execute("UPDATE events SET status = 'closed' WHERE id = ?", (event_id,))
        return cursor.lastrowid


def has_user_responded(event_id, user_id):
    with db_connection() as conn:
        return conn.execute(
            "SELECT 1 FROM event_responses WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        ).fetchone() is not None


def get_event_responses_list(event_id, user_id):
    """List responses only if the requesting user owns the event."""
    with db_connection() as conn:
        return conn.execute(
            """SELECT er.id, er.user_id, er.created_at, er.temp_profile_id,
                      up.name, up.photo, up.start_year, up.group_num, up.faculty,
                      tp.goal, tp.description
               FROM event_responses er
               JOIN events e ON e.id = er.event_id
               LEFT JOIN user_profiles up ON up.user_id = er.user_id
               LEFT JOIN temp_profiles tp ON tp.id = er.temp_profile_id
               WHERE er.event_id = ? AND e.user_id = ?
               ORDER BY er.created_at ASC""",
            (event_id, user_id),
        ).fetchall()


def mark_event_viewed(user_id, event_id):
    with db_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO viewed_events (user_id, event_id) VALUES (?, ?)",
            (user_id, event_id),
        )


def reset_events_viewed(user_id):
    with db_connection() as conn:
        conn.execute("DELETE FROM viewed_events WHERE user_id = ?", (user_id,))


def close_event_by_owner(event_id, user_id):
    with db_connection() as conn:
        cursor = conn.execute(
            "UPDATE events SET status = 'closed' WHERE id = ? AND user_id = ? AND status = 'active'",
            (event_id, user_id),
        )
        return cursor.rowcount > 0


def extend_event_by_owner(event_id, user_id, new_expires_at):
    with db_connection() as conn:
        cursor = conn.execute(
            "UPDATE events SET expires_at = ?, status = 'active' WHERE id = ? AND user_id = ?",
            (new_expires_at, event_id, user_id),
        )
        return cursor.rowcount > 0


def get_user_events_full(user_id):
    with db_connection() as conn:
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        conn.execute(
            "UPDATE events SET status = 'expired' WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        return conn.execute(
            """SELECT e.id, e.title, e.date_start, e.date_end, e.time_start,
                      e.people_needed, e.description, e.location, e.category_id,
                      e.status, e.created_at, e.expires_at, ec.name AS category_name
               FROM events e LEFT JOIN event_categories ec ON e.category_id = ec.id
               WHERE e.user_id = ? AND e.status IN ('active', 'closed', 'expired')
               ORDER BY e.created_at DESC""",
            (user_id,),
        ).fetchall()


def should_auto_close_event(event_id):
    with db_connection() as conn:
        row = conn.execute(
            """SELECT e.people_needed,
                      (SELECT COUNT(*) FROM event_responses r WHERE r.event_id = e.id)
               FROM events e WHERE e.id = ?""",
            (event_id,),
        ).fetchone()
        return bool(row and row[0] is not None and row[1] >= row[0])


def get_event_responses(event_id, user_id):
    """Backward-compatible alias for get_event_responses_list."""
    return get_event_responses_list(event_id, user_id)


# Legacy alias kept for imports in older versions of this project.
def get_active_events(user_id, limit=10):
    return get_active_events_for_search(user_id, limit=limit)
