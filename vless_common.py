#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Общие функции для VLESS Observer и модуля триггеров.

Здесь собраны функции, которые используются и в observer.py, и в triggers.py.
Вынесены в отдельный модуль, чтобы избежать циклических импортов.
"""

import json
import os
import re
import ssl
import socks
import socket
import shutil
import sqlite3
import subprocess
import tempfile
import time
from urllib.parse import unquote
from typing import List, Tuple, Optional

from observer_config import (
    XRAY_PATH, DB_PATH, TEST_HOST, TEST_PORT, TEST_PATH,
    TEST_TIMEOUT, TEST_BUFFER_SIZE, DEEP_CHECK_HOSTS, DEEP_CHECK_PORT,
    DEEP_CHECK_PATH, DEEP_CHECK_TIMEOUT, DEEP_CHECK_EXPECTED_STRING,
    OUTBOUND_NAME, FILE_READ_RETRIES, FILE_READ_RETRY_DELAY,
)

# Устойчивое чтение параметров двойной проверки
import observer_config as _cfg

BACKUP_CHECK_ATTEMPTS = getattr(_cfg, 'BACKUP_CHECK_ATTEMPTS', 2)
BACKUP_CHECK_INTERVAL = getattr(_cfg, 'BACKUP_CHECK_INTERVAL', 2)
BACKUP_TEST_TIMEOUT = getattr(_cfg, 'BACKUP_TEST_TIMEOUT', 4)


# ============================================================
# ПАРСИНГ ССЫЛОК
# ============================================================

def parse_vless_link(link: str) -> Optional[dict]:
    """Парсит VLESS-ссылку. Fragment (#COUNTRY) отсекается."""
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
    except Exception:
        return None


def link_base(link: str) -> str:
    """Возвращает ссылку без fragment (#COUNTRY)."""
    return link.split('#', 1)[0]


def extract_geo_from_link(link: str) -> str:
    """
    Извлекает #COUNTRY из ссылки.

    Возвращает:
        'DE', 'NL', ...  — корректный код
        'UNKNOWN'        — если #UNKNOWN
        'N/A'            — если fragment отсутствует или не распознан
    """
    if '#' not in link:
        return 'N/A'
    fragment = link.split('#', 1)[1].strip()
    if not fragment:
        return 'N/A'
    if re.match(r'^[A-Z]{2}$', fragment):
        return fragment
    if fragment == "UNKNOWN":
        return "UNKNOWN"
    return 'N/A'


def format_host_with_geo(link: str) -> str:
    """Возвращает 'host [XX]'. Если ссылка не парсится — 'unknown [N/A]'."""
    parsed = parse_vless_link(link)
    if not parsed:
        return 'unknown [N/A]'
    host = parsed['host']
    geo = extract_geo_from_link(link)
    return f"{host} [{geo}]"


def validate_reality_params(params: dict) -> Tuple[bool, str]:
    """Проверяет обязательные Reality-параметры."""
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


# ============================================================
# РАБОТА С ФАЙЛАМИ
# ============================================================

def read_links_file(path: str) -> List[str]:
    """Атомарное чтение файла ссылок с повторами при пустом файле."""
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
        except Exception:
            time.sleep(FILE_READ_RETRY_DELAY)
    return []


# ============================================================
# XRAY
# ============================================================

def create_xray_config(link: str, proxy_port: int) -> dict:
    """Создаёт Xray-конфиг для проверки ссылки."""
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
    """Запускает Xray-процесс."""
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


def wait_for_xray_port(proxy_port: int, timeout: float = 3.0,
                       shutdown_event=None) -> bool:
    """Ждёт открытия порта Xray."""
    start = time.time()
    while time.time() - start < timeout:
        if shutdown_event is not None and shutdown_event.is_set():
            return False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.2)
            result = sock.connect_ex(('127.0.0.1', proxy_port))
            sock.close()
            if result == 0:
                return True
        except Exception:
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


def test_link_through_xray(link: str, proxy_port: int,
                            timeout: int = TEST_TIMEOUT,
                            shutdown_event=None) -> Tuple[bool, float, int]:
    """Проверяет ссылку через Xray."""
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

        if not wait_for_xray_port(proxy_port, timeout=3.0, shutdown_event=shutdown_event):
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
            except Exception:
                pass
        _kill_process(process)
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def test_link_double_check(link: str, proxy_port: int,
                            attempts: int = None,
                            interval: float = None,
                            timeout: int = None,
                            shutdown_event=None) -> Tuple[bool, float]:
    """
    Проверяет ссылку НЕСКОЛЬКО раз с интервалом.

    Используется перед добавлением в резерв — чтобы отсеять ссылки,
    которые отвечают нестабильно (1 раз из N).

    Возвращает:
        (True, ping)  — ВСЕ проверки прошли успешно (ping от последней)
        (False, 0)    — хотя бы одна проверка FAIL

    Параметры:
        attempts  — сколько раз проверять (по умолчанию из конфига)
        interval  — пауза между проверками в секундах
        timeout   — таймаут на каждую проверку
    """
    if attempts is None:
        attempts = BACKUP_CHECK_ATTEMPTS
    if interval is None:
        interval = BACKUP_CHECK_INTERVAL
    if timeout is None:
        timeout = BACKUP_TEST_TIMEOUT

    # Если нужна только одна проверка — просто вызываем test_link_through_xray
    if attempts <= 1:
        is_working, ping, _ = test_link_through_xray(
            link, proxy_port, timeout=timeout, shutdown_event=shutdown_event
        )
        return (is_working, ping if is_working else 0)

    last_ping = 0

    for attempt in range(1, attempts + 1):
        if shutdown_event is not None and shutdown_event.is_set():
            return (False, 0)

        is_working, ping, _ = test_link_through_xray(
            link, proxy_port, timeout=timeout, shutdown_event=shutdown_event
        )

        if not is_working:
            return (False, 0)

        last_ping = ping

        # Пауза перед следующей проверкой (кроме последней)
        if attempt < attempts:
            # Разбиваем сон на секунды, чтобы реагировать на shutdown
            remaining = interval
            while remaining > 0:
                if shutdown_event is not None and shutdown_event.is_set():
                    return (False, 0)
                sleep_chunk = min(1.0, remaining)
                time.sleep(sleep_chunk)
                remaining -= sleep_chunk

    return (True, last_ping)


def test_link_deep(link: str, proxy_port: int,
                    timeout: int = DEEP_CHECK_TIMEOUT,
                    shutdown_event=None) -> Tuple[bool, float, str]:
    """Глубокая проверка через запрещённые ресурсы."""
    temp_dir = tempfile.mkdtemp(prefix="observer_deep_")
    process = None
    start_time = time.time()

    try:
        config = create_xray_config(link, proxy_port)
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        process = start_xray(config_path)

        if not wait_for_xray_port(proxy_port, timeout=3.0, shutdown_event=shutdown_event):
            return (False, 0, "")

        for test_host in DEEP_CHECK_HOSTS:
            if shutdown_event is not None and shutdown_event.is_set():
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
                    return (True, elapsed, test_host)
            except Exception:
                pass
            finally:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass

        return (False, 0, "")

    except Exception:
        return (False, 0, "")
    finally:
        _kill_process(process)
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


# ============================================================
# 3X-UI
# ============================================================

def create_outbound_config(link: str, name: str) -> Optional[dict]:
    """Создаёт outbound-конфиг для 3x-ui."""
    parsed = parse_vless_link(link)
    if not parsed:
        return None

    ok, reason = validate_reality_params(parsed['params'])
    if not ok:
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
            "tcpSettings": {"header": {"type": "none"}},
            "realitySettings": reality_settings
        }
    }
    return outbound


def update_3xui_outbound(link: str, name: str = OUTBOUND_NAME) -> bool:
    """Обновляет outbound в БД 3x-ui."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'xrayTemplateConfig'")
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False
        config = json.loads(row[0])
        outbounds = config.get('outbounds', [])
        new_outbound = create_outbound_config(link, name)
        if not new_outbound:
            conn.close()
            return False
        found = False
        for i, outbound in enumerate(outbounds):
            if outbound.get('tag') == name:
                outbounds[i] = new_outbound
                found = True
                break
        if not found:
            outbounds.append(new_outbound)
        config['outbounds'] = outbounds
        cursor.execute(
            "UPDATE settings SET value = ? WHERE key = 'xrayTemplateConfig'",
            (json.dumps(config, indent=2),)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def reload_xray() -> bool:
    """Перезапускает x-ui через systemctl."""
    try:
        result = subprocess.run(
            ['systemctl', 'restart', 'x-ui'],
            capture_output=True,
            text=True,
            timeout=15
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False
