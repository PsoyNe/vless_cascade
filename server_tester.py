#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import json
import os
import time
import threading
import logging
import logging.handlers
import sys
import signal
import tempfile
import shutil
import re
import socket
import socks
import ssl
import statistics
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
    "/var/log/server_test.log",
    when=LOG_ROTATION_WHEN,
    interval=LOG_ROTATION_INTERVAL,
    backupCount=LOG_ROTATION_BACKUPS,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)


# ============================================================
# ГЛОБАЛЬНЫЙ ФЛАГ ОСТАНОВКИ
# ============================================================
_shutdown_requested = threading.Event()
_active_tester = None


def _handle_sigterm(signum, frame):
    """SIGTERM/SIGINT — graceful shutdown + убийство дочерних Xray."""
    logger.warning(f"🛑 Получен сигнал {signum} — завершаем работу...")
    _shutdown_requested.set()
    global _active_tester
    if _active_tester is not None:
        try:
            _active_tester.cleanup()
        except Exception as e:
            logger.error(f"Ошибка cleanup при shutdown: {e}")


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


# ============================================================
# ЭТАП 2: ТЕСТИРОВАНИЕ ПУЛА ССЫЛОК
# ============================================================

class ServerTester:
    def __init__(self, xray_path: str = XRAY_PATH):
        self.xray_path = xray_path
        self.temp_dir = tempfile.mkdtemp(prefix="server_tester_")
        self.base_port = 30000
        self.port_lock = threading.Lock()
        self.current_port = self.base_port
        self.xray_semaphore = threading.Semaphore(STAGE2_MAX_WORKERS)
        self.active_threads = 0
        self.threads_lock = threading.Lock()
        self.completed_count = 0
        self.start_time = None
        self.working_results = []
        self.processes = []
        self.processes_lock = threading.Lock()
        self.xray_lock = threading.Lock()

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
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        except Exception:
            pass
        with self.processes_lock:
            if process in self.processes:
                self.processes.remove(process)

    def test_https_through_proxy(self, proxy_port: int, timeout: int = STAGE2_TIMEOUT) -> Tuple[bool, float, int]:
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

    def test_single_server_full(self, link: str, index: int) -> Dict:
        parsed = self.parse_vless_params(link)
        host = parsed.get('host', 'unknown') if parsed else 'unknown'

        logger.info(f"[{index}/30] 🔄 Тестирование {host} ({STAGE2_TEST_DURATION} сек)")

        result = {
            'index': index,
            'link': link,
            'host': host,
            'success_count': 0,
            'fail_count': 0,
            'pings': [],
            'response_sizes': [],
            'failures': [],
            'uptime_percent': 0,
            'ping_mean': 0,
            'ping_median': 0,
            'ping_min': 0,
            'ping_max': 0,
            'ping_stdev': 0,
            'max_consecutive_failures': 0,
            'is_stable': False,
            'avg_response_size': 0
        }

        if _shutdown_requested.is_set():
            return result

        proxy_port = self.get_next_port()
        config_path = None
        process = None

        try:
            config = self._create_xray_config(link, proxy_port)
            config_path = os.path.join(self.temp_dir, f"config_{index}_{proxy_port}.json")
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)

            with self.xray_lock:
                process = self.start_xray(config_path)

            if not self.wait_for_xray_port(proxy_port, timeout=3.0):
                logger.warning(f"[{index}/30] ⚠️ Порт {proxy_port} не открылся")
                self._kill_process(process)
                if config_path and os.path.exists(config_path):
                    try:
                        os.remove(config_path)
                    except:
                        pass
                return result

            start_time = time.time()
            end_time = start_time + STAGE2_TEST_DURATION
            check_count = 0
            consecutive_fails = 0

            logger.info(f"[{index}/30] 📊 {host} | Тест {STAGE2_TEST_DURATION}с, интервал {STAGE2_CHECK_INTERVAL}с")

            while time.time() < end_time:
                if _shutdown_requested.is_set():
                    logger.info(f"[{index}/30] ⏹️ Прерывание теста {host} по shutdown")
                    break

                check_count += 1
                is_working, ping, resp_size = self.test_https_through_proxy(proxy_port, timeout=STAGE2_TIMEOUT)

                if is_working:
                    result['success_count'] += 1
                    result['pings'].append(ping)
                    result['response_sizes'].append(resp_size)
                    consecutive_fails = 0
                    if check_count % 3 == 0:
                        logger.info(f"[{index}/30]   ✅ [{check_count}] {host} | {ping:.0f}мс")
                else:
                    result['fail_count'] += 1
                    result['failures'].append(time.time() - start_time)
                    consecutive_fails += 1
                    result['max_consecutive_failures'] = max(
                        result['max_consecutive_failures'], consecutive_fails
                    )
                    logger.warning(f"[{index}/30]   ❌ [{check_count}] {host} | ОТКАЗ (серия: {consecutive_fails})")

                for _ in range(STAGE2_CHECK_INTERVAL):
                    if _shutdown_requested.is_set():
                        break
                    time.sleep(1)

            self._kill_process(process)

            if config_path and os.path.exists(config_path):
                try:
                    os.remove(config_path)
                except:
                    pass

            total_checks = result['success_count'] + result['fail_count']
            result['uptime_percent'] = (result['success_count'] / total_checks * 100) if total_checks > 0 else 0

            if result['pings']:
                result['ping_mean'] = statistics.mean(result['pings'])
                result['ping_median'] = statistics.median(result['pings'])
                result['ping_min'] = min(result['pings'])
                result['ping_max'] = max(result['pings'])
                result['ping_stdev'] = statistics.stdev(result['pings']) if len(result['pings']) > 1 else 0
                result['avg_response_size'] = statistics.mean(result['response_sizes']) if result['response_sizes'] else 0

            # Учитываем минимальный размер ответа
            response_size_ok = result['avg_response_size'] >= STAGE2_MIN_RESPONSE_SIZE

            result['is_stable'] = (
                result['uptime_percent'] >= STAGE2_STABLE_UPTIME and
                result['max_consecutive_failures'] < STAGE2_MAX_FAILURES and
                total_checks > 0 and
                result['fail_count'] < total_checks * (STAGE2_MAX_FAIL_PERCENT / 100) and
                result['ping_mean'] < STAGE2_MAX_PING and
                response_size_ok
            )

            status = "✅ СТАБИЛЬНАЯ" if result['is_stable'] else "❌ НЕСТАБИЛЬНАЯ"
            logger.info(f"[{index}/30] {status} {host} | "
                       f"аптайм {result['uptime_percent']:.1f}% | "
                       f"ср.пинг {result['ping_mean']:.1f}мс | "
                       f"отказов {result['fail_count']}/{total_checks} | "
                       f"ср.размер {result['avg_response_size']:.0f}б")

        except Exception as e:
            logger.error(f"[{index}/30] ❌ Ошибка: {e}")
        finally:
            if process is not None:
                self._kill_process(process)
            if config_path and os.path.exists(config_path):
                try:
                    os.remove(config_path)
                except:
                    pass

        return result

    def test_all_servers(self, links: List[str]) -> List[Dict]:
        total = len(links)
        logger.info(f"🚀 Запуск тестирования {total} серверов (по {STAGE2_TEST_DURATION} сек)")
        logger.info(f"   Общее время: ~{(total / STAGE2_MAX_WORKERS) * (STAGE2_TEST_DURATION/60):.1f} минут")

        results = []
        with ThreadPoolExecutor(max_workers=STAGE2_MAX_WORKERS) as executor:
            futures = {}
            for i, link in enumerate(links, 1):
                if _shutdown_requested.is_set():
                    logger.info("⏹️ shutdown — прекращаем submit новых задач")
                    break
                future = executor.submit(self.test_single_server_full, link, i)
                futures[future] = i

            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error(f"Ошибка: {e}")

        results.sort(key=lambda x: x['index'])
        return results


def main():
    global _active_tester

    logger.info("="*60)
    logger.info(f"ЭТАП 2: Тестирование пула ссылок по {STAGE2_TEST_DURATION} сек ({TEST_HOST})")
    logger.info("="*60)

    if not os.path.exists(XRAY_PATH):
        logger.error(f"Xray не найден по пути: {XRAY_PATH}")
        return

    if not os.path.exists(STABLE_LINKS_10_FILE):
        logger.error(f"❌ Файл {STABLE_LINKS_10_FILE} не найден!")
        return

    # Атомарное чтение входного файла
    links = []
    for attempt in range(FILE_READ_RETRIES):
        try:
            with open(STABLE_LINKS_10_FILE, 'r', encoding='utf-8') as f:
                links = [line.strip() for line in f if line.strip().startswith('vless://')]
            if links:
                break
            time.sleep(FILE_READ_RETRY_DELAY)
        except Exception as e:
            logger.error(f"Ошибка чтения {STABLE_LINKS_10_FILE}: {e}")
            time.sleep(FILE_READ_RETRY_DELAY)

    if not links:
        logger.error("Нет ссылок для проверки!")
        return

    logger.info(f"Загружено {len(links)} ссылок из {STABLE_LINKS_10_FILE}")

    tester = ServerTester(XRAY_PATH)
    _active_tester = tester

    try:
        results = tester.test_all_servers(links)

        stable = [r for r in results if r['is_stable']]
        unstable = [r for r in results if not r['is_stable']]
        stable.sort(key=lambda x: (x['ping_mean'] if x['ping_mean'] else 9999))

        best_links = [r['link'] for r in stable[:STAGE2_TARGET_COUNT]]

        if len(best_links) < STAGE2_TARGET_COUNT:
            unstable.sort(key=lambda x: (x['ping_mean'] if x['ping_mean'] else 9999))
            for r in unstable:
                if len(best_links) >= STAGE2_TARGET_COUNT:
                    break
                best_links.append(r['link'])

        # Атомарная запись через .tmp + os.replace
        tmp_file = STABLE_LINKS_10_FILE + ".tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            for link in best_links:
                f.write(f"{link}\n")
        os.replace(tmp_file, STABLE_LINKS_10_FILE)

        logger.info("\n" + "="*60)
        logger.info("📊 РЕЗУЛЬТАТЫ ЭТАПА 2")
        logger.info("="*60)
        logger.info(f"   Всего протестировано: {len(results)}")
        logger.info(f"   Стабильных: {len(stable)}")
        logger.info(f"   Отобрано в ТОП-10: {len(best_links)}")
        logger.info(f"   Сохранено: {STABLE_LINKS_10_FILE}")
        logger.info("="*60)

        logger.info("\n🏆 ТОП-10:")
        for i, r in enumerate(stable[:STAGE2_TARGET_COUNT], 1):
            if r['ping_mean']:
                logger.info(f"   {i}. {r['host']} | "
                           f"Пинг: {r['ping_mean']:.1f}мс | "
                           f"аптайм: {r['uptime_percent']:.1f}% | "
                           f"отказов: {r['fail_count']}")

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        tester.cleanup()
        _active_tester = None
        logger.info("🧹 Очистка завершена")


if __name__ == "__main__":
    main()
