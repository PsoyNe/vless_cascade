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
# Разные порты, чтобы потоки не конфликтовали (bind: address already in use)
PROXY_PORT_PRIMARY = 10808       # поток 1 — основная ссылка
PROXY_PORT_BACKUP = 10809        # поток 2 — резервные ссылки
PROXY_PORT_DEFERRED = 10810      # поток 3 — отложенные ссылки

# -------------------- ПРИОРИТЕТНАЯ СТРАНА --------------------
# Код страны (ISO 3166-1 alpha-2), например 'DE', 'NL', 'US'.
#
# Если задано — observer в первую очередь берёт ссылки с этой страной:
#   - при поиске основной ссылки при старте;
#   - при пополнении резерва из файла.
#
# Если пустая строка ('') — приоритета нет, все страны равны.
# Если код невалидный (не 2 буквы) — игнорируется, приоритет отключён.
#
# Примечание: приоритет — это НЕ ограничение. Если ссылок с этой страной
# нет или они мертвы, observer добирает ссылки из остальных стран.
PREFERRED_COUNTRY = ""

# -------------------- НАСТРОЙКИ МОНИТОРИНГА --------------------
CHECK_INTERVAL_PRIMARY = 5        # Проверка основной ссылки (сек)
CHECK_INTERVAL_BACKUP = 30        # Интервал между циклами проверки резерва (сек)
CHECK_INTERVAL_DEFERRED = 60      # Интервал проверки отложенных (сек)
CHECK_INTERVAL_POOL_UPDATE = 60   # Интервал попытки обновления пула (сек)

FAILURES_TO_SWITCH = 5            # Отказов подряд для переключения
BACKUP_POOL_SIZE = 4              # Размер резервного пула

# -------------------- ТАЙМАУТЫ --------------------
TEST_TIMEOUT = 8                  # Таймаут для основной ссылки
BACKUP_TEST_TIMEOUT = 4           # Таймаут для резервных (быстрее)
DEFERRED_TEST_TIMEOUT = 6         # Таймаут для отложенных

# -------------------- ОТЛОЖЕННЫЕ ССЫЛКИ --------------------
DEAD_LINK_RETRY_INTERVAL = 600    # 10 минут — перепроверка
DEAD_LINK_DELETE_AFTER = 7200     # 2 часа — удаление, если не ожила

# -------------------- ПЕРЕЧИТЫВАНИЕ ФАЙЛА --------------------
POOL_UPDATE_INTERVAL = 600        # 10 минут — реальное обновление из файла

# -------------------- ЗАЩИТА ОТ КРУГОВОРОТА --------------------
# Время (сек), в течение которого старая основная ссылка НЕ возвращается
# в резерв после переключения. Защита от ситуации, когда observer выкидывает
# ссылку из основной, а потом тут же берёт её обратно в резерв.
RECENTLY_PRIMARY_COOLDOWN = 60

# -------------------- ТРИГГЕРЫ --------------------
# Максимальный возраст файла-триггера (сек).
#
# Если триггер старше — он удаляется без выполнения. Это защита от ситуации,
# когда бот создал триггер, observer был недоступен (упал/перезапуск), а потом
# поднялся и выполнил бы устаревшую команду.
#
# Используется os.path.getmtime() — время последней модификации файла.
TRIGGER_MAX_AGE = 30

# -------------------- НАСТРОЙКИ ТЕСТИРОВАНИЯ (Google) --------------------
TEST_HOST = 'www.google.com'
TEST_PORT = 443
TEST_PATH = '/generate_204'
TEST_METHOD = 'HEAD'
TEST_BUFFER_SIZE = 1024
TEST_EXPECTED_STATUS = 204

# -------------------- НАСТРОЙКИ ГЛУБОКОЙ ПРОВЕРКИ (запрещённые сайты) --------------------
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

# -------------------- НАСТРОЙКИ TELEGRAM (опционально) --------------------
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
