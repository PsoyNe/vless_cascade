#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ============================================================
# КОНФИГУРАЦИЯ ДЛЯ VLESS OBSERVER
# ============================================================

# -------------------- ПУТИ --------------------
XRAY_PATH = "/usr/local/x-ui/bin/xray-linux-arm32"
DB_PATH = "/etc/x-ui/x-ui.db"
LINKS_FILE = "/root/vless_checker/stable_links.txt"
STATE_FILE = "/root/vless_observer/observer_state.json"
LOG_FILE = "/var/log/vless_observer.log"

# -------------------- НАСТРОЙКИ МОНИТОРИНГА --------------------
CHECK_INTERVAL_PRIMARY = 5        # Проверка основной ссылки (сек)
CHECK_INTERVAL_BACKUP = 30        # Проверка резервных ссылок (сек)
FAILURES_TO_SWITCH = 5            # ← ИЗМЕНЕНО: 5 отказов подряд (было 2)
BACKUP_POOL_SIZE = 4              # Размер резервного пула
POOL_UPDATE_INTERVAL = 21600      # Обновление пула из файла (сек) = 6 часов

# -------------------- НАСТРОЙКИ ТЕСТИРОВАНИЯ --------------------
TEST_HOST = 'check.torproject.org'
TEST_PORT = 443
TEST_PATH = '/'
TEST_TIMEOUT = 10
TEST_BUFFER_SIZE = 65536
TEST_EXPECTED_STRING = b'You are not using Tor'

# -------------------- НАСТРОЙКИ 3X-UI --------------------
OUTBOUND_NAME = "vless_obs"

# -------------------- НАСТРОЙКИ TELEGRAM (опционально) --------------------
TELEGRAM_ENABLED = False
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# -------------------- НАСТРОЙКИ СЛУЖБЫ --------------------
SERVICE_NAME = "vless_observer"
SERVICE_DESCRIPTION = "VLESS Observer - automatic outbound monitoring and switching"
