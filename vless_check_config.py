#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ============================================================
# КОНФИГУРАЦИОННЫЙ ФАЙЛ ДЛЯ VLESS ЧЕКЕРА
# ============================================================

# -------------------- ОБЩИЕ НАСТРОЙКИ --------------------
XRAY_PATH = "/usr/local/x-ui/bin/xray-linux-arm32"
DEFAULT_URL = "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/vless_configs.txt"

# -------------------- НАСТРОЙКИ ОТБОРА ССЫЛОК --------------------
# Режим отбора:
#   'reality_443' - отбираем ТОЛЬКО ссылки с security=reality И портом 443
#   'reality'     - отбираем ТОЛЬКО ссылки с security=reality (порт любой)
#   'port_443'    - отбираем ТОЛЬКО ссылки с портом 443 (security любой)
#   'all'         - отбираем ВСЕ ссылки (без фильтра)
FILTER_MODE = 'reality_443'

# -------------------- НАСТРОЙКИ ПРОВЕРКИ ССЫЛОК --------------------
# Режим проверки:
#   'all'          - проверяем ВСЕ отобранные ссылки, потом выбираем 30 лучших
#   'until_30'     - проверяем ссылки, пока не наберём 30 рабочих, потом останавливаемся
CHECK_MODE = 'until_30'

# -------------------- НАСТРОЙКИ ЭТАПА 1 --------------------
STAGE1_WORKING_COUNT = 30        # Сколько ссылок сохранять в пул
STAGE1_MAX_WORKERS = 8           # Потоков
STAGE1_TIMEOUT = 10              # Таймаут на запрос (сек)

# -------------------- НАСТРОЙКИ ЭТАПА 2 --------------------
STAGE2_TEST_DURATION = 180       # Длительность теста на сервер (сек)
STAGE2_CHECK_INTERVAL = 10       # Интервал между проверками (сек)
STAGE2_MAX_WORKERS = 8           # Потоков
STAGE2_TIMEOUT = 10              # Таймаут на запрос (сек)
STAGE2_STABLE_UPTIME = 85        # Минимальный аптайм для стабильности (%)
STAGE2_MAX_FAILURES = 3          # Максимум отказов подряд
STAGE2_MAX_FAIL_PERCENT = 10     # Максимальный процент отказов
STAGE2_MAX_PING = 3000           # Максимальный пинг (мс)
STAGE2_MIN_RESPONSE_SIZE = 5000  # Минимальный размер ответа (байт)
STAGE2_TARGET_COUNT = 10         # Сколько ссылок отбирать в ТОП

# -------------------- НАСТРОЙКИ ТЕСТИРОВАНИЯ --------------------
TEST_PROTOCOL = 'https'
TEST_HOST = 'check.torproject.org'
TEST_PORT = 443
TEST_PATH = '/'
TEST_METHOD = 'HEAD'
TEST_TIMEOUT = 10
TEST_BUFFER_SIZE = 1024

# -------------------- НАСТРОЙКИ ФАЙЛОВ --------------------
WORKING_LINKS_FILE = "/root/vless_checker/working_links.txt"
STABLE_LINKS_10_FILE = "/root/vless_checker/stable_links.txt"
QUARANTINE_FILE = "/root/vless_checker/quarantine_links.txt"

# -------------------- РОТАЦИЯ ЛОГОВ --------------------
LOG_ROTATION_WHEN = "midnight"
LOG_ROTATION_INTERVAL = 1
LOG_ROTATION_BACKUPS = 7

# -------------------- АТОМАРНОЕ ЧТЕНИЕ ФАЙЛОВ --------------------
FILE_READ_RETRIES = 3
FILE_READ_RETRY_DELAY = 0.3
