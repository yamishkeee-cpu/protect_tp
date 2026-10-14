"""SQLite data access for the university matching bot.

The database location can be overridden with DATABASE_PATH. By default the
file is stored next to this module, so running the bot from another working
folder will not silently create a second database.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

def _resolve_db_path(configured_path: Optional[str]) -> Path:
    """Resolve configured relative paths beside this module, not the shell CWD."""
    project_dir = Path(__file__).resolve().parent
    if not configured_path or not configured_path.strip():
        return project_dir / "dating_bot.db"
    path = Path(configured_path.strip()).expanduser()
    if not path.is_absolute():
        path = project_dir / path
    return path


DB_PATH = _resolve_db_path(os.getenv("DATABASE_PATH"))


def connect_db() -> sqlite3.Connection:
    """Open a configured SQLite connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def db_connection() -> Iterator[sqlite3.Connection]:
    conn = connect_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables and safely migrate data from the original prototype."""
    with db_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                start_year TEXT,
                group_num TEXT,
                faculty TEXT,
                photo TEXT,
                viewed INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                start_year TEXT,
                group_num TEXT,
                faculty TEXT,
                photo TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS viewed_profiles (
                user_id INTEGER NOT NULL,
                profile_user_id INTEGER NOT NULL,
                viewed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, profile_user_id)
            );

            CREATE TABLE IF NOT EXISTS user_likes (
                user_id INTEGER NOT NULL,
                liked_user_id INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, liked_user_id),
                CHECK (user_id <> liked_user_id)
            );

            CREATE TABLE IF NOT EXISTS temp_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT,
                start_year TEXT,
                group_num TEXT,
                faculty TEXT,
                photo TEXT,
                goal TEXT,
                description TEXT,
                created_at TIMESTAMP,
                expires_at TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1,
                event_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS viewed_temp (
                user_id INTEGER NOT NULL,
                temp_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, temp_id)
            );

            CREATE TABLE IF NOT EXISTS temp_profile_responses (
                temp_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (temp_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS event_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                date_start TEXT NOT NULL,
                date_end TEXT,
                time_start TEXT,
                category_id INTEGER,
                people_needed INTEGER,
                description TEXT DEFAULT '',
                location TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP,
                expires_at TIMESTAMP,
                participant_profile_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS event_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP,
                temp_profile_id INTEGER,
                UNIQUE (event_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS viewed_events (
                user_id INTEGER NOT NULL,
                event_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, event_id)
            );

            CREATE INDEX IF NOT EXISTS idx_temp_profiles_active_expiry
                ON temp_profiles (is_active, expires_at);
            CREATE INDEX IF NOT EXISTS idx_events_status_expiry
                ON events (status, expires_at);
            CREATE INDEX IF NOT EXISTS idx_event_responses_event
                ON event_responses (event_id);
            """
        )

        # Migrate event/profile linkage columns for existing databases.
        for table, column, definition in (
            ("temp_profiles", "event_id", "INTEGER"),
            ("event_responses", "temp_profile_id", "INTEGER"),
            ("events", "participant_profile_id", "INTEGER"),
        ):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

        # Existing DBs may predate the events tables or have duplicate responses.
        # Create a unique index only after de-duplicating old rows.
        conn.execute(
            "DELETE FROM event_responses WHERE id NOT IN "
            "(SELECT MIN(id) FROM event_responses GROUP BY event_id, user_id)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_event_responses_event_user "
            "ON event_responses (event_id, user_id)"
        )

        # Migrate legacy permanent profiles in both directions without replacing
        # newer entries. save_user() now writes both tables during normal use.
        conn.execute(
            """INSERT OR IGNORE INTO user_profiles
               (user_id, name, start_year, group_num, faculty, photo, created_at, updated_at)
               SELECT user_id, name, start_year, group_num, faculty, photo,
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
               FROM users WHERE user_id IS NOT NULL"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO users
               (user_id, name, start_year, group_num, faculty, photo, viewed)
               SELECT user_id, name, start_year, group_num, faculty, photo, 0
               FROM user_profiles WHERE user_id IS NOT NULL"""
        )
        # user_profiles is the canonical table for the current application.
        # Synchronize an older users row in case the two tables had diverged.
        conn.execute(
            """UPDATE users SET
                 name = (SELECT p.name FROM user_profiles p WHERE p.user_id = users.user_id),
                 start_year = (SELECT p.start_year FROM user_profiles p WHERE p.user_id = users.user_id),
                 group_num = (SELECT p.group_num FROM user_profiles p WHERE p.user_id = users.user_id),
                 faculty = (SELECT p.faculty FROM user_profiles p WHERE p.user_id = users.user_id),
                 photo = (SELECT p.photo FROM user_profiles p WHERE p.user_id = users.user_id)
               WHERE EXISTS (SELECT 1 FROM user_profiles p WHERE p.user_id = users.user_id)"""
        )

        default_categories = (
            ("Учебные проекты", "учебные"),
            ("Внеучебные проекты", "внеучебные"),
            ("События не связанные с учебой", "связанные_с_жизнью"),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO event_categories (name, type) VALUES (?, ?)",
            default_categories,
        )


def save_user_profile(user_id: int, name: str, start_year: str, group_num: str,
                      faculty: str, photo: Optional[str]) -> None:
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO user_profiles
               (user_id, name, start_year, group_num, faculty, photo, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 name=excluded.name, start_year=excluded.start_year,
                 group_num=excluded.group_num, faculty=excluded.faculty,
                 photo=excluded.photo, updated_at=excluded.updated_at""",
            (user_id, name, start_year, group_num, faculty, photo, now, now),
        )
        conn.execute(
            """INSERT INTO users (user_id, name, start_year, group_num, faculty, photo, viewed)
               VALUES (?, ?, ?, ?, ?, ?, 0)
               ON CONFLICT(user_id) DO UPDATE SET
                 name=excluded.name, start_year=excluded.start_year,
                 group_num=excluded.group_num, faculty=excluded.faculty, photo=excluded.photo""",
            (user_id, name, start_year, group_num, faculty, photo),
        )


def save_user(user_id: int, name: str, start_year: str, group_num: str,
              faculty: str, photo: Optional[str]) -> None:
    """Compatibility function: save the same current profile in both tables."""
    save_user_profile(user_id, name, start_year, group_num, faculty, photo)


def get_user(user_id: int):
    with db_connection() as conn:
        row = conn.execute(
            "SELECT name, start_year, group_num, faculty, photo FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT name, start_year, group_num, faculty, photo FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row


def get_user_profile(user_id: int):
    with db_connection() as conn:
        row = conn.execute(
            "SELECT name, start_year, group_num, faculty, photo FROM user_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row


def get_random_stranger(user_id: int):
    """Get a profile the requesting user has not viewed yet."""
    with db_connection() as conn:
        return conn.execute(
            """SELECT u.user_id, u.name, u.start_year, u.group_num, u.faculty, u.photo
               FROM users AS u
               WHERE u.user_id <> ?
                 AND EXISTS (SELECT 1 FROM user_profiles p WHERE p.user_id = u.user_id)
                 AND NOT EXISTS (
                     SELECT 1 FROM viewed_profiles v
                     WHERE v.user_id = ? AND v.profile_user_id = u.user_id
                 )
               ORDER BY RANDOM() LIMIT 1""",
            (user_id, user_id),
        ).fetchone()


def mark_stranger_viewed(user_id: int, stranger_id: Optional[int] = None) -> None:
    """Mark a profile viewed by a specific user (legacy one-arg calls supported)."""
    with db_connection() as conn:
        if stranger_id is None:
            # Backward compatibility with the old globally shared viewed flag.
            conn.execute("UPDATE users SET viewed = 1 WHERE user_id = ?", (user_id,))
        else:
            conn.execute(
                "INSERT OR IGNORE INTO viewed_profiles (user_id, profile_user_id) VALUES (?, ?)",
                (user_id, stranger_id),
            )


def reset_all_viewed(user_id: Optional[int] = None) -> None:
    """Reset views for one user; no global cross-user interference."""
    with db_connection() as conn:
        if user_id is None:
            conn.execute("DELETE FROM viewed_profiles")
            conn.execute("UPDATE users SET viewed = 0")
        else:
            conn.execute("DELETE FROM viewed_profiles WHERE user_id = ?", (user_id,))


def add_like(user_id: int, liked_user_id: int) -> bool:
    if user_id == liked_user_id:
        return False
    with db_connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO user_likes (user_id, liked_user_id) VALUES (?, ?)",
            (user_id, liked_user_id),
        )
        return cursor.rowcount > 0


def has_like(user_id: int, liked_user_id: int) -> bool:
    with db_connection() as conn:
        return conn.execute(
            "SELECT 1 FROM user_likes WHERE user_id = ? AND liked_user_id = ?",
            (user_id, liked_user_id),
        ).fetchone() is not None


def create_temp_profile(user_id, name, start_year, group_num, faculty, photo,
                        goal, description=None, expires_at=None):
    now = datetime.now()
    if expires_at is None:
        expires_at = now + timedelta(days=3)
    with db_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO temp_profiles
               (user_id, name, start_year, group_num, faculty, photo, goal, description,
                created_at, expires_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (user_id, name, start_year, group_num, faculty, photo, goal, description or "",
             now.isoformat(sep=" ", timespec="seconds"), expires_at),
        )
        return cursor.lastrowid


def get_active_temp_profiles_for_search(user_id, goal_preference=None):
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    params = [user_id, now, user_id]
    query = """SELECT tp.id, tp.name, tp.start_year, tp.group_num, tp.faculty,
                      tp.photo, tp.goal, tp.description, tp.user_id, tp.event_id,
                      e.title AS event_title, e.date_start AS event_date_start,
                      e.date_end AS event_date_end, e.people_needed AS event_people_needed
               FROM temp_profiles tp
               LEFT JOIN events e ON e.id = tp.event_id
               WHERE tp.user_id <> ? AND tp.is_active = 1 AND tp.expires_at > ?
                 AND NOT EXISTS (
                   SELECT 1 FROM viewed_temp v WHERE v.user_id = ? AND v.temp_id = tp.id
                 )"""
    if goal_preference == "ищу_людей":
        query += " AND tp.goal = ?"
        params.append("предлагаю_себя")
    elif goal_preference == "предлагаю_себя":
        query += " AND tp.goal = ?"
        params.append("ищу_людей")
    query += " ORDER BY RANDOM() LIMIT 1"
    with db_connection() as conn:
        return conn.execute(query, params).fetchone()


def mark_temp_viewed(user_id, temp_id):
    with db_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO viewed_temp (user_id, temp_id) VALUES (?, ?)",
            (user_id, temp_id),
        )


def reset_temp_viewed(user_id):
    with db_connection() as conn:
        conn.execute("DELETE FROM viewed_temp WHERE user_id = ?", (user_id,))


def get_user_temp_profiles(user_id):
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    with db_connection() as conn:
        return conn.execute(
            """SELECT id, name, start_year, group_num, faculty, photo, goal, description,
                      created_at, expires_at
               FROM temp_profiles
               WHERE user_id = ? AND is_active = 1 AND expires_at > ?
               ORDER BY created_at DESC""",
            (user_id, now),
        ).fetchall()


def get_temp_profile_by_id(temp_id):
    with db_connection() as conn:
        return conn.execute(
            """SELECT id, user_id, name, start_year, group_num, faculty, photo, goal, description,
                      is_active, expires_at
               FROM temp_profiles WHERE id = ?""",
            (temp_id,),
        ).fetchone()


def add_temp_profile_response(temp_id, user_id):
    with db_connection() as conn:
        row = conn.execute(
            "SELECT user_id, is_active, expires_at FROM temp_profiles WHERE id = ?",
            (temp_id,),
        ).fetchone()
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        if not row or row[0] == user_id or not row[1] or (row[2] and row[2] <= now):
            return False
        try:
            cursor = conn.execute(
                "INSERT INTO temp_profile_responses (temp_id, user_id) VALUES (?, ?)",
                (temp_id, user_id),
            )
            return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            return False


def close_temp_profile(temp_id, user_id):
    with db_connection() as conn:
        cursor = conn.execute(
            "UPDATE temp_profiles SET is_active = 0 WHERE id = ? AND user_id = ?",
            (temp_id, user_id),
        )
        return cursor.rowcount > 0


# Initialize schema on import to preserve behavior of the original project.
init_db()
