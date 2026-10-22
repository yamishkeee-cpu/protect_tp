"""Inline keyboards for the admin panel. All callback_data start with "adm:"."""
from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

from app.features.admin.admin_db import JOURNAL_ACTIONS, ROLE_ADMIN, SETTINGS_META, REPORT_REASONS

BACK_TO_MENU = [Btn(text="🔙 В админ-меню", callback_data="adm:menu")]


def menu_kb(role: str, new_reports: int = 0) -> Markup:
    rows = [
        [Btn(text="👥 Пользователи", callback_data="adm:users")],
        [Btn(text=f"🚩 Жалобы ({new_reports})" if new_reports else "🚩 Жалобы", callback_data="adm:rep:n:0")],
    ]
    if role == ROLE_ADMIN:
        rows.append([Btn(text="⚙️ Настройки", callback_data="adm:set")])
        rows.append([Btn(text="📢 Реклама", callback_data="adm:ads")])
    rows.append([Btn(text="📜 Журнал действий", callback_data="adm:log:0")])
    return Markup(inline_keyboard=rows)


def cancel_kb() -> Markup:
    return Markup(inline_keyboard=[[Btn(text="❌ Отмена", callback_data="adm:menu")]])


def user_card_kb(uid: int, banned: bool, registered: bool, role: str) -> Markup:
    rows = [
        [Btn(text="⏳ Бан 1 д", callback_data=f"adm:s:temp:{uid}:1:0"),
         Btn(text="⏳ Бан 7 д", callback_data=f"adm:s:temp:{uid}:7:0"),
         Btn(text="⏳ Бан 30 д", callback_data=f"adm:s:temp:{uid}:30:0")],
    ]
    if role == ROLE_ADMIN:
        rows.append([Btn(text="⛔ Бан навсегда", callback_data=f"adm:s:perm:{uid}:0:0")])
    rows.append([Btn(text="⚠️ Предупреждение", callback_data=f"adm:s:warn:{uid}:0:0")])
    if banned:
        rows.append([Btn(text="✅ Снять блокировку", callback_data=f"adm:s:unban:{uid}:0:0")])
    rows.append([Btn(text="📜 История санкций", callback_data=f"adm:hist:{uid}")])
    rows.append(BACK_TO_MENU)
    return Markup(inline_keyboard=rows)


def report_card_kb(report_id: int, target_id: int, is_new: bool, role: str) -> Markup:
    rows = []
    if is_new:
        rows.append([Btn(text="✖️ Отклонить", callback_data=f"adm:s:dismiss:{target_id}:0:{report_id}"),
                     Btn(text="⚠️ Предупредить", callback_data=f"adm:s:warn:{target_id}:0:{report_id}")])
        rows.append([Btn(text="⏳ 1 д", callback_data=f"adm:s:temp:{target_id}:1:{report_id}"),
                     Btn(text="⏳ 7 д", callback_data=f"adm:s:temp:{target_id}:7:{report_id}"),
                     Btn(text="⏳ 30 д", callback_data=f"adm:s:temp:{target_id}:30:{report_id}")])
        if role == ROLE_ADMIN:
            rows.append([Btn(text="⛔ Заблокировать навсегда", callback_data=f"adm:s:perm:{target_id}:0:{report_id}")])
    rows.append([Btn(text="👤 Профиль нарушителя", callback_data=f"adm:u:{target_id}")])
    rows.append([Btn(text="🔙 К жалобам", callback_data="adm:rep:n:0")])
    return Markup(inline_keyboard=rows)


def reports_list_kb(rows_data, group: str, page: int, total: int, page_size: int) -> Markup:
    rows = []
    for item in rows_data:
        label = f"#{item['id']} · {REPORT_REASONS.get(item['reason'], item['reason'])} · {item['target_name'] or item['target_id']}"
        rows.append([Btn(text=label[:60], callback_data=f"adm:r:{item['id']}")])
    nav = []
    if page > 0:
        nav.append(Btn(text="⬅️", callback_data=f"adm:rep:{group}:{page - 1}"))
    if (page + 1) * page_size < total:
        nav.append(Btn(text="➡️", callback_data=f"adm:rep:{group}:{page + 1}"))
    if nav:
        rows.append(nav)
    other = ("d", "📁 Обработанные") if group == "n" else ("n", "🆕 Новые")
    rows.append([Btn(text=other[1], callback_data=f"adm:rep:{other[0]}:0")])
    rows.append(BACK_TO_MENU)
    return Markup(inline_keyboard=rows)


def confirm_kb(yes_cb: str, yes_text: str = "✅ Подтвердить", no_cb: str = "adm:menu") -> Markup:
    return Markup(inline_keyboard=[[Btn(text=yes_text, callback_data=yes_cb),
                                    Btn(text="❌ Отмена", callback_data=no_cb)]])


SETTING_SHORT = {
    "default_registered": "Новый аккаунт при входе",
    "reports_only_registered": "Жалобы только от верифицированных",
    "reports_per_day": "Жалоб в сутки от одного человека",
    "likes_per_hour": "Лайков в час",
    "skips_per_hour": "Пропусков в час",
    "creations_per_day": "Создание анкет и событий в сутки",
    "burst_actions": "Действий за 10 сек до ограничения",
    "restrict_minutes": "Длительность ограничения, мин",
}


def setting_state_text(key: str, value: str) -> str:
    """Human-readable current state of a setting (used on buttons and in pop-up answers)."""
    if key == "default_registered":
        return "✅ ЗАРЕГАН" if value == "1" else "🕓 НЕ ЗАРЕГАН"
    if SETTINGS_META[key][1] == "bool":
        return "🟢 ВКЛ" if value == "1" else "🔴 ВЫКЛ"
    return value


def settings_kb(values: dict) -> Markup:
    """The current state is the first thing on every button: [state] name.
    Switches flip on tap; numeric items open an input prompt (✏️)."""
    rows = []
    for key, (_title, kind, _lo, _hi) in SETTINGS_META.items():
        state = setting_state_text(key, values[key])
        label = f"{state} · {SETTING_SHORT[key]}" if kind == "bool" else f"✏️ {SETTING_SHORT[key]}: {state}"
        rows.append([Btn(text=label, callback_data=f"adm:setv:{key}")])
    rows.append([Btn(text="🧹 Снять все ограничения", callback_data="adm:climit")])
    rows.append(BACK_TO_MENU)
    return Markup(inline_keyboard=rows)


def search_results_kb(results) -> Markup:
    rows = []
    for item in results:
        name = item.get("name") or "без анкеты"
        tag = f" · @{item['username']}" if item.get("username") else ""
        rows.append([Btn(text=f"{name}{tag} · {item['user_id']}"[:60], callback_data=f"adm:u:{item['user_id']}")])
    rows.append([Btn(text="🔎 Искать ещё", callback_data="adm:users")])
    rows.append(BACK_TO_MENU)
    return Markup(inline_keyboard=rows)


def ads_list_kb(ads, status_label) -> Markup:
    rows = [[Btn(text="➕ Новая реклама", callback_data="adm:adnew")]]
    for ad in ads:
        rows.append([Btn(text=f"#{ad['id']} {status_label(ad)} · {ad['text'][:25]}", callback_data=f"adm:ad:{ad['id']}")])
    rows.append(BACK_TO_MENU)
    return Markup(inline_keyboard=rows)


def ad_card_kb(ad_id: int, is_active: bool) -> Markup:
    toggle = (Btn(text="⏸ Выключить", callback_data=f"adm:adt:{ad_id}:0") if is_active
              else Btn(text="▶️ Включить", callback_data=f"adm:adt:{ad_id}:1"))
    return Markup(inline_keyboard=[
        [toggle],
        [Btn(text="✏️ Редактировать", callback_data=f"adm:adedit:{ad_id}")],
        [Btn(text="🗑 Удалить слот", callback_data=f"adm:addelete:{ad_id}")],
        [Btn(text="🔙 К рекламе", callback_data="adm:ads")],
    ])


def ad_edit_kb(ad_id: int, fields: dict) -> Markup:
    return Markup(inline_keyboard=[
        [Btn(text=label, callback_data=f"adm:adfield:{ad_id}:{field}")]
        for field, label in fields.items()
    ] + [[Btn(text="🔙 К слоту", callback_data=f"adm:ad:{ad_id}")]])


def ad_edit_value_kb(ad_id: int, clearable: bool) -> Markup:
    rows = []
    if clearable:
        rows.append([Btn(text="🗑 Убрать значение", callback_data="adm:adeditclear")])
    rows.append([Btn(text="❌ Отмена", callback_data=f"adm:adedit:{ad_id}")])
    return Markup(inline_keyboard=rows)


def ad_create_confirm_kb() -> Markup:
    return Markup(inline_keyboard=[
        [Btn(text="🚀 Запустить сейчас", callback_data="adm:adsave:1")],
        [Btn(text="💾 Сохранить выключенной", callback_data="adm:adsave:0")],
        [Btn(text="❌ Отмена", callback_data="adm:menu")],
    ])


def skip_kb() -> Markup:
    return Markup(inline_keyboard=[[Btn(text="⏭ Пропустить", callback_data="adm:adskip")],
                                   [Btn(text="❌ Отмена", callback_data="adm:menu")]])


def journal_kb(page: int, total: int, page_size: int) -> Markup:
    rows = []
    nav = []
    if page > 0:
        nav.append(Btn(text="⬅️", callback_data=f"adm:log:{page - 1}"))
    if (page + 1) * page_size < total:
        nav.append(Btn(text="➡️", callback_data=f"adm:log:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([Btn(text="👮 Админ", callback_data="adm:lf:admin"),
                 Btn(text="👤 Пользователь", callback_data="adm:lf:user")])
    rows.append([Btn(text="🏷 Тип действия", callback_data="adm:lf:type"),
                 Btn(text="📅 Дата", callback_data="adm:lf:date")])
    rows.append([Btn(text="♻️ Сбросить фильтры", callback_data="adm:lf:clear")])
    rows.append(BACK_TO_MENU)
    return Markup(inline_keyboard=rows)


def journal_types_kb() -> Markup:
    rows = [[Btn(text=title, callback_data=f"adm:lt:{code}")] for code, title in JOURNAL_ACTIONS.items()]
    rows.append([Btn(text="🔙 К журналу", callback_data="adm:log:0")])
    return Markup(inline_keyboard=rows)
