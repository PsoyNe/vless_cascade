#!/bin/bash
# ============================================================
# VLESS CHECKER INSTALLER
# ============================================================
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

# ============================================================
# ПЕРЕМЕННЫЕ
# ============================================================
INSTALL_DIR="/root/vless_checker"
GITHUB_RAW="https://raw.githubusercontent.com/PsoyNe/vless_cascade/refs/heads/main"
LOG_DIR="/var/log"

# Список файлов для скачивания
FILES=(
    "vless_check_config.py"
    "vless_checker.py"
    "server_tester.py"
    "update_db.py"
    "full_check.py"
    "run_stage1.sh"
    "run_stage2.sh"
    "run_full_check.sh"
)

# ============================================================
# ФУНКЦИИ
# ============================================================
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_header() {
    echo ""
    echo "============================================================"
    echo " $1"
    echo "============================================================"
    echo ""
}

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

# Проверка архитектуры
ARCH=$(uname -m)
print_info "Архитектура: $ARCH"

if [[ "$ARCH" != "armv7l" && "$ARCH" != "aarch64" ]]; then
    print_warning "Архитектура не ARM. Скрипт оптимизирован для NanoPi Neo."
fi

# Проверка ОС
if command -v lsb_release &> /dev/null; then
    OS=$(lsb_release -is 2>/dev/null || echo "Unknown")
else
    OS="Unknown"
fi

if [[ "$OS" != "Debian" && "$OS" != "Ubuntu" ]]; then
    print_warning "ОС: $OS. Рекомендуется Debian/Ubuntu."
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

# Проверка Xray
if [ ! -f "/usr/local/x-ui/bin/xray-linux-arm32" ]; then
    print_warning "Xray не найден по пути /usr/local/x-ui/bin/xray-linux-arm32"
    print_info "Попробуйте найти Xray: find / -name 'xray*' -type f 2>/dev/null"
    print_info "Измените путь XRAY_PATH в vless_check_config.py"
fi

# ============================================================
# СОЗДАНИЕ ДИРЕКТОРИИ
# ============================================================
print_header "СОЗДАНИЕ ДИРЕКТОРИИ"

if [ -d "$INSTALL_DIR" ]; then
    print_warning "Директория $INSTALL_DIR уже существует"
    read -p "Перезаписать файлы? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Установка отменена"
        exit 0
    fi
    rm -rf "$INSTALL_DIR"
fi

mkdir -p "$INSTALL_DIR"
print_success "Директория создана: $INSTALL_DIR"

# ============================================================
# СКАЧИВАНИЕ ФАЙЛОВ
# ============================================================
print_header "СКАЧИВАНИЕ ФАЙЛОВ"

cd "$INSTALL_DIR"

for file in "${FILES[@]}"; do
    print_info "Скачивание: $file"
    if wget -q "$GITHUB_RAW/$file" -O "$file"; then
        print_success "  $file"
    else
        print_error "  Не удалось скачать $file"
        exit 1
    fi
done

# Делаем скрипты исполняемыми
chmod +x *.py 2>/dev/null
chmod +x *.sh 2>/dev/null

print_success "Все файлы скачаны и готовы к использованию"

# ============================================================
# ПРОВЕРКА УСТАНОВКИ
# ============================================================
print_header "ПРОВЕРКА УСТАНОВКИ"

print_info "Проверка конфига..."
if python3 -c "import vless_check_config" 2>/dev/null; then
    print_success "Конфиг корректен"
else
    print_warning "Ошибка импорта конфига"
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

echo "📁 Директория: $INSTALL_DIR"
echo ""
echo "📋 Структура:"
ls -la "$INSTALL_DIR"
echo ""
echo "🚀 Запуск вручную:"
echo "  cd $INSTALL_DIR && nohup python3 full_check.py >> /var/log/vless_full.log 2>&1 &"
echo ""
echo "📊 Логи:"
echo "  tail -f /var/log/vless_full.log"
echo ""
echo "⏰ Добавьте задание в cron (ежедневно в 2:00):"
echo "  crontab -e"
echo "  Добавьте строку:"
echo "  0 2 * * * /root/vless_checker/run_full_check.sh"
echo ""
echo "✅ Готово!"

exit 0
