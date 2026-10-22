"""Database layer for the admin panel: roles, bans, reports, journal, settings, spam limits, ads.

Design notes
* Every public function opens ONE connection and does all of its writes on it
  (SQLite does not like nested writers from separate connections).
* The `accounts` table itself is created in db.init_db() because the feed
  queries in db.py / events_db.py join against it; everything else lives here.
* The journal (`admin_actions`) is append-only: triggers reject UPDATE/DELETE.
"""
from __future__ import annotations

import os
import random
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

from app.core.db import db_connection

PERMANENT_UNTIL = "9999-12-31 23:59:59"
ROLE_ADMIN = "admin"
ROLE_MODERATOR = "moderator"

REPORT_REASONS = {
    "spam": "Спам",
    "abuse": "Оскорбления",
    "fake": "Фейк",
    "photo": "Неприемлемое фото",
    "other": "Другое",
}

# key -> (title, kind, min, max). Defaults are in SETTINGS_DEFAULTS.
SETTINGS_META = {
    "reports_only_registered": ("Жалобы принимаются только от верифицированных", "bool", None, None),\
    "reports_per_day": ("Жалоб в сутки от одного пользователя", "int", 1, 100),
    "likes_per_hour": ("Лайков в час", "int", 1, 1000),
    "skips_per_hour": ("Пропусков в час", "int", 1, 5000),
    "creations_per_day": ("Создание анкет и событий в сутки", "int", 1, 100),
    "burst_actions": ("Действий за 10 сек до временного ограничения", "int", 3, 200),
    "restrict_minutes": ("Длительность временного ограничения, мин", "int", 1, 1440),
}
SETTINGS_DEFAULTS = {
    "reports_only_registered": "1",
    "reports_per_day": "5",
    "likes_per_hour": "30",
    "skips_per_hour": "100",
    "creations_per_day": "5",
    "burst_actions": "15",
    "restrict_minutes": "10",
}

JOURNAL_ACTIONS = {
    "ban_temp": "Временный бан",
    "ban_perm": "Бан навсегда",
    "unban": "Снятие блокировки",
    "warn": "Предупреждение",
    "report_dismiss": "Жалоба отклонена",
    "status_change": "Смена статуса",
    "setting_change": "Изменение настроек",
    "ad_create": "Создание рекламы",
    "ad_toggle": "Вкл/выкл рекламы",
    "ad_delete": "Удаление рекламы",
    "ad_edit": "Редактирование рекламы",
    "auto_restrict": "Ограничение активности",
    "admin_bind": "Назначение админа по username",
}


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


@contextmanager
def _conn():
    with db_connection() as conn:
        conn.row_factory = sqlite3.Row
        yield conn


# ----------------------------------------------------------------- schema
def init_admin_db() -> None:
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL CHECK (role IN ('admin', 'moderator')),
                added_at TEXT NOT NULL,
                username TEXT,                               -- lowercase, set when bound by username
                source TEXT NOT NULL DEFAULT 'id'            -- id (ADMIN_IDS) | username (ADMIN_USERNAMES)
            );

            -- Usernames from .env waiting for the person to write to the bot once.
            CREATE TABLE IF NOT EXISTS admin_usernames (
                username TEXT PRIMARY KEY,                   -- lowercase, without @
                role TEXT NOT NULL CHECK (role IN ('admin', 'moderator'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                comment TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new',          -- new | reviewed | auto_banned
                decision TEXT,                               -- dismiss | warn | temp_ban | perm_ban | auto_ban | covered
                moderator_id INTEGER,
                moderator_comment TEXT NOT NULL DEFAULT '',
                target_was_registered INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_reports_status ON reports (status, created_at);
            CREATE INDEX IF NOT EXISTS idx_reports_target ON reports (target_id, status);

            CREATE TABLE IF NOT EXISTS sanctions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,                          -- warning | temp_ban | perm_ban | unban
                reason TEXT NOT NULL DEFAULT '',
                comment TEXT NOT NULL DEFAULT '',
                admin_id INTEGER,                            -- NULL for automatic actions
                source TEXT NOT NULL DEFAULT 'admin',        -- admin | auto
                report_id INTEGER,
                created_at TEXT NOT NULL,
                expires_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sanctions_user ON sanctions (user_id, created_at);

            CREATE TABLE IF NOT EXISTS admin_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                admin_id INTEGER,                            -- NULL for automatic actions
                source TEXT NOT NULL,                        -- admin | auto
                action TEXT NOT NULL,
                target_user_id INTEGER,
                reason TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_admin_actions_created ON admin_actions (created_at);
            CREATE TRIGGER IF NOT EXISTS admin_actions_no_update
                BEFORE UPDATE ON admin_actions
                BEGIN SELECT RAISE(ABORT, 'admin_actions is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS admin_actions_no_delete
                BEFORE DELETE ON admin_actions
                BEGIN SELECT RAISE(ABORT, 'admin_actions is append-only'); END;

            -- A limit was exceeded: the action is blocked for the user until `until`.
            CREATE TABLE IF NOT EXISTS action_blocks (
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                until TEXT NOT NULL,
                PRIMARY KEY (user_id, action)
            );

            CREATE TABLE IF NOT EXISTS action_log (
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_action_log ON action_log (user_id, action, created_at);

            CREATE TABLE IF NOT EXISTS ad_campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                image TEXT,                                  -- Telegram file_id
                url TEXT NOT NULL,
                button_text TEXT NOT NULL,
                every_n INTEGER NOT NULL DEFAULT 10,         -- one ad per N profiles
                max_per_user INTEGER,                        -- NULL = unlimited
                start_date TEXT,                             -- YYYY-MM-DD, NULL = immediately
                end_date TEXT,                               -- YYYY-MM-DD inclusive, NULL = no end
                is_active INTEGER NOT NULL DEFAULT 0,
                created_by INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ad_impressions (
                ad_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                shown_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ad_impr ON ad_impressions (ad_id, user_id);

            CREATE TABLE IF NOT EXISTS ad_clicks (
                ad_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                clicked_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ad_clicks ON ad_clicks (ad_id, user_id);

            CREATE TABLE IF NOT EXISTS user_ad_state (
                user_id INTEGER PRIMARY KEY,
                counter INTEGER NOT NULL DEFAULT 0
            );
            """
        )


        # Migrations for databases created by earlier versions of the admin panel.
        def columns(table):
            return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}

        if "username" not in columns("accounts"):
            conn.execute("ALTER TABLE accounts ADD COLUMN username TEXT")
        if "username" not in columns("admins"):
            conn.execute("ALTER TABLE admins ADD COLUMN username TEXT")
        if "source" not in columns("admins"):
            conn.execute("ALTER TABLE admins ADD COLUMN source TEXT NOT NULL DEFAULT 'id'")

        # Older versions limited a reporter to ONE complaint per person; that UNIQUE
        # constraint silently dropped complaints. SQLite cannot drop it in place: rebuild.
        if any(r["unique"] and r["origin"] == "u" for r in conn.execute("PRAGMA index_list(reports)")):
            conn.executescript(
                """
                ALTER TABLE reports RENAME TO reports_old;
                CREATE TABLE reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reporter_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    comment TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'new',
                    decision TEXT,
                    moderator_id INTEGER,
                    moderator_comment TEXT NOT NULL DEFAULT '',
                    target_was_registered INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                );
                INSERT INTO reports SELECT * FROM reports_old;
                DROP TABLE reports_old;
                CREATE INDEX IF NOT EXISTS idx_reports_status ON reports (status, created_at);
                CREATE INDEX IF NOT EXISTS idx_reports_target ON reports (target_id, status);
                """
            )
            # Подтвердившие почту считаются верифицированными (строку accounts создаём, если её нет).
            verified_ids = ("SELECT user_id FROM users WHERE status = 'verified' "
                            "UNION SELECT user_id FROM verified_emails")
            conn.execute(
                f"INSERT OR IGNORE INTO accounts (user_id, is_registered, created_at) "
                f"SELECT user_id, 1, ? FROM ({verified_ids})", (_now(),))
            conn.execute(
                f"UPDATE accounts SET is_registered = 1 WHERE is_registered = 0 "
                f"AND user_id IN ({verified_ids})")
            # Бан верифицированного не должен сниматься подтверждением почты: только администратором.
            conn.execute(
                f"UPDATE accounts SET ban_source = 'admin' "
                f"WHERE ban_source IN ('unverified', 'auto_report') AND banned_until > ? "
                f"AND user_id IN ({verified_ids})", (_now(),))
            # Подтвердившие почту считаются зарегистрированными (строку в accounts создаём, если её нет).
            conn.execute(
                "INSERT OR IGNORE INTO accounts (user_id, is_registered, created_at) "
                "SELECT user_id, 1, ? FROM users WHERE status = 'verified'",
                (_now(),),
            )
            conn.execute(
                "UPDATE accounts SET is_registered = 1 WHERE is_registered = 0 "
                "AND user_id IN (SELECT user_id FROM users WHERE status = 'verified')"
            )


_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")


def _parse_usernames(env_name: str) -> list[str]:
    raw = os.getenv(env_name, "")
    names = (x.strip().lstrip("@").lower() for x in re.split(r"[,\s;]+", raw))
    return [n for n in names if _USERNAME_RE.match(n)]


def sync_admins_from_env() -> None:
    """Read admins from .env.

    ADMIN_USERNAMES / MODERATOR_USERNAMES  - Telegram @usernames (main way). The person is
        bound to the role the first time they write to the bot (see bind_admin_by_username).
        .env is the source of truth: removing a name and restarting revokes the access.
    ADMIN_IDS / MODERATOR_IDS              - optional fallback by numeric Telegram ID.
    """
    def parse_ids(name: str) -> list[int]:
        raw = os.getenv(name, "")
        return [int(x) for x in re.split(r"[,\s;]+", raw) if x.strip().lstrip("-").isdigit()]

    with _conn() as conn:
        # -- usernames: replace the waiting list; admin wins if a name is in both lists
        conn.execute("DELETE FROM admin_usernames")
        for role, env_name in ((ROLE_MODERATOR, "MODERATOR_USERNAMES"), (ROLE_ADMIN, "ADMIN_USERNAMES")):
            for name in _parse_usernames(env_name):
                conn.execute(
                    "INSERT INTO admin_usernames (username, role) VALUES (?, ?) "
                    "ON CONFLICT(username) DO UPDATE SET role = excluded.role",
                    (name, role),
                )
        # revoke / re-role people who were bound by username earlier
        conn.execute(
            "DELETE FROM admins WHERE source = 'username' "
            "AND (username IS NULL OR username NOT IN (SELECT username FROM admin_usernames))"
        )
        conn.execute(
            "UPDATE admins SET role = (SELECT role FROM admin_usernames u WHERE u.username = admins.username) "
            "WHERE source = 'username'"
        )
        # -- numeric IDs (fallback)
        for role, env_name in ((ROLE_MODERATOR, "MODERATOR_IDS"), (ROLE_ADMIN, "ADMIN_IDS")):
            # admins are written last, so an ID listed in both ends up as admin
            for uid in parse_ids(env_name):
                conn.execute(
                    "INSERT INTO admins (user_id, role, added_at, source) VALUES (?, ?, ?, 'id') "
                    "ON CONFLICT(user_id) DO UPDATE SET role = excluded.role, source = 'id'",
                    (uid, role, _now()),
                )


def bind_admin_by_username(user_id: int, username) -> Optional[str]:
    """Called for every incoming update. If this @username is in ADMIN_USERNAMES /
    MODERATOR_USERNAMES, remember the person's Telegram ID with that role.
    Afterwards rights are checked by ID, so a later username change does not matter.
    Returns the role or None."""
    name = (username or "").lstrip("@").lower()
    if not name:
        return None
    with _conn() as conn:
        wanted = conn.execute("SELECT role FROM admin_usernames WHERE username = ?", (name,)).fetchone()
        if not wanted:
            return None
        existing = conn.execute("SELECT role, source FROM admins WHERE user_id = ?", (user_id,)).fetchone()
        if existing and existing["source"] == "id":
            return existing["role"]          # an explicit ID entry is never touched
        if existing:
            if existing["role"] != wanted["role"]:
                conn.execute("UPDATE admins SET role = ?, username = ? WHERE user_id = ?",
                             (wanted["role"], name, user_id))
            return wanted["role"]
        conn.execute(
            "INSERT INTO admins (user_id, role, added_at, username, source) VALUES (?, ?, ?, ?, 'username')",
            (user_id, wanted["role"], _now(), name),
        )
        _log(conn, None, "auto", "admin_bind", user_id, f"@{name}", f"роль: {wanted['role']}")
        return wanted["role"]


# ---------------------------------------------------------------- journal
def _log(conn, admin_id, source, action, target_user_id=None, reason="", result="") -> None:
    conn.execute(
        "INSERT INTO admin_actions (created_at, admin_id, source, action, target_user_id, reason, result) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (_now(), admin_id, source, action, target_user_id, reason or "", result or ""),
    )


def query_journal(admin_id=None, user_id=None, action=None, date=None, page=0, page_size=8):
    """Return (rows, total). `date` is YYYY-MM-DD."""
    where, params = [], []
    if admin_id is not None:
        where.append("admin_id = ?")
        params.append(admin_id)
    if user_id is not None:
        where.append("target_user_id = ?")
        params.append(user_id)
    if action:
        where.append("action = ?")
        params.append(action)
    if date:
        where.append("substr(created_at, 1, 10) = ?")
        params.append(date)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with _conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM admin_actions{clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM admin_actions{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, max(0, page) * page_size],
        ).fetchall()
    return [dict(r) for r in rows], total


# --------------------------------------------------------------- settings
def _get_setting(conn, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else SETTINGS_DEFAULTS[key]


def get_setting(key: str) -> str:
    with _conn() as conn:
        return _get_setting(conn, key)


def get_int_setting(key: str) -> int:
    try:
        return int(get_setting(key))
    except ValueError:
        return int(SETTINGS_DEFAULTS[key])


def get_all_settings() -> dict:
    with _conn() as conn:
        return {key: _get_setting(conn, key) for key in SETTINGS_DEFAULTS}


def set_setting(key: str, value: str, admin_id: int) -> None:
    if key not in SETTINGS_META:
        raise ValueError("Неизвестная настройка")
    title, kind, lo, hi = SETTINGS_META[key]
    if kind == "bool":
        value = "1" if str(value) == "1" else "0"
    else:
        number = int(value)
        if not lo <= number <= hi:
            raise ValueError(f"Значение должно быть от {lo} до {hi}")
        value = str(number)
    with _conn() as conn:
        old = _get_setting(conn, key)
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        _log(conn, admin_id, "admin", "setting_change", None, title, f"{old} → {value}")


# ------------------------------------------------------------------ admins
def get_admin_role(user_id: int) -> Optional[str]:
    with _conn() as conn:
        row = conn.execute("SELECT role FROM admins WHERE user_id = ?", (user_id,)).fetchone()
    return row["role"] if row else None


def _admin_role(conn, user_id: int) -> Optional[str]:
    row = conn.execute("SELECT role FROM admins WHERE user_id = ?", (user_id,)).fetchone()
    return row["role"] if row else None


# ---------------------------------------------------------------- accounts
_UNSET = object()


def ensure_account(user_id: int, username=_UNSET) -> dict:
    """Return the account row, creating it if needed.

    Pass `username` (str, or None when the person has no @username) to keep the stored
    username fresh; omit it to leave the stored value untouched."""
    clean = None if username is _UNSET or not username else str(username).lstrip("@")
    with _conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            if username is not _UNSET and row["username"] != clean:
                conn.execute("UPDATE accounts SET username = ? WHERE user_id = ?", (clean, user_id))
                row = conn.execute("SELECT * FROM accounts WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row)
        default = 0
        conn.execute(
            "INSERT OR IGNORE INTO accounts (user_id, is_registered, username, created_at) VALUES (?, ?, ?, ?)",
            (user_id, default, clean, _now()),
        )
        return dict(conn.execute("SELECT * FROM accounts WHERE user_id = ?", (user_id,)).fetchone())


def find_account(query: str) -> Optional[dict]:
    """Find by Telegram ID first, then by internal ID."""
    q = (query or "").strip().lstrip("#")
    if not q.isdecimal():
        return None
    number = int(q)
    with _conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE user_id = ?", (number,)).fetchone()
        if not row:
            row = conn.execute("SELECT * FROM accounts WHERE internal_id = ?", (number,)).fetchone()
        if row:
            return dict(row)
        has_profile = conn.execute(
            "SELECT 1 FROM user_profiles WHERE user_id = ?", (number,)
        ).fetchone()
    return ensure_account(number) if has_profile else None


def search_accounts(query: str, limit: int = 10) -> tuple[list[dict], int]:
    """Find people by Telegram ID / internal ID, @username or name from the profile.

    Returns (results, total_matches). A query starting with @ searches usernames only;
    any other text is matched against both the username and the profile name
    (case-insensitive, substring). Exact matches come first."""
    q = (query or "").strip()
    if not q:
        return [], 0
    if q.lstrip("#").isdecimal():
        account = find_account(q)
        if not account:
            return [], 0
        card = get_user_card(account["user_id"])
        return [card], 1
    username_only = q.startswith("@")
    needle = q.lstrip("@").casefold()
    if not needle:
        return [], 0
    with _conn() as conn:
        rows = conn.execute(
            """SELECT a.user_id, a.internal_id, a.username, p.name
               FROM accounts a LEFT JOIN user_profiles p ON p.user_id = a.user_id"""
        ).fetchall()
    scored = []
    for row in rows:
        username = (row["username"] or "").casefold()
        name = (row["name"] or "").casefold()
        if username == needle:
            rank = 0
        elif not username_only and name == needle:
            rank = 1
        elif username and needle in username:
            rank = 2
        elif not username_only and needle in name:
            rank = 3
        else:
            continue
        scored.append((rank, name, dict(row)))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored[:limit]], len(scored)


def get_user_card(user_id: int) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute(
            """SELECT a.*, p.name, p.start_year, p.group_num, p.faculty, p.photo,
                      u.status AS verify_status, u.verified_at AS verification_at,
                      EXISTS(SELECT 1 FROM verified_emails e WHERE e.user_id = a.user_id) AS has_email
               FROM accounts a
               LEFT JOIN user_profiles p ON p.user_id = a.user_id
               LEFT JOIN users u ON u.user_id = a.user_id
               WHERE a.user_id = ?""",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def active_ban(account: dict) -> Optional[dict]:
    until = account.get("banned_until")
    if until and until > _now():
        return {
            "until": until,
            "permanent": until == PERMANENT_UNTIL,
            "reason": account.get("ban_reason") or "",
        }
    return None


def active_restriction(account: dict) -> Optional[str]:
    until = account.get("restricted_until")
    return until if until and until > _now() else None


def last_ban_details(user_id: int) -> dict:
    """Reason and moderator comment of the latest ban (for the notice shown to the person)."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT reason, comment FROM sanctions WHERE user_id = ? AND kind IN ('temp_ban', 'perm_ban') "
            "ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
    return dict(row) if row else {"reason": "", "comment": ""}


def sanction_history(user_id: int, limit: int = 10) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sanctions WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def _ensure_row(conn, user_id: int) -> None:
    default = 0 # «верифицирован» выставляет только подтверждение почты
    conn.execute(
        "INSERT OR IGNORE INTO accounts (user_id, is_registered, created_at) VALUES (?, ?, ?)",
        (user_id, default, _now()),
    )


def _apply_ban(conn, user_id, days, reason, comment, admin_id, source, report_id=None,
               ban_source="admin"):
    """days=None -> permanent. Returns the `banned_until` value."""
    if _admin_role(conn, user_id):
        raise ValueError("Нельзя заблокировать администратора или модератора")
    _ensure_row(conn, user_id)
    acct = conn.execute("SELECT is_registered FROM accounts WHERE user_id = ?", (user_id,)).fetchone()
    if acct and not acct["is_registered"]:
        ban_source = "unverified"  # lifted automatically once the account is registered
    until = PERMANENT_UNTIL if days is None else (
        datetime.now() + timedelta(days=days)).isoformat(sep=" ", timespec="seconds")
    conn.execute(
        "UPDATE accounts SET banned_until = ?, ban_source = ?, ban_reason = ? WHERE user_id = ?",
        (until, ban_source, reason, user_id),
    )
    kind = "perm_ban" if days is None else "temp_ban"
    conn.execute(
        "INSERT INTO sanctions (user_id, kind, reason, comment, admin_id, source, report_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, kind, reason, comment or "", admin_id, source, report_id, _now(),
         None if days is None else until),
    )
    _log(conn, admin_id, source, "ban_perm" if days is None else "ban_temp", user_id,
         f"{reason}. {comment}".strip(". ") if comment else reason,
         "навсегда" if days is None else f"до {until}")
    # Other open reports against the same person are now moot.
    conn.execute(
        "UPDATE reports SET status = 'reviewed', decision = 'covered', reviewed_at = ?, "
        "moderator_id = ? WHERE target_id = ? AND status = 'new' AND id <> ?",
        (_now(), admin_id, user_id, report_id or 0),
    )
    return until


def _apply_unban(conn, user_id, admin_id, source, comment="") -> bool:
    row = conn.execute("SELECT banned_until FROM accounts WHERE user_id = ?", (user_id,)).fetchone()
    was_banned = bool(row and row["banned_until"] and row["banned_until"] > _now())
    conn.execute(
        "UPDATE accounts SET banned_until = NULL, ban_source = NULL, ban_reason = NULL WHERE user_id = ?",
        (user_id,),
    )
    if was_banned:
        conn.execute(
            "INSERT INTO sanctions (user_id, kind, reason, comment, admin_id, source, created_at) "
            "VALUES (?, 'unban', 'Блокировка снята', ?, ?, ?, ?)",
            (user_id, comment or "", admin_id, source, _now()),
        )
        _log(conn, admin_id, source, "unban", user_id, comment or "", "блокировка снята")
    return was_banned


def ban_user(user_id: int, days: Optional[int], reason: str, admin_id: int, comment: str = "") -> str:
    with _conn() as conn:
        return _apply_ban(conn, user_id, days, reason or "Нарушение правил", comment, admin_id, "admin")


def unban_user(user_id: int, admin_id: int, comment: str = "") -> bool:
    with _conn() as conn:
        return _apply_unban(conn, user_id, admin_id, "admin", comment)


def warn_user(user_id: int, reason: str, admin_id: int, report_id: Optional[int] = None, conn=None) -> None:
    def run(c):
        if _admin_role(c, user_id):
            raise ValueError("Нельзя вынести предупреждение администратору")
        _ensure_row(c, user_id)
        c.execute(
            "INSERT INTO sanctions (user_id, kind, reason, admin_id, source, report_id, created_at) "
            "VALUES (?, 'warning', ?, ?, 'admin', ?, ?)",
            (user_id, reason, admin_id, report_id, _now()),
        )
        _log(c, admin_id, "admin", "warn", user_id, reason, "предупреждение")

    if conn is not None:
        run(conn)
    else:
        with _conn() as c:
            run(c)


def set_registered(user_id: int, registered: bool, admin_id: Optional[int], source: str = "admin") -> bool:
    """Switch an account between registered / not registered.

    Becoming registered lifts bans that were issued automatically for being
    unregistered (hook for the future e-mail verification flow: call this
    with source='auto' once the HSE e-mail is confirmed).
    Returns True if an automatic ban was lifted.
    """
    with _conn() as conn:
        _ensure_row(conn, user_id)
        conn.execute("UPDATE accounts SET is_registered = ? WHERE user_id = ?", (1 if registered else 0, user_id))
                # Статус верификации в users должен совпадать с флагом.
        if registered:
            conn.execute(
                "UPDATE users SET status = 'verified', verified_at = COALESCE(verified_at, ?) "
                "WHERE user_id = ? AND status <> 'verified'",
                (_now(), user_id),
            )
        else:
            conn.execute(
                "UPDATE users SET status = 'guest' WHERE user_id = ? AND status = 'verified'",
                (user_id,),
            )
        _log(conn, admin_id, source, "status_change", user_id, "",
             "зарегистрирован" if registered else "не зарегистрирован")
        lifted = False
        if registered:
            row = conn.execute("SELECT ban_source FROM accounts WHERE user_id = ?", (user_id,)).fetchone()
            if row and row["ban_source"] in ("auto_report", "unverified"):
                lifted = _apply_unban(conn, user_id, admin_id, source, "Подтверждена регистрация")
        return lifted


def restrict_user(user_id: int, minutes: int, reason: str) -> str:
    until = (datetime.now() + timedelta(minutes=minutes)).isoformat(sep=" ", timespec="seconds")
    with _conn() as conn:
        _ensure_row(conn, user_id)
        conn.execute("UPDATE accounts SET restricted_until = ? WHERE user_id = ?", (until, user_id))
        _log(conn, None, "auto", "auto_restrict", user_id, reason, f"до {until}")
    return until


# ----------------------------------------------------------------- reports
def create_report(reporter_id: int, target_id: int, reason: str, comment: str = ""):
    """Returns a status code:
    invalid | not_allowed | duplicate | limit | already_banned | auto_banned | queued
    """
    if reporter_id == target_id or reason not in REPORT_REASONS:
        return "invalid"
    comment = (comment or "").strip()[:500]
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM user_profiles WHERE user_id = ?", (target_id,)).fetchone():
            return "invalid"
        if _admin_role(conn, target_id):
            return "invalid"
        _ensure_row(conn, reporter_id)
        _ensure_row(conn, target_id)
        reporter = conn.execute("SELECT is_registered FROM accounts WHERE user_id = ?", (reporter_id,)).fetchone()
        if _get_setting(conn, "reports_only_registered") == "1" and not reporter["is_registered"]:
            return "not_allowed"
        day_ago = (datetime.now() - timedelta(days=1)).isoformat(sep=" ", timespec="seconds")
        sent = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE reporter_id = ? AND created_at > ?", (reporter_id, day_ago)
        ).fetchone()[0]
        try:
            per_day = int(_get_setting(conn, "reports_per_day"))
        except ValueError:
            per_day = int(SETTINGS_DEFAULTS["reports_per_day"])
        if sent >= per_day:
            return "limit"
        target = conn.execute(
            "SELECT is_registered, banned_until FROM accounts WHERE user_id = ?", (target_id,)
        ).fetchone()
        registered = bool(target["is_registered"])
        already_banned = bool(target["banned_until"] and target["banned_until"] > _now())
        # EVERY complaint is stored (any number per person, also repeated ones and ones against
        # an already banned person). Against a banned person there is nothing left to decide,
        # so it goes straight to the «Обработанные» folder.
        if already_banned:
            status, decision = "reviewed", "already_banned"
        elif registered:
            status, decision = "new", None
        else:
            status, decision = "auto_banned", "auto_ban"
        cursor = conn.execute(
            "INSERT INTO reports (reporter_id, target_id, reason, comment, status, decision, "
            "target_was_registered, created_at, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (reporter_id, target_id, reason, comment, status, decision,
             1 if registered else 0, _now(), None if status == "new" else _now()),
        )
        report_id = cursor.lastrowid
        if already_banned:
            return "already_banned"
        if registered:
            return "queued"
        # Not registered: instant ban without moderation.
        _apply_ban(conn, target_id, None, REPORT_REASONS[reason], "",
                   None, "auto", report_id=report_id, ban_source="auto_report")
        return "auto_banned"


def count_new_reports() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM reports WHERE status = 'new'").fetchone()[0]


def list_reports(group: str, page: int = 0, page_size: int = 6):
    """group: 'n' (new, oldest first) or 'd' (processed, newest first)."""
    if group == "n":
        where, order = "r.status = 'new'", "r.created_at ASC"
    else:
        where, order = "r.status <> 'new'", "r.created_at DESC"
    with _conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM reports r WHERE {where}").fetchone()[0]
        rows = conn.execute(
            f"""SELECT r.id, r.reason, r.status, r.decision, r.target_id, tp.name AS target_name
                FROM reports r LEFT JOIN user_profiles tp ON tp.user_id = r.target_id
                WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?""",
            (page_size, max(0, page) * page_size),
        ).fetchall()
    return [dict(r) for r in rows], total


def get_report(report_id: int) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute(
            """SELECT r.*, tp.name AS target_name, tp.faculty AS target_faculty,
                      tp.start_year AS target_year, tp.group_num AS target_group,
                      tp.photo AS target_photo, rp.name AS reporter_name,
                      a.is_registered AS target_registered_now, a.banned_until AS target_banned_until
               FROM reports r
               LEFT JOIN user_profiles tp ON tp.user_id = r.target_id
               LEFT JOIN user_profiles rp ON rp.user_id = r.reporter_id
               LEFT JOIN accounts a ON a.user_id = r.target_id
               WHERE r.id = ?""",
            (report_id,),
        ).fetchone()
    return dict(row) if row else None


def resolve_report(report_id: int, admin_id: int, decision: str, moderator_comment: str = "",
                   days: Optional[int] = None) -> Optional[dict]:
    """decision: dismiss | warn | temp_ban | perm_ban. None if already processed."""
    if decision not in {"dismiss", "warn", "temp_ban", "perm_ban"}:
        raise ValueError("Неизвестное решение")
    with _conn() as conn:
        report = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not report or report["status"] != "new":
            return None
        claimed = conn.execute(
            "UPDATE reports SET status = 'reviewed', decision = ?, moderator_id = ?, "
            "moderator_comment = ?, reviewed_at = ? WHERE id = ? AND status = 'new'",
            (decision, admin_id, moderator_comment, _now(), report_id),
        ).rowcount
        if not claimed:
            return None
        target_id = report["target_id"]
        reason = REPORT_REASONS.get(report["reason"], report["reason"])
        until = None
        if decision == "dismiss":
            _log(conn, admin_id, "admin", "report_dismiss", target_id, moderator_comment,
                 f"жалоба #{report_id} отклонена")
        elif decision == "warn":
            warn_user(target_id, f"{reason}. {moderator_comment}".strip(". "), admin_id, report_id, conn=conn)
        else:
            until = _apply_ban(conn, target_id, None if decision == "perm_ban" else days, reason,
                               moderator_comment, admin_id, "admin", report_id=report_id)
        return {"target_id": target_id, "decision": decision, "until": until, "reason": reason}


# --------------------------------------------------------------- spam guard
_ACTION_LIMITS = {
    "like": ("likes_per_hour", 3600, "лайков", "час"),
    "skip": ("skips_per_hour", 3600, "пропусков", "час"),
    "create": ("creations_per_day", 86400, "созданий анкет и событий", "сутки"),
}


def check_and_record_action(user_id: int, action: str) -> Optional[str]:
    """Return a user-facing message if the limit is exceeded, otherwise record the action."""
    if action not in _ACTION_LIMITS:
        return None
    key, window, label, period = _ACTION_LIMITS[action]
    limit = get_int_setting(key)
    since = (datetime.now() - timedelta(seconds=window)).isoformat(sep=" ", timespec="seconds")
    with _conn() as conn:
        def blocked_text(until: str) -> str:
            return (f"⛔ Лимит {label} превышен (не более {limit} за {period}). "
                    f"Это действие заблокировано до {datetime.fromisoformat(until).strftime('%H:%M')}.")

        block = conn.execute(
            "SELECT until FROM action_blocks WHERE user_id = ? AND action = ? AND until > ?",
            (user_id, action, _now()),
        ).fetchone()
        if block:
            return blocked_text(block["until"])
        used = conn.execute(
            "SELECT COUNT(*) FROM action_log WHERE user_id = ? AND action = ? AND created_at > ?",
            (user_id, action, since),
        ).fetchone()[0]
        if used >= limit:
            until = (datetime.now() + timedelta(hours=1)).isoformat(sep=" ", timespec="seconds")
            conn.execute(
                "INSERT INTO action_blocks (user_id, action, until) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, action) DO UPDATE SET until = excluded.until",
                (user_id, action, until),
            )
            return blocked_text(until)
        conn.execute(
            "INSERT INTO action_log (user_id, action, created_at) VALUES (?, ?, ?)",
            (user_id, action, _now()),
        )
        if random.random() < 0.02:  # cheap periodic cleanup
            old = (datetime.now() - timedelta(days=2)).isoformat(sep=" ", timespec="seconds")
            conn.execute("DELETE FROM action_log WHERE created_at < ?", (old,))
    return None


def clear_all_restrictions(admin_id: int) -> tuple[int, int]:
    """Lift every active action block and access restriction, reset the limit counters.
    Returns (blocks_removed, restrictions_removed)."""
    with _conn() as conn:
        blocks = conn.execute("DELETE FROM action_blocks").rowcount
        conn.execute("DELETE FROM action_log")
        restrictions = conn.execute(
            "UPDATE accounts SET restricted_until = NULL WHERE restricted_until IS NOT NULL"
        ).rowcount
        _log(conn, admin_id, "admin", "setting_change", None, "Сняты все ограничения",
             f"блокировок действий: {blocks}, ограничений доступа: {restrictions}")
    return blocks, restrictions


# --------------------------------------------------------------------- ads
_SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly", "clck.ru", "vk.cc", "ow.ly", "rb.gy"}


def validate_ad_url(url: str) -> Optional[str]:
    """Return an error text, or None if the link is acceptable."""
    url = (url or "").strip()
    if not url or len(url) > 500 or any(ch.isspace() for ch in url):
        return "Ссылка пустая, длиннее 500 символов или содержит пробелы."
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        credentials = bool(parsed.username or parsed.password)
    except ValueError:
        return "Не удалось разобрать ссылку."
    if parsed.scheme != "https":
        return "Допускаются только ссылки, начинающиеся с https://"
    if not host or "." not in host:
        return "Не удалось определить домен ссылки."
    if credentials:
        return "Ссылка не должна содержать логин и пароль."
    if re.fullmatch(r"[\d.]+", host):
        return "Ссылки на IP-адреса не допускаются."
    if host in _SHORTENERS:
        return "Сокращатели ссылок не допускаются: укажи прямую ссылку."
    return None


def create_ad(admin_id, text, image, url, button_text, every_n, max_per_user, start_date, end_date) -> int:
    with _conn() as conn:
        cursor = conn.execute(
            "INSERT INTO ad_campaigns (text, image, url, button_text, every_n, max_per_user, start_date, "
            "end_date, is_active, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (text, image, url, button_text, every_n, max_per_user, start_date, end_date, admin_id, _now()),
        )
        ad_id = cursor.lastrowid
        _log(conn, admin_id, "admin", "ad_create", None, f"Реклама #{ad_id}", "создана (выключена)")
        return ad_id


def set_ad_active(ad_id: int, active: bool, admin_id: int) -> bool:
    with _conn() as conn:
        changed = conn.execute(
            "UPDATE ad_campaigns SET is_active = ? WHERE id = ?", (1 if active else 0, ad_id)
        ).rowcount
        if changed:
            _log(conn, admin_id, "admin", "ad_toggle", None, f"Реклама #{ad_id}",
                 "включена" if active else "выключена")
        return bool(changed)


def get_ad(ad_id: int) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM ad_campaigns WHERE id = ?", (ad_id,)).fetchone()
    return dict(row) if row else None


AD_EDIT_FIELDS = {
    "text": "Текст", "image": "Картинка", "url": "Ссылка",
    "button_text": "Текст кнопки", "every_n": "Частота",
    "max_per_user": "Лимит на пользователя", "start_date": "Дата начала",
    "end_date": "Дата окончания",
}


def update_ad_field(ad_id: int, field: str, value, admin_id: int) -> bool:
    """Validate and update a single field without replacing the campaign or its stats."""
    if field not in AD_EDIT_FIELDS:
        raise ValueError("Неизвестный параметр рекламы.")
    if field in ("text", "button_text"):
        limit = 800 if field == "text" else 30
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
            raise ValueError(f"Введите текст от 1 до {limit} символов.")
        value = value.strip()
    elif field == "url":
        error = validate_ad_url(value)
        if error:
            raise ValueError(error)
        value = value.strip()
    elif field in ("every_n", "max_per_user"):
        maximum = 1000 if field == "every_n" else 1_000_000
        minimum = 1 if field == "every_n" else 0
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"Введите целое число от {minimum} до {maximum}.")
        if field == "max_per_user":
            value = value or None
    elif field in ("start_date", "end_date") and value is not None:
        try:
            value = datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except (ValueError, TypeError):
            raise ValueError("Некорректная дата.") from None
    elif field == "image" and value is not None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Отправьте картинку как фото.")
    with _conn() as conn:
        row = conn.execute("SELECT * FROM ad_campaigns WHERE id = ?", (ad_id,)).fetchone()
        if not row:
            return False
        candidate = dict(row)
        candidate[field] = value
        if candidate["start_date"] and candidate["end_date"] and candidate["start_date"] > candidate["end_date"]:
            raise ValueError("Дата окончания не может быть раньше даты начала.")
        conn.execute(f"UPDATE ad_campaigns SET {field} = ? WHERE id = ?", (value, ad_id))
        _log(conn, admin_id, "admin", "ad_edit", None,
             f"Реклама #{ad_id}", f"Изменён параметр: {AD_EDIT_FIELDS[field]}")
        return True


def delete_ad(ad_id: int, admin_id: int) -> bool:
    """Remove a slot; retain historical statistics and the audit trail."""
    with _conn() as conn:
        changed = conn.execute("DELETE FROM ad_campaigns WHERE id = ?", (ad_id,)).rowcount
        if changed:
            _log(conn, admin_id, "admin", "ad_delete", None, f"Реклама #{ad_id}", "удалена")
        return bool(changed)


def list_ads() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM ad_campaigns ORDER BY id DESC LIMIT 30").fetchall()
    return [dict(r) for r in rows]


def ad_status_label(ad: dict) -> str:
    today = datetime.now().date().isoformat()
    if not ad["is_active"]:
        return "⏸ выключена"
    if ad["start_date"] and ad["start_date"] > today:
        return "🕓 ждёт начала"
    if ad["end_date"] and ad["end_date"] < today:
        return "⌛ завершена"
    return "▶️ идёт"


def next_ad_for_user(user_id: int) -> Optional[dict]:
    """Count one more profile shown to the user; return an ad if it is time for one."""
    today = datetime.now().date().isoformat()
    with _conn() as conn:
        conn.execute("INSERT OR IGNORE INTO user_ad_state (user_id, counter) VALUES (?, 0)", (user_id,))
        conn.execute("UPDATE user_ad_state SET counter = counter + 1 WHERE user_id = ?", (user_id,))
        counter = conn.execute("SELECT counter FROM user_ad_state WHERE user_id = ?", (user_id,)).fetchone()[0]
        row = conn.execute(
            """SELECT c.* FROM ad_campaigns c
               WHERE c.is_active = 1
                 AND (c.start_date IS NULL OR c.start_date <= ?)
                 AND (c.end_date IS NULL OR c.end_date >= ?)
                 AND c.every_n <= ?
                 AND (c.max_per_user IS NULL OR
                      (SELECT COUNT(*) FROM ad_impressions i WHERE i.ad_id = c.id AND i.user_id = ?) < c.max_per_user)
               ORDER BY (SELECT COUNT(*) FROM ad_impressions i WHERE i.ad_id = c.id AND i.user_id = ?) ASC,
                        RANDOM()
               LIMIT 1""",
            (today, today, counter, user_id, user_id),
        ).fetchone()
        if row:
            return dict(row)
    return None


def record_impression(ad_id: int, user_id: int) -> None:
    with _conn() as conn:
        conn.execute("INSERT INTO ad_impressions (ad_id, user_id, shown_at) VALUES (?, ?, ?)",
                     (ad_id, user_id, _now()))
        conn.execute("UPDATE user_ad_state SET counter = 0 WHERE user_id = ?", (user_id,))


def record_click(ad_id: int, user_id: int) -> None:
    with _conn() as conn:
        conn.execute("INSERT INTO ad_clicks (ad_id, user_id, clicked_at) VALUES (?, ?, ?)",
                     (ad_id, user_id, _now()))


def ad_stats(ad_id: int) -> dict:
    with _conn() as conn:
        impressions, unique_viewers = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT user_id) FROM ad_impressions WHERE ad_id = ?", (ad_id,)
        ).fetchone()
        clicks, unique_clickers = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT user_id) FROM ad_clicks WHERE ad_id = ?", (ad_id,)
        ).fetchone()
    ctr = (clicks / impressions * 100) if impressions else 0.0
    return {"impressions": impressions, "unique_viewers": unique_viewers,
            "clicks": clicks, "unique_clickers": unique_clickers, "ctr": ctr}


init_admin_db()
