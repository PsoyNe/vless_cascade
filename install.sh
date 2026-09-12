#!/bin/bash
# ============================================================
# VLESS CHECKER + OBSERVER INSTALLER
# Установка системы автоматического обновления outbound'ов 3x-ui
# ============================================================

set -e

# ============================================================
# ЦВЕТА ДЛЯ ВЫВОДА
# ============================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[OK]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_header()  { echo ""; echo "============================================================"; echo " $1"; echo "============================================================"; echo ""; }

# ============================================================
# ПРОГРЕСС-БАР
# ============================================================
# Использование:
#   progress_bar_init "Скачивание" 12
#   progress_bar_step "vless_checker.py"
#   ...
#   progress_bar_finish

PROGRESS_TOTAL=0
PROGRESS_CURRENT=0
PROGRESS_LABEL=""
PROGRESS_WIDTH=30

progress_bar_init() {
    PROGRESS_LABEL="$1"
    PROGRESS_TOTAL="$2"
    PROGRESS_CURRENT=0
}

progress_bar_step() {
    PROGRESS_CURRENT=$((PROGRESS_CURRENT + 1))
    if [ "$PROGRESS_TOTAL" -le 0 ]; then
        return
    fi

    local percent=$((PROGRESS_CURRENT * 100 / PROGRESS_TOTAL))
    local filled=$((PROGRESS_CURRENT * PROGRESS_WIDTH / PROGRESS_TOTAL))
    local empty=$((PROGRESS_WIDTH - filled))

    local bar=""
    for ((i=0; i<filled; i++)); do bar="${bar}█"; done
    for ((i=0; i<empty; i++)); do bar="${bar}░"; done

    local item="${1:-}"
    # Обрезаем item до 40 символов, чтобы не ломать строку
    if [ ${#item} -gt 40 ]; then
        item="${item:0:37}..."
    fi

    printf "\r${CYAN}%s${NC} [%s] %3d%% %-40s" \
        "$PROGRESS_LABEL" "$bar" "$percent" "$item"
}

progress_bar_finish() {
    if [ "$PROGRESS_TOTAL" -le 0 ]; then
        echo ""
        return
    fi
    local bar=""
    for ((i=0; i<PROGRESS_WIDTH; i++)); do bar="${bar}█"; done
    printf "\r${GREEN}%s${NC} [%s] 100%% %-40s\n" \
        "$PROGRESS_LABEL" "$bar" "Готово"
}

# Анимированный прогресс для операций без известного количества шагов
# Использование:
#   animate_start "Установка пакетов"
#   <долгая операция>
#   animate_stop
ANIMATE_PID=""

animate_start() {
    local label="$1"
    (
        local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
        local i=0
        while true; do
            i=$(( (i+1) % ${#spin} ))
            printf "\r${CYAN}%s${NC} %s" "$label" "${spin:$i:1}"
            sleep 0.1
        done
    ) &
    ANIMATE_PID=$!
}

animate_stop() {
    if [ -n "$ANIMATE_PID" ]; then
        kill "$ANIMATE_PID" 2>/dev/null || true
        wait "$ANIMATE_PID" 2>/dev/null || true
        printf "\r\033[K"   # очищаем строку
        ANIMATE_PID=""
    fi
}

# Гарантированная очистка анимации при выходе
trap 'animate_stop' EXIT

# ============================================================
# ПРОВЕРКА ПРАВ
# ============================================================
if [ "$EUID" -ne 0 ]; then
    print_error "Запустите скрипт с правами root: sudo bash install.sh"
    exit 1
fi

# ============================================================
# ПРОВЕРКА СИСТЕМЫ
# ============================================================
print_header "ПРОВЕРКА СИСТЕМЫ"

ARCH=$(uname -m)
print_info "Архитектура: $ARCH"

if [[ "$ARCH" != "armv7l" && "$ARCH" != "aarch64" ]]; then
    print_warning "Архитектура не ARM. Скрипт оптимизирован для NanoPi Neo."
fi

# ============================================================
# УСТАНОВКА ЗАВИСИМОСТЕЙ
# ============================================================
print_header "УСТАНОВКА ЗАВИСИМОСТЕЙ"

print_info "Обновление пакетов (apt-get update)..."
animate_start "apt-get update"
apt-get update -qq > /dev/null 2>&1
animate_stop
print_success "Списки пакетов обновлены"

print_info "Установка необходимых пакетов..."
PACKAGES="python3 python3-pip python3-venv wget curl unzip sqlite3 jq"
progress_bar_init "Пакеты" 8

for pkg in $PACKAGES; do
    progress_bar_step "$pkg"
    apt-get install -y -qq "$pkg" > /dev/null 2>&1 || true
done
progress_bar_finish

print_info "Установка Python-модулей (requests, pysocks)..."
animate_start "pip3 install"
pip3 install requests pysocks --break-system-packages > /dev/null 2>&1
animate_stop
print_success "Зависимости установлены"

# ============================================================
# ПРОВЕРКА 3X-UI
# ============================================================
print_header "ПРОВЕРКА 3X-UI"

if ! command -v x-ui &> /dev/null; then
    print_warning "3x-ui не найден. Установите 3x-ui перед запуском:"
    echo ""
    echo "  bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)"
    echo ""
    print_warning "После установки создайте в панели исходящее соединение с тегом vless_obs,"
    print_warning "а затем запустите install.sh заново."
    echo ""
    read -p "Продолжить установку? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    print_success "3x-ui найден"

    if systemctl is-active --quiet x-ui; then
        print_success "Служба x-ui работает"
    else
        print_warning "Служба x-ui не запущена. Запустите: systemctl start x-ui"
    fi
fi

# ============================================================
# СКАЧИВАНИЕ ФАЙЛОВ ИЗ GITHUB
# ============================================================
GITHUB_RAW="https://raw.githubusercontent.com/PsoyNe/vless_cascade/refs/heads/main"

download_file() {
    local url="$1"
    local dest="$2"
    local name="$3"

    if ! wget -q "$url" -O "$dest" 2>/dev/null; then
        print_error "Не удалось скачать: $name"
        return 1
    fi
    if [ ! -s "$dest" ]; then
        print_error "Файл пустой: $name (возможно, не существует в репозитории)"
        rm -f "$dest"
        return 1
    fi
    return 0
}

# ============================================================
# УСТАНОВКА VLESS CHECKER (Этап 1)
# ============================================================
print_header "УСТАНОВКА VLESS CHECKER (Этап 1)"

CHECKER_DIR="/root/vless_checker"

if [ -d "$CHECKER_DIR" ]; then
    print_warning "Директория $CHECKER_DIR уже существует"
    read -p "Перезаписать файлы? (y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$CHECKER_DIR"
    else
        print_info "Установка чекера пропущена"
        CHECKER_SKIP=1
    fi
fi

if [ -z "$CHECKER_SKIP" ]; then
    mkdir -p "$CHECKER_DIR"

    # Основные файлы этапа 1 + скрипты
    CHECKER_FILES="vless_check_config.py vless_checker.py server_tester.py run_stage1.sh run_stage2.sh run_full_check.sh"

    # Считаем количество для прогресса
    NUM_CHECKER_FILES=$(echo "$CHECKER_FILES" | wc -w)
    progress_bar_init "Checker" "$NUM_CHECKER_FILES"

    for file in $CHECKER_FILES; do
        download_file "$GITHUB_RAW/$file" "$CHECKER_DIR/$file" "$file" || true
        progress_bar_step "$file"
    done
    progress_bar_finish

    # Создаём пустые файлы данных, чтобы observer не падал при старте
    touch "$CHECKER_DIR/working_links.txt"
    touch "$CHECKER_DIR/stable_links.txt"
    touch "$CHECKER_DIR/quarantine_links.txt"

    chmod +x "$CHECKER_DIR"/*.py "$CHECKER_DIR"/*.sh 2>/dev/null || true
    print_success "VLESS Checker установлен в $CHECKER_DIR"
fi

# ============================================================
# УСТАНОВКА VLESS OBSERVER
# ============================================================
print_header "УСТАНОВКА VLESS OBSERVER"

OBSERVER_DIR="/root/vless_observer"

if [ -d "$OBSERVER_DIR" ]; then
    print_warning "Директория $OBSERVER_DIR уже существует"
    read -p "Перезаписать файлы? (y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$OBSERVER_DIR"
    else
        print_info "Установка обсерватории пропущена"
        OBSERVER_SKIP=1
    fi
fi

if [ -z "$OBSERVER_SKIP" ]; then
    mkdir -p "$OBSERVER_DIR"

    OBSERVER_FILES="observer_config.py observer.py show_logs.sh run_observer.sh"
    NUM_OBSERVER_FILES=$(echo "$OBSERVER_FILES" | wc -w)
    progress_bar_init "Observer" "$NUM_OBSERVER_FILES"

    for file in $OBSERVER_FILES; do
        download_file "$GITHUB_RAW/$file" "$OBSERVER_DIR/$file" "$file" || true
        progress_bar_step "$file"
    done
    progress_bar_finish

    chmod +x "$OBSERVER_DIR"/*.py "$OBSERVER_DIR"/*.sh 2>/dev/null || true
    print_success "VLESS Observer установлен в $OBSERVER_DIR"
fi

# ============================================================
# НАСТРОЙКА CRON ДЛЯ ЧЕКЕРА
# ============================================================
print_header "НАСТРОЙКА CRON ДЛЯ ЧЕКЕРА"

# Этап 1 запускается 4 раза в сутки: 01:00, 07:00, 13:00, 19:00
CRON_JOB='0 1,7,13,19 * * * /usr/bin/python3 /root/vless_checker/vless_checker.py >> /var/log/vless_checker_cron.log 2>&1'

if crontab -l 2>/dev/null | grep -q "vless_checker"; then
    print_warning "Cron задание для чекера уже существует"
    read -p "Перезаписать? (y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        (crontab -l 2>/dev/null | grep -v "vless_checker"; echo "$CRON_JOB") | crontab -
        print_success "Cron задание для чекера обновлено"
    fi
else
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    print_success "Cron задание для чекера добавлено (01:00, 07:00, 13:00, 19:00)"
fi

# ============================================================
# НАСТРОЙКА СИСТЕМНОЙ СЛУЖБЫ ДЛЯ OBSERVER
# ============================================================
print_header "НАСТРОЙКА СЛУЖБЫ OBSERVER"

print_info "Создание systemd-юнита..."
cat > /etc/systemd/system/vless_observer.service << 'EOF'
[Unit]
Description=VLESS Observer - automatic outbound monitoring and switching
After=network.target x-ui.service
Wants=x-ui.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/vless_observer
ExecStart=/usr/bin/python3 /root/vless_observer/observer.py

# Graceful shutdown через SIGTERM (обрабатывается в observer.py)
KillSignal=SIGTERM
TimeoutStopSec=30

Restart=always
RestartSec=10

# Логи пишет сам Python через TimedRotatingFileHandler.
# systemd не должен дублировать их в тот же файл.
StandardOutput=null
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
print_success "Юнит создан"

print_info "Активация и запуск службы..."
animate_start "systemctl daemon-reload"
systemctl daemon-reload
animate_stop

animate_start "systemctl enable"
systemctl enable vless_observer > /dev/null 2>&1
animate_stop

animate_start "systemctl start"
systemctl start vless_observer
animate_stop

print_success "Служба Observer запущена"

# ============================================================
# ПРОВЕРКА УСТАНОВКИ
# ============================================================
print_header "ПРОВЕРКА УСТАНОВКИ"

print_info "Проверка конфига чекера..."
if python3 -c "import sys; sys.path.insert(0, '/root/vless_checker'); import vless_check_config" 2>/dev/null; then
    print_success "Конфиг чекера корректен"
else
    print_warning "Ошибка импорта конфига чекера"
fi

print_info "Проверка конфига обсерватории..."
if python3 -c "import sys; sys.path.insert(0, '/root/vless_observer'); import observer_config" 2>/dev/null; then
    print_success "Конфиг обсерватории корректен"
else
    print_warning "Ошибка импорта конфига обсерватории"
fi

print_info "Проверка Python модулей..."
if python3 -c "import requests, socks, ssl, sqlite3" 2>/dev/null; then
    print_success "Все модули установлены"
else
    print_warning "Некоторые модули отсутствуют. Установите: pip3 install requests pysocks"
fi

print_info "Проверка Xray..."
if [ -f /usr/local/x-ui/bin/xray-linux-arm32 ]; then
    print_success "Xray найден: /usr/local/x-ui/bin/xray-linux-arm32"
else
    print_warning "Xray не найден по пути /usr/local/x-ui/bin/xray-linux-arm32"
    print_warning "Проверьте путь в vless_check_config.py и observer_config.py (XRAY_PATH)"
fi

# ============================================================
# ИТОГ
# ============================================================
print_header "УСТАНОВКА ЗАВЕРШЕНА"

echo "📁 VLESS Checker:  /root/vless_checker/"
echo "📁 VLESS Observer: /root/vless_observer/"
echo ""
echo "⏰ Cron задание (этап 1, 4 раза в сутки):"
crontab -l | grep vless_checker || echo "  Не найдено"
echo ""
echo "🔄 Служба Observer:"
systemctl status vless_observer --no-pager | head -15
echo ""
echo "🚀 Запуск вручную:"
echo "  Этап 1 (сбор 30 ссылок):"
echo "    cd /root/vless_checker && nohup python3 vless_checker.py > /dev/null 2>&1 &"
echo "    tail -f /var/log/vless_checker.log"
echo ""
echo "  Observer:"
echo "    systemctl start vless_observer"
echo "    tail -f /var/log/vless_observer.log"
echo ""
echo "📊 Логи:"
echo "  tail -f /var/log/vless_checker.log      # этап 1"
echo "  tail -f /var/log/vless_observer.log     # observer"
echo "  tail -f /var/log/vless_checker_cron.log # запуск из cron (обёртка)"
echo ""
echo "🔧 Триггеры Observer:"
echo "  touch /tmp/vless_observer_trigger    # имитация отказа"
echo "  touch /tmp/vless_quarantine_trigger  # отправить основную в карантин"
echo "  touch /tmp/vless_deep_check_trigger  # глубокая проверка"
echo ""
echo "📋 Просмотр логов через меню:"
echo "  bash /root/vless_observer/show_logs.sh"
echo ""

print_warning "ВАЖНО: Первый запуск этапа 1 соберёт 30 ссылок в working_links.txt."
print_warning "Observer без файла будет ждать — это нормально."
print_warning "Запустите этап 1 вручную или дождитесь cron (01:00, 07:00, 13:00, 19:00)."
echo ""

print_success "✅ Готово!"
