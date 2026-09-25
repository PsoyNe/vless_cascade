#!/usr/bin/env bash
# ============================================================
# УСТАНОВКА VLESS BOT
# ============================================================
#
# Ставит Telegram-бота vless_bot как отдельную systemd-службу
# vless_bot.service. Observer НЕ трогает.
#
# Файлы бота качаются с GitHub:
#   https://raw.githubusercontent.com/PsoyNe/vless_cascade/refs/heads/main/
#
# Что делает:
#   1. Проверяет root.
#   2. Проверяет наличие curl/wget.
#   3. Создаёт /root/vless_bot/.
#   4. Качает файлы бота с GitHub.
#   5. Спрашивает токен бота и chat_id.
#   6. Подставляет их в vless_bot_config.py.
#   7. Создаёт venv, ставит aiogram, aiohttp-socks, psutil.
#   8. Создаёт /etc/systemd/system/vless_bot.service.
#   9. Запускает и включает службу.
#
# Запуск:
#   bash install_bot.sh
#
# Повторный запуск — обновит файлы с GitHub и перезапустит службу.
# ============================================================

set -euo pipefail

# -------------------- ЦВЕТА --------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[install]${NC} $*"; }
ok()   { echo -e "${GREEN}[ ok ]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[err ]${NC} $*" >&2; }

# -------------------- КОНСТАНТЫ --------------------
GITHUB_BASE="https://raw.githubusercontent.com/PsoyNe/vless_cascade/refs/heads/main"

BOT_DIR="/root/vless_bot"
VENV_DIR="${BOT_DIR}/venv"
CONFIG_DEST="${BOT_DIR}/vless_bot_config.py"
SERVICE_FILE="/etc/systemd/system/vless_bot.service"
LOG_FILE="/var/log/vless_bot.log"

# Файлы бота, которые качаем с GitHub.
# Порядок: сначала конфиг (потом его патчим), потом остальное.
BOT_FILES=(
    "vless_bot_config.py"
    "vless_bot.py"
    "bot_observer_client.py"
    "bot_handlers.py"
    "bot_formatters.py"
    "bot_keyboards.py"
)

# -------------------- ПРОВЕРКИ --------------------
if [[ $EUID -ne 0 ]]; then
    err "Скрипт надо запускать от root (sudo bash install_bot.sh)"
    exit 1
fi

# Определяем, чем качать. Предпочитаем curl, fallback — wget.
DOWNLOADER=""
if command -v curl >/dev/null 2>&1; then
    DOWNLOADER="curl"
elif command -v wget >/dev/null 2>&1; then
    DOWNLOADER="wget"
else
    err "Не найден ни curl, ни wget. Установи: apt install curl"
    exit 1
fi
log "Скачивание через: ${DOWNLOADER}"

# -------------------- ПРОВЕРКА PYTHON --------------------
log "Проверяю Python 3..."
if ! command -v python3 >/dev/null 2>&1; then
    err "python3 не найден. Установи: apt install python3 python3-venv python3-pip"
    exit 1
fi
PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
log "Найден Python ${PY_VER}"

if ! python3 -c 'import venv' >/dev/null 2>&1; then
    err "Модуль venv недоступен. Установи: apt install python3-venv"
    exit 1
fi

# -------------------- ВВОД ТОКЕНА И CHAT_ID --------------------
echo
echo "============================================================"
echo "  Настройка бота"
echo "============================================================"
echo
echo "Понадобится:"
echo "  1. Токен бота — получить у @BotFather в Telegram."
echo "  2. Твой chat_id — узнать у @userinfobot в Telegram."
echo

# Токен
while true; do
    read -r -p "Введи токен бота (формат 123456:ABC-DEF...): " BOT_TOKEN
    if [[ -z "${BOT_TOKEN}" ]]; then
        warn "Токен не может быть пустым."
        continue
    fi
    if [[ ! "${BOT_TOKEN}" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
        warn "Токен не похож на настоящий. Уверен? (Enter — да, Ctrl+C — прервать)"
        read -r _
    fi
    break
done

# Chat ID
while true; do
    read -r -p "Введи твой chat_id (число, можно отрицательное): " BOT_CHAT_ID
    if [[ -z "${BOT_CHAT_ID}" ]]; then
        warn "chat_id не может быть пустым."
        continue
    fi
    if [[ ! "${BOT_CHAT_ID}" =~ ^-?[0-9]+$ ]]; then
        warn "chat_id должен быть числом."
        continue
    fi
    break
done

# -------------------- СОЗДАНИЕ ДИРЕКТОРИЙ --------------------
log "Создаю директории..."
mkdir -p "${BOT_DIR}"
ok "Создано: ${BOT_DIR}"

# -------------------- СКАЧИВАНИЕ ФАЙЛОВ --------------------
log "Качаю файлы бота с GitHub (${GITHUB_BASE})..."

download_file() {
    local filename="$1"
    local url="${GITHUB_BASE}/${filename}"
    local dest="${BOT_DIR}/${filename}"
    local tmp="${dest}.tmp"

    if [[ "${DOWNLOADER}" == "curl" ]]; then
        if ! curl -fsSL --connect-timeout 15 -o "${tmp}" "${url}"; then
            err "Не удалось скачать ${url}"
            rm -f "${tmp}"
            return 1
        fi
    else
        if ! wget -q --timeout=15 -O "${tmp}" "${url}"; then
            err "Не удалось скачать ${url}"
            rm -f "${tmp}"
            return 1
        fi
    fi

    if [[ ! -s "${tmp}" ]]; then
        err "Скачался пустой файл: ${filename}"
        rm -f "${tmp}"
        return 1
    fi

    local head_bytes
    head_bytes="$(head -c 100 "${tmp}" | tr -d '\n\r' | tr '[:upper:]' '[:lower:]')"
    if [[ "${head_bytes}" == "<!doctype"* ]] || [[ "${head_bytes}" == "<html"* ]]; then
        err "Вместо ${filename} скачалась HTML-страница (404?). Проверь URL."
        rm -f "${tmp}"
        return 1
    fi

    mv -f "${tmp}" "${dest}"
    ok "  ↓ ${filename}"
    return 0
}

for f in "${BOT_FILES[@]}"; do
    download_file "${f}"
done

ok "Все файлы скачаны в ${BOT_DIR}."

# -------------------- ПОДСТАНОВКА ТОКЕНА И CHAT_ID --------------------
log "Подставляю токен и chat_id в конфиг..."

python3 - "${CONFIG_DEST}" "${BOT_TOKEN}" "${BOT_CHAT_ID}" <<'PYEOF'
import sys
import re

config_path, token, chat_id = sys.argv[1], sys.argv[2], sys.argv[3]

with open(config_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Заменяем значение токена
content = re.sub(
    r'^(TELEGRAM_BOT_TOKEN\s*=\s*).*$',
    lambda m: f'{m.group(1)}"{token}"',
    content,
    flags=re.MULTILINE,
)

# Заменяем chat_id (число, без кавычек)
content = re.sub(
    r'^(TELEGRAM_CHAT_ID\s*=\s*).*$',
    lambda m: f'{m.group(1)}{chat_id}',
    content,
    flags=re.MULTILINE,
)

with open(config_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("config updated")
PYEOF

ok "Токен и chat_id подставлены в ${CONFIG_DEST}."

# -------------------- VENV И ЗАВИСИМОСТИ --------------------
log "Создаю виртуальное окружение..."
if [[ ! -d "${VENV_DIR}" ]]; then
    python3 -m venv "${VENV_DIR}"
fi
ok "venv: ${VENV_DIR}"

log "Обновляю pip и ставлю зависимости (aiogram, aiohttp-socks, psutil)..."
"${VENV_DIR}/bin/pip" install --upgrade pip >/dev/null
"${VENV_DIR}/bin/pip" install --upgrade "aiogram>=3.0,<4.0" "aiohttp-socks>=0.8" "psutil>=5.9" >/dev/null
ok "Зависимости установлены."

"${VENV_DIR}/bin/pip" show aiogram aiohttp-socks psutil | grep -E '^(Name|Version):'

# -------------------- ЛОГ-ФАЙЛ --------------------
log "Готовлю лог-файл ${LOG_FILE}..."
touch "${LOG_FILE}"
chmod 640 "${LOG_FILE}"
ok "Лог-файл готов."

# -------------------- SYSTEMD UNIT --------------------
log "Создаю systemd-юнит ${SERVICE_FILE}..."

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=VLESS Bot - Telegram control for VLESS Observer
After=network-online.target vless_observer.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${BOT_DIR}
ExecStart=${VENV_DIR}/bin/python ${BOT_DIR}/vless_bot.py
Restart=on-failure
RestartSec=10
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF

ok "Юнит создан."

# -------------------- ЗАПУСК СЛУЖБЫ --------------------
log "Перезагружаю systemd и запускаю службу..."
systemctl daemon-reload
systemctl enable vless_bot.service >/dev/null
systemctl restart vless_bot.service

sleep 2

# -------------------- СТАТУС --------------------
echo
if systemctl is-active --quiet vless_bot.service; then
    ok "Служба vless_bot запущена."
    echo
    echo "Проверь статус:"
    echo "  systemctl status vless_bot.service"
    echo
    echo "Смотри лог:"
    echo "  tail -f ${LOG_FILE}"
    echo "  journalctl -u vless_bot.service -f"
    echo
    echo "Отправь боту в Telegram /start или /help."
else
    err "Служба не запустилась. Смотри лог:"
    echo "  journalctl -u vless_bot.service -n 50 --no-pager"
    echo "  tail -n 50 ${LOG_FILE}"
    exit 1
fi

echo
ok "Установка завершена."
