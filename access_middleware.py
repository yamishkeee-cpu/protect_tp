from __future__ import annotations
"""Ban check, temporary restrictions and spam limits for every incoming message/callback."""
import logging
import time
from collections import defaultdict, deque
from datetime import datetime

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

import admin_db

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

        # Admins and moderators are never banned or rate-limited.
        if admin_db.get_admin_role(user.id):
            return await handler(event, data)

        account = admin_db.ensure_account(user.id)

        ban = admin_db.active_ban(account)
        if ban:
            where = "навсегда" if ban["permanent"] else f"до {_fmt(ban['until'])}"
            reason = f"\nПричина: {ban['reason']}" if ban["reason"] else ""
            await self._deny(event, f"🚫 Твой аккаунт заблокирован {where}.{reason}")
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
