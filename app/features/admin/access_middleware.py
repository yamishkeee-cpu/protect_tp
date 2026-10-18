"""Ban check, temporary restrictions and spam limits for every incoming message/callback."""
import logging
import time
from collections import defaultdict, deque
from datetime import datetime

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from app.features.admin import admin_db

logger = logging.getLogger(__name__)

BURST_WINDOW_SECONDS = 10


def _fmt(dt_text: str) -> str:
    try:
        return datetime.fromisoformat(dt_text).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return dt_text


def _classify(event) -> str | None:
    """Map a callback to a limited action. Messages are not limited by type."""
    if isinstance(event, CallbackQuery) and event.data:
        data = event.data
        if data.startswith("like_"):
            return "like"
        if data.startswith("next_profile_") or data.startswith("dislike_"):
            return "skip"
        if data in {"confirm_event_creation", "confirm_temp_profile_yes"}:
            return "create"
    return None


class AccessMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._recent: dict[int, deque] = defaultdict(deque)

    async def _deny(self, event, text: str) -> None:
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
        except TelegramAPIError:
            logger.info("Could not deliver access notice")

    def _burst_exceeded(self, user_id: int) -> bool:
        now = time.monotonic()
        window = self._recent[user_id]
        window.append(now)
        while window and now - window[0] > BURST_WINDOW_SECONDS:
            window.popleft()
        return len(window) > admin_db.get_int_setting("burst_actions")

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)

        # Keep the @username fresh (it makes the person searchable in the admin panel) and
        # turn an @username from ADMIN_USERNAMES / MODERATOR_USERNAMES into a role.
        account = admin_db.ensure_account(user.id, user.username)
        admin_db.bind_admin_by_username(user.id, user.username)

        # Admins and moderators are never banned or rate-limited.
        if admin_db.get_admin_role(user.id):
            return await handler(event, data)

        ban = admin_db.active_ban(account)
        if ban:
            if not account["is_registered"]:
                # not registered: the ban is lifted automatically after registration
                await self._deny(event, "🚫 Твой аккаунт заблокирован, но его можно восстановить, зарегистрировавшись.")
                return None
            details = admin_db.last_ban_details(user.id)
            lines = ["🚫 Твой аккаунт заблокирован.",
                     f"Причина: {details['reason'] or ban['reason'] or 'Нарушение правил'}"]
            if details["comment"]:
                lines.append(f"Комментарий: {details['comment']}")
            lines.append("До: " + ("бессрочно" if ban["permanent"] else _fmt(ban["until"])))
            await self._deny(event, "\n".join(lines))
            return None

        restricted_until = admin_db.active_restriction(account)
        if restricted_until:
            await self._deny(event, f"⏳ Слишком много действий. Доступ ограничен до {_fmt(restricted_until)}.")
            return None

        if self._burst_exceeded(user.id):
            minutes = admin_db.get_int_setting("restrict_minutes")
            until = admin_db.restrict_user(user.id, minutes, "Подозрительно частые действия")
            self._recent[user.id].clear()
            await self._deny(event, f"⏳ Слишком много действий подряд. Доступ ограничен до {_fmt(until)}.")
            return None

        action = _classify(event)
        if action:
            notice = admin_db.check_and_record_action(user.id, action)
            if notice:
                await self._deny(event, notice)
                return None

        return await handler(event, data)
