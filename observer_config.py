#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ============================================================
# КОНФИГУРАЦИЯ ДЛЯ VLESS OBSERVER
# ============================================================

# -------------------- ПУТИ --------------------
XRAY_PATH = "/usr/local/x-ui/bin/xray-linux-arm32"
DB_PATH = "/etc/x-ui/x-ui.db"
LINKS_FILE = "/root/vless_checker/working_links.txt"
STATE_FILE = "/root/vless_observer/observer_state.json"
LOG_FILE = "/var/log/vless_observer.log"

# -------------------- ПОРТЫ XRAY --------------------
PROXY_PORT_PRIMARY = 10808       # поток 1 — основная ссылка
PROXY_PORT_BACKUP = 10809        # поток 2 — резервные ссылки
PROXY_PORT_DEFERRED = 10810      # поток 3 — отложенные ссылки

# -------------------- ПРИОРИТЕТНАЯ СТРАНА --------------------
PREFERRED_COUNTRY = ""

# -------------------- НАСТРОЙКИ МОНИТОРИНГА --------------------
CHECK_INTERVAL_PRIMARY = 5        # Проверка основной ссылки (сек)
CHECK_INTERVAL_BACKUP = 30        # Интервал между циклами проверки резерва (сек)
CHECK_INTERVAL_DEFERRED = 60      # Интервал проверки отложенных (сек)
CHECK_INTERVAL_POOL_UPDATE = 60   # Интервал попытки обновления пула (сек)

FAILURES_TO_SWITCH = 3            # Отказов подряд для переключения
BACKUP_POOL_SIZE = 4              # Размер резервного пула

# -------------------- ТАЙМАУТЫ --------------------
TEST_TIMEOUT = 8                  # Таймаут для основной ссылки
BACKUP_TEST_TIMEOUT = 4           # Таймаут для резервных (быстрее)
DEFERRED_TEST_TIMEOUT = 6         # Таймаут для отложенных

# -------------------- ДВОЙНАЯ ПРОВЕРКА РЕЗЕРВА --------------------
BACKUP_CHECK_ATTEMPTS = 2
BACKUP_CHECK_INTERVAL = 2

# -------------------- ОТЛОЖЕННЫЕ ССЫЛКИ --------------------
DEAD_LINK_RETRY_INTERVAL = 600    # 10 минут — перепроверка
DEAD_LINK_DELETE_AFTER = 7200     # 2 часа — удаление, если не ожила

# -------------------- ПЕРЕЧИТЫВАНИЕ ФАЙЛА --------------------
POOL_UPDATE_INTERVAL = 600        # 10 минут — реальное обновление из файла

# -------------------- ЗАЩИТА ОТ КРУГОВОРОТА --------------------
RECENTLY_PRIMARY_COOLDOWN = 60

# -------------------- ТРИГГЕРЫ --------------------
TRIGGER_MAX_AGE = 30

# -------------------- НАСТРОЙКИ ТЕСТИРОВАНИЯ (Google) --------------------
TEST_HOST = 'www.google.com'
TEST_PORT = 443
TEST_PATH = '/generate_204'
TEST_METHOD = 'HEAD'
TEST_BUFFER_SIZE = 1024
TEST_EXPECTED_STATUS = 204

# -------------------- НАСТРОЙКИ ГЛУБОКОЙ ПРОВЕРКИ --------------------
DEEP_CHECK_HOSTS = [
    'www.instagram.com',
    'www.facebook.com',
    'check.torproject.org',
]

DEEP_CHECK_PORT = 443
DEEP_CHECK_PATH = '/'
DEEP_CHECK_METHOD = 'HEAD'
DEEP_CHECK_TIMEOUT = 10
DEEP_CHECK_EXPECTED_STRING = b'HTTP/'

# -------------------- НАСТРОЙКИ 3X-UI --------------------
OUTBOUND_NAME = "vless_obs"

# -------------------- НАСТРОЙКИ TELEGRAM --------------------
TELEGRAM_ENABLED = False
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# -------------------- НАСТРОЙКИ СЛУЖБЫ --------------------
SERVICE_NAME = "vless_observer"
SERVICE_DESCRIPTION = "VLESS Observer - automatic outbound monitoring and switching"

# -------------------- РОТАЦИЯ ЛОГОВ --------------------
LOG_ROTATION_WHEN = "midnight"
LOG_ROTATION_INTERVAL = 1
LOG_ROTATION_BACKUPS = 7
LOG_ROTATION_UTCFORMAT = "%Y-%m-%d"

# -------------------- АТОМАРНОЕ ЧТЕНИЕ ФАЙЛОВ --------------------
FILE_READ_RETRIES = 3
FILE_READ_RETRY_DELAY = 0.3

# ============================================================
# НОВЫЕ НАСТРОЙКИ: ШТРАФНОЙ СПИСОК (PENALTY BOX)
# ============================================================
PENALTY_ENABLED = True
PENALTY_TIME = 1800             # 30 минут (в секундах) держим ссылку в изоляции
PENALTY_MAX_FAILS = 3           # После 3 провалов ссылка уходит в мертвые
PRIMARY_GRACE_PERIOD = 180      # 3 минуты. Если упала в первые 3 минуты — это провал нагрузки
