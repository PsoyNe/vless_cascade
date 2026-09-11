#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import re
import subprocess
import json
import tempfile
import os
import time
import socket
import socks
import threading
import logging
import logging.handlers
import signal
import shutil
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional, Dict
from urllib.parse import unquote

from vless_check_config import *

# ============================================================
# ЛОГИРОВАНИЕ (ротация)
# ============================================================
os.makedirs("/var/log", exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = logging.handlers.TimedRotatingFileHandler(
    "/var/log/vless_checker.log",
    when=LOG_ROTATION_WHEN,
    interval=LOG_ROTATION_INTERVAL,
    backupCount=LOG_ROTATION_BACKUPS,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)


# ============================================================
# ГЛОБАЛЬНЫЙ ФЛАГ ОСТАНОВКИ
# ============================================================
_shutdown_requested = threading.Event()
_active_checker = None


def _handle_sigterm(signum, frame):
    """SIGTERM/SIGINT — graceful shutdown + убийство дочерних Xray."""
    logger.warning(f"🛑 Получен сигнал {signum} — завершаем работу...")
    _shutdown_requested.set()
    global _active_checker
    if _active_checker is not None:
        try:
            _active_checker.cleanup()
        except Exception as e:
            logger.error(f"Ошибка cleanup при shutdown: {e}")


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


# ============================================================
# ЭТАП 1: СБОР ПУЛА ССЫЛОК
# ============================================================

class VlessChecker:
    def __init__(self, xray_path: str = XRAY_PATH):
        self.xray_path = xray_path
        self.temp_dir = tempfile.mkdtemp(prefix="vless_checker_")
        self.base_port = 20000
        self.port_lock = threading.Lock()
        self.current_port = self.base_port
        self.xray_semaphore = threading.Semaphore(STAGE1_MAX_WORKERS)
        self.active_threads = 0
        self.threads_lock = threading.Lock()
        self.completed_count = 0
        self.start_time = None
        self.working_results = []
        self.processes = []
        self.processes_lock = threading.Lock()
        self.xray_lock = threading.Lock()

        self.stop_checking = False
        self.found_count = 0
        self.found_lock = threading.Lock()

        self.checked_count = 0
        self.progress_lock = threading.Lock()
        self.total_links = 0

    def cleanup(self):
        """Убивает все дочерние Xray-процессы и удаляет temp-директорию."""
        try:
            with self.processes_lock:
                procs = list(self.processes)
                self.processes.clear()

            for proc in procs:
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                except Exception:
                    pass

            if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                logger.info(f"Временная директория очищена: {self.temp_dir}")
        except Exception as e:
            logger.error(f"Ошибка при очистке: {e}")

    def get_next_port(self) -> int:
        with self.port_lock:
            port = self.current_port
            self.current_port += 1
            while self._is_port_in_use(port):
                port = self.current_port
                self.current_port += 1
            return port

    def _is_port_in_use(self, port: int) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            return result == 0
        except:
            return True

    def wait_for_xray_port(self, proxy_port: int, timeout: float = 3.0) -> bool:
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

    def download_vless_file(self, url: str) -> str:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 11; NanoPi) AppleWebKit/537.36'
        }
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return response.text

    def extract_vless_links(self, content: str) -> List[str]:
        pattern = r'vless://[^\s<>"\']+'
        links = re.findall(pattern, content)
        return links

    def parse_vless_params(self, link: str) -> dict:
        try:
            link_without_protocol = link[8:]
            if '@' not in link_without_protocol:
                return {}
            before_at, after_at = link_without_protocol.split('@', 1)
            if ':' not in after_at:
                return {}
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
            params['host'] = host_port
            params['port'] = port
            return params
        except Exception:
            return {}

    def validate_reality_params(self, params: dict) -> Tuple[bool, str]:
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

    def load_quarantine_links(self) -> set:
        quarantine = set()
        try:
            if os.path.exists(QUARANTINE_FILE):
                with open(QUARANTINE_FILE, 'r', encoding='utf-8') as f:
                    for line in f:
                        link = line.strip()
                        if link.startswith('vless://'):
                            quarantine.add(link)
                logger.info(f"Загружено {len(quarantine)} ссылок из карантина")
        except Exception as e:
            logger.error(f"Ошибка загрузки карантина: {e}")
        return quarantine

    def load_existing_links(self) -> List[str]:
        existing = []
        for attempt in range(FILE_READ_RETRIES):
            try:
                if not os.path.exists(WORKING_LINKS_FILE):
                    time.sleep(FILE_READ_RETRY_DELAY)
                    continue
                with open(WORKING_LINKS_FILE, 'r', encoding='utf-8') as f:
                    for line in f:
                        link = line.strip()
                        if link.startswith('vless://'):
                            existing.append(link)
                if existing:
                    logger.info(f"Загружено {len(existing)} существующих ссылок из {WORKING_LINKS_FILE}")
                    return existing
                time.sleep(FILE_READ_RETRY_DELAY)
            except Exception as e:
                logger.error(f"Ошибка загрузки существующих ссылок: {e}")
                time.sleep(FILE_READ_RETRY_DELAY)
        return existing

    def filter_links(self, links: List[str]) -> List[str]:
        filtered = []
        seen_hosts = set()
        quarantine = self.load_quarantine_links()

        logger.info(f"Режим фильтрации: {FILTER_MODE}")

        stats = {
            'total': len(links),
            'quarantine': 0,
            'no_params': 0,
            'wrong_security': 0,
            'wrong_port': 0,
            'duplicate_host': 0,
            'invalid_reality': 0,
            'accepted': 0
        }

        for link in links:
            if link in quarantine:
                stats['quarantine'] += 1
                continue

            params = self.parse_vless_params(link)
            if not params:
                stats['no_params'] += 1
                continue

            security = params.get('security', '').lower()
            port = params.get('port', '')

            if FILTER_MODE == 'reality_443':
                if security != 'reality':
                    stats['wrong_security'] += 1
                    continue
                if port != '443':
                    stats['wrong_port'] += 1
                    continue
            elif FILTER_MODE == 'reality':
                if security != 'reality':
                    stats['wrong_security'] += 1
                    continue
            elif FILTER_MODE == 'port_443':
                if port != '443':
                    stats['wrong_port'] += 1
                    continue
            elif FILTER_MODE == 'all':
                pass
            else:
                logger.error(f"Неверный FILTER_MODE: {FILTER_MODE}")
                continue

            ok, reason = self.validate_reality_params(params)
            if not ok:
                stats['invalid_reality'] += 1
                continue

            host = params.get('host', '')
            if host in seen_hosts:
                stats['duplicate_host'] += 1
                continue
            seen_hosts.add(host)

            filtered.append(link)
            stats['accepted'] += 1

        logger.info(f"Статистика фильтрации:")
        logger.info(f"  Всего ссылок: {stats['total']}")
        logger.info(f"  В карантине: {stats['quarantine']}")
        logger.info(f"  Без параметров: {stats['no_params']}")
        logger.info(f"  Неверный security: {stats['wrong_security']}")
        logger.info(f"  Неверный порт: {stats['wrong_port']}")
        logger.info(f"  Невалидный Reality: {stats['invalid_reality']}")
        logger.info(f"  Дубликаты хостов: {stats['duplicate_host']}")
        logger.info(f"  Принято: {stats['accepted']}")

        return filtered

    def _create_xray_config(self, vless_link: str, proxy_port: int) -> dict:
        params = self.parse_vless_params(vless_link)
        if not params or 'host' not in params:
            raise ValueError("Неверный формат vless ссылки")

        ok, reason = self.validate_reality_params(params)
        if not ok:
            raise ValueError(f"Невалидная Reality-ссылка: {reason}")

        link_without_protocol = vless_link[8:]
        uuid = link_without_protocol.split('@')[0]
        host = params['host']
        port = int(params['port'])

        reality_settings = {
            "serverName": params.get('sni', host),
            "fingerprint": params.get('fp', 'chrome'),
            "publicKey": params.get('pbk', ''),
            "shortId": params.get('sid', ''),
        }
        spx = params.get('spx', '')
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
                            "encryption": params.get('encryption', 'none'),
                            "flow": params.get('flow', ''),
                            "level": 0
                        }]
                    }]
                },
                "streamSettings": {
                    "network": params.get('type', 'tcp'),
                    "security": params.get('security', 'none'),
                    "realitySettings": reality_settings if params.get('security') == 'reality' else None
                }
            }]
        }
        if 'streamSettings' in config['outbounds'][0]:
            stream = config['outbounds'][0]['streamSettings']
            if stream.get('realitySettings') is None:
                del stream['realitySettings']
        return config

    def start_xray(self, config_path: str) -> subprocess.Popen:
        cmd = [self.xray_path, "-config", config_path]
        env = os.environ.copy()
        env['XRAY_LOCATION_ASSET'] = '/usr/local/share/xray'

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid if hasattr(os, 'setsid') else None,
            env=env
        )

        with self.processes_lock:
            self.processes.append(process)
        return process

    def _kill_process(self, process: subprocess.Popen):
        """Безопасное убийство процесса + удаление из списка."""
        try:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
        except Exception:
            pass
        with self.processes_lock:
            if process in self.processes:
                self.processes.remove(process)

    def test_https_through_proxy(self, proxy_port: int, timeout: int = STAGE1_TIMEOUT) -> Tuple[bool, float, int]:
        start_time = time.time()
        response_size = 0
        s = None

        try:
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
            response_size = len(response)
            elapsed = (time.time() - start_time) * 1000

            if response and b"HTTP/" in response:
                return (True, elapsed, response_size)
            else:
                return (False, elapsed, response_size)

        except Exception:
            elapsed = (time.time() - start_time) * 1000
            return (False, elapsed, 0)
        finally:
            if s:
                try:
                    s.close()
                except:
                    pass

    def test_single_link_real(self, link: str, thread_id: int, is_existing: bool = False) -> Tuple[str, Optional[float], str]:
        if self.stop_checking or _shutdown_requested.is_set():
            return (link, None, "STOPPED")

        with self.threads_lock:
            self.active_threads += 1

        with self.xray_semaphore:
            # Проверяем флаг ПОСЛЕ получения семафора,
            # чтобы не запускать Xray для уже ненужных ссылок
            if self.stop_checking or _shutdown_requested.is_set():
                with self.threads_lock:
                    self.active_threads -= 1
                return (link, None, "STOPPED")

            process = None
            config_path = None

            try:
                proxy_port = self.get_next_port()
                config = self._create_xray_config(link, proxy_port)
                config_path = os.path.join(self.temp_dir, f"config_{hash(link)}_{proxy_port}.json")
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)

                with self.xray_lock:
                    process = self.start_xray(config_path)

                if not self.wait_for_xray_port(proxy_port, timeout=3.0):
                    self._kill_process(process)
                    if config_path and os.path.exists(config_path):
                        try:
                            os.remove(config_path)
                        except:
                            pass

                    with self.threads_lock:
                        self.active_threads -= 1
                        self.completed_count += 1

                    with self.progress_lock:
                        self.checked_count += 1
                        checked = self.checked_count
                        found = self.found_count

                    if checked % 10 == 0:
                        total = self.total_links
                        percent = (checked / total) * 100 if total > 0 else 0
                        logger.info(f"📊 Прогресс: проверено {checked}/{total} ({percent:.1f}%), найдено рабочих: {found}")

                    return (link, None, "PORT_TIMEOUT")

                is_working, response_time, resp_size = self.test_https_through_proxy(proxy_port, timeout=STAGE1_TIMEOUT)

                self._kill_process(process)

                if config_path and os.path.exists(config_path):
                    try:
                        os.remove(config_path)
                    except:
                        pass

                with self.threads_lock:
                    self.active_threads -= 1
                    self.completed_count += 1

                with self.progress_lock:
                    self.checked_count += 1
                    checked = self.checked_count
                    found = self.found_count

                if checked % 10 == 0:
                    total = self.total_links
                    percent = (checked / total) * 100 if total > 0 else 0
                    logger.info(f"📊 Прогресс: проверено {checked}/{total} ({percent:.1f}%), найдено рабочих: {found}")

                if is_working:
                    with self.found_lock:
                        self.found_count += 1
                        found = self.found_count

                    if not is_existing and CHECK_MODE == 'until_30' and found >= STAGE1_WORKING_COUNT:
                        logger.info(f"✅ Набрано {found} рабочих ссылок! Останавливаем проверку.")
                        self.stop_checking = True

                    return (link, response_time, f"OK ({resp_size} байт)")
                else:
                    return (link, None, "FAIL")
            except Exception as e:
                if process is not None:
                    self._kill_process(process)
                with self.threads_lock:
                    self.active_threads -= 1
                    self.completed_count += 1
                return (link, None, f"ERROR: {str(e)[:50]}")

    def check_links_real(self, links: List[str], max_workers: int = STAGE1_MAX_WORKERS,
                          is_existing: bool = False) -> List[Tuple[str, float, str]]:
        self.start_time = time.time()
        self.active_threads = 0
        self.completed_count = 0
        self.stop_checking = False
        self.checked_count = 0
        self.total_links = len(links)

        if not is_existing:
            self.found_count = 0
            self.working_results = []

        total = len(links)

        mode_str = "СУЩЕСТВУЮЩИХ" if is_existing else "НОВЫХ"
        logger.info(f"Начало проверки {total} {mode_str} ссылок (HTTPS, {TEST_HOST}, {TEST_METHOD})")

        results = []

        # Ограничиваем количество одновременных фьючерсов,
        # чтобы не плодить Xray для ссылок, которые уже не нужны.
        # Работаем чанками по max_workers * 4.
        chunk_size = max(max_workers * 4, max_workers)

        for chunk_start in range(0, total, chunk_size):
            if self.stop_checking or _shutdown_requested.is_set():
                logger.info(f"⏹️ Остановка проверки на {chunk_start}/{total} (набрано {self.found_count})")
                break

            chunk = links[chunk_start:chunk_start + chunk_size]

            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Xray") as executor:
                futures = {}
                for link in chunk:
                    if self.stop_checking or _shutdown_requested.is_set():
                        break
                    futures[executor.submit(self.test_single_link_real, link, 0, is_existing)] = link

                for future in as_completed(futures):
                    try:
                        result = future.result()
                        if result[1] is not None:
                            results.append(result)
                    except Exception as e:
                        logger.error(f"Ошибка при получении результата: {e}")

        logger.info(f"Проверка {mode_str} завершена. Найдено {len(results)} рабочих из {self.checked_count}")
        return results

    def save_working_links(self, all_working_links: List[Tuple[str, float, str]]):
        unique_links = {}
        for link, ping, status in all_working_links:
            if link not in unique_links:
                unique_links[link] = ping
            else:
                unique_links[link] = min(unique_links[link], ping)

        host_best = {}
        for link, ping in unique_links.items():
            params = self.parse_vless_params(link)
            host = params.get('host', '')
            if host not in host_best or ping < host_best[host][1]:
                host_best[host] = (link, ping)

        combined = list(host_best.values())
        combined.sort(key=lambda x: x[1])

        top_30 = combined[:STAGE1_WORKING_COUNT]

        # Атомарная запись через временный файл
        tmp_file = WORKING_LINKS_FILE + ".tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            for link, ping in top_30:
                f.write(f"{link}\n")
        os.replace(tmp_file, WORKING_LINKS_FILE)

        logger.info(f"Сохранено {len(top_30)} лучших ссылок в {WORKING_LINKS_FILE}")
        logger.info(f"  Уникальных хостов: {len(host_best)}")


def main():
    global _active_checker

    logger.info("="*60)
    logger.info(f"ЭТАП 1: Сбор {STAGE1_WORKING_COUNT} лучших ссылок")
    logger.info(f"Режим фильтрации: {FILTER_MODE}")
    logger.info(f"Режим проверки: {CHECK_MODE}")
    logger.info(f"Метод проверки: {TEST_METHOD}")
    logger.info("="*60)

    if not os.path.exists(XRAY_PATH):
        logger.error(f"Xray не найден по пути: {XRAY_PATH}")
        return

    checker = VlessChecker(XRAY_PATH)
    _active_checker = checker
    all_working_links = []

    try:
        logger.info("="*60)
        logger.info("ШАГ 1: Проверка существующих ссылок из working_links.txt")
        logger.info("="*60)

        existing_links = checker.load_existing_links()

        if existing_links and not _shutdown_requested.is_set():
            logger.info(f"Проверяем {len(existing_links)} существующих ссылок...")

            existing_working = checker.check_links_real(
                existing_links,
                max_workers=STAGE1_MAX_WORKERS,
                is_existing=True
            )

            logger.info(f"Из {len(existing_links)} существующих ссылок работают: {len(existing_working)}")
            all_working_links.extend(existing_working)
        else:
            logger.info("Существующих ссылок нет")

        if not _shutdown_requested.is_set():
            logger.info("="*60)
            logger.info("ШАГ 2: Скачивание и проверка новых ссылок")
            logger.info("="*60)

            logger.info("Скачивание и фильтрация ссылок...")

            content = checker.download_vless_file(DEFAULT_URL)
            all_links = checker.extract_vless_links(content)
            logger.info(f"Найдено {len(all_links)} ссылок")

            existing_set = set(existing_links)
            new_links = [l for l in all_links if l not in existing_set]

            logger.info(f"Новых ссылок (не из working_links.txt): {len(new_links)}")

            filtered_links = checker.filter_links(new_links)

            if filtered_links:
                workers = min(STAGE1_MAX_WORKERS, len(filtered_links))
                new_working = checker.check_links_real(
                    filtered_links,
                    max_workers=workers,
                    is_existing=False
                )

                logger.info(f"Из {len(filtered_links)} новых ссылок работают: {len(new_working)}")
                all_working_links.extend(new_working)
            else:
                logger.info("Нет новых ссылок для проверки")

        logger.info("="*60)
        logger.info("ШАГ 3: Объединение и сохранение ТОП-30")
        logger.info("="*60)

        if not all_working_links:
            logger.error("Нет рабочих ссылок!")
            return

        logger.info(f"Всего рабочих ссылок (существующие + новые): {len(all_working_links)}")

        checker.save_working_links(all_working_links)

        logger.info("="*60)
        logger.info("✅ ЭТАП 1 ЗАВЕРШЕН")
        logger.info(f"📁 Лучшие ссылки сохранены в: {WORKING_LINKS_FILE}")
        logger.info("="*60)

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        checker.cleanup()
        _active_checker = None


if __name__ == "__main__":
    main()
