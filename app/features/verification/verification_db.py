"""База данных для подтверждения почты: статусы, коды, привязка почты.

Почта в открытом виде нигде не хранится, только HMAC-хэш.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.core.db import db_connection

VALID_STATUSES = ("guest", "verified", "banned")
TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_ts(dt: datetime) -> str:
    """aware-datetime -> строка UTC (сравнимая лексикографически)."""
    return dt.astimezone(timezone.utc).strftime(TS_FORMAT)


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, TS_FORMAT).replace(tzinfo=timezone.utc)


def now_str() -> str:
    return format_ts(datetime.now(timezone.utc))


# ---------- статусы ----------

def get_user_status(user_id: int) -> str:
    """Статус пользователя; для несуществующего возвращает 'guest'."""
    with db_connection() as conn:
        row = conn.execute(
            "SELECT status FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row and row[0] in VALID_STATUSES:
        return row[0]
    return "guest"

def was_ever_verified(user_id: int) -> bool:
    """True, если пользователь когда-либо подтверждал почту (даже если сейчас забанен)."""
    with db_connection() as conn:
        row = conn.execute(
            "SELECT verified_at FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row and row[0]:
            return True
        row = conn.execute(
            "SELECT 1 FROM verified_emails WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row is not None


def set_status(user_id: int, status: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    """Единственная точка смены статуса. True, если пользователь найден.

    Можно передать conn, чтобы выполнить смену в чужой транзакции.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Неизвестный статус: {status!r}")

    def _apply(c: sqlite3.Connection) -> bool:
        if status == "verified":
            cur = c.execute(
                "UPDATE users SET status = ?, verified_at = ? WHERE user_id = ?",
                (status, now_str(), user_id),
            )
        else:
            cur = c.execute(
                "UPDATE users SET status = ? WHERE user_id = ?", (status, user_id)
            )
        return cur.rowcount > 0

    if conn is not None:
        return _apply(conn)
    with db_connection() as own:
        return _apply(own)


# ---------- коды и лимиты ----------

def get_last_request_at(user_id: int) -> Optional[str]:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT MAX(created_at) FROM email_verifications WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return row[0] if row else None


def count_requests_since(user_id: int, since_ts: str) -> int:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM email_verifications WHERE user_id = ? AND created_at >= ?",
            (user_id, since_ts),
        ).fetchone()
    return int(row[0])

def count_requests_for_email_since(email_hash: str, since_ts: str) -> int:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM email_verifications WHERE email_hash = ? AND created_at >= ?",
            (email_hash, since_ts),
        ).fetchone()
    return int(row[0])


def create_verification(user_id: int, code_hash: str, email_hash: str,
                        created_at: str, expires_at: str, is_used: bool = False) -> int:
    """Создаёт запись о запросе. Новый активный код гасит все прежние коды пользователя.

    is_used=True создаёт «служебную» запись (например, отклонённая занятая почта):
    она учитывается в лимитах, но кодом не является.
    """
    with db_connection() as conn:
        if not is_used:
            conn.execute(
                "UPDATE email_verifications SET is_used = 1 WHERE user_id = ? AND is_used = 0",
                (user_id,),
            )
        cur = conn.execute(
            """INSERT INTO email_verifications
               (user_id, code_hash, email_hash, created_at, expires_at, attempts, is_used)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (user_id, code_hash, email_hash, created_at, expires_at, 1 if is_used else 0),
        )
        return cur.lastrowid


def delete_verification(verification_id: int) -> None:
    with db_connection() as conn:
        conn.execute("DELETE FROM email_verifications WHERE id = ?", (verification_id,))


def get_active_verification(user_id: int):
    """Последний неиспользованный код: (id, code_hash, email_hash, expires_at, attempts)."""
    with db_connection() as conn:
        return conn.execute(
            """SELECT id, code_hash, email_hash, expires_at, attempts
               FROM email_verifications
               WHERE user_id = ? AND is_used = 0
               ORDER BY id DESC LIMIT 1""",
            (user_id,),
        ).fetchone()


def increment_attempts(verification_id: int) -> int:
    with db_connection() as conn:
        conn.execute(
            "UPDATE email_verifications SET attempts = attempts + 1 WHERE id = ?",
            (verification_id,),
        )
        row = conn.execute(
            "SELECT attempts FROM email_verifications WHERE id = ?", (verification_id,)
        ).fetchone()
    return int(row[0]) if row else 0


def mark_verification_used(verification_id: int) -> None:
    with db_connection() as conn:
        conn.execute(
            "UPDATE email_verifications SET is_used = 1 WHERE id = ?", (verification_id,)
        )


# ---------- привязка почты ----------

def get_email_owner(email_hash: str) -> Optional[int]:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT user_id FROM verified_emails WHERE email_hash = ?", (email_hash,)
        ).fetchone()
    return row[0] if row else None


def complete_verification(verification_id: int, user_id: int, email_hash: str) -> str:
    """Атомарно: привязать почту, поставить статус verified, погасить код.

    Возвращает 'ok', 'email_taken' или 'no_profile'.
    """
    with db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")  # берём блокировку записи сразу
        owner = conn.execute(
            "SELECT user_id FROM verified_emails WHERE email_hash = ?", (email_hash,)
        ).fetchone()
        if owner is not None and owner[0] != user_id:
            conn.execute(
                "UPDATE email_verifications SET is_used = 1 WHERE id = ?", (verification_id,)
            )
            return "email_taken"
        if not set_status(user_id, "verified", conn=conn):
            return "no_profile"
        conn.execute(
            """INSERT INTO verified_emails (email_hash, user_id, verified_at)
               VALUES (?, ?, ?)
               ON CONFLICT(email_hash) DO UPDATE SET verified_at = excluded.verified_at""",
            (email_hash, user_id, now_str()),
        )
        conn.execute(
            "UPDATE email_verifications SET is_used = 1 WHERE id = ?", (verification_id,)
        )
        return "ok"