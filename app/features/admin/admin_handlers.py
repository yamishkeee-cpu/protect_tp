"""Admin panel: /admin -> users, reports, settings, ads, journal.

Access rules
* The whole router is gated by a filter (Telegram ID must be in `admins`), and
  every handler re-reads the role from the DB, so rights are checked on the
  server for each action.
* admin     - everything.
* moderator - users (warn / temporary ban / unban), reports, journal (read-only).
  Permanent bans, status switch, settings and ads are admin-only.
"""
import html
import logging
from datetime import datetime

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.features.admin import admin_db
from app.features.admin.admin_db import JOURNAL_ACTIONS, PERMANENT_UNTIL, REPORT_REASONS, ROLE_ADMIN, SETTINGS_META
from app.features.admin.admin_keyboards import (
    ad_card_kb, ad_create_confirm_kb, ad_edit_kb, ad_edit_value_kb, ads_list_kb, cancel_kb, confirm_kb, journal_kb,
    journal_types_kb, menu_kb, report_card_kb, reports_list_kb, search_results_kb, setting_state_text,
    settings_kb, skip_kb, user_card_kb,
)
from app.features.admin.admin_keyboards import SETTING_SHORT
from app.features.admin.admin_states import AdCreate, AdEdit, AdminFlow
from app.features.admin.ads import send_ad_card

logger = logging.getLogger(__name__)
admin_router = Router()

REPORTS_PAGE = 6
JOURNAL_PAGE = 8

SANCTION_TITLES = {
    "warn": "предупреждение",
    "temp": "временный бан",
    "perm": "БАН НАВСЕГДА",
    "unban": "снятие блокировки",
    "dismiss": "отклонение жалобы",
}
SANCTION_KIND_LABEL = {
    "warning": "⚠️ предупреждение",
    "temp_ban": "⏳ временный бан",
    "perm_ban": "⛔ бан навсегда",
    "unban": "✅ снятие блокировки",
}


class AdminOnly(BaseFilter):
    """Only Telegram IDs listed in the admins table get past this point."""

    async def __call__(self, event) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and admin_db.get_admin_role(user.id))


admin_router.message.filter(AdminOnly())
admin_router.callback_query.filter(AdminOnly())


# ---------------------------------------------------------------- helpers
def esc(value) -> str:
    return html.escape(str(value)) if value not in (None, "") else "—"


def fmt_dt(value) -> str:
    if not value:
        return "—"
    if value == PERMANENT_UNTIL:
        return "навсегда"
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return str(value)


def _role(user_id: int):
    return admin_db.get_admin_role(user_id)


async def _show(call: types.CallbackQuery, text: str, kb=None) -> None:
    """Edit the current message; fall back to a new one (e.g. when it is a photo)."""
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as exc:
        if "not modified" in str(exc):
            return
        await call.message.answer(text, reply_markup=kb)


async def _send_card(target: Message, text: str, photo, kb) -> None:
    if photo:
        try:
            await target.answer_photo(photo=photo, caption=text[:1020], reply_markup=kb)
            return
        except TelegramBadRequest:
            logger.warning("Admin card: photo is not available")
    await target.answer(text, reply_markup=kb)


async def _notify_user(bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except TelegramAPIError:
        logger.info("Could not notify user %s", user_id)


async def _deny(call: types.CallbackQuery) -> None:
    await call.answer("Недостаточно прав для этого действия", show_alert=True)


def _parse_date(text: str):
    try:
        return datetime.strptime((text or "").strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def _menu_text(role: str) -> str:
    who = "администратор" if role == ROLE_ADMIN else "модератор"
    return f"🛡️ <b>Админ-панель</b>\nТвоя роль: {who}"


# -------------------------------------------------------------- main menu
@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    role = _role(message.from_user.id)
    await message.answer(_menu_text(role), reply_markup=menu_kb(role, admin_db.count_new_reports()))


@admin_router.callback_query(F.data == "adm:menu")
async def cb_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    role = _role(call.from_user.id)
    await call.answer()
    await _show(call, _menu_text(role), menu_kb(role, admin_db.count_new_reports()))


@admin_router.callback_query(F.data == "adm:noop")
async def cb_noop(call: types.CallbackQuery):
    await call.answer("Это предпросмотр: кнопка в боте откроет ссылку", show_alert=True)


# ------------------------------------------------------------------ users
def _user_card_text(card: dict) -> str:
    ban = admin_db.active_ban(card)
    restriction = admin_db.active_restriction(card)
    verified = card.get("verify_status") == "verified"
    status = "✅ верифицирован" if verified else "🕓 не верифицирован"
    if bool(card["is_registered"]) != verified:
        status += " ⚠️ флаг регистрации в админке расходится"
    lines = [
        "👤 <b>Пользователь</b>",
        f"Telegram ID: <code>{card['user_id']}</code>",
        f"Внутренний ID: <code>{card['internal_id']}</code>",
        f"Username: {'@' + html.escape(card['username']) if card.get('username') else '—'}",
        f"Имя: {esc(card.get('name'))}",
        f"Направление: {esc(card.get('faculty'))}",
        f"Год поступления: {esc(card.get('start_year'))} · группа: {esc(card.get('group_num'))}",
        f"Статус: {status}",
        f"Почта ВШЭ: {'привязана' if card.get('has_email') else 'не привязана'}",
        f"Дата верификации: {esc(str(card['verification_at'])[:10]) if card.get('verification_at') else '—'}",
    ]
    if ban:
        lines.append(f"Блокировка: 🚫 {fmt_dt(ban['until'])}" + (f" ({esc(ban['reason'])})" if ban["reason"] else ""))
    else:
        lines.append("Блокировка: нет")
    if restriction:
        lines.append(f"Ограничение активности до: {fmt_dt(restriction)}")
    if not card.get("name"):
        lines.append("<i>Профиль ещё не заполнен</i>")
    return "\n".join(lines)


async def _send_user_card(target: Message, user_id: int, role: str) -> None:
    card = admin_db.get_user_card(user_id)
    if not card:
        await target.answer("Пользователь не найден.")
        return
    banned = admin_db.active_ban(card) is not None
    await _send_card(target, _user_card_text(card), card.get("photo"),
                     user_card_kb(user_id, banned, bool(card["is_registered"]), role))


@admin_router.callback_query(F.data == "adm:users")
async def cb_users(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlow.user_search)
    await call.answer()
    await _show(call, "👥 <b>Пользователи</b>\n\nВведи для поиска:\n"
                      "• Telegram ID или внутренний ID,\n"
                      "• @username из Telegram,\n"
                      "• имя из анкеты (можно часть имени).\n\n"
                      "<i>Username известен только тем, кто писал боту после обновления.</i>",
                cancel_kb())


@admin_router.message(StateFilter(AdminFlow.user_search))
async def msg_user_search(message: Message, state: FSMContext):
    results, total = admin_db.search_accounts(message.text or "")
    if not results:
        await message.answer("Никого не нашёл. Попробуй другой запрос: ID, @username или имя из анкеты.",
                             reply_markup=cancel_kb())
        return
    if len(results) == 1:
        await state.clear()
        await _send_user_card(message, results[0]["user_id"], _role(message.from_user.id))
        return
    await state.clear()
    more = f" (показаны первые {len(results)}, уточни запрос)" if total > len(results) else ""
    await message.answer(f"Нашёл совпадений: {total}{more}. Выбери человека:",
                         reply_markup=search_results_kb(results))


@admin_router.callback_query(F.data.startswith("adm:u:"))
async def cb_user_card(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        uid = int(call.data.split(":")[2])
    except (ValueError, IndexError):
        await call.answer()
        return
    await call.answer()
    await _send_user_card(call.message, uid, _role(call.from_user.id))


@admin_router.callback_query(F.data.startswith("adm:hist:"))
async def cb_history(call: types.CallbackQuery):
    uid = int(call.data.split(":")[2])
    rows = admin_db.sanction_history(uid)
    await call.answer()
    if not rows:
        text = f"📜 История санкций <code>{uid}</code>: пусто."
    else:
        lines = [f"📜 <b>История санкций</b> <code>{uid}</code>"]
        for r in rows:
            who = "авто" if r["source"] == "auto" else f"админ {r['admin_id']}"
            until = f" до {fmt_dt(r['expires_at'])}" if r["expires_at"] else ""
            detail = " · ".join(x for x in (r["reason"], r["comment"]) if x)
            lines.append(f"{fmt_dt(r['created_at'])} · {SANCTION_KIND_LABEL.get(r['kind'], r['kind'])}{until} · {who}\n   {esc(detail[:150])}")
        text = "\n".join(lines)
    await call.message.answer(text, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="👤 К профилю", callback_data=f"adm:u:{uid}")]]))


@admin_router.callback_query(F.data.startswith("adm:reg:"))
async def cb_toggle_registered(call: types.CallbackQuery):
    await call.answer("Статус определяется подтверждением почты и вручную не меняется.", show_alert=True)
    _, _, uid_raw, value = call.data.split(":")
    uid, registered = int(uid_raw), value == "1"
    lifted = admin_db.set_registered(uid, registered, call.from_user.id)
    await call.answer("Теперь: ✅ зарегистрирован" if registered else "Теперь: 🕓 не зарегистрирован",
                      show_alert=True)
    if lifted:
        await _notify_user(call.bot, uid, "✅ Регистрация подтверждена, блокировка снята.")
    await _send_user_card(call.message, uid, ROLE_ADMIN)


# -------------------------------------------- sanctions / report decisions
@admin_router.callback_query(F.data.startswith("adm:s:"))
async def cb_sanction_start(call: types.CallbackQuery, state: FSMContext):
    role = _role(call.from_user.id)
    try:
        _, _, action, uid, days, rid = call.data.split(":")
        uid, days, rid = int(uid), int(days), int(rid)
    except ValueError:
        await call.answer()
        return
    if action not in SANCTION_TITLES:
        await call.answer()
        return
    if action == "perm" and role != ROLE_ADMIN:
        await _deny(call)
        return
    if rid:
        report = admin_db.get_report(rid)
        if not report or report["status"] != "new":
            await call.answer("Жалоба уже обработана", show_alert=True)
            return
    await state.set_state(AdminFlow.sanction_comment)
    await state.update_data(action=action, uid=uid, days=days, report_id=rid)
    await call.answer()
    title = SANCTION_TITLES[action]
    suffix = f" на {days} д." if action == "temp" else ""
    await call.message.answer(
        f"✍️ <b>{title.capitalize()}{suffix}</b> · пользователь <code>{uid}</code>\n\n"
        "Напиши комментарий (причину) — он сохранится в решении и в журнале. "
        "Отправь «-», чтобы пропустить.",
        reply_markup=cancel_kb(),
    )


@admin_router.message(StateFilter(AdminFlow.sanction_comment))
async def msg_sanction_comment(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text or len(text) > 500:
        await message.answer("Комментарий — текст до 500 символов (или «-»).")
        return
    comment = "" if text == "-" else text
    data = await state.get_data()
    if data.get("action") == "perm":
        await state.update_data(comment=comment)
        await state.set_state(AdminFlow.sanction_confirm)
        await message.answer(
            f"⛔ Заблокировать <code>{data['uid']}</code> <b>навсегда</b>?\n"
            f"Комментарий: {esc(comment)}",
            reply_markup=confirm_kb("adm:sc:yes", "⛔ Да, заблокировать"),
        )
        return
    await state.clear()
    await _execute_sanction(message, message.from_user.id, data, comment)


@admin_router.callback_query(StateFilter(AdminFlow.sanction_confirm), F.data == "adm:sc:yes")
async def cb_sanction_confirm(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await _execute_sanction(call.message, call.from_user.id, data, data.get("comment", ""), bot=call.bot)


async def _execute_sanction(target: Message, admin_id: int, data: dict, comment: str, bot=None) -> None:
    bot = bot or target.bot
    role = _role(admin_id)
    action, uid = data.get("action"), data.get("uid")
    days = data.get("days") or None
    rid = data.get("report_id") or 0
    if role is None or action not in SANCTION_TITLES or uid is None:
        await target.answer("Действие недоступно.")
        return
    if action == "perm" and role != ROLE_ADMIN:
        await target.answer("Недостаточно прав для бана навсегда.")
        return

    until, reason = None, "Нарушение правил"
    try:
        if rid:
            decision = {"dismiss": "dismiss", "warn": "warn", "temp": "temp_ban", "perm": "perm_ban"}[action]
            result = admin_db.resolve_report(rid, admin_id, decision, comment, days)
            if result is None:
                await target.answer("Эта жалоба уже обработана другим модератором.")
                return
            until, reason = result["until"], result["reason"]
        elif action == "warn":
            admin_db.warn_user(uid, comment or reason, admin_id)
        elif action == "temp":
            until = admin_db.ban_user(uid, days, reason, admin_id, comment)
        elif action == "perm":
            until = admin_db.ban_user(uid, None, reason, admin_id, comment)
        elif action == "unban":
            if not admin_db.unban_user(uid, admin_id, comment):
                await target.answer("У пользователя нет активной блокировки.")
                return
    except ValueError as exc:
        await target.answer(f"⚠️ {html.escape(str(exc))}")
        return

    # tell the person concerned (not on report dismissal): only reason, comment and end date
    card = admin_db.get_user_card(uid)
    registered = bool(card and card["is_registered"])
    details = f"Причина: {html.escape(reason)}" + (f"\nКомментарий: {html.escape(comment)}" if comment else "")
    if action == "warn":
        await _notify_user(bot, uid, f"⚠️ Предупреждение от модерации.\n{details}")
    elif action in {"temp", "perm"}:
        if registered:
            await _notify_user(bot, uid, f"🚫 Твой аккаунт заблокирован.\n{details}\n"
                                         f"До: {'бессрочно' if action == 'perm' else fmt_dt(until)}")
        else:
            await _notify_user(bot, uid, "🚫 Твой аккаунт заблокирован, но его можно восстановить, подтвердив почту ВШЭ в боте.")
    elif action == "unban":
        await _notify_user(bot, uid, "✅ Блокировка снята.")

    summary = {
        "warn": "⚠️ Предупреждение вынесено",
        "temp": f"⏳ Бан до {fmt_dt(until)}",
        "perm": "⛔ Пользователь заблокирован навсегда",
        "unban": "✅ Блокировка снята",
        "dismiss": "✖️ Жалоба отклонена",
    }[action]
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="👤 К профилю", callback_data=f"adm:u:{uid}")],
        [types.InlineKeyboardButton(text="🚩 К жалобам", callback_data="adm:rep:n:0")],
        [types.InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm:menu")],
    ])
    await target.answer(f"{summary}. Решение сохранено в журнале.", reply_markup=kb)


# ----------------------------------------------------------------- reports
@admin_router.callback_query(F.data.startswith("adm:rep:"))
async def cb_reports(call: types.CallbackQuery):
    try:
        _, _, group, page = call.data.split(":")
        page = int(page)
    except ValueError:
        await call.answer()
        return
    role = _role(call.from_user.id)
    rows, total = admin_db.list_reports(group, page, REPORTS_PAGE)
    title = "🆕 Новые жалобы" if group == "n" else "📁 Обработанные жалобы"
    text = f"🚩 <b>{title}</b>: {total}\n\nЖалобы на неверифицированные аккаунты блокируются автоматически и попадают в «Обработанные»."
    if not rows:
        text += "\n\nСписок пуст."
    await call.answer()
    await _show(call, text, reports_list_kb(rows, group, page, total, REPORTS_PAGE))


@admin_router.callback_query(F.data.startswith("adm:r:"))
async def cb_report_card(call: types.CallbackQuery):
    try:
        report_id = int(call.data.split(":")[2])
    except (ValueError, IndexError):
        await call.answer()
        return
    report = admin_db.get_report(report_id)
    if not report:
        await call.answer("Жалоба не найдена", show_alert=True)
        return
    role = _role(call.from_user.id)
    is_new = report["status"] == "new"
    status = {"new": "🆕 новая", "reviewed": "✅ рассмотрена", "auto_banned": "🤖 авто-бан"}.get(report["status"], report["status"])
    registered = "верифицирован" if report["target_was_registered"] else "не верифицирован"
    lines = [
        f"🚩 <b>Жалоба #{report_id}</b> · {status}",
        f"Причина: {esc(REPORT_REASONS.get(report['reason'], report['reason']))}",
    ]
    if report["comment"]:
        lines.append(f"Комментарий: {esc(report['comment'][:300])}")
    lines += [
        f"Дата: {fmt_dt(report['created_at'])}",
        f"От: {esc(report['reporter_name'])} (<code>{report['reporter_id']}</code>)",
        f"На: {esc(report['target_name'])} (<code>{report['target_id']}</code>), {registered}",
        f"Направление: {esc(report['target_faculty'])}",
    ]
    if report["target_banned_until"] and report["target_banned_until"] > admin_db._now():
        lines.append(f"Сейчас заблокирован: {fmt_dt(report['target_banned_until'])}")
    if not is_new:
        lines.append(f"Решение: {esc(report['decision'])}" + (f" · модератор {report['moderator_id']}" if report["moderator_id"] else ""))
        if report["moderator_comment"]:
            lines.append(f"Комментарий модератора: {esc(report['moderator_comment'][:200])}")
    await call.answer()
    await _send_card(call.message, "\n".join(lines), report.get("target_photo"),
                     report_card_kb(report_id, report["target_id"], is_new, role))


# ---------------------------------------------------------------- settings
def _settings_text() -> str:
    values = admin_db.get_all_settings()
    only = "🟢 вкл" if values["reports_only_registered"] == "1" else "🔴 выкл"
    return ("⚙️ <b>Настройки</b>\n\n"
            "Состояние каждого пункта написано на кнопке. Переключатели (🟢/🔴, ✅/🕓) меняются "
            "одним нажатием, у пунктов с ✏️ бот спросит новое число.\n\n"
            "<b>Сейчас:</b>\n"
            f"• Жалобы принимаются только от верифицированных: {only}\n\n"
            "ℹ️ Не зарегистрированному аккаунту бан по жалобе выдаётся автоматически, "
            "по зарегистрированному решает модератор. Если пользователь превысил лимит, это действие "
            "блокируется для него на 1 час. При слишком частых действиях доступ ограничивается на время. "
            "«Снять все ограничения» отменяет все такие блокировки и обнуляет счётчики.")


@admin_router.callback_query(F.data == "adm:set")
async def cb_settings(call: types.CallbackQuery):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    await call.answer()
    await _show(call, _settings_text(), settings_kb(admin_db.get_all_settings()))


@admin_router.callback_query(F.data == "adm:climit")
async def cb_clear_limits(call: types.CallbackQuery):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    blocks, restrictions = admin_db.clear_all_restrictions(call.from_user.id)
    await call.answer(f"Все ограничения сняты.\nБлокировок действий: {blocks}\n"
                      f"Ограничений доступа: {restrictions}", show_alert=True)


@admin_router.callback_query(F.data.startswith("adm:setv:"))
async def cb_setting_change(call: types.CallbackQuery, state: FSMContext):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    key = call.data.split(":", 2)[2]
    if key not in SETTINGS_META:
        await call.answer()
        return
    title, kind, lo, hi = SETTINGS_META[key]
    if kind == "bool":
        current = admin_db.get_setting(key)
        new_value = "0" if current == "1" else "1"
        admin_db.set_setting(key, new_value, call.from_user.id)
        await call.answer(f"{SETTING_SHORT[key]}: теперь {setting_state_text(key, new_value)}", show_alert=True)
        await _show(call, _settings_text(), settings_kb(admin_db.get_all_settings()))
        return
    await state.set_state(AdminFlow.setting_value)
    await state.update_data(setting_key=key)
    await call.answer()
    await call.message.answer(
        f"✏️ <b>{html.escape(title)}</b>\nСейчас: {admin_db.get_setting(key)}\n\nВведи число от {lo} до {hi}:",
        reply_markup=cancel_kb())


@admin_router.message(StateFilter(AdminFlow.setting_value))
async def msg_setting_value(message: Message, state: FSMContext):
    key = (await state.get_data()).get("setting_key")
    if _role(message.from_user.id) != ROLE_ADMIN or key not in SETTINGS_META:
        await state.clear()
        await message.answer("Недостаточно прав.")
        return
    try:
        admin_db.set_setting(key, (message.text or "").strip(), message.from_user.id)
    except ValueError as exc:
        text = str(exc) if "должно" in str(exc) else "Введи целое число."
        await message.answer(html.escape(text))
        return
    await state.clear()
    await message.answer(_settings_text(), reply_markup=settings_kb(admin_db.get_all_settings()))


# --------------------------------------------------------------------- ads
async def _render_ads_list(call: types.CallbackQuery) -> None:
    ads = admin_db.list_ads()
    text = "📢 <b>Реклама</b>\n\nВставки показываются отдельной карточкой с пометкой «Реклама» между анкетами."
    if not ads:
        text += "\n\nКампаний пока нет."
    await _show(call, text, ads_list_kb(ads, admin_db.ad_status_label))


def _ad_card_text(ad: dict) -> str:
    stats = admin_db.ad_stats(ad["id"])
    limit = ad["max_per_user"] if ad["max_per_user"] else "без ограничения"
    return (
        f"📢 <b>Реклама #{ad['id']}</b> · {admin_db.ad_status_label(ad)}\n"
        f"Текст: {esc(ad['text'][:200])}\n"
        f"Кнопка: {esc(ad['button_text'])} → {esc(ad['url'])}\n"
        f"Частота: 1 реклама на {ad['every_n']} анкет · лимит на пользователя: {limit}\n"
        f"Период: {ad['start_date'] or 'сразу'} — {ad['end_date'] or 'без окончания'}\n\n"
        f"👁 Показов: {stats['impressions']} (уникальных: {stats['unique_viewers']})\n"
        f"👆 Нажатий: {stats['clicks']} (уникальных: {stats['unique_clickers']})\n"
        f"CTR: {stats['ctr']:.1f}%"
    )


@admin_router.callback_query(F.data == "adm:ads")
async def cb_ads(call: types.CallbackQuery, state: FSMContext):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    await state.clear()
    await call.answer()
    await _render_ads_list(call)


@admin_router.callback_query(F.data.startswith("adm:ad:"))
async def cb_ad_card(call: types.CallbackQuery, state: FSMContext):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    ad = admin_db.get_ad(int(call.data.split(":")[2]))
    if not ad:
        await call.answer("Кампания не найдена", show_alert=True)
        return
    await call.answer()
    await state.clear()
    await _show(call, _ad_card_text(ad), ad_card_kb(ad["id"], bool(ad["is_active"])))
    try:
        await send_ad_card(call.message, ad, preview=True)
    except TelegramAPIError:
        logger.warning("Ad preview failed for %s", ad["id"])


@admin_router.callback_query(F.data.startswith("adm:adt:"))
async def cb_ad_toggle(call: types.CallbackQuery):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    _, _, ad_raw, value = call.data.split(":")
    ad_id = int(ad_raw)
    ad = admin_db.get_ad(ad_id)
    if not ad:
        await call.answer("Кампания не найдена", show_alert=True)
        return
    await call.answer()
    if value == "1":  # enabling = launching: ask for confirmation first
        await _show(call, f"🚀 Запустить рекламу #{ad_id}?\n\n{html.escape(ad['text'][:300])}\n\n"
                          f"Ссылка: {html.escape(ad['url'])}",
                    confirm_kb(f"adm:adc:{ad_id}", "🚀 Запустить", f"adm:ad:{ad_id}"))
        return
    admin_db.set_ad_active(ad_id, False, call.from_user.id)
    await _show(call, _ad_card_text(admin_db.get_ad(ad_id)), ad_card_kb(ad_id, False))


@admin_router.callback_query(F.data.startswith("adm:adc:"))
async def cb_ad_launch(call: types.CallbackQuery):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    ad_id = int(call.data.split(":")[2])
    if not admin_db.set_ad_active(ad_id, True, call.from_user.id):
        await call.answer("Кампания не найдена", show_alert=True)
        return
    await call.answer("Реклама запущена")
    await _show(call, _ad_card_text(admin_db.get_ad(ad_id)), ad_card_kb(ad_id, True))


@admin_router.callback_query(F.data.startswith("adm:addelete:"))
async def cb_ad_delete(call: types.CallbackQuery):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    ad_id = int(call.data.split(":")[2])
    ad = admin_db.get_ad(ad_id)
    if not ad:
        await call.answer("Кампания не найдена", show_alert=True)
        return
    await call.answer()
    await _show(call, f"🗑 Удалить рекламный слот #{ad_id}?\n\n{esc(ad['text'][:300])}",
                confirm_kb(f"adm:addeleteconfirm:{ad_id}", "🗑 Удалить", f"adm:ad:{ad_id}"))


@admin_router.callback_query(F.data.startswith("adm:addeleteconfirm:"))
async def cb_ad_delete_confirm(call: types.CallbackQuery):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    ad_id = int(call.data.split(":")[2])
    deleted = admin_db.delete_ad(ad_id, call.from_user.id)
    await call.answer("Слот удалён" if deleted else "Кампания уже удалена")
    await _render_ads_list(call)


# --- editing an existing slot
@admin_router.callback_query(F.data.startswith("adm:adedit:"))
async def cb_ad_edit(call: types.CallbackQuery, state: FSMContext):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    ad_id = int(call.data.split(":")[2])
    if not admin_db.get_ad(ad_id):
        await state.clear()
        await call.answer("Кампания не найдена", show_alert=True)
        return
    await state.clear()
    await call.answer()
    await _show(call, f"✏️ Реклама #{ad_id} · выбери параметр для изменения.",
                ad_edit_kb(ad_id, admin_db.AD_EDIT_FIELDS))


@admin_router.callback_query(F.data.startswith("adm:adfield:"))
async def cb_ad_edit_field(call: types.CallbackQuery, state: FSMContext):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    _, _, raw_id, field = call.data.split(":")
    ad_id = int(raw_id)
    ad = admin_db.get_ad(ad_id)
    if not ad or field not in admin_db.AD_EDIT_FIELDS:
        await call.answer("Параметр или кампания не найдены", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdEdit.value)
    await state.update_data(ad_id=ad_id, field=field)
    hints = {
        "text": "Введите новый текст (1–800 символов).",
        "image": "Отправьте новую картинку как фото или уберите текущую.",
        "url": "Введите прямую ссылку, начинающуюся с https://.",
        "button_text": "Введите текст кнопки (1–30 символов).",
        "every_n": "Введите частоту: от 1 до 1000 анкет.",
        "max_per_user": "Введите лимит: от 0 до 1000000. 0 — без ограничения.",
        "start_date": "Введите дату начала в формате ДД.ММ.ГГГГ или уберите ограничение.",
        "end_date": "Введите дату окончания включительно в формате ДД.ММ.ГГГГ или уберите ограничение.",
    }
    current = "есть фото" if field == "image" and ad[field] else ad[field]
    if field == "max_per_user" and current is None:
        current = "без ограничения"
    await call.answer()
    await _show(call, f"✏️ {admin_db.AD_EDIT_FIELDS[field]} · реклама #{ad_id}\n"
                      f"Сейчас: {esc(current)}\n\n{hints[field]}\nИзменение сохранится после ввода.",
                ad_edit_value_kb(ad_id, field in ("image", "start_date", "end_date")))


async def _save_ad_edit(message: Message, state: FSMContext, value):
    data = await state.get_data()
    ad_id, field = data["ad_id"], data["field"]
    try:
        updated = admin_db.update_ad_field(ad_id, field, value, message.from_user.id)
    except ValueError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.clear()
    ad = admin_db.get_ad(ad_id) if updated else None
    if not ad:
        await message.answer("Кампания уже удалена.")
        return
    await message.answer("✅ Изменения сохранены.\n\n" + _ad_card_text(ad),
                         reply_markup=ad_card_kb(ad_id, bool(ad["is_active"])))


@admin_router.message(StateFilter(AdEdit.value))
async def ad_edit_value(message: Message, state: FSMContext):
    if not _admin_only_message(message):
        return
    field = (await state.get_data())["field"]
    raw = (message.text or "").strip()
    value = raw
    if field == "image":
        if not message.photo:
            await message.answer("Отправьте именно фото или нажмите «Убрать значение».")
            return
        value = message.photo[-1].file_id
    elif field in ("every_n", "max_per_user"):
        if not raw.isdecimal() or len(raw) > 7:
            await message.answer("Введите целое число в указанном диапазоне.")
            return
        value = int(raw)
    elif field in ("start_date", "end_date"):
        parsed = _parse_date(raw)
        if not parsed:
            await message.answer("Формат даты: ДД.ММ.ГГГГ.")
            return
        value = parsed.isoformat()
    await _save_ad_edit(message, state, value)


@admin_router.callback_query(StateFilter(AdEdit.value), F.data == "adm:adeditclear")
async def cb_ad_edit_clear(call: types.CallbackQuery, state: FSMContext):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    data = await state.get_data()
    if data.get("field") not in ("image", "start_date", "end_date"):
        await call.answer("Этот параметр нельзя убрать", show_alert=True)
        return
    # Callback messages belong to the bot, so use the administrator's ID explicitly.
    try:
        updated = admin_db.update_ad_field(data["ad_id"], data["field"], None, call.from_user.id)
    except ValueError as exc:
        await call.answer(str(exc), show_alert=True)
        return
    await state.clear()
    await call.answer("Сохранено" if updated else "Кампания уже удалена")
    ad = admin_db.get_ad(data["ad_id"]) if updated else None
    if ad:
        await _show(call, _ad_card_text(ad), ad_card_kb(ad["id"], bool(ad["is_active"])))


# --- ad creation dialog
async def _ask_text(m: Message, state: FSMContext):
    await state.set_state(AdCreate.text)
    await m.answer("📢 <b>Новая реклама · 1/8</b>\nНапиши текст рекламы (до 800 символов).", reply_markup=cancel_kb())


async def _ask_image(m: Message, state: FSMContext):
    await state.set_state(AdCreate.image)
    await m.answer("2/8 · Отправь картинку (как фото) или пропусти.", reply_markup=skip_kb())


async def _ask_url(m: Message, state: FSMContext):
    await state.set_state(AdCreate.url)
    await m.answer("3/8 · Ссылка для кнопки (только https://, без сокращателей).", reply_markup=cancel_kb())


async def _ask_button(m: Message, state: FSMContext):
    await state.set_state(AdCreate.button)
    await m.answer("4/8 · Текст кнопки (до 30 символов), например «Узнать больше».", reply_markup=cancel_kb())


async def _ask_every(m: Message, state: FSMContext):
    await state.set_state(AdCreate.every_n)
    await m.answer("5/8 · Частота: одна реклама на сколько анкет? Например, 10.", reply_markup=cancel_kb())


async def _ask_max(m: Message, state: FSMContext):
    await state.set_state(AdCreate.max_per_user)
    await m.answer("6/8 · Сколько раз максимум показать одному пользователю? «0» — без ограничения.",
                   reply_markup=cancel_kb())


async def _ask_start(m: Message, state: FSMContext):
    await state.set_state(AdCreate.start_date)
    await m.answer("7/8 · Дата начала (ДД.ММ.ГГГГ) или пропусти — тогда сразу после запуска.", reply_markup=skip_kb())


async def _ask_end(m: Message, state: FSMContext):
    await state.set_state(AdCreate.end_date)
    await m.answer("8/8 · Дата окончания включительно (ДД.ММ.ГГГГ) или пропусти — без окончания.", reply_markup=skip_kb())


async def _ask_confirm(m: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(AdCreate.confirm)
    preview = {"id": 0, "text": data["text"], "image": data.get("image"), "button_text": data["button"]}
    await m.answer("👁 Так реклама будет выглядеть для пользователей:")
    await send_ad_card(m, preview, preview=True)
    limit = data["max_per_user"] or "без ограничения"
    await m.answer(
        f"Ссылка: {html.escape(data['url'])}\n"
        f"Частота: 1 на {data['every_n']} анкет · лимит на пользователя: {limit}\n"
        f"Период: {data.get('start_date') or 'сразу'} — {data.get('end_date') or 'без окончания'}\n\n"
        "Проверь текст и ссылку. Запускаем?",
        reply_markup=ad_create_confirm_kb())


@admin_router.callback_query(F.data == "adm:adnew")
async def cb_ad_new(call: types.CallbackQuery, state: FSMContext):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    await state.clear()
    await call.answer()
    await _ask_text(call.message, state)


def _admin_only_message(message: Message) -> bool:
    return _role(message.from_user.id) == ROLE_ADMIN


@admin_router.message(StateFilter(AdCreate.text))
async def ad_text(message: Message, state: FSMContext):
    if not _admin_only_message(message):
        return
    text = (message.text or "").strip()
    if not text or len(text) > 800:
        await message.answer("Текст — от 1 до 800 символов.")
        return
    await state.update_data(text=text)
    await _ask_image(message, state)


@admin_router.message(StateFilter(AdCreate.image))
async def ad_image(message: Message, state: FSMContext):
    if not _admin_only_message(message):
        return
    if message.photo:
        await state.update_data(image=message.photo[-1].file_id)
        await _ask_url(message, state)
        return
    await message.answer("Отправь именно фото или нажми «Пропустить».", reply_markup=skip_kb())


@admin_router.message(StateFilter(AdCreate.url))
async def ad_url(message: Message, state: FSMContext):
    if not _admin_only_message(message):
        return
    url = (message.text or "").strip()
    error = admin_db.validate_ad_url(url)
    if error:
        await message.answer(f"⚠️ {html.escape(error)}")
        return
    await state.update_data(url=url)
    await _ask_button(message, state)


@admin_router.message(StateFilter(AdCreate.button))
async def ad_button(message: Message, state: FSMContext):
    if not _admin_only_message(message):
        return
    text = (message.text or "").strip()
    if not text or len(text) > 30:
        await message.answer("Текст кнопки — от 1 до 30 символов.")
        return
    await state.update_data(button=text)
    await _ask_every(message, state)


@admin_router.message(StateFilter(AdCreate.every_n))
async def ad_every(message: Message, state: FSMContext):
    if not _admin_only_message(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdecimal() or not 1 <= int(raw) <= 1000:
        await message.answer("Введи целое число от 1 до 1000.")
        return
    await state.update_data(every_n=int(raw))
    await _ask_max(message, state)


@admin_router.message(StateFilter(AdCreate.max_per_user))
async def ad_max(message: Message, state: FSMContext):
    if not _admin_only_message(message):
        return
    raw = (message.text or "").strip()
    if not raw.isdecimal() or int(raw) > 1_000_000:
        await message.answer("Введи целое число (0 — без ограничения).")
        return
    await state.update_data(max_per_user=int(raw) or None)
    await _ask_start(message, state)


@admin_router.message(StateFilter(AdCreate.start_date))
async def ad_start(message: Message, state: FSMContext):
    if not _admin_only_message(message):
        return
    parsed = _parse_date(message.text or "")
    if not parsed:
        await message.answer("Формат даты: ДД.ММ.ГГГГ, например 20.10.2026.", reply_markup=skip_kb())
        return
    await state.update_data(start_date=parsed.isoformat())
    await _ask_end(message, state)


@admin_router.message(StateFilter(AdCreate.end_date))
async def ad_end(message: Message, state: FSMContext):
    if not _admin_only_message(message):
        return
    parsed = _parse_date(message.text or "")
    if not parsed:
        await message.answer("Формат даты: ДД.ММ.ГГГГ, например 31.10.2026.", reply_markup=skip_kb())
        return
    start = (await state.get_data()).get("start_date")
    if start and parsed.isoformat() < start:
        await message.answer("Дата окончания не может быть раньше даты начала.", reply_markup=skip_kb())
        return
    await state.update_data(end_date=parsed.isoformat())
    await _ask_confirm(message, state)


@admin_router.callback_query(F.data == "adm:adskip")
async def cb_ad_skip(call: types.CallbackQuery, state: FSMContext):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    current = await state.get_state()
    await call.answer()
    if current == AdCreate.image.state:
        await _ask_url(call.message, state)
    elif current == AdCreate.start_date.state:
        await _ask_end(call.message, state)
    elif current == AdCreate.end_date.state:
        await _ask_confirm(call.message, state)


@admin_router.callback_query(StateFilter(AdCreate.confirm), F.data.startswith("adm:adsave:"))
async def cb_ad_save(call: types.CallbackQuery, state: FSMContext):
    if _role(call.from_user.id) != ROLE_ADMIN:
        await _deny(call)
        return
    launch = call.data.endswith(":1")
    data = await state.get_data()
    await state.clear()
    ad_id = admin_db.create_ad(
        call.from_user.id, data["text"], data.get("image"), data["url"], data["button"],
        data["every_n"], data["max_per_user"], data.get("start_date"), data.get("end_date"),
    )
    if launch:
        admin_db.set_ad_active(ad_id, True, call.from_user.id)
    await call.answer("Сохранено")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    ad = admin_db.get_ad(ad_id)
    await call.message.answer(_ad_card_text(ad), reply_markup=ad_card_kb(ad_id, bool(ad["is_active"])))


# ----------------------------------------------------------------- journal
def _journal_view(filters: dict, page: int):
    rows, total = admin_db.query_journal(
        admin_id=filters.get("admin"), user_id=filters.get("user"),
        action=filters.get("action"), date=filters.get("date"),
        page=page, page_size=JOURNAL_PAGE)
    active = []
    if filters.get("admin") is not None:
        active.append(f"админ {filters['admin']}")
    if filters.get("user") is not None:
        active.append(f"пользователь {filters['user']}")
    if filters.get("action"):
        active.append(JOURNAL_ACTIONS.get(filters["action"], filters["action"]))
    if filters.get("date"):
        active.append(filters["date"])
    lines = [f"📜 <b>Журнал действий</b> · записей: {total}"]
    if active:
        lines.append("Фильтры: " + ", ".join(html.escape(x) for x in active))
    if not rows:
        lines.append("\nЗаписей нет.")
    for r in rows:
        who = "🤖 авто" if r["source"] == "auto" else f"👮 {r['admin_id']}"
        target = f" → 👤 {r['target_user_id']}" if r["target_user_id"] else ""
        detail = " · ".join(x for x in (r["reason"], r["result"]) if x)
        lines.append(f"\n<b>{fmt_dt(r['created_at'])}</b> · {who} · "
                     f"{JOURNAL_ACTIONS.get(r['action'], r['action'])}{target}\n   {esc(detail[:120])}")
    return "\n".join(lines), journal_kb(page, total, JOURNAL_PAGE)


@admin_router.callback_query(F.data.startswith("adm:log:"))
async def cb_journal(call: types.CallbackQuery, state: FSMContext):
    try:
        page = int(call.data.split(":")[2])
    except (ValueError, IndexError):
        page = 0
    await state.set_state(None)
    filters = (await state.get_data()).get("jf", {})
    text, kb = _journal_view(filters, page)
    await call.answer()
    await _show(call, text, kb)


@admin_router.callback_query(F.data.startswith("adm:lf:"))
async def cb_journal_filter(call: types.CallbackQuery, state: FSMContext):
    kind = call.data.split(":")[2]
    await call.answer()
    if kind == "clear":
        await state.update_data(jf={})
        text, kb = _journal_view({}, 0)
        await _show(call, text, kb)
        return
    if kind == "type":
        await _show(call, "🏷 Выбери тип действия:", journal_types_kb())
        return
    prompts = {
        "admin": "Введи Telegram ID администратора:",
        "user": "Введи Telegram ID пользователя:",
        "date": "Введи дату в формате ДД.ММ.ГГГГ:",
    }
    if kind not in prompts:
        return
    await state.set_state(AdminFlow.journal_value)
    await state.update_data(jf_kind=kind)
    await call.message.answer(prompts[kind], reply_markup=cancel_kb())


@admin_router.callback_query(F.data.startswith("adm:lt:"))
async def cb_journal_type(call: types.CallbackQuery, state: FSMContext):
    code = call.data.split(":")[2]
    if code not in JOURNAL_ACTIONS:
        await call.answer()
        return
    filters = dict((await state.get_data()).get("jf", {}))
    filters["action"] = code
    await state.update_data(jf=filters)
    text, kb = _journal_view(filters, 0)
    await call.answer()
    await _show(call, text, kb)


@admin_router.message(StateFilter(AdminFlow.journal_value))
async def msg_journal_value(message: Message, state: FSMContext):
    data = await state.get_data()
    kind = data.get("jf_kind")
    raw = (message.text or "").strip()
    filters = dict(data.get("jf", {}))
    if kind in {"admin", "user"}:
        if not raw.lstrip("-").isdigit():
            await message.answer("Нужен числовой Telegram ID.")
            return
        filters[kind] = int(raw)
    elif kind == "date":
        parsed = _parse_date(raw)
        if not parsed:
            await message.answer("Формат даты: ДД.ММ.ГГГГ.")
            return
        filters["date"] = parsed.isoformat()
    else:
        await state.set_state(None)
        return
    await state.set_state(None)
    await state.update_data(jf=filters)
    text, kb = _journal_view(filters, 0)
    await message.answer(text, reply_markup=kb)
