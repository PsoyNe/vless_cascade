#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sqlite3
import os
import sys
import time
import logging
import logging.handlers
import subprocess
import signal
import socket
import socks
import ssl
import re
import tempfile
import shutil
import threading
from urllib.parse import unquote
from datetime import datetime
from typing import List, Tuple, Optional, Dict

from observer_config import *

# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_FILE,
    when=LOG_ROTATION_WHEN,
    interval=LOG_ROTATION_INTERVAL,
    backupCount=LOG_ROTATION_BACKUPS,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S'))
file_handler.suffix = LOG_ROTATION_UTCFORMAT
logger.addHandler(file_handler)

if sys.stdout.isatty():
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S'))
    logger.addHandler(console_handler)


# ============================================================
# ГЛОБАЛЬНЫЙ ФЛАГ ОСТАНОВКИ
# ============================================================
_shutdown_requested = threading.Event()


def _handle_sigterm(signum, frame):
    logger.info(f"🛑 Получен сигнал {signum} — завершаем работу...")
    _shutdown_requested.set()


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def read_links_file(path: str) -> List[str]:
    for attempt in range(FILE_READ_RETRIES):
        try:
            if not os.path.exists(path):
                time.sleep(FILE_READ_RETRY_DELAY)
                continue
            with open(path, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip().startswith('vless://')]
            if lines:
                return lines
            time.sleep(FILE_READ_RETRY_DELAY)
        except Exception as e:
            logger.error(f"Ошибка чтения {path}: {e}")
            time.sleep(FILE_READ_RETRY_DELAY)
    return []


def validate_reality_params(params: dict) -> Tuple[bool, str]:
    security = params.get('security', '').lower()
    if security != 'reality':
        return True, ''

    pbk = params.get('pbk', '').strip()
    if not pbk:
        return False, 'пустой publicKey (pbk)'

    sid = params.get('sid', '').strip()
    if sid and len(sid) > 16:
        return False, f'подозрительная длина shortId: {len(sid)}'

    sni = params.get('sni', '').strip()
    if not sni:
        return False, 'пустой serverName (sni)'

    return True, ''


def parse_vless_link(link: str) -> Optional[dict]:
    try:
        if not link.startswith('vless://'):
            return None
        link_without_protocol = link[8:]
        if '@' not in link_without_protocol:
            return None
        uuid, after_at = link_without_protocol.split('@', 1)
        if ':' not in after_at:
            return None
        host_port, rest = after_at.split(':', 1)
        if '?' in rest:
            port, params_str = rest.split('?', 1)
        else:
            port = rest
            params_str = ''
        params = {}
        if params_str:
            if '#' in params_str:
                params_str = params_str.split('#')[0]
            for param in params_str.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key] = unquote(value)
        return {
            'uuid': uuid,
            'host': host_port,
            'port': int(port),
            'params': params
        }
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return None


def create_xray_config(link: str, proxy_port: int) -> dict:
    parsed = parse_vless_link(link)
    if not parsed:
        raise ValueError("Неверный формат vless ссылки")

    ok, reason = validate_reality_params(parsed['params'])
    if not ok:
        raise ValueError(f"Невалидная Reality-ссылка: {reason}")

    uuid = parsed['uuid']
    host = parsed['host']
    port = parsed['port']

    reality_settings = {
        "serverName": parsed['params'].get('sni', host),
        "fingerprint": parsed['params'].get('fp', 'chrome'),
        "publicKey": parsed['params'].get('pbk', ''),
        "shortId": parsed['params'].get('sid', ''),
        "spiderX": "",
        "mldsa65Verify": ""
    }

    spx = parsed['params'].get('spx', '')
    if spx:
        spx_clean = re.sub(r'[^a-zA-Z0-9/]', '', spx)
        if spx_clean:
            reality_settings["spiderX"] = spx_clean

    config = {
        "log": {"loglevel": "error"},
        "inbounds": [{
            "port": proxy_port,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True}
        }],
        "outbounds": [{
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": host,
                    "port": port,
                    "users": [{
                        "id": uuid,
                        "encryption": parsed['params'].get('encryption', 'none'),
                        "flow": parsed['params'].get('flow', ''),
                        "level": 0
                    }]
                }]
            },
            "streamSettings": {
                "network": parsed['params'].get('type', 'tcp'),
                "security": parsed['params'].get('security', 'reality'),
                "tcpSettings": {"header": {"type": "none"}},
                "realitySettings": reality_settings
            }
        }]
    }

    if 'streamSettings' in config['outbounds'][0]:
        stream = config['outbounds'][0]['streamSettings']
        if stream.get('realitySettings') is None:
            del stream['realitySettings']

    return config


def start_xray(config_path: str, xray_path: str = XRAY_PATH) -> subprocess.Popen:
    cmd = [xray_path, "-config", config_path]
    env = os.environ.copy()
    env['XRAY_LOCATION_ASSET'] = '/usr/local/share/xray'

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid if hasattr(os, 'setsid') else None,
        env=env
    )

    return process


def wait_for_xray_port(proxy_port: int, timeout: float = 3.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if _shutdown_requested.is_set():
            return False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.2)
            result = sock.connect_ex(('127.0.0.1', proxy_port))
            sock.close()
            if result == 0:
                return True
        except:
            pass
        time.sleep(0.05)
    return False


def _kill_process(process: subprocess.Popen):
    """Безопасное убийство процесса с ожиданием завершения."""
    if process is None:
        return
    try:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    except Exception:
        pass


def test_link_through_xray(link: str, proxy_port: int, timeout: int = TEST_TIMEOUT) -> Tuple[bool, float, int]:
    temp_dir = tempfile.mkdtemp(prefix="observer_test_")
    process = None
    s = None
    start_time = time.time()

    try:
        config = create_xray_config(link, proxy_port)
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        process = start_xray(config_path)

        if not wait_for_xray_port(proxy_port, timeout=3.0):
            return (False, 0, 0)

        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, "127.0.0.1", proxy_port)
        s.settimeout(timeout)

        s.connect((TEST_HOST, TEST_PORT))

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        ssl_sock = context.wrap_socket(s, server_hostname=TEST_HOST)
        s = ssl_sock

        request = f"HEAD {TEST_PATH} HTTP/1.1\r\nHost: {TEST_HOST}\r\nConnection: close\r\n\r\n".encode()
        s.send(request)

        response = s.recv(TEST_BUFFER_SIZE)
        elapsed = (time.time() - start_time) * 1000

        if response and (b"204" in response or b"200" in response):
            return (True, elapsed, len(response))
        else:
            return (False, elapsed, len(response))

    except Exception:
        elapsed = (time.time() - start_time) * 1000
        return (False, elapsed, 0)
    finally:
        if s:
            try:
                s.close()
            except:
                pass
        _kill_process(process)
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass


def test_link_deep(link: str, proxy_port: int, timeout: int = DEEP_CHECK_TIMEOUT) -> Tuple[bool, float, str]:
    temp_dir = tempfile.mkdtemp(prefix="observer_deep_")
    process = None
    start_time = time.time()

    try:
        config = create_xray_config(link, proxy_port)
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        process = start_xray(config_path)

        if not wait_for_xray_port(proxy_port, timeout=3.0):
            return (False, 0, "")

        for test_host in DEEP_CHECK_HOSTS:
            if _shutdown_requested.is_set():
                return (False, 0, "")
            s = None
            try:
                start_time = time.time()
                s = socks.socksocket()
                s.set_proxy(socks.SOCKS5, "127.0.0.1", proxy_port)
                s.settimeout(timeout)

                s.connect((test_host, DEEP_CHECK_PORT))

                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE

                ssl_sock = context.wrap_socket(s, server_hostname=test_host)
                s = ssl_sock

                request = f"HEAD {DEEP_CHECK_PATH} HTTP/1.1\r\nHost: {test_host}\r\nConnection: close\r\n\r\n".encode()
                s.send(request)

                response = s.recv(TEST_BUFFER_SIZE)
                elapsed = (time.time() - start_time) * 1000

                if response and DEEP_CHECK_EXPECTED_STRING in response:
                    logger.info(f"✅ Глубокая проверка: {test_host} доступен ({elapsed:.0f}мс)")
                    return (True, elapsed, test_host)
                else:
                    logger.warning(f"⚠️ Глубокая проверка: {test_host} не ответил")
            except Exception as e:
                logger.warning(f"⚠️ Глубокая проверка: {test_host} ошибка — {str(e)[:50]}")
            finally:
                if s:
                    try:
                        s.close()
                    except:
                        pass

        return (False, 0, "")

    except Exception as e:
        logger.error(f"Ошибка глубокой проверки: {e}")
        return (False, 0, "")
    finally:
        _kill_process(process)
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass


def create_outbound_config(link: str, name: str) -> Optional[dict]:
    parsed = parse_vless_link(link)
    if not parsed:
        return None

    ok, reason = validate_reality_params(parsed['params'])
    if not ok:
        logger.error(f"Невалидная ссылка для outbound: {reason}")
        return None

    reality_settings = {
        "serverName": parsed['params'].get('sni', parsed['host']),
        "fingerprint": parsed['params'].get('fp', 'chrome'),
        "publicKey": parsed['params'].get('pbk', ''),
        "shortId": parsed['params'].get('sid', ''),
        "spiderX": "",
        "mldsa65Verify": ""
    }
    spx = parsed['params'].get('spx', '')
    if spx:
        spx_clean = re.sub(r'[^a-zA-Z0-9/]', '', spx)
        if spx_clean:
            reality_settings["spiderX"] = spx_clean

    outbound = {
        "tag": name,
        "protocol": "vless",
        "settings": {
            "address": parsed['host'],
            "port": parsed['port'],
            "id": parsed['uuid'],
            "flow": parsed['params'].get('flow', ''),
            "encryption": parsed['params'].get('encryption', 'none'),
            "testseed": [900, 500, 900, 256]
        },
        "streamSettings": {
            "network": parsed['params'].get('type', 'tcp'),
            "security": parsed['params'].get('security', 'reality'),
            "tcpSettings": {
                "header": {
                    "type": "none"
                }
            },
            "realitySettings": reality_settings
        }
    }
    return outbound


def update_3xui_outbound(link: str, name: str = OUTBOUND_NAME) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'xrayTemplateConfig'")
        row = cursor.fetchone()
        if not row:
            logger.error("xrayTemplateConfig не найден!")
            conn.close()
            return False
        config = json.loads(row[0])
        outbounds = config.get('outbounds', [])
        new_outbound = create_outbound_config(link, name)
        if not new_outbound:
            logger.error(f"Не удалось создать конфиг для {name}")
            conn.close()
            return False
        found = False
        for i, outbound in enumerate(outbounds):
            if outbound.get('tag') == name:
                outbounds[i] = new_outbound
                found = True
                logger.info(f"✅ Обновлен outbound: {name}")
                break
        if not found:
            outbounds.append(new_outbound)
            logger.info(f"➕ Добавлен outbound: {name}")
        config['outbounds'] = outbounds
        cursor.execute(
            "UPDATE settings SET value = ? WHERE key = 'xrayTemplateConfig'",
            (json.dumps(config, indent=2),)
        )
        conn.commit()
        conn.close()
        logger.info(f"✅ Outbound {name} обновлен в БД")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка обновления 3x-ui: {e}")
        return False


def reload_xray() -> bool:
    try:
        result = subprocess.run(
            ['systemctl', 'restart', 'x-ui'],
            capture_output=True,
            text=True,
            timeout=15
        )
        if result.returncode == 0:
            logger.info("✅ x-ui перезапущен через systemctl")
            return True
        else:
            logger.error(f"❌ systemctl restart x-ui вернул {result.returncode}: {result.stderr.strip()[:200]}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("❌ Таймаут перезапуска x-ui (15 сек)")
        return False
    except Exception as e:
        logger.error(f"❌ Не удалось перезапустить x-ui: {e}")
        return False


# ============================================================
# ОСНОВНОЙ КЛАСС
# ============================================================

class VlessObserver:
    def __init__(self):
        self.links = []
        self.primary = None
        self.backup_pool = []

        # Защита от гонок
        self.primary_lock = threading.Lock()
        self.pool_lock = threading.Lock()
        self.deferred_lock = threading.Lock()
        self.stats_lock = threading.Lock()
        self.dead_links_lock = threading.Lock()

        self.primary_stats = {'fail_count': 0, 'success_count': 0}
        self.switch_count = 0

        self.last_log_time = 0
        self.last_state = ""
        self.last_primary_host = ""
        self.critical_error_logged = False
        self.backup_check_counter = 0
        self.last_pool_refill_time = 0
        self.last_pool_update_time = 0
        self.waiting_for_links = False

        self.trigger_file = "/tmp/vless_observer_trigger"
        self.quarantine_trigger = "/tmp/vless_quarantine_trigger"
        self.deep_check_trigger = "/tmp/vless_deep_check_trigger"
        self.quarantine_file = "/root/vless_checker/quarantine_links.txt"

        # deferred_links: {link: {'deferred_at': ts, 'last_checked_at': ts}}
        self.deferred_links = {}
        self.dead_links = set()

        self.switching = threading.Event()

    # --------------------------------------------------------
    # Загрузка и инициализация
    # --------------------------------------------------------

    def load_links(self) -> bool:
        self.links = read_links_file(LINKS_FILE)
        if not self.links:
            logger.warning(f"⚠️ Файл {LINKS_FILE} пуст или не найден! Ожидание...")
            return False
        if len(self.links) < 2:
            logger.warning(f"⚠️ В файле меньше 2 ссылок: {len(self.links)}. Ожидание...")
            return False
        logger.info(f"✅ Загружено {len(self.links)} ссылок")
        return True

    def wait_for_links(self) -> bool:
        logger.info("⏳ Ожидание появления ссылок в рабочем файле...")
        self.waiting_for_links = True

        while self.waiting_for_links and not _shutdown_requested.is_set():
            links = read_links_file(LINKS_FILE)
            if len(links) >= 2:
                self.links = links
                logger.info(f"✅ Появилось {len(self.links)} ссылок. Продолжаем работу.")
                self.waiting_for_links = False
                return True

            logger.info(f"⏳ Ссылок пока нет ({len(links)}), проверка через 60 секунд...")
            for _ in range(60):
                if _shutdown_requested.is_set():
                    return False
                time.sleep(1)

        return False

    def load_quarantine(self) -> set:
        quarantine = set()
        try:
            if os.path.exists(self.quarantine_file):
                with open(self.quarantine_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        link = line.strip()
                        if link.startswith('vless://'):
                            quarantine.add(link)
        except Exception as e:
            logger.error(f"Ошибка загрузки карантина: {e}")
        return quarantine

    def init_pool(self):
        with self.primary_lock:
            self.primary = self.links[0]

        parsed_primary = parse_vless_link(self.primary)
        if not parsed_primary:
            logger.error("❌ Не удалось распарсить основную ссылку!")
            return

        ok, reason = validate_reality_params(parsed_primary['params'])
        if not ok:
            logger.error(f"❌ Основная ссылка невалидна: {reason}")
            return

        with self.pool_lock:
            self.backup_pool = []
            for link in self.links[1:]:
                parsed = parse_vless_link(link)
                if not parsed:
                    continue
                ok, reason = validate_reality_params(parsed['params'])
                if not ok:
                    logger.warning(f"⚠️ Пропуск невалидной ссылки {parsed['host']}: {reason}")
                    with self.dead_links_lock:
                        self.dead_links.add(link)
                    continue
                self.backup_pool.append({
                    'link': link,
                    'host': parsed['host'],
                    'alive': True,
                    'ping': 0
                })
                if len(self.backup_pool) >= BACKUP_POOL_SIZE:
                    break

        primary_host = parsed_primary['host']
        logger.info(f"Установка основной: {primary_host}")

        if update_3xui_outbound(self.primary, OUTBOUND_NAME):
            reload_xray()

        logger.info(f"Резерв: {len(self.backup_pool)} ссылок")
        for item in self.backup_pool:
            logger.info(f"  - {item['host']}")

        self.last_primary_host = primary_host
        self.last_state = f"OK | основная: {primary_host} | резерв: {len(self.backup_pool)}"
        self.last_log_time = time.time()
        logger.info(self.last_state)
        self.critical_error_logged = False
        self.last_pool_refill_time = time.time()
        self.last_pool_update_time = time.time()

    # --------------------------------------------------------
    # Логирование статуса
    # --------------------------------------------------------

    def log_status(self, force: bool = False):
        current_time = time.time()

        with self.primary_lock:
            primary = self.primary
        parsed = parse_vless_link(primary) if primary else None
        primary_host = parsed['host'] if parsed else 'NONE'

        with self.pool_lock:
            alive_count = len([item for item in self.backup_pool if item.get('alive', False)])
            total_backup = len(self.backup_pool)

        with self.deferred_lock:
            deferred_count = len(self.deferred_links)

        with self.stats_lock:
            switch_count = self.switch_count

        state = f"OK | {primary_host} | резерв: {alive_count}/{total_backup} живых | отложено: {deferred_count} | перекл: {switch_count}"

        if force or state != self.last_state or (current_time - self.last_log_time) >= 60:
            logger.info(state)
            self.last_state = state
            self.last_log_time = current_time
            self.last_primary_host = primary_host

    # --------------------------------------------------------
    # ПОТОК 1: проверка основной ссылки
    # --------------------------------------------------------

    def primary_loop(self):
        logger.info("▶️ Поток 1 (основная) запущен")

        while not _shutdown_requested.is_set():
            try:
                self.test_primary()
                self.log_status()
            except Exception as e:
                logger.error(f"❌ Ошибка в потоке основной: {e}")
                import traceback
                logger.error(traceback.format_exc())

            for _ in range(CHECK_INTERVAL_PRIMARY):
                if _shutdown_requested.is_set():
                    break
                time.sleep(1)

        logger.info("⏹️ Поток 1 (основная) завершён")

    def test_primary(self):
        if self.check_deep_check_trigger():
            return
        if self.check_quarantine_trigger():
            return
        if self.check_trigger_file():
            logger.warning(f"❌ ИМИТАЦИЯ 2 ОТКАЗОВ: переключение...")
            self.switch_to_backup()
            self.log_status(force=True)
            return

        with self.primary_lock:
            primary = self.primary

        is_working, ping, size = test_link_through_xray(
            primary,
            PROXY_PORT_PRIMARY,
            timeout=TEST_TIMEOUT
        )

        if is_working:
            with self.stats_lock:
                self.primary_stats['success_count'] += 1
                self.primary_stats['fail_count'] = 0
            self.critical_error_logged = False
            logger.debug(f"✅ Основная ссылка работает (пинг: {ping:.0f}мс)")
        else:
            with self.stats_lock:
                self.primary_stats['fail_count'] += 1
                fail_count = self.primary_stats['fail_count']

            logger.warning(f"❌ Отказ основной ссылки ({fail_count}/{FAILURES_TO_SWITCH})")

            if fail_count >= FAILURES_TO_SWITCH:
                self.switch_to_backup()
                self.log_status(force=True)

    # --------------------------------------------------------
    # ПОТОК 2: проверка резерва
    # --------------------------------------------------------

    def backup_loop(self):
        logger.info("▶️ Поток 2 (резерв) запущен")

        first_run = True

        while not _shutdown_requested.is_set():
            try:
                if not first_run:
                    for _ in range(CHECK_INTERVAL_BACKUP):
                        if _shutdown_requested.is_set():
                            break
                        time.sleep(1)

                if _shutdown_requested.is_set():
                    break

                if self.switching.is_set():
                    logger.info("⏸️ Поток 2 ждёт завершения переключения...")
                    self.switching.wait(timeout=30)

                self.test_backup_pool()
                self.log_status()
                first_run = False

            except Exception as e:
                logger.error(f"❌ Ошибка в потоке резерва: {e}")
                import traceback
                logger.error(traceback.format_exc())

        logger.info("⏹️ Поток 2 (резерв) завершён")

    def test_backup_pool(self):
        with self.pool_lock:
            backup_snapshot = list(self.backup_pool)

        if not backup_snapshot:
            self.refill_pool_excluding_deferred()
            return

        self.backup_check_counter += 1

        dead_links = []
        ping_updates = {}

        for item in backup_snapshot:
            if _shutdown_requested.is_set():
                break

            is_working, ping, size = test_link_through_xray(
                item['link'],
                PROXY_PORT_BACKUP,
                timeout=BACKUP_TEST_TIMEOUT
            )

            if is_working:
                ping_updates[item['link']] = (True, ping)
            else:
                ping_updates[item['link']] = (False, 0)
                dead_links.append(item['link'])
                logger.warning(f"⚠️ Резервная ссылка {item['host']} мертва! Откладываем на 10 минут")

        with self.pool_lock:
            for item in self.backup_pool:
                if item['link'] in ping_updates:
                    alive, ping = ping_updates[item['link']]
                    item['alive'] = alive
                    item['ping'] = ping

            if dead_links:
                self.backup_pool = [item for item in self.backup_pool if item['link'] not in dead_links]

        if dead_links:
            current_time = time.time()
            with self.deferred_lock:
                for link in dead_links:
                    # Структура: {'deferred_at': ..., 'last_checked_at': ...}
                    self.deferred_links[link] = {
                        'deferred_at': current_time,
                        'last_checked_at': current_time,
                    }

            logger.warning(f"⚠️ Отложено {len(dead_links)} ссылок")

            with self.pool_lock:
                need_refill = len(self.backup_pool) < BACKUP_POOL_SIZE
            if need_refill:
                self.refill_pool_excluding_deferred()

        with self.pool_lock:
            self.backup_pool.sort(key=lambda x: (not x.get('alive', False), x.get('ping', 9999)))
            alive_count = len([item for item in self.backup_pool if item.get('alive', False)])
            total = len(self.backup_pool)

        if alive_count == 0 and total > 0:
            logger.warning("⚠️ Все резервные ссылки мертвы! Пополнение пула...")
            self.refill_pool_excluding_deferred()

    # --------------------------------------------------------
    # ПОТОК 3: отложенные + обновление пула
    # --------------------------------------------------------

    def maintenance_loop(self):
        logger.info("▶️ Поток 3 (deferred + pool update) запущен")

        last_deferred_check = 0
        last_pool_update = 0

        while not _shutdown_requested.is_set():
            try:
                current_time = time.time()

                if current_time - last_deferred_check >= CHECK_INTERVAL_DEFERRED:
                    self.check_deferred_links()
                    last_deferred_check = current_time

                if current_time - last_pool_update >= CHECK_INTERVAL_POOL_UPDATE:
                    self.update_pool_from_file()
                    last_pool_update = current_time

            except Exception as e:
                logger.error(f"❌ Ошибка в потоке maintenance: {e}")
                import traceback
                logger.error(traceback.format_exc())

            for _ in range(CHECK_INTERVAL_DEFERRED):
                if _shutdown_requested.is_set():
                    break
                time.sleep(1)

        logger.info("⏹️ Поток 3 (deferred + pool update) завершён")

    def check_deferred_links(self):
        with self.deferred_lock:
            if not self.deferred_links:
                return
            current_time = time.time()
            to_check = []
            to_delete = []
            original = dict(self.deferred_links)

        # Определяем, кого проверять и кого удалять
        # - total_elapsed >= DEAD_LINK_DELETE_AFTER (2 часа) → удалить
        # - since_last_check >= DEAD_LINK_RETRY_INTERVAL (10 минут) → проверить
        for link, info in original.items():
            deferred_at = info['deferred_at']
            last_checked_at = info['last_checked_at']

            total_elapsed = current_time - deferred_at
            since_last_check = current_time - last_checked_at

            if total_elapsed >= DEAD_LINK_DELETE_AFTER:
                to_delete.append(link)
            elif since_last_check >= DEAD_LINK_RETRY_INTERVAL:
                to_check.append(link)

        # Удаление отложенных, не оживших за 2 часа
        if to_delete:
            with self.deferred_lock:
                for link in to_delete:
                    if link in self.deferred_links:
                        del self.deferred_links[link]

            for link in to_delete:
                with self.dead_links_lock:
                    self.dead_links.add(link)
                parsed = parse_vless_link(link)
                host = parsed['host'] if parsed else 'unknown'
                logger.warning(f"🗑️ Ссылка {host} не ожила за 2 часа — удалена из пула")

        # Перепроверка отложенных
        if to_check:
            logger.info(f"🔄 Проверяем {len(to_check)} отложенных ссылок...")

            for link in to_check:
                if _shutdown_requested.is_set():
                    break

                is_working, ping, size = test_link_through_xray(
                    link,
                    PROXY_PORT_DEFERRED,
                    timeout=DEFERRED_TEST_TIMEOUT
                )

                parsed = parse_vless_link(link)
                host = parsed['host'] if parsed else 'unknown'

                with self.deferred_lock:
                    info = self.deferred_links.get(link)
                    if info is None:
                        continue
                    total_elapsed_min = int((current_time - info['deferred_at']) / 60)

                if is_working:
                    # Ссылка ожила — убираем из deferred
                    with self.deferred_lock:
                        if link in self.deferred_links:
                            del self.deferred_links[link]

                    # Убираем из dead_links (если она там была — теперь живая)
                    with self.dead_links_lock:
                        self.dead_links.discard(link)

                    logger.info(f"✅ Отложенная ссылка {host} ожила! Пинг: {ping:.0f}мс (была в отложенных {total_elapsed_min} мин)")

                    with self.pool_lock:
                        existing_links = [item['link'] for item in self.backup_pool]
                        if link not in existing_links and len(self.backup_pool) < BACKUP_POOL_SIZE:
                            self.backup_pool.append({
                                'link': link,
                                'host': host,
                                'alive': True,
                                'ping': ping
                            })
                            logger.info(f"➕ Ссылка {host} возвращена в резерв")
                        else:
                            logger.info(f"↩️ Ссылка {host} ожила, но пул полный — возвращена в общий оборот")
                else:
                    # Ссылка всё ещё мертва — обновляем last_checked_at
                    # (deferred_at НЕ трогаем — он для удаления через 2 часа)
                    with self.deferred_lock:
                        if link in self.deferred_links:
                            self.deferred_links[link]['last_checked_at'] = time.time()

                    logger.warning(f"❌ Отложенная ссылка {host} всё ещё мертва ({total_elapsed_min} мин в deferred)")

    def update_pool_from_file(self):
        current_time = time.time()
        if current_time - self.last_pool_update_time < POOL_UPDATE_INTERVAL:
            return

        all_links = read_links_file(LINKS_FILE)
        if len(all_links) < 2:
            self.last_pool_update_time = current_time
            return

        try:
            quarantine = self.load_quarantine()

            with self.primary_lock:
                current_primary = self.primary

            with self.pool_lock:
                current_links = set()
                if current_primary:
                    current_links.add(current_primary)
                for item in self.backup_pool:
                    current_links.add(item['link'])

                with self.deferred_lock:
                    deferred_set = set(self.deferred_links.keys())

                with self.dead_links_lock:
                    dead_set = set(self.dead_links)

                new_links = [
                    l for l in all_links
                    if l not in current_links
                    and l not in dead_set
                    and l not in deferred_set
                    and l not in quarantine
                ]

                if not new_links:
                    self.last_pool_update_time = current_time
                    return

                logger.info(f"📥 Найдено {len(new_links)} новых ссылок")
                added_count = 0

                for link in new_links:
                    if len(self.backup_pool) >= BACKUP_POOL_SIZE:
                        break
                    parsed = parse_vless_link(link)
                    if not parsed:
                        continue
                    ok, reason = validate_reality_params(parsed['params'])
                    if not ok:
                        with self.dead_links_lock:
                            self.dead_links.add(link)
                        continue
                    self.backup_pool.append({
                        'link': link,
                        'host': parsed['host'],
                        'alive': True,
                        'ping': 0
                    })
                    added_count += 1
                    logger.info(f"➕ Добавлена новая резервная: {parsed['host']}")

            if added_count > 0:
                logger.info(f"✅ Добавлено {added_count} новых ссылок")
                self.log_status(force=True)

            self.last_pool_update_time = current_time

        except Exception as e:
            logger.error(f"❌ Ошибка обновления пула: {e}")
            self.last_pool_update_time = current_time

    def refill_pool_excluding_deferred(self):
        all_links = read_links_file(LINKS_FILE)
        if not all_links:
            return

        try:
            quarantine = self.load_quarantine()

            with self.primary_lock:
                current = self.primary

            with self.pool_lock:
                existing_links = [item['link'] for item in self.backup_pool]
                with self.deferred_lock:
                    deferred_set = set(self.deferred_links.keys())
                with self.dead_links_lock:
                    dead_set = set(self.dead_links)

                available = [
                    l for l in all_links
                    if l != current
                    and l not in existing_links
                    and l not in deferred_set
                    and l not in dead_set
                    and l not in quarantine
                ]

                if not available:
                    return

                for link in available[:BACKUP_POOL_SIZE - len(self.backup_pool)]:
                    parsed = parse_vless_link(link)
                    if not parsed:
                        continue
                    ok, reason = validate_reality_params(parsed['params'])
                    if not ok:
                        with self.dead_links_lock:
                            self.dead_links.add(link)
                        continue
                    self.backup_pool.append({
                        'link': link,
                        'host': parsed['host'],
                        'alive': True,
                        'ping': 0
                    })
                    logger.info(f"➕ Добавлена новая резервная: {parsed['host']}")

            self.last_pool_refill_time = time.time()

        except Exception as e:
            logger.error(f"❌ Ошибка пополнения пула: {e}")

    # --------------------------------------------------------
    # Триггеры
    # --------------------------------------------------------

    def check_trigger_file(self) -> bool:
        if os.path.exists(self.trigger_file):
            try:
                os.remove(self.trigger_file)
                logger.warning(f"⚠️ ТРИГГЕР: имитация отказов")
                with self.stats_lock:
                    self.primary_stats['fail_count'] = FAILURES_TO_SWITCH
                return True
            except Exception as e:
                logger.error(f"Ошибка удаления триггер-файла: {e}")
        return False

    def check_quarantine_trigger(self) -> bool:
        if os.path.exists(self.quarantine_trigger):
            try:
                os.remove(self.quarantine_trigger)
                logger.warning(f"⚠️ КАРАНТИН триггер")
                self.move_primary_to_quarantine()
                return True
            except Exception as e:
                logger.error(f"Ошибка удаления триггера карантина: {e}")
        return False

    def check_deep_check_trigger(self) -> bool:
        if os.path.exists(self.deep_check_trigger):
            try:
                os.remove(self.deep_check_trigger)
                logger.warning(f"⚠️ ГЛУБОКАЯ ПРОВЕРКА триггер")
                self.perform_deep_check()
                return True
            except Exception as e:
                logger.error(f"Ошибка удаления триггера глубокой проверки: {e}")
        return False

    def perform_deep_check(self):
        with self.primary_lock:
            primary = self.primary

        if not primary:
            logger.warning("Нет основной ссылки для глубокой проверки")
            return

        parsed = parse_vless_link(primary)
        primary_host = parsed['host'] if parsed else 'unknown'
        logger.info(f"🔍 ГЛУБОКАЯ ПРОВЕРКА: {primary_host}")

        logger.info(f"  Шаг 1: Google...")
        google_ok, google_ping, _ = test_link_through_xray(
            primary, PROXY_PORT_PRIMARY, timeout=TEST_TIMEOUT
        )
        if google_ok:
            logger.info(f"  ✅ Google доступен ({google_ping:.0f}мс)")
        else:
            logger.warning(f"  ❌ Google НЕдоступен")

        logger.info(f"  Шаг 2: Запрещённые ресурсы...")
        deep_ok, deep_ping, deep_host = test_link_deep(
            primary, PROXY_PORT_PRIMARY, timeout=DEEP_CHECK_TIMEOUT
        )
        if deep_ok:
            logger.info(f"  ✅ Запрещённый доступен: {deep_host} ({deep_ping:.0f}мс)")
        else:
            logger.warning(f"  ❌ Ни один запрещённый НЕдоступен")

        if google_ok and not deep_ok:
            logger.warning(f"  ⚠️ ССЫЛКА РАБОТАЕТ ТОЛЬКО НА GOOGLE!")
            logger.warning(f"  🛑 Отправляем в карантин...")
            self.move_primary_to_quarantine()
        elif google_ok and deep_ok:
            logger.info(f"  ✅ Ссылка работает нормально")
        elif not google_ok:
            logger.warning(f"  ⚠️ Ссылка не работает даже на Google")
            with self.stats_lock:
                self.primary_stats['fail_count'] += 1
                fail_count = self.primary_stats['fail_count']
            if fail_count >= FAILURES_TO_SWITCH:
                self.switch_to_backup()

    def move_primary_to_quarantine(self):
        with self.primary_lock:
            old_primary = self.primary

        if not old_primary:
            logger.warning("Нет основной ссылки")
            return

        parsed = parse_vless_link(old_primary)
        old_host = parsed['host'] if parsed else 'unknown'

        logger.warning(f"🛑 КАРАНТИН: {old_host}")

        try:
            os.makedirs(os.path.dirname(self.quarantine_file), exist_ok=True)
            with open(self.quarantine_file, 'a', encoding='utf-8') as f:
                f.write(f"{old_primary}\n")
            logger.info(f"✅ Ссылка добавлена в карантин")
        except Exception as e:
            logger.error(f"❌ Ошибка записи в карантин: {e}")

        with self.dead_links_lock:
            self.dead_links.add(old_primary)

        with self.pool_lock:
            self.backup_pool = [item for item in self.backup_pool if item['link'] != old_primary]
        self.switch_to_backup()

    # --------------------------------------------------------
    # Переключение на резерв
    # --------------------------------------------------------

    def switch_to_backup(self):
        """Вызывается ТОЛЬКО из потока 1 (primary_loop)."""
        self.switching.set()

        try:
            self._switch_to_backup_impl()
        finally:
            self.switching.clear()

    def _switch_to_backup_impl(self):
        tried_links = set()
        max_attempts = BACKUP_POOL_SIZE + 2

        for attempt in range(max_attempts):
            if _shutdown_requested.is_set():
                logger.info("🛑 shutdown во время переключения — прерываем")
                return

            with self.pool_lock:
                alive_backups = [
                    item for item in self.backup_pool
                    if item.get('alive', False) and item['link'] not in tried_links
                ]

            if not alive_backups:
                logger.warning("⚠️ Нет живых резервных! Пополнение пула...")
                self.refill_pool_excluding_deferred()

                with self.pool_lock:
                    alive_backups = [
                        item for item in self.backup_pool
                        if item.get('alive', False) and item['link'] not in tried_links
                    ]

                if not alive_backups:
                    if not self.critical_error_logged:
                        with self.primary_lock:
                            primary = self.primary
                        parsed = parse_vless_link(primary) if primary else None
                        last_host = parsed['host'] if parsed else 'NONE'
                        logger.critical("🔴 КРИТИЧЕСКАЯ ОШИБКА: НЕТ РАБОЧИХ ССЫЛОК В РЕЗЕРВЕ!")
                        logger.critical(f"Последняя рабочая: {last_host}")
                        self.critical_error_logged = True
                    return

            backup = alive_backups[0]
            new_primary = backup['link']

            with self.primary_lock:
                old_primary = self.primary

            parsed_old = parse_vless_link(old_primary) if old_primary else None
            parsed_new = parse_vless_link(new_primary)
            old_host = parsed_old['host'] if parsed_old else 'NONE'
            new_host = parsed_new['host'] if parsed_new else 'unknown'

            logger.warning(f"⚠️ ПЕРЕКЛЮЧЕНИЕ: {old_host} → {new_host}")

            if update_3xui_outbound(new_primary, OUTBOUND_NAME):
                if reload_xray():
                    with self.primary_lock:
                        self.primary = new_primary

                    with self.pool_lock:
                        self.backup_pool = [item for item in self.backup_pool if item['link'] != new_primary]

                    with self.stats_lock:
                        self.switch_count += 1
                        self.primary_stats['fail_count'] = 0

                    self.critical_error_logged = False
                    self.refill_pool_excluding_deferred()

                    logger.info(f"✅ Переключение выполнено (№{self.switch_count})")
                    self.log_status(force=True)
                    return
                else:
                    logger.error("❌ x-ui не перезапустился — пробуем следующую")
                    tried_links.add(new_primary)
            else:
                logger.error("❌ Не удалось обновить outbound — пробуем следующую")
                tried_links.add(new_primary)

        logger.error("❌ Все попытки переключения исчерпаны")

    # --------------------------------------------------------
    # Запуск
    # --------------------------------------------------------

    def run(self):
        logger.info("="*50)
        logger.info("🚀 VLESS OBSERVER (multi-threaded)")
        logger.info("="*50)

        while not self.load_links():
            if _shutdown_requested.is_set():
                return
            if not self.wait_for_links():
                if _shutdown_requested.is_set():
                    return
                logger.error("❌ Не удалось дождаться ссылок")
                time.sleep(60)

        self.init_pool()

        logger.info(f"Порты: primary={PROXY_PORT_PRIMARY}, backup={PROXY_PORT_BACKUP}, deferred={PROXY_PORT_DEFERRED}")
        logger.info(f"Проверка основной: каждые {CHECK_INTERVAL_PRIMARY}с (timeout {TEST_TIMEOUT}с)")
        logger.info(f"Проверка резерва: каждые {CHECK_INTERVAL_BACKUP}с (timeout {BACKUP_TEST_TIMEOUT}с)")
        logger.info(f"Проверка deferred: каждые {CHECK_INTERVAL_DEFERRED}с")
        logger.info(f"Перепроверка отложенных: раз в {DEAD_LINK_RETRY_INTERVAL//60} минут")
        logger.info(f"Удаление отложенных: через {DEAD_LINK_DELETE_AFTER//60} минут")
        logger.info(f"Обновление пула: каждые {CHECK_INTERVAL_POOL_UPDATE}с")
        logger.info(f"Переключение: после {FAILURES_TO_SWITCH} отказов подряд")
        logger.info(f"Источник ссылок: {LINKS_FILE}")
        logger.info("="*50)

        threads = [
            threading.Thread(target=self.primary_loop, name="Primary", daemon=False),
            threading.Thread(target=self.backup_loop, name="Backup", daemon=False),
            threading.Thread(target=self.maintenance_loop, name="Maintenance", daemon=False),
        ]

        for t in threads:
            t.start()

        try:
            while not _shutdown_requested.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n🛑 Остановлен пользователем")
            _shutdown_requested.set()

        for t in threads:
            t.join(timeout=CHECK_INTERVAL_BACKUP + 10)

        with self.primary_lock:
            primary = self.primary
        parsed = parse_vless_link(primary) if primary else None
        primary_host = parsed['host'] if parsed else 'NONE'

        with self.stats_lock:
            switch_count = self.switch_count

        logger.info("="*50)
        logger.info(f"📊 ИТОГИ: переключений: {switch_count} | основная: {primary_host}")
        logger.info("="*50)


if __name__ == "__main__":
    observer = VlessObserver()
    observer.run()
