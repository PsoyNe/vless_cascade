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

# Триггер-файлы
TRIGGER_SWITCH="/tmp/vless_observer_trigger"
TRIGGER_QUARANTINE="/tmp/vless_quarantine_trigger"
TRIGGER_DEEP_CHECK="/tmp/vless_deep_check_trigger"

print_header() {
    echo ""
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${BLUE} $1${NC}"
    echo -e "${BLUE}============================================================${NC}"
    echo ""
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
    echo "  0) Выход"
    echo ""
    read -p "Введите номер (0-15): " choice
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
        0) echo -e "${GREEN}Выход${NC}"; exit 0 ;;
        *) echo -e "${RED}Неверный выбор${NC}" ;;
    esac

    echo ""
    read -p "Нажмите Enter для продолжения..." &
    wait $!
done
