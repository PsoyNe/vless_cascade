#!/bin/bash
# ============================================================
# СБОРЩИК И ВЫВОД ЛОГОВ VLESS OBSERVER
# ============================================================

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

# Файлы логов
LOG_OBSERVER="/var/log/vless_observer.log"
LOG_CHECKER="/var/log/vless_checker.log"
LOG_CRON="/var/log/vless_checker_cron.log"

# Триггер-файлы (старые)
TRIGGER_SWITCH="/tmp/vless_observer_trigger"
TRIGGER_QUARANTINE="/tmp/vless_quarantine_trigger"
TRIGGER_DEEP_CHECK="/tmp/vless_deep_check_trigger"

# Файлы обновления
VERSION_FILE_LOCAL="/root/.vless_cascade_version"
UPDATE_SCRIPT="/root/update.sh"
GITHUB_VERSION_URL="https://raw.githubusercontent.com/PsoyNe/vless_cascade/refs/heads/main/VERSION"

# Конфиги
CHECKER_CONFIG="/root/vless_checker/vless_check_config.py"
OBSERVER_CONFIG="/root/vless_observer/observer_config.py"

# Службы
OBSERVER_SERVICE="vless_observer"

print_header() {
    echo ""
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${BLUE} $1${NC}"
    echo -e "${BLUE}============================================================${NC}"
    echo ""
}

pause() {
    echo ""
    read -p "Нажмите Enter для продолжения..." &
    wait $!
}

show_menu() {
    echo ""
    echo -e "${CYAN}ВЫБЕРИТЕ ДЕЙСТВИЕ:${NC}"
    echo ""
    echo -e "${YELLOW}--- ЛОГИ ---${NC}"
    echo "  1) Показать логи Observer (последние 50 строк)"
    echo "  2) Показать логи Observer (в реальном времени)"
    echo "  3) Показать логи Чекера (этап 1, последние 50 строк)"
    echo "  4) Показать логи Чекера (в реальном времени)"
    echo "  5) Показать логи cron-обёртки чекера"
    echo "  6) Показать все логи (сводка)"
    echo "  7) Показать ошибки во всех логах"
    echo "  8) Показать статистику Observer"
    echo "  9) Очистить все логи"
    echo ""
    echo -e "${YELLOW}--- СТАТУС ---${NC}"
    echo " 14) Статус служб (observer, x-ui, cron)"
    echo " 15) Кто сейчас работает (observer, checker, xray)"
    echo ""
    echo -e "${YELLOW}--- РОТАЦИЯ ЛОГОВ ---${NC}"
    echo " 13) Показать ротированные архивы логов"
    echo ""
    echo -e "${MAGENTA}--- ТРИГГЕРЫ ---${NC}"
    echo " 10) Триггер: имитация отказа (переключение на резерв)"
    echo " 11) Триггер: карантин (основная ссылка → в файл карантина)"
    echo " 12) Триггер: глубокая проверка (Google + запрещённые)"
    echo ""
    echo -e "${GREEN}--- ОБНОВЛЕНИЕ ---${NC}"
    echo " 16) Проверить наличие обновлений"
    echo " 17) Обновить (с подтверждением)"
    echo " 18) Откатиться из последнего бэкапа"
    echo ""
    echo -e "${CYAN}--- КОНФИГИ ---${NC}"
    echo " 19) Просмотреть конфиг чекера"
    echo " 20) Редактировать конфиг чекера"
    echo " 21) Просмотреть конфиг обсервера"
    echo " 22) Редактировать конфиг обсервера"
    echo " 23) Проверить конфиги на ошибки"
    echo " 24) Редактировать конфиг + перезапустить observer"
    echo ""
    echo "  0) Выход"
    echo ""
    read -p "Введите номер (0-24): " choice
}

show_observer() {
    print_header "ЛОГИ OBSERVER (последние 50 строк)"
    if [ -f "$LOG_OBSERVER" ]; then
        tail -50 "$LOG_OBSERVER"
    else
        echo -e "${RED}Файл $LOG_OBSERVER не найден${NC}"
    fi
}

show_observer_live() {
    print_header "ЛОГИ OBSERVER (в реальном времени, Ctrl+C для выхода)"
    if [ -f "$LOG_OBSERVER" ]; then
        tail -f "$LOG_OBSERVER"
    else
        echo -e "${RED}Файл $LOG_OBSERVER не найден${NC}"
    fi
}

show_checker() {
    print_header "ЛОГИ ЧЕКЕРА (этап 1, последние 50 строк)"
    if [ -f "$LOG_CHECKER" ]; then
        tail -50 "$LOG_CHECKER"
    else
        echo -e "${RED}Файл $LOG_CHECKER не найден${NC}"
    fi
}

show_checker_live() {
    print_header "ЛОГИ ЧЕКЕРА (в реальном времени, Ctrl+C для выхода)"
    if [ -f "$LOG_CHECKER" ]; then
        tail -f "$LOG_CHECKER"
    else
        echo -e "${RED}Файл $LOG_CHECKER не найден${NC}"
    fi
}

show_cron() {
    print_header "ЛОГИ CRON-ОБЁРТКИ ЧЕКЕРА (последние 50 строк)"
    if [ -f "$LOG_CRON" ]; then
        tail -50 "$LOG_CRON"
    else
        echo -e "${YELLOW}Файл $LOG_CRON не найден или пуст${NC}"
        echo ""
        echo "Это нормально, если чекер пишет только через Python logging"
        echo "в /var/log/vless_checker.log. Cron-лог — это stdout/stderr"
        echo "обёртки, туда попадает только то, что чекер печатает в консоль."
    fi
}

show_all() {
    print_header "СВОДКА ПО ВСЕМ ЛОГАМ"

    echo -e "${CYAN}📊 OBSERVER:${NC}"
    if [ -f "$LOG_OBSERVER" ]; then
        tail -10 "$LOG_OBSERVER"
    else
        echo "  Файл не найден"
    fi

    echo ""
    echo -e "${CYAN}📊 ЧЕКЕР (этап 1):${NC}"
    if [ -f "$LOG_CHECKER" ]; then
        tail -5 "$LOG_CHECKER"
    else
        echo "  Файл не найден"
    fi

    echo ""
    echo -e "${CYAN}📊 CRON-ОБЁРТКА:${NC}"
    if [ -f "$LOG_CRON" ]; then
        tail -5 "$LOG_CRON"
    else
        echo "  Файл не найден"
    fi
}

show_errors() {
    print_header "ОШИБКИ ВО ВСЕХ ЛОГАХ"

    echo -e "${CYAN}📊 OBSERVER:${NC}"
    if [ -f "$LOG_OBSERVER" ]; then
        grep -i "error\|ошибка\|❌\|критическая" "$LOG_OBSERVER" | tail -10 || echo "  Ошибок нет"
    fi

    echo ""
    echo -e "${CYAN}📊 ЧЕКЕР:${NC}"
    if [ -f "$LOG_CHECKER" ]; then
        grep -i "error\|ошибка\|❌" "$LOG_CHECKER" | tail -5 || echo "  Ошибок нет"
    fi

    echo ""
    echo -e "${CYAN}📊 CRON-ОБЁРТКА:${NC}"
    if [ -f "$LOG_CRON" ]; then
        grep -i "error\|ошибка\|❌" "$LOG_CRON" | tail -5 || echo "  Ошибок нет"
    fi
}

show_stats() {
    print_header "СТАТИСТИКА OBSERVER"

    if [ ! -f "$LOG_OBSERVER" ]; then
        echo -e "${RED}Файл $LOG_OBSERVER не найден${NC}"
        return
    fi

    echo -e "${CYAN}📊 Общая статистика:${NC}"
    echo "  Переключений: $(grep -c "ПЕРЕКЛЮЧЕНИЕ" "$LOG_OBSERVER")"
    echo "  Мёртвых ссылок: $(grep -c "мертва" "$LOG_OBSERVER")"
    echo "  Удалено из пула: $(grep -c "🗑️" "$LOG_OBSERVER")"
    echo "  Карантинов: $(grep -c "КАРАНТИН" "$LOG_OBSERVER")"
    echo "  Глубоких проверок: $(grep -c "ГЛУБОКАЯ ПРОВЕРКА" "$LOG_OBSERVER")"
    echo "  Ожило из отложенных: $(grep -c "ожила" "$LOG_OBSERVER")"

    echo ""
    echo -e "${CYAN}📊 Текущий статус:${NC}"
    grep "OK |" "$LOG_OBSERVER" | tail -1

    echo ""
    echo -e "${CYAN}📊 Последнее переключение:${NC}"
    grep "ПЕРЕКЛЮЧЕНИЕ" "$LOG_OBSERVER" | tail -1 || echo "  Переключений не было"
}

clear_logs() {
    print_header "ОЧИСТКА ВСЕХ ЛОГОВ"
    read -p "Вы уверены? (y/n): " confirm

    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        > "$LOG_OBSERVER" 2>/dev/null
        > "$LOG_CHECKER" 2>/dev/null
        > "$LOG_CRON" 2>/dev/null
        echo -e "${GREEN}✅ Все логи очищены${NC}"
    else
        echo -e "${YELLOW}Отменено${NC}"
    fi
}

trigger_switch() {
    print_header "ТРИГГЕР: ИМИТАЦИЯ ОТКАЗА"

    if [ -f "$TRIGGER_SWITCH" ]; then
        echo -e "${YELLOW}⚠️ Триггер уже существует: $TRIGGER_SWITCH${NC}"
        read -p "Пересоздать? (y/n): " confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            return
        fi
        rm -f "$TRIGGER_SWITCH"
    fi

    touch "$TRIGGER_SWITCH"

    if [ -f "$TRIGGER_SWITCH" ]; then
        echo -e "${GREEN}✅ Триггер создан: $TRIGGER_SWITCH${NC}"
        echo ""
        echo -e "${CYAN}Что произойдёт:${NC}"
        echo "  1. Observer обнаружит триггер (в течение 5 сек)"
        echo "  2. Имитирует 5 отказов подряд"
        echo "  3. Мгновенно переключится на резервную ссылку"
    else
        echo -e "${RED}❌ Не удалось создать триггер${NC}"
    fi
}

trigger_quarantine() {
    print_header "ТРИГГЕР: КАРАНТИН"

    if [ -f "$TRIGGER_QUARANTINE" ]; then
        echo -e "${YELLOW}⚠️ Триггер уже существует: $TRIGGER_QUARANTINE${NC}"
        read -p "Пересоздать? (y/n): " confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            return
        fi
        rm -f "$TRIGGER_QUARANTINE"
    fi

    touch "$TRIGGER_QUARANTINE"

    if [ -f "$TRIGGER_QUARANTINE" ]; then
        echo -e "${GREEN}✅ Триггер создан: $TRIGGER_QUARANTINE${NC}"
        echo ""
        echo -e "${CYAN}Что произойдёт:${NC}"
        echo "  1. Observer обнаружит триггер (в течение 5 сек)"
        echo "  2. Текущая основная ссылка → в файл карантина"
        echo "  3. Чекер больше НИКОГДА её не проверит"
        echo "  4. Observer переключится на резервную"
    else
        echo -e "${RED}❌ Не удалось создать триггер${NC}"
    fi
}

trigger_deep_check() {
    print_header "ТРИГГЕР: ГЛУБОКАЯ ПРОВЕРКА"

    if [ -f "$TRIGGER_DEEP_CHECK" ]; then
        echo -e "${YELLOW}⚠️ Триггер уже существует: $TRIGGER_DEEP_CHECK${NC}"
        read -p "Пересоздать? (y/n): " confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            return
        fi
        rm -f "$TRIGGER_DEEP_CHECK"
    fi

    touch "$TRIGGER_DEEP_CHECK"

    if [ -f "$TRIGGER_DEEP_CHECK" ]; then
        echo -e "${GREEN}✅ Триггер создан: $TRIGGER_DEEP_CHECK${NC}"
        echo ""
        echo -e "${CYAN}Что произойдёт:${NC}"
        echo "  1. Observer обнаружит триггер (в течение 5 сек)"
        echo "  2. Проверит основную ссылку через Google (204)"
        echo "  3. Проверит её же через запрещённые ресурсы:"
        echo "     - www.instagram.com"
        echo "     - www.facebook.com"
        echo "     - check.torproject.org"
        echo "  4. Если Google ✅, а запрещённые ❌ → в карантин"
    else
        echo -e "${RED}❌ Не удалось создать триггер${NC}"
    fi
}

show_rotated() {
    print_header "РОТИРОВАННЫЕ АРХИВЫ ЛОГОВ"

    for base in "$LOG_OBSERVER" "$LOG_CHECKER" "$LOG_CRON"; do
        echo -e "${CYAN}📁 ${base}*${NC}"
        ls -lh "${base}"* 2>/dev/null | tail -n +2 || echo "  Архивов нет"
        echo ""
    done
}

show_services() {
    print_header "СТАТУС СЛУЖБ"

    echo -e "${CYAN}🔄 VLESS Observer:${NC}"
    systemctl status vless_observer --no-pager 2>/dev/null | head -12 || echo "  Служба не найдена"
    echo ""

    echo -e "${CYAN}🔄 x-ui:${NC}"
    systemctl status x-ui --no-pager 2>/dev/null | head -8 || echo "  Служба не найдена"
    echo ""

    echo -e "${CYAN}🔄 cron:${NC}"
    systemctl status cron --no-pager 2>/dev/null | head -8 || echo "  Служба не найдена"
}

show_processes() {
    print_header "АКТИВНЫЕ ПРОЦЕССЫ"

    echo -e "${CYAN}📊 Observer:${NC}"
    pgrep -af "observer.py" || echo "  Не запущен"
    echo ""

    echo -e "${CYAN}📊 Checker:${NC}"
    pgrep -af "vless_checker.py" || echo "  Не запущен"
    echo ""

    echo -e "${CYAN}📊 Xray-процессы (всего):${NC}"
    local count=$(pgrep -fc "xray-linux-arm32" 2>/dev/null || echo 0)
    echo "  Всего: $count"
    echo ""
    ps -eo pid,ppid,etime,pcpu,cmd 2>/dev/null | grep "xray-linux-arm32" | grep -v grep | awk '{printf "  PID %-7s PPID %-7s uptime %-10s CPU %-6s %s\n", $1, $2, $3, $4, $5}' | head -20

    echo ""
    echo -e "${CYAN}📊 Lock-файл чекера:${NC}"
    if [ -f /var/run/vless_checker.lock ]; then
        ls -lh /var/run/vless_checker.lock
        if flock -n /var/run/vless_checker.lock echo "  Статус: свободен" 2>/dev/null; then
            :
        else
            echo "  Статус: ЗАНЯТ (чекер работает)"
        fi
    else
        echo "  Файл не создан (чекер ещё не запускался)"
    fi
}

# ============================================================
# ОБНОВЛЕНИЕ
# ============================================================

check_update() {
    print_header "ПРОВЕРКА ОБНОВЛЕНИЙ"

    local local_version="0.0.0"
    if [ -f "$VERSION_FILE_LOCAL" ]; then
        local_version=$(cat "$VERSION_FILE_LOCAL" | tr -d '[:space:]')
    else
        echo -e "${YELLOW}⚠️ Файл версии не найден: $VERSION_FILE_LOCAL${NC}"
        echo -e "${YELLOW}   Считаем, что установлена версия 0.0.0${NC}"
    fi

    echo -e "${CYAN}📊 Версии:${NC}"
    echo "  Установленная: $local_version"

    local remote_version
    remote_version=$(wget -q --timeout=10 -O - "$GITHUB_VERSION_URL" 2>/dev/null | tr -d '[:space:]')

    if [ -z "$remote_version" ]; then
        echo -e "${RED}  Не удалось получить версию с GitHub${NC}"
        echo ""
        echo "Проверьте интернет и повторите."
        return 1
    fi

    echo "  На GitHub:     $remote_version"
    echo ""

    if [ "$local_version" = "$remote_version" ]; then
        echo -e "${GREEN}✅ У вас последняя версия ($local_version).${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠️ Доступно обновление: $local_version → $remote_version${NC}"
        echo ""
        echo -e "${CYAN}Для обновления используйте пункт 17 меню${NC}"
        return 2
    fi
}

do_update() {
    print_header "ОБНОВЛЕНИЕ"

    if [ ! -f "$UPDATE_SCRIPT" ]; then
        echo -e "${RED}❌ Скрипт обновления не найден: $UPDATE_SCRIPT${NC}"
        echo ""
        echo "Скачайте его вручную:"
        echo "  wget -qO /root/update.sh https://raw.githubusercontent.com/PsoyNe/vless_cascade/refs/heads/main/update.sh"
        echo "  chmod +x /root/update.sh"
        return 1
    fi

    if [ ! -x "$UPDATE_SCRIPT" ]; then
        echo -e "${YELLOW}⚠️ Скрипт обновления не исполняемый. Исправляем...${NC}"
        chmod +x "$UPDATE_SCRIPT"
    fi

    echo -e "${CYAN}Запуск скрипта обновления...${NC}"
    echo ""
    echo "────────────────────────────────────────────────────────────"
    echo ""

    bash "$UPDATE_SCRIPT"

    echo ""
    echo "────────────────────────────────────────────────────────────"
    echo -e "${GREEN}✅ Скрипт обновления завершён${NC}"
}

do_rollback() {
    print_header "ОТКАТ ИЗ БЭКАПА"

    if [ ! -f "$UPDATE_SCRIPT" ]; then
        echo -e "${RED}❌ Скрипт обновления не найден: $UPDATE_SCRIPT${NC}"
        return 1
    fi

    echo -e "${CYAN}📁 Доступные бэкапы:${NC}"
    if ls -dt /root/vless_backup_* 2>/dev/null | head -5 | while read -r b; do
        echo "  $(basename "$b")"
    done; then
        :
    else
        echo -e "${YELLOW}  Бэкапы не найдены${NC}"
        return 1
    fi

    echo ""
    echo -e "${YELLOW}⚠️ Откат восстановит файлы из последнего бэкапа.${NC}"
    echo ""
    read -p "Продолжить? (y/n): " confirm

    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Отменено${NC}"
        return 0
    fi

    echo ""
    echo "────────────────────────────────────────────────────────────"
    echo ""

    bash "$UPDATE_SCRIPT" --rollback

    echo ""
    echo "────────────────────────────────────────────────────────────"
    echo -e "${GREEN}✅ Откат завершён${NC}"
}

# ============================================================
# КОНФИГИ
# ============================================================

view_checker_config() {
    print_header "КОНФИГ ЧЕКЕРА: vless_check_config.py"

    if [ ! -f "$CHECKER_CONFIG" ]; then
        echo -e "${RED}❌ Файл не найден: $CHECKER_CONFIG${NC}"
        return 1
    fi

    echo -e "${CYAN}Путь:${NC} $CHECKER_CONFIG"
    echo -e "${CYAN}Размер:${NC} $(stat -c%s "$CHECKER_CONFIG") байт"
    echo -e "${CYAN}Изменён:${NC} $(stat -c%y "$CHECKER_CONFIG" | cut -d'.' -f1)"
    echo ""
    echo "────────────────────────────────────────────────────────────"

    cat "$CHECKER_CONFIG"

    echo ""
    echo "────────────────────────────────────────────────────────────"
}

edit_checker_config() {
    print_header "РЕДАКТИРОВАНИЕ КОНФИГА ЧЕКЕРА"

    if [ ! -f "$CHECKER_CONFIG" ]; then
        echo -e "${RED}❌ Файл не найден: $CHECKER_CONFIG${NC}"
        return 1
    fi

    echo -e "${CYAN}Путь:${NC} $CHECKER_CONFIG"
    echo ""

    # Бэкап перед редактированием
    local backup="${CHECKER_CONFIG}.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$CHECKER_CONFIG" "$backup"
    echo -e "${YELLOW}📁 Бэкап: $backup${NC}"
    echo ""

    read -p "Открыть в nano? (y/n): " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Отменено${NC}"
        rm -f "$backup"
        return 0
    fi

    nano "$CHECKER_CONFIG"

    echo ""
    echo -e "${CYAN}Проверка конфига...${NC}"
    if python3 -c "import sys; sys.path.insert(0, '/root/vless_checker'); import vless_check_config" 2>/dev/null; then
        echo -e "${GREEN}✅ Конфиг корректен${NC}"
        echo ""
        echo -e "${YELLOW}Настройки применятся при следующем запуске чекера${NC}"
        echo -e "${YELLOW}(cron: 01:00, 07:00, 13:00, 19:00)${NC}"
    else
        echo -e "${RED}❌ Ошибка в конфиге!${NC}"
        echo ""
        echo -e "${YELLOW}Восстановить из бэкапа?${NC}"
        read -p "(y/n): " restore
        if [[ "$restore" =~ ^[Yy]$ ]]; then
            cp "$backup" "$CHECKER_CONFIG"
            echo -e "${GREEN}✅ Восстановлено из бэкапа${NC}"
        else
            echo -e "${YELLOW}Бэкап сохранён: $backup${NC}"
        fi
    fi
}

view_observer_config() {
    print_header "КОНФИГ ОБСЕРВЕРА: observer_config.py"

    if [ ! -f "$OBSERVER_CONFIG" ]; then
        echo -e "${RED}❌ Файл не найден: $OBSERVER_CONFIG${NC}"
        return 1
    fi

    echo -e "${CYAN}Путь:${NC} $OBSERVER_CONFIG"
    echo -e "${CYAN}Размер:${NC} $(stat -c%s "$OBSERVER_CONFIG") байт"
    echo -e "${CYAN}Изменён:${NC} $(stat -c%y "$OBSERVER_CONFIG" | cut -d'.' -f1)"
    echo ""
    echo "────────────────────────────────────────────────────────────"

    cat "$OBSERVER_CONFIG"

    echo ""
    echo "────────────────────────────────────────────────────────────"
}

edit_observer_config() {
    print_header "РЕДАКТИРОВАНИЕ КОНФИГА ОБСЕРВЕРА"

    if [ ! -f "$OBSERVER_CONFIG" ]; then
        echo -e "${RED}❌ Файл не найден: $OBSERVER_CONFIG${NC}"
        return 1
    fi

    echo -e "${CYAN}Путь:${NC} $OBSERVER_CONFIG"
    echo ""

    # Бэкап перед редактированием
    local backup="${OBSERVER_CONFIG}.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$OBSERVER_CONFIG" "$backup"
    echo -e "${YELLOW}📁 Бэкап: $backup${NC}"
    echo ""

    read -p "Открыть в nano? (y/n): " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Отменено${NC}"
        rm -f "$backup"
        return 0
    fi

    nano "$OBSERVER_CONFIG"

    echo ""
    echo -e "${CYAN}Проверка конфига...${NC}"
    if python3 -c "import sys; sys.path.insert(0, '/root/vless_observer'); import observer_config" 2>/dev/null; then
        echo -e "${GREEN}✅ Конфиг корректен${NC}"
        echo ""
        echo -e "${YELLOW}Перезапустить observer для применения? (y/n)${NC}"
        read -p "(y/n): " restart
        if [[ "$restart" =~ ^[Yy]$ ]]; then
            systemctl restart vless_observer
            sleep 2
            if systemctl is-active --quiet vless_observer; then
                echo -e "${GREEN}✅ Observer перезапущен${NC}"
            else
                echo -e "${RED}❌ Observer не запустился!${NC}"
                echo -e "${YELLOW}Проверьте: journalctl -u vless_observer -n 50${NC}"
                echo -e "${YELLOW}Откатить из бэкапа? (y/n)${NC}"
                read -p "(y/n): " rollback
                if [[ "$rollback" =~ ^[Yy]$ ]]; then
                    cp "$backup" "$OBSERVER_CONFIG"
                    systemctl restart vless_observer
                    sleep 2
                    if systemctl is-active --quiet vless_observer; then
                        echo -e "${GREEN}✅ Откат выполнен, observer запущен${NC}"
                    else
                        echo -e "${RED}❌ Observer всё ещё не работает${NC}"
                    fi
                fi
            fi
        fi
    else
        echo -e "${RED}❌ Ошибка в конфиге!${NC}"
        echo ""
        echo -e "${YELLOW}Восстановить из бэкапа?${NC}"
        read -p "(y/n): " restore
        if [[ "$restore" =~ ^[Yy]$ ]]; then
            cp "$backup" "$OBSERVER_CONFIG"
            echo -e "${GREEN}✅ Восстановлено из бэкапа${NC}"
        else
            echo -e "${YELLOW}Бэкап сохранён: $backup${NC}"
        fi
    fi
}

check_configs() {
    print_header "ПРОВЕРКА КОНФИГОВ"

    echo -e "${CYAN}📊 Конфиг чекера:${NC}"
    echo "  Путь: $CHECKER_CONFIG"
    if [ -f "$CHECKER_CONFIG" ]; then
        if python3 -c "import sys; sys.path.insert(0, '/root/vless_checker'); import vless_check_config" 2>/dev/null; then
            echo -e "  ${GREEN}✅ Корректен${NC}"
        else
            echo -e "  ${RED}❌ Ошибка импорта${NC}"
            echo ""
            echo "  Проверить вручную:"
            echo "    python3 -c \"import sys; sys.path.insert(0, '/root/vless_checker'); import vless_check_config\""
        fi
    else
        echo -e "  ${RED}❌ Файл не найден${NC}"
    fi
    echo ""

    echo -e "${CYAN}📊 Конфиг обсервера:${NC}"
    echo "  Путь: $OBSERVER_CONFIG"
    if [ -f "$OBSERVER_CONFIG" ]; then
        if python3 -c "import sys; sys.path.insert(0, '/root/vless_observer'); import observer_config" 2>/dev/null; then
            echo -e "  ${GREEN}✅ Корректен${NC}"
        else
            echo -e "  ${RED}❌ Ошибка импорта${NC}"
            echo ""
            echo "  Проверить вручную:"
            echo "    python3 -c \"import sys; sys.path.insert(0, '/root/vless_observer'); import observer_config\""
        fi
    else
        echo -e "  ${RED}❌ Файл не найден${NC}"
    fi
    echo ""

    # Дополнительно — проверка зависимостей
    echo -e "${CYAN}📊 Зависимости observer'а:${NC}"
    for module in vless_common triggers; do
        if python3 -c "import sys; sys.path.insert(0, '/root/vless_observer'); import $module" 2>/dev/null; then
            echo -e "  ${GREEN}✅ $module.py${NC}"
        else
            echo -e "  ${RED}❌ $module.py — ошибка импорта${NC}"
        fi
    done
    echo ""

    # Статус службы
    echo -e "${CYAN}📊 Служба observer:${NC}"
    if systemctl is-active --quiet vless_observer; then
        echo -e "  ${GREEN}✅ Активна${NC}"
    else
        echo -e "  ${RED}❌ Не активна${NC}"
    fi
}

edit_and_restart() {
    print_header "РЕДАКТИРОВАНИЕ + ПЕРЕЗАПУСК"

    echo -e "${CYAN}Какой конфиг редактировать?${NC}"
    echo "  1) vless_check_config.py (чекер)"
    echo "  2) observer_config.py (обсервер)"
    echo "  0) Отмена"
    echo ""
    read -p "Выбор: " cfg_choice

    case $cfg_choice in
        1)
            view_checker_config
            echo ""
            read -p "Редактировать? (y/n): " confirm
            if [[ "$confirm" =~ ^[Yy]$ ]]; then
                edit_checker_config
            fi
            ;;
        2)
            view_observer_config
            echo ""
            read -p "Редактировать? (y/n): " confirm
            if [[ "$confirm" =~ ^[Yy]$ ]]; then
                edit_observer_config
            fi
            ;;
        0) return 0 ;;
        *) echo -e "${RED}Неверный выбор${NC}" ;;
    esac
}

# ============================================================
# ГЛАВНЫЙ ЦИКЛ
# ============================================================
while true; do
    show_menu

    case $choice in
        1) show_observer ;;
        2) show_observer_live ;;
        3) show_checker ;;
        4) show_checker_live ;;
        5) show_cron ;;
        6) show_all ;;
        7) show_errors ;;
        8) show_stats ;;
        9) clear_logs ;;
        10) trigger_switch ;;
        11) trigger_quarantine ;;
        12) trigger_deep_check ;;
        13) show_rotated ;;
        14) show_services ;;
        15) show_processes ;;
        16) check_update ;;
        17) do_update ;;
        18) do_rollback ;;
        19) view_checker_config ;;
        20) edit_checker_config ;;
        21) view_observer_config ;;
        22) edit_observer_config ;;
        23) check_configs ;;
        24) edit_and_restart ;;
        0) echo -e "${GREEN}Выход${NC}"; exit 0 ;;
        *) echo -e "${RED}Неверный выбор${NC}" ;;
    esac

    pause
done
