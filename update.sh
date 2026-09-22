#!/bin/bash
# ============================================================
# VLESS CASCADE UPDATER
# Обновление установленной системы до последней версии с GitHub
# ============================================================
#
# Использование:
#   bash update.sh              — проверить и обновить (с подтверждением)
#   bash update.sh --check      — только проверить, есть ли обновление
#   bash update.sh --auto       — обновить без вопросов (merge конфигов пропускается)
#   bash update.sh --rollback   — откатиться из последнего бэкапа
#   bash update.sh --help       — справка
#
# ============================================================

set -e

# ============================================================
# НАСТРОЙКИ
# ============================================================
GITHUB_RAW="https://raw.githubusercontent.com/PsoyNe/vless_cascade/refs/heads/main"
GITHUB_BASE="https://github.com/PsoyNe/vless_cascade"

VERSION_FILE_LOCAL="/root/.vless_cascade_version"
VERSION_FILE_REMOTE="$GITHUB_RAW/VERSION"
CHANGELOG_REMOTE="$GITHUB_RAW/CHANGELOG.md"

CHECKER_DIR="/root/vless_checker"
OBSERVER_DIR="/root/vless_observer"
SERVICE_FILE="/etc/systemd/system/vless_observer.service"
BACKUP_DIR_BASE="/root"
BACKUP_KEEP=5

UPDATE_SCRIPT_PATH="/root/update.sh"
MERGE_SCRIPT_PATH="/root/merge_config.py"

# Файлы, которые обновляются как обычно (замена)
CHECKER_FILES="vless_checker.py server_tester.py run_stage1.sh run_stage2.sh run_full_check.sh"
OBSERVER_FILES="vless_common.py triggers.py observer.py show_logs.sh run_observer.sh"

# Файлы-конфиги, которые обновляются через merge_config.py
CHECKER_CONFIG_FILES="vless_check_config.py"
OBSERVER_CONFIG_FILES="observer_config.py"

# ============================================================
# ЦВЕТА
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
# АНИМАЦИЯ (спиннер)
# ============================================================
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
        printf "\r\033[K"
        ANIMATE_PID=""
    fi
}

trap 'animate_stop' EXIT

# ============================================================
# СПРАВКА
# ============================================================
show_help() {
    cat << EOF
VLESS CASCADE UPDATER

Использование:
  bash update.sh              Проверить и обновить (с подтверждением)
  bash update.sh --check      Только проверить наличие обновления
  bash update.sh --auto       Обновить без вопросов (merge конфигов пропускается)
  bash update.sh --rollback   Откатиться из последнего бэкапа
  bash update.sh --help       Показать эту справку

Файлы:
  VERSION (GitHub):           $VERSION_FILE_REMOTE
  VERSION (локально):         $VERSION_FILE_LOCAL
  Бэкапы:                     ${BACKUP_DIR_BASE}/vless_backup_*

EOF
}

# ============================================================
# РАЗБОР АРГУМЕНТОВ
# ============================================================
MODE="normal"

case "$1" in
    --check)    MODE="check" ;;
    --auto)     MODE="auto" ;;
    --rollback) MODE="rollback" ;;
    --help|-h)  show_help; exit 0 ;;
    "")         MODE="normal" ;;
    *)
        print_error "Неизвестный аргумент: $1"
        show_help
        exit 1
        ;;
esac

# ============================================================
# ПРОВЕРКА ПРАВ
# ============================================================
if [ "$EUID" -ne 0 ]; then
    print_error "Запустите скрипт с правами root: sudo bash update.sh"
    exit 1
fi

# ============================================================
# ФУНКЦИЯ: СКАЧАТЬ ФАЙЛ
# ============================================================
download_file() {
    local url="$1"
    local dest="$2"
    local name="$3"

    if ! wget -q --timeout=10 "$url" -O "$dest" 2>/dev/null; then
        print_error "Не удалось скачать: $name"
        return 1
    fi
    if [ ! -s "$dest" ]; then
        print_error "Файл пустой: $name"
        rm -f "$dest"
        return 1
    fi
    return 0
}

# ============================================================
# ФУНКЦИЯ: ПРОВЕРИТЬ SHEBANG
# ============================================================
check_shebang() {
    local file="$1"
    local first_line
    first_line=$(head -n 1 "$file")

    case "$file" in
        *.py)
            if [[ "$first_line" != "#!/usr/bin/env python3"* ]]; then
                print_error "Неверный shebang в $file: $first_line"
                return 1
            fi
            ;;
        *.sh)
            if [[ "$first_line" != "#!/bin/bash"* ]]; then
                print_error "Неверный shebang в $file: $first_line"
                return 1
            fi
            ;;
    esac
    return 0
}

# ============================================================
# РЕЖИМ: ROLLBACK
# ============================================================
do_rollback() {
    print_header "ОТКАТ ИЗ БЭКАПА"

    local latest_backup
    latest_backup=$(ls -dt ${BACKUP_DIR_BASE}/vless_backup_* 2>/dev/null | head -n 1)

    if [ -z "$latest_backup" ]; then
        print_error "Бэкапы не найдены (${BACKUP_DIR_BASE}/vless_backup_*)"
        exit 1
    fi

    print_info "Последний бэкап: $latest_backup"

    local backup_version="unknown"
    if [ -f "$latest_backup/.vless_cascade_version" ]; then
        backup_version=$(cat "$latest_backup/.vless_cascade_version")
    fi
    print_info "Версия в бэкапе: $backup_version"

    read -p "Откатиться к этой версии? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Отменено"
        exit 0
    fi

    print_info "Останавливаем observer..."
    animate_start "systemctl stop vless_observer"
    systemctl stop vless_observer 2>/dev/null || true
    animate_stop

    print_info "Восстанавливаем файлы..."
    if [ -d "$latest_backup/vless_checker" ]; then
        rm -rf "$CHECKER_DIR"
        cp -r "$latest_backup/vless_checker" "$CHECKER_DIR"
        print_success "Восстановлен: $CHECKER_DIR"
    fi

    if [ -d "$latest_backup/vless_observer" ]; then
        rm -rf "$OBSERVER_DIR"
        cp -r "$latest_backup/vless_observer" "$OBSERVER_DIR"
        print_success "Восстановлен: $OBSERVER_DIR"
    fi

    if [ -f "$latest_backup/vless_observer.service" ]; then
        cp "$latest_backup/vless_observer.service" "$SERVICE_FILE"
        systemctl daemon-reload
        print_success "Восстановлен systemd-юнит"
    fi

    if [ -f "$latest_backup/.vless_cascade_version" ]; then
        cp "$latest_backup/.vless_cascade_version" "$VERSION_FILE_LOCAL"
        print_success "Восстановлена версия: $(cat $VERSION_FILE_LOCAL)"
    fi

    print_info "Запускаем observer..."
    animate_start "systemctl start vless_observer"
    systemctl start vless_observer
    animate_stop

    sleep 2
    if systemctl is-active --quiet vless_observer; then
        print_success "Observer запущен"
    else
        print_error "Observer НЕ запустился. Проверьте: journalctl -u vless_observer -n 50"
        exit 1
    fi

    print_success "✅ Откат завершён"
}

if [ "$MODE" = "rollback" ]; then
    do_rollback
    exit 0
fi

# ============================================================
# ПРОВЕРКА УСТАНОВКИ
# ============================================================
if [ ! -d "$CHECKER_DIR" ] || [ ! -d "$OBSERVER_DIR" ]; then
    print_error "VLESS CASCADE не установлен."
    print_error "Ожидаются директории: $CHECKER_DIR и $OBSERVER_DIR"
    print_info "Установите: wget -qO- $GITHUB_RAW/install.sh | bash"
    exit 1
fi

# ============================================================
# ЧТЕНИЕ ЛОКАЛЬНОЙ ВЕРСИИ
# ============================================================
print_header "ПРОВЕРКА ВЕРСИЙ"

local_version="0.0.0"
if [ -f "$VERSION_FILE_LOCAL" ]; then
    local_version=$(cat "$VERSION_FILE_LOCAL" | tr -d '[:space:]')
else
    print_warning "Локальный файл версии не найден: $VERSION_FILE_LOCAL"
    print_warning "Считаем, что установлена версия 0.0.0"
fi

print_info "Установленная версия: $local_version"

# ============================================================
# СКАЧИВАНИЕ ВЕРСИИ С GITHUB
# ============================================================
print_info "Проверяем версию на GitHub..."

tmp_version=$(mktemp)
if ! download_file "$VERSION_FILE_REMOTE" "$tmp_version" "VERSION"; then
    rm -f "$tmp_version"
    print_error "Не удалось связаться с GitHub."
    print_error "Проверьте интернет и повторите попытку."
    exit 1
fi

remote_version=$(cat "$tmp_version" | tr -d '[:space:]')
rm -f "$tmp_version"

print_info "Версия на GitHub:     $remote_version"
echo ""

# ============================================================
# СРАВНЕНИЕ
# ============================================================
if [ "$local_version" = "$remote_version" ]; then
    print_success "У вас последняя версия ($local_version)."
    exit 0
fi

print_warning "Доступно обновление: $local_version → $remote_version"

# ============================================================
# РЕЖИМ --check
# ============================================================
if [ "$MODE" = "check" ]; then
    echo ""
    print_info "Для обновления запустите: bash $UPDATE_SCRIPT_PATH"
    exit 0
fi

# ============================================================
# CHANGELOG
# ============================================================
echo ""
print_header "ЧТО НОВОГО"

tmp_changelog=$(mktemp)
if download_file "$CHANGELOG_REMOTE" "$tmp_changelog" "CHANGELOG.md"; then
    awk -v ver="$remote_version" '
        $0 ~ "\\[?"ver"\\]?" { found=1 }
        found && /^## \[/ && !/'"$remote_version"'/ && seen { exit }
        found { print; seen=1 }
    ' "$tmp_changelog" | head -n 40
    rm -f "$tmp_changelog"
else
    print_warning "Не удалось скачать CHANGELOG.md"
fi

echo ""

# ============================================================
# ПОДТВЕРЖДЕНИЕ
# ============================================================
if [ "$MODE" != "auto" ]; then
    read -p "Обновить до версии $remote_version? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Отменено"
        exit 0
    fi
fi

# ============================================================
# БЭКАП
# ============================================================
print_header "СОЗДАНИЕ БЭКАПА"

timestamp=$(date +%Y%m%d_%H%M%S)
backup_dir="${BACKUP_DIR_BASE}/vless_backup_${timestamp}"

print_info "Создаём бэкап: $backup_dir"
mkdir -p "$backup_dir"

animate_start "Копирование vless_checker"
cp -r "$CHECKER_DIR" "$backup_dir/vless_checker"
animate_stop

animate_start "Копирование vless_observer"
cp -r "$OBSERVER_DIR" "$backup_dir/vless_observer"
animate_stop

if [ -f "$SERVICE_FILE" ]; then
    cp "$SERVICE_FILE" "$backup_dir/vless_observer.service"
fi

if [ -f "$VERSION_FILE_LOCAL" ]; then
    cp "$VERSION_FILE_LOCAL" "$backup_dir/.vless_cascade_version"
fi

print_success "Бэкап создан"

# Удаляем старые бэкапы (оставляем 5 последних)
backup_count=$(ls -dt ${BACKUP_DIR_BASE}/vless_backup_* 2>/dev/null | wc -l)
if [ "$backup_count" -gt "$BACKUP_KEEP" ]; then
    print_info "Удаляем старые бэкапы (оставляем $BACKUP_KEEP последних)..."
    ls -dt ${BACKUP_DIR_BASE}/vless_backup_* 2>/dev/null | tail -n +$((BACKUP_KEEP + 1)) | while read -r old; do
        rm -rf "$old"
        print_info "  Удалён: $(basename $old)"
    done
fi

# ============================================================
# ОСТАНОВКА OBSERVER
# ============================================================
print_header "ОСТАНОВКА OBSERVER"

if systemctl is-active --quiet vless_observer; then
    print_info "Останавливаем службу..."
    animate_start "systemctl stop vless_observer"
    systemctl stop vless_observer
    animate_stop
    print_success "Observer остановлен"
else
    print_info "Observer не запущен — пропускаем"
fi

# ============================================================
# СКАЧИВАНИЕ MERGE_CONFIG.PY
# ============================================================
print_info "Скачиваем merge_config.py..."
if download_file "$GITHUB_RAW/merge_config.py" "$MERGE_SCRIPT_PATH" "merge_config.py"; then
    chmod +x "$MERGE_SCRIPT_PATH"
    print_success "merge_config.py готов"
    HAVE_MERGE=1
else
    print_warning "Не удалось скачать merge_config.py"
    print_warning "Конфиги будут обновлены стандартным способом (перезапись)"
    HAVE_MERGE=0
fi

# ============================================================
# СКАЧИВАНИЕ ФАЙЛОВ
# ============================================================
print_header "ОБНОВЛЕНИЕ ФАЙЛОВ"

download_and_check() {
    local url="$1"
    local dest="$2"
    local name="$3"
    local tmp="${dest}.new"

    if ! download_file "$url" "$tmp" "$name"; then
        rm -f "$tmp"
        return 1
    fi

    if ! check_shebang "$tmp"; then
        rm -f "$tmp"
        return 1
    fi

    mv "$tmp" "$dest"
    chmod +x "$dest" 2>/dev/null || true
    return 0
}

# Обычные файлы чекера
print_info "Обновляем Чекер (код)..."
for file in $CHECKER_FILES; do
    if download_and_check "$GITHUB_RAW/$file" "$CHECKER_DIR/$file" "$file"; then
        print_success "  ✓ $file"
    else
        print_warning "  ✗ $file (пропущен)"
    fi
done

# Обычные файлы observer'а
print_info "Обновляем Observer (код)..."
for file in $OBSERVER_FILES; do
    if download_and_check "$GITHUB_RAW/$file" "$OBSERVER_DIR/$file" "$file"; then
        print_success "  ✓ $file"
    else
        print_warning "  ✗ $file (пропущен)"
    fi
done

# Обновляем сам update.sh
print_info "Обновляем скрипт update.sh..."
if download_and_check "$GITHUB_RAW/update.sh" "$UPDATE_SCRIPT_PATH" "update.sh"; then
    print_success "  ✓ update.sh"
else
    print_warning "  ✗ update.sh (пропущен)"
fi

# ============================================================
# СЛИЯНИЕ КОНФИГОВ
# ============================================================
print_header "КОНФИГИ (умное слияние)"

merge_one_config() {
    local dir="$1"
    local file="$2"
    local current_path="$dir/$file"
    local tmp_new="/tmp/${file}.new"

    if [ ! -f "$current_path" ]; then
        print_warning "Конфиг не найден: $current_path — скачиваем как новый"
        if download_and_check "$GITHUB_RAW/$file" "$current_path" "$file"; then
            print_success "  ✓ $file (установлен впервые)"
        fi
        return
    fi

    if ! download_file "$GITHUB_RAW/$file" "$tmp_new" "$file"; then
        print_warning "  ✗ $file: не удалось скачать новую версию — пропущен"
        rm -f "$tmp_new"
        return
    fi

    if ! check_shebang "$tmp_new"; then
        print_warning "  ✗ $file: неверный shebang — пропущен"
        rm -f "$tmp_new"
        return
    fi

    local merge_args=("$current_path" "$tmp_new" "$file")
    if [ "$MODE" = "auto" ]; then
        merge_args+=("--auto")
    fi

    set +e
    python3 "$MERGE_SCRIPT_PATH" "${merge_args[@]}"
    local merge_exit=$?
    set -e

    rm -f "$tmp_new"

    case $merge_exit in
        0) print_success "  ✓ $file: слияние завершено" ;;
        2) print_warning "  ⊘ $file: слияние отменено пользователем" ;;
        *) print_warning "  ✗ $file: ошибка слияния (код $merge_exit)" ;;
    esac
}

if [ "$HAVE_MERGE" = "1" ]; then
    print_info "Чекер: vless_check_config.py"
    for file in $CHECKER_CONFIG_FILES; do
        merge_one_config "$CHECKER_DIR" "$file"
    done

    print_info "Observer: observer_config.py"
    for file in $OBSERVER_CONFIG_FILES; do
        merge_one_config "$OBSERVER_DIR" "$file"
    done
else
    print_warning "merge_config.py недоступен — конфиги НЕ обновляем."
    print_warning "Скачайте merge_config.py вручную или обновите конфиги самостоятельно."
fi

# ============================================================
# ОБНОВЛЕНИЕ ВЕРСИИ
# ============================================================
print_info "Обновляем файл версии..."
echo "$remote_version" > "$VERSION_FILE_LOCAL"
print_success "Версия обновлена: $local_version → $remote_version"

# ============================================================
# ЗАПУСК OBSERVER
# ============================================================
print_header "ЗАПУСК OBSERVER"

print_info "Запускаем службу..."
animate_start "systemctl start vless_observer"
systemctl start vless_observer
animate_stop

sleep 3

if systemctl is-active --quiet vless_observer; then
    print_success "Observer запущен"
else
    print_error "Observer НЕ запустился!"
    echo ""
    print_warning "Проверьте логи:"
    echo "  journalctl -u vless_observer -n 50"
    echo "  tail -50 /var/log/vless_observer.log"
    echo ""
    print_warning "Для отката выполните:"
    echo "  bash $UPDATE_SCRIPT_PATH --rollback"
    exit 1
fi

# ============================================================
# ИТОГ
# ============================================================
print_header "ОБНОВЛЕНИЕ ЗАВЕРШЕНО"

echo "✅ Версия: $local_version → $remote_version"
echo "📁 Бэкап:  $backup_dir"
echo ""
echo "🔄 Статус службы:"
systemctl status vless_observer --no-pager | head -10
echo ""
echo "📊 Логи:"
echo "  tail -f /var/log/vless_observer.log"
echo ""
echo "↩️  Откат (если что-то не так):"
echo "  bash $UPDATE_SCRIPT_PATH --rollback"
echo ""

print_success "✅ Готово!"
