"""Database access helpers for temporary task/project profiles."""
from __future__ import annotations

from db import (
    add_temp_profile_response,
    close_temp_profile,
    get_active_temp_profiles_for_search,
    get_temp_profile_by_id,
    get_user_temp_profiles,
    mark_temp_viewed,
    reset_temp_viewed,
    save_user_profile,
    db_connection,
)


def get_temp_profile_fields_from_user(user_id):
    with db_connection() as conn:
        return conn.execute(
            "SELECT name, start_year, group_num, faculty, photo FROM user_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def save_temp_profile_with_partial_fill(user_id, field_data, event_id=None):
    """Create an active temporary profile.

    A missing/None field inherits from the permanent profile; an empty string
    means the user explicitly skipped that field.
    """
    from datetime import datetime, timedelta

    profile_data = get_temp_profile_fields_from_user(user_id)
    profile_dict = None
    if profile_data:
        profile_dict = dict(zip(
            ("name", "start_year", "group_num", "faculty", "photo"), profile_data
        ))

    resolved = {}
    for key in ("name", "start_year", "group_num", "faculty", "photo"):
        value = field_data.get(key)
        if value is None and profile_dict:
            value = profile_dict.get(key)
        resolved[key] = value if value is not None else ""

    goal = field_data.get("goal")
    if goal not in {"ищу_людей", "предлагаю_себя"}:
        raise ValueError("Не указана корректная цель временной анкеты")

    now = datetime.now()
    expires_at = field_data.get("expires_at") or (now + timedelta(days=3))
    with db_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO temp_profiles
               (user_id, name, start_year, group_num, faculty, photo, goal, description,
                created_at, expires_at, is_active, event_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (user_id, resolved["name"], resolved["start_year"], resolved["group_num"],
             resolved["faculty"], resolved["photo"], goal,
             (field_data.get("description") or "").strip(),
             now.isoformat(sep=" ", timespec="seconds"),
             expires_at.isoformat(sep=" ", timespec="seconds"), event_id),
        )
        return cursor.lastrowid


__all__ = [
    "get_temp_profile_fields_from_user", "save_temp_profile_with_partial_fill",
    "get_active_temp_profiles_for_search", "mark_temp_viewed", "reset_temp_viewed",
    "get_user_temp_profiles", "get_temp_profile_by_id", "add_temp_profile_response",
    "close_temp_profile",
]
