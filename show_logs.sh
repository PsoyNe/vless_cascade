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
LOG_SERVER="/var/log/server_test.log"
LOG_FULL="/var/log/vless_full.log"

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
    echo "  3) Показать логи Чекера (этап 1)"
    echo "  4) Показать логи Тестера (этап 2)"
    echo "  5) Показать полный цикл чекера"
    echo "  6) Показать все логи (сводка)"
    echo "  7) Показать ошибки во всех логах"
    echo "  8) Показать статистику Observer"
    echo "  9) Очистить все логи"
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
    read -p "Введите номер (0-13): " choice
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

show_server() {
    print_header "ЛОГИ ТЕСТЕРА (этап 2, последние 50 строк)"
    if [ -f "$LOG_SERVER" ]; then
        tail -50 "$LOG_SERVER"
    else
        echo -e "${RED}Файл $LOG_SERVER не найден${NC}"
    fi
}

show_full() {
    print_header "ЛОГИ ПОЛНОГО ЦИКЛА (последние 50 строк)"
    if [ -f "$LOG_FULL" ]; then
        tail -50 "$LOG_FULL"
    else
        echo -e "${RED}Файл $LOG_FULL не найден${NC}"
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
    echo -e "${CYAN}📊 ТЕСТЕР (этап 2):${NC}"
    if [ -f "$LOG_SERVER" ]; then
        tail -5 "$LOG_SERVER"
    else
        echo "  Файл не найден"
    fi

    echo ""
    echo -e "${CYAN}📊 ПОЛНЫЙ ЦИКЛ:${NC}"
    if [ -f "$LOG_FULL" ]; then
        tail -5 "$LOG_FULL"
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
    echo -e "${CYAN}📊 ТЕСТЕР:${NC}"
    if [ -f "$LOG_SERVER" ]; then
        grep -i "error\|ошибка\|❌" "$LOG_SERVER" | tail -5 || echo "  Ошибок нет"
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
    echo "  Возвратов: $(grep -c "ВОЗВРАТ" "$LOG_OBSERVER")"
    echo "  Мёртвых ссылок: $(grep -c "мертва" "$LOG_OBSERVER")"
    echo "  Удалено из пула: $(grep -c "🗑️" "$LOG_OBSERVER")"
    echo "  Карантинов: $(grep -c "КАРАНТИН" "$LOG_OBSERVER")"
    echo "  Глубоких проверок: $(grep -c "ГЛУБОКАЯ ПРОВЕРКА" "$LOG_OBSERVER")"

    echo ""
    echo -e "${CYAN}📊 Текущий статус:${NC}"
    grep "OK |" "$LOG_OBSERVER" | tail -1

    echo ""
    echo -e "${CYAN}📊 Последнее переключение:${NC}"
    grep "ПЕРЕКЛЮЧЕНИЕ" "$LOG_OBSERVER" | tail -1
}

clear_logs() {
    print_header "ОЧИСТКА ВСЕХ ЛОГОВ"
    read -p "Вы уверены? (y/n): " confirm

    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        > "$LOG_OBSERVER" 2>/dev/null
        > "$LOG_CHECKER" 2>/dev/null
        > "$LOG_SERVER" 2>/dev/null
        > "$LOG_FULL" 2>/dev/null
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
        echo "  3. Первый этап больше НИКОГДА её не проверит"
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

    for base in "$LOG_OBSERVER" "$LOG_CHECKER" "$LOG_SERVER" "$LOG_FULL"; do
        echo -e "${CYAN}📁 ${base}*${NC}"
        ls -lh "${base}"* 2>/dev/null | tail -n +2 || echo "  Архивов нет"
        echo ""
    done
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
        4) show_server ;;
        5) show_full ;;
        6) show_all ;;
        7) show_errors ;;
        8) show_stats ;;
        9) clear_logs ;;
        10) trigger_switch ;;
        11) trigger_quarantine ;;
        12) trigger_deep_check ;;
        13) show_rotated ;;
        0) echo -e "${GREEN}Выход${NC}"; exit 0 ;;
        *) echo -e "${RED}Неверный выбор${NC}" ;;
    esac

    echo ""
    read -p "Нажмите Enter для продолжения..." &
    wait $!
done
