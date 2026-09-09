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
NC='\033[0m'

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[OK]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_header() { echo ""; echo "============================================================"; echo " $1"; echo "============================================================"; echo ""; }

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

print_info "Обновление пакетов..."
apt-get update -qq

print_info "Установка необходимых пакетов..."
apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    wget \
    curl \
    unzip \
    sqlite3 \
    jq \
    > /dev/null 2>&1

print_info "Установка Python модулей..."
pip3 install requests pysocks --break-system-packages > /dev/null 2>&1

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
    print_warning "Или установите вручную и настройте outbound'ы:"
    echo "  vless_1, vless_2, ... vless_10"
    echo ""
    read -p "Продолжить установку? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    print_success "3x-ui найден"
fi

# ============================================================
# УСТАНОВКА VLESS CHECKER (Alpha)
# ============================================================
print_header "УСТАНОВКА VLESS CHECKER (Alpha)"

CHECKER_DIR="/root/vless_checker"
GITHUB_RAW="https://raw.githubusercontent.com/PsoyNe/vless_cascade/refs/heads/main"

if [ -d "$CHECKER_DIR" ]; then
    print_warning "Директория $CHECKER_DIR уже существует"
    read -p "Перезаписать файлы? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Установка чекера пропущена"
    else
        rm -rf "$CHECKER_DIR"
        mkdir -p "$CHECKER_DIR"
        cd "$CHECKER_DIR"
        
        # Скачиваем файлы чекера
        for file in vless_check_config.py vless_checker.py server_tester.py full_check.py run_stage1.sh run_stage2.sh run_full_check.sh; do
            print_info "Скачивание: $file"
            wget -q "$GITHUB_RAW/$file" -O "$file"
        done
        
        chmod +x *.py *.sh 2>/dev/null
        print_success "VLESS Checker установлен"
    fi
else
    mkdir -p "$CHECKER_DIR"
    cd "$CHECKER_DIR"
    
    for file in vless_check_config.py vless_checker.py server_tester.py full_check.py run_stage1.sh run_stage2.sh run_full_check.sh; do
        print_info "Скачивание: $file"
        wget -q "$GITHUB_RAW/$file" -O "$file"
    done
    
    chmod +x *.py *.sh 2>/dev/null
    print_success "VLESS Checker установлен"
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
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Установка обсерватории пропущена"
    else
        rm -rf "$OBSERVER_DIR"
        mkdir -p "$OBSERVER_DIR"
        cd "$OBSERVER_DIR"
        
        wget -q "$GITHUB_RAW/observer_config.py" -O observer_config.py
        wget -q "$GITHUB_RAW/observer.py" -O observer.py
        
        chmod +x observer.py
        print_success "VLESS Observer установлен"
    fi
else
    mkdir -p "$OBSERVER_DIR"
    cd "$OBSERVER_DIR"
    
    wget -q "$GITHUB_RAW/observer_config.py" -O observer_config.py
    wget -q "$GITHUB_RAW/observer.py" -O observer.py
    
    chmod +x observer.py
    print_success "VLESS Observer установлен"
fi

# ============================================================
# НАСТРОЙКА CRON ДЛЯ ЧЕКЕРА
# ============================================================
print_header "НАСТРОЙКА CRON ДЛЯ ЧЕКЕРА"

CRON_JOB_CHECKER="0 2 * * * /root/vless_checker/run_full_check.sh"

if crontab -l 2>/dev/null | grep -q "vless_checker"; then
    print_warning "Cron задание для чекера уже существует"
    read -p "Перезаписать? (y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        (crontab -l 2>/dev/null | grep -v "vless_checker"; echo "$CRON_JOB_CHECKER") | crontab -
        print_success "Cron задание для чекера обновлено"
    fi
else
    (crontab -l 2>/dev/null; echo "$CRON_JOB_CHECKER") | crontab -
    print_success "Cron задание для чекера добавлено"
fi

# ============================================================
# НАСТРОЙКА СИСТЕМНОЙ СЛУЖБЫ ДЛЯ OBSERVER
# ============================================================
print_header "НАСТРОЙКА СЛУЖБЫ OBSERVER"

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
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=10
StandardOutput=append:/var/log/vless_observer.log
StandardError=append:/var/log/vless_observer.log
PIDFile=/var/run/vless_observer.pid

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vless_observer
systemctl start vless_observer

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
    print_warning "Некоторые модули отсутствуют"
fi

# ============================================================
# ИТОГ
# ============================================================
print_header "УСТАНОВКА ЗАВЕРШЕНА"

echo "📁 VLESS Checker: /root/vless_checker/"
echo "📁 VLESS Observer: /root/vless_observer/"
echo ""
echo "⏰ Cron задание:"
crontab -l | grep vless_checker || echo "  Не найдено"
echo ""
echo "🔄 Служба Observer:"
systemctl status vless_observer --no-pager
echo ""
echo "🚀 Запуск вручную:"
echo "  VLESS Checker: cd /root/vless_checker && python3 full_check.py"
echo "  VLESS Observer: systemctl start vless_observer"
echo ""
echo "📊 Логи:"
echo "  tail -f /var/log/vless_full.log"
echo "  tail -f /var/log/vless_observer.log"
echo ""
echo "🔧 Триггер Observer (имитация отказа):"
echo "  touch /tmp/vless_observer_trigger"
echo ""

print_success "✅ Готово!"
