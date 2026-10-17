#!/usr/bin/env bash
# Реорганизация репозитория protect_tp по папкам.
# Запуск из корня репозитория (где лежит bot.py), с активированным .venv:
#     git checkout -b restructure
#     bash restructure.sh
set -euo pipefail

[ -f bot.py ] && [ -f db.py ] || { echo "Запустите скрипт из корня репозитория (там, где bot.py и db.py)."; exit 1; }
[ -d app ] && { echo "Папка app уже есть: реорганизация уже сделана."; exit 1; }
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Есть незакоммиченные изменения. Сначала закоммитьте их или уберите (git stash)."; exit 1
fi
PY="${PYTHON:-python3}"

echo "0/6 Исправляю лишний пробел в temp_profile_handlers.py (из-за него бот не запускался)"
if [ -f temp_profile_handlers.py ]; then
  sed -i.bak 's/^     text = ($/    text = (/' temp_profile_handlers.py && rm -f temp_profile_handlers.py.bak
fi

echo "1/6 Создаю папки"
mkdir -p app/core app/dev app/features/profile app/features/temp_profile \
         app/features/events app/features/verification app/features/admin docs tests

echo "2/6 Переношу файлы"
mv_() {
  if [ -e "$1" ]; then
    git mv "$1" "$2" 2>/dev/null || mv "$1" "$2"
  else
    echo "  пропуск: $1 не найден"
  fi
}
# общее: база, клавиатуры
mv_ db.py                       app/core/
mv_ keyboards.py                app/core/
# профиль
mv_ handlers.py                 app/features/profile/
mv_ states.py                   app/features/profile/
# временные анкеты
mv_ temp_profile_db.py          app/features/temp_profile/
mv_ temp_profile_handlers.py    app/features/temp_profile/
mv_ temp_profile_states.py      app/features/temp_profile/
# мероприятия
mv_ events_db.py                app/features/events/
mv_ events_handlers.py          app/features/events/
mv_ events_states.py            app/features/events/
# подтверждение почты
mv_ verification_db.py          app/features/verification/
mv_ verification_handlers.py    app/features/verification/
mv_ verification_keyboards.py   app/features/verification/
mv_ verification_service.py     app/features/verification/
mv_ verification_states.py      app/features/verification/
# админка, жалобы, реклама, доступ (баны)
mv_ admin_db.py                 app/features/admin/
mv_ admin_handlers.py           app/features/admin/
mv_ admin_keyboards.py          app/features/admin/
mv_ admin_states.py             app/features/admin/
mv_ ads.py                      app/features/admin/
mv_ report_handlers.py          app/features/admin/
mv_ access_middleware.py        app/features/admin/
# только для тестов
mv_ dev_reset.py                app/dev/
# документы
mv_ README_admin.md             docs/
mv_ plan.txt                    docs/
mv_ "Подробный_план_разработки_бота_знакомств_ВШЭ_НН.docx" docs/
# тесты
mv_ test_verification.py        tests/

echo "3/6 Удаляю устаревшее"
# delete2.py: старый прототип бота, в нём вписан токен, а к текущему коду он не подключён
[ -f delete2.py ] && { git rm -q -f delete2.py || rm -f delete2.py; }
# корневой __init__.py не нужен: корень репозитория не пакет
[ -f __init__.py ] && { git rm -q -f __init__.py || rm -f __init__.py; }

echo "4/6 Создаю пакеты (__init__.py)"
for d in app app/core app/dev app/features app/features/profile app/features/temp_profile \
         app/features/events app/features/verification app/features/admin tests; do
  [ -f "$d/__init__.py" ] || : > "$d/__init__.py"
done

echo "5/6 Исправляю импорты и путь к базе данных"
"$PY" - <<'PYEOF'
import re, pathlib

PKG = {
    "db": "app.core", "keyboards": "app.core",
    "handlers": "app.features.profile", "states": "app.features.profile",
    "temp_profile_db": "app.features.temp_profile", "temp_profile_handlers": "app.features.temp_profile",
    "temp_profile_states": "app.features.temp_profile",
    "events_db": "app.features.events", "events_handlers": "app.features.events",
    "events_states": "app.features.events",
    "verification_db": "app.features.verification", "verification_handlers": "app.features.verification",
    "verification_keyboards": "app.features.verification", "verification_service": "app.features.verification",
    "verification_states": "app.features.verification",
    "admin_db": "app.features.admin", "admin_handlers": "app.features.admin",
    "admin_keyboards": "app.features.admin", "admin_states": "app.features.admin",
    "ads": "app.features.admin", "report_handlers": "app.features.admin",
    "access_middleware": "app.features.admin",
    "dev_reset": "app.dev",
}
names = "|".join(sorted(PKG, key=len, reverse=True))
re_from = re.compile(rf"^(\s*)from ({names}) import ")
re_imp = re.compile(rf"^(\s*)import ({names})(?:\s+as\s+(\w+))?(\s*(?:#.*)?)$")
re_dyn = re.compile(rf'__import__\("({names})"\)')

files = [pathlib.Path("bot.py")] + sorted(pathlib.Path("app").rglob("*.py")) + sorted(pathlib.Path("tests").rglob("*.py"))
changed = 0
for path in files:
    if not path.exists():
        continue
    out = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        m = re_from.match(line)
        if m:
            line = f"{m.group(1)}from {PKG[m.group(2)]}.{m.group(2)} import " + line[m.end():]
        else:
            m = re_imp.match(line)
            if m:
                alias = f" as {m.group(3)}" if m.group(3) else ""
                line = f"{m.group(1)}from {PKG[m.group(2)]} import {m.group(2)}{alias}{m.group(4)}"
        line = re_dyn.sub(lambda k: f'__import__("{PKG[k.group(1)]}.{k.group(1)}", fromlist=["_"])', line)
        out.append(line)
    new = "\n".join(out)
    if new != path.read_text(encoding="utf-8"):
        path.write_text(new, encoding="utf-8")
        changed += 1
print(f"  обновлено файлов: {changed}")

# База данных по-прежнему лежит в КОРНЕ проекта (рядом с bot.py), а не внутри app/core
db = pathlib.Path("app/core/db.py")
text = db.read_text(encoding="utf-8")
old = "project_dir = Path(__file__).resolve().parent"
assert old in text, "не нашёл строку с путём к базе в db.py"
db.write_text(text.replace(old, "project_dir = Path(__file__).resolve().parents[2]  # корень репозитория"), encoding="utf-8")
print("  путь к базе данных: корень репозитория")

# Тест проверял «база рядом с db.py»; теперь ожидаем корень репозитория
t = pathlib.Path("tests/test_database.py")
if t.exists():
    tt = t.read_text(encoding="utf-8")
    old_t = 'expected = Path(db.__file__).resolve().parent / "alternate.db"'
    if old_t in tt:
        t.write_text(tt.replace(old_t, 'expected = Path(db.__file__).resolve().parents[2] / "alternate.db"'), encoding="utf-8")
        print("  тест пути к базе обновлён")
PYEOF

echo "6/6 Файл-образец настроек .env.example (без секретов)"
if [ ! -f .env.example ]; then
cat > .env.example <<'ENVEOF'
# Скопируйте в .env и заполните. Файл .env в git не попадает.
BOT_TOKEN=
# Администраторы и модераторы (через запятую)
ADMIN_USERNAMES=
ADMIN_IDS=
MODERATOR_USERNAMES=
MODERATOR_IDS=
# Прокси для Telegram, если нужен (например socks5://127.0.0.1:1080)
PROXY_URL=
LOG_LEVEL=INFO
# Подтверждение почты
EMAIL_HASH_SECRET=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
# Только для разработки: TEST_MODE=1 включает тестовые команды
TEST_MODE=
TEST_USER_IDS=
EMAIL_DEV_MODE=
ENVEOF
fi

# Мусор, который уже попал в репозиторий (в .gitignore он есть, но уже отслеживается).
# --cached: файлы остаются на диске, из git пропадают. dating_bot.db тоже остаётся у вас.
git rm -r -q --cached --ignore-unmatch .DS_Store __pycache__ tests/__pycache__ .idea dating_bot.db >/dev/null 2>&1 || true

git add -A . >/dev/null 2>&1 || true

echo
echo "Проверка: компиляция, тесты, запуск сборки диспетчера"
"$PY" -m compileall -q app bot.py tests && echo "  синтаксис: ОК"
"$PY" -m unittest discover -s tests -t . 2>&1 | tail -3 || echo "  ВНИМАНИЕ: тесты не прошли"
BOT_TOKEN=1:TEST "$PY" -c "import bot; bot.build_dispatcher(); print('  бот собирается: ОК')" \
  || echo "  ВНИМАНИЕ: бот не собирается (проверьте, что активирован .venv)"

echo
echo "Готово. Посмотрите git status, затем:"
echo "  git commit -m 'Реорганизация: структура папок app/, docs/, tests/'"
