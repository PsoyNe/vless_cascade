#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ============================================================
# КОНФИГУРАЦИОННЫЙ ФАЙЛ ДЛЯ VLESS ЧЕКЕРА
# ============================================================

# -------------------- ОБЩИЕ НАСТРОЙКИ --------------------
XRAY_PATH = "/usr/local/x-ui/bin/xray-linux-arm32"
DEFAULT_URL = "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/vless_configs.txt"

# -------------------- НАСТРОЙКИ ЭТАПА 1 (vless_checker.py) --------------------
STAGE1_WORKING_COUNT = 30        # Сколько ссылок сохранять в пул
STAGE1_MAX_WORKERS = 8
STAGE1_TIMEOUT = 10

# -------------------- НАСТРОЙКИ ЭТАПА 2 (server_tester.py) --------------------
STAGE2_TEST_DURATION = 180
STAGE2_CHECK_INTERVAL = 10
STAGE2_MAX_WORKERS = 8
STAGE2_TIMEOUT = 10
STAGE2_STABLE_UPTIME = 85
STAGE2_MAX_FAILURES = 3
STAGE2_MAX_FAIL_PERCENT = 10
STAGE2_MAX_PING = 3000
STAGE2_MIN_RESPONSE_SIZE = 5000
STAGE2_TARGET_COUNT = 9

# -------------------- НАСТРОЙКИ ТЕСТИРОВАНИЯ --------------------
TEST_PROTOCOL = 'https'
TEST_HOST = 'check.torproject.org'
TEST_PORT = 443
TEST_EXPECTED_STRING = b'You are not using Tor'
TEST_PATH = '/'
TEST_BUFFER_SIZE = 65536

# -------------------- НАСТРОЙКИ ФАЙЛОВ --------------------
WORKING_LINKS_FILE = "/root/vless_checker/working_links.txt"
STABLE_LINKS_10_FILE = "/root/vless_checker/stable_links.txt"
