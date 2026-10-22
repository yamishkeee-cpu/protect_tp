"""Подтверждение университетской почты: проверка домена, коды, хэши, письма, лимиты.

"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import os
import re
import secrets
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from app.core.db import get_user_profile
from app.features.admin.admin_db import active_ban, ensure_account, set_registered
from app.features.admin.admin_db import set_registered
from app.features.verification.verification_db import (
    complete_verification,
    count_requests_for_email_since,
    count_requests_since,
    create_verification,
    delete_verification,
    format_ts,
    get_active_verification,
    get_email_owner,
    get_last_request_at,
    get_user_status,
    increment_attempts,
    mark_verification_used,
    parse_ts,
    was_ever_verified,
)

logger = logging.getLogger(__name__)

# ---------- настройки (меняются здесь) ----------
ALLOWED_DOMAINS = frozenset({"edu.hse.ru", "hse.ru"})
CODE_LENGTH = 6
CODE_TTL_MINUTES = 10
MAX_ATTEMPTS_PER_CODE = 5
RESEND_COOLDOWN_SECONDS = 60
MAX_REQUESTS_PER_DAY = 5
# Сколько раз за сутки на один адрес можно отправлять код (со всех аккаунтов вместе).
MAX_REQUESTS_PER_EMAIL_PER_DAY = 3
# Может ли забаненный снять бан, подтвердив почту заново (открытый вопрос).
ALLOW_BANNED_REVERIFY = True

_LOCAL_PART_RE = re.compile(r"[a-z0-9._\-]{1,64}")


class VerificationConfigError(RuntimeError):
    """Не настроен секрет или SMTP."""


@dataclass(frozen=True)
class CodeRequestResult:
    # sent | invalid_domain | email_taken | cooldown | daily_limit | banned
    # | no_profile | send_failed | config_error
    status: str
    retry_after: int = 0


@dataclass(frozen=True)
class CodeCheckResult:
    # verified | bad_format | wrong_code | too_many_attempts | expired | no_code
    # | email_taken | no_profile | config_error | banned
    status: str
    attempts_left: int = 0
    unbanned: bool = False  # при подтверждении был снят бан


# ---------- 1. проверка домена ----------

def normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def is_allowed_email(raw: str) -> bool:
    """Чистая функция: после последней @ ровно edu.hse.ru или hse.ru."""
    email = normalize_email(raw)
    if not email or len(email) > 254:
        return False
    local, at, domain = email.rpartition("@")
    if not at:
        return False
    return domain in ALLOWED_DOMAINS and _LOCAL_PART_RE.fullmatch(local) is not None


# ---------- хэши ----------

def _secret() -> bytes:
    value = os.getenv("EMAIL_HASH_SECRET", "").strip()
    if len(value) < 16:
        raise VerificationConfigError(
            "EMAIL_HASH_SECRET не задан или слишком короткий (нужно минимум 16 символов)."
        )
    return value.encode("utf-8")


def hash_email(raw_email: str) -> str:
    msg = ("email:" + normalize_email(raw_email)).encode("utf-8")
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def hash_code(user_id: int, code: str) -> str:
    msg = f"code:{user_id}:{code}".encode("utf-8")
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def generate_code() -> str:
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


# ---------- 3. отправка письма ----------

def _send_email_sync(to_email: str, code: str) -> None:
    """Блокирующая отправка; вызывать только через asyncio.to_thread."""
    if os.getenv("EMAIL_DEV_MODE", "").strip() == "1":
        print(f"[EMAIL_DEV_MODE] Код подтверждения для {to_email}: {code}", flush=True)
        return

    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", "").strip() or user
    port = int(os.getenv("SMTP_PORT", "587"))
    if not host or not sender:
        raise VerificationConfigError("SMTP не настроен (SMTP_HOST / SMTP_FROM).")

    msg = EmailMessage()
    msg["Subject"] = "Код подтверждения для бота знакомств ВШЭ НН"
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(
        f"Твой код подтверждения: {code}\n\n"
        f"Он действует {CODE_TTL_MINUTES} минут. "
        "Если ты не запрашивал код, просто проигнорируй это письмо."
    )
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls(context=context)
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)


# ---------- запрос кода ----------

async def request_code(user_id: int, raw_email: str) -> CodeRequestResult:
    if not get_user_profile(user_id):
        return CodeRequestResult("no_profile")
    if get_user_status(user_id) == "banned" and (
        not ALLOW_BANNED_REVERIFY or was_ever_verified(user_id)
    ):
        return CodeRequestResult("banned")
    # Реальный бан живёт в админке (accounts). Верифицированный (или ранее верифицированный)
    # не может снять его подтверждением почты: решает только администратор.
    account = ensure_account(user_id)
    if active_ban(account) and (account["is_registered"] or was_ever_verified(user_id)):
        return CodeRequestResult("banned")

    email = normalize_email(raw_email)
    if not is_allowed_email(email):
        return CodeRequestResult("invalid_domain")

    now = datetime.now(timezone.utc)

    last = get_last_request_at(user_id)
    if last:
        wait = RESEND_COOLDOWN_SECONDS - (now - parse_ts(last)).total_seconds()
        if wait > 0:
            return CodeRequestResult("cooldown", retry_after=math.ceil(wait))

    since = format_ts(now - timedelta(hours=24))
    if count_requests_since(user_id, since) >= MAX_REQUESTS_PER_DAY:
        return CodeRequestResult("daily_limit")

    try:
        email_hash = hash_email(email)
    except VerificationConfigError:
        logger.error("EMAIL_HASH_SECRET не настроен")
        return CodeRequestResult("config_error")

    created = format_ts(now)
    expires = format_ts(now + timedelta(minutes=CODE_TTL_MINUTES))

    owner = get_email_owner(email_hash)
    if owner is not None and owner != user_id:
        # Служебная запись: попытка учитывается в лимитах (против перебора чужих почт).
        create_verification(user_id, "", email_hash, created, expires, is_used=True)
        return CodeRequestResult("email_taken")
    if count_requests_for_email_since(email_hash, since) >= MAX_REQUESTS_PER_EMAIL_PER_DAY:
        return CodeRequestResult("email_limit")
    
    code = generate_code()
    verification_id = create_verification(
        user_id, hash_code(user_id, code), email_hash, created, expires
    )
    try:
        await asyncio.to_thread(_send_email_sync, email, code)
    except VerificationConfigError:
        logger.error("SMTP не настроен")
        delete_verification(verification_id)
        return CodeRequestResult("config_error")
    except Exception:
        logger.exception("Не удалось отправить письмо с кодом (user %s)", user_id)
        delete_verification(verification_id)
        return CodeRequestResult("send_failed")
    return CodeRequestResult("sent")


# ---------- 4. проверка кода ----------

async def verify_code(user_id: int, raw_code: str) -> CodeCheckResult:
    code = (raw_code or "").strip()
    if len(code) != CODE_LENGTH or not code.isascii() or not code.isdecimal():
        return CodeCheckResult("bad_format")
    
    account = ensure_account(user_id)
    if active_ban(account) and (account["is_registered"] or was_ever_verified(user_id)):
        return CodeCheckResult("banned")
    
    row = get_active_verification(user_id)
    if row is None:
        return CodeCheckResult("no_code")
    verification_id, code_hash, email_hash, expires_at, attempts = row

    if parse_ts(expires_at) <= datetime.now(timezone.utc):
        mark_verification_used(verification_id)
        return CodeCheckResult("expired")
    if attempts >= MAX_ATTEMPTS_PER_CODE:
        mark_verification_used(verification_id)
        return CodeCheckResult("too_many_attempts")

    # Попытка списывается ДО сравнения: параллельные запросы не обходят лимит.
    used_attempts = increment_attempts(verification_id)
    try:
        expected = hash_code(user_id, code)
    except VerificationConfigError:
        logger.error("EMAIL_HASH_SECRET не настроен")
        return CodeCheckResult("config_error")

    if not hmac.compare_digest(expected, code_hash):
        if used_attempts >= MAX_ATTEMPTS_PER_CODE:
            mark_verification_used(verification_id)
            return CodeCheckResult("too_many_attempts")
        return CodeCheckResult("wrong_code", attempts_left=MAX_ATTEMPTS_PER_CODE - used_attempts)

    # 5. привязка почты + set_status(..., 'verified') одной транзакцией
    outcome = complete_verification(verification_id, user_id, email_hash)
    if outcome == "ok":
        # Вызывать ПОСЛЕ транзакции complete_verification (она уже закрыта).
        unbanned = False
        try:
            unbanned = set_registered(user_id, True, None, source="auto")
        except Exception:
            logger.exception("Не удалось выставить флаг регистрации (user %s)", user_id)
        return CodeCheckResult("verified", unbanned=unbanned)