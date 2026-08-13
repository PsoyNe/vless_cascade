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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional, Dict
import statistics
import sys
from urllib.parse import unquote
import datetime
import shutil
import signal
import random
import logging
import ssl

from vless_check_config import *

# ============================================================
# ЭТАП 1: СБОР ПУЛА ССЫЛОК (vless_checker.py)
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/var/log/vless_checker.log")
    ]
)
logger = logging.getLogger(__name__)

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
        self.xray_lock = threading.Lock()
        
    def cleanup(self):
        try:
            for proc in self.processes:
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        time.sleep(0.5)
                        if proc.poll() is None:
                            proc.kill()
                except:
                    pass
            
            if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
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
    
    def filter_links(self, links: List[str]) -> List[str]:
        filtered = []
        for link in links:
            params = self.parse_vless_params(link)
            if params.get('security', '').lower() != 'reality':
                continue
            if params.get('port') != '443':
                continue
            filtered.append(link)
        return filtered
    
    def _create_xray_config(self, vless_link: str, proxy_port: int) -> dict:
        params = self.parse_vless_params(vless_link)
        if not params or 'host' not in params:
            raise ValueError("Неверный формат vless ссылки")
        
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
        
        self.processes.append(process)
        return process
    
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
            
            request = f"GET {TEST_PATH} HTTP/1.1\r\nHost: {TEST_HOST}\r\nConnection: close\r\n\r\n".encode()
            s.send(request)
            
            response = b""
            while True:
                try:
                    chunk = s.recv(TEST_BUFFER_SIZE)
                    if not chunk:
                        break
                    response += chunk
                    if len(chunk) < TEST_BUFFER_SIZE:
                        break
                except socket.timeout:
                    break
            
            response_size = len(response)
            elapsed = (time.time() - start_time) * 1000
            
            if response and TEST_EXPECTED_STRING in response:
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
    
    def test_single_link_real(self, link: str, thread_id: int) -> Tuple[str, Optional[float], str]:
        with self.threads_lock:
            self.active_threads += 1
        
        with self.xray_semaphore:
            try:
                proxy_port = self.get_next_port()
                config = self._create_xray_config(link, proxy_port)
                config_path = os.path.join(self.temp_dir, f"config_{hash(link)}_{proxy_port}.json")
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                
                with self.xray_lock:
                    process = self.start_xray(config_path)
                
                time.sleep(2)
                is_working, response_time, resp_size = self.test_https_through_proxy(proxy_port, timeout=STAGE1_TIMEOUT)
                
                process.terminate()
                try:
                    process.wait(timeout=2)
                except:
                    process.kill()
                
                if process in self.processes:
                    self.processes.remove(process)
                
                try:
                    os.remove(config_path)
                except:
                    pass
                
                with self.threads_lock:
                    self.active_threads -= 1
                    self.completed_count += 1
                
                if is_working:
                    return (link, response_time, f"OK ({resp_size} байт)")
                else:
                    return (link, None, "FAIL")
            except Exception as e:
                with self.threads_lock:
                    self.active_threads -= 1
                    self.completed_count += 1
                return (link, None, f"ERROR: {str(e)[:50]}")
    
    def check_links_real(self, links: List[str], max_workers: int = STAGE1_MAX_WORKERS) -> List[Tuple[str, float, str]]:
        self.start_time = time.time()
        self.active_threads = 0
        self.completed_count = 0
        self.working_results = []
        total = len(links)
        
        logger.info(f"Начало проверки {total} ссылок (HTTPS, {TEST_HOST})")
        
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Xray") as executor:
            futures = {}
            thread_counter = 0
            for link in links:
                thread_counter += 1
                futures[executor.submit(self.test_single_link_real, link, thread_counter)] = link
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result[1] is not None:
                        self.working_results.append(result)
                except Exception as e:
                    logger.error(f"Ошибка при получении результата: {e}")
        
        logger.info(f"Проверка завершена. Найдено {len(self.working_results)} рабочих ссылок из {total}")
        return self.working_results
    
    def save_working_links(self, working_links: List[Tuple[str, float, str]]):
        sorted_links = sorted(working_links, key=lambda x: x[1])
        top_30 = sorted_links[:STAGE1_WORKING_COUNT]
        
        with open(WORKING_LINKS_FILE, 'w', encoding='utf-8') as f:
            for link, ping, status in top_30:
                f.write(f"{link}\n")
        
        logger.info(f"Сохранено {len(top_30)} лучших ссылок (HTTPS, {TEST_HOST}) в {WORKING_LINKS_FILE}")
        logger.info(f"Пинги сохранённых: {[f'{ping:.0f}' for link, ping, status in top_30]}")

def main():
    logger.info("="*60)
    logger.info(f"ЭТАП 1: Сбор {STAGE1_WORKING_COUNT} лучших ссылок (HTTPS, {TEST_HOST})")
    logger.info("="*60)
    
    if not os.path.exists(XRAY_PATH):
        logger.error(f"Xray не найден по пути: {XRAY_PATH}")
        return
    
    checker = VlessChecker(XRAY_PATH)
    
    try:
        logger.info("Скачивание и фильтрация ссылок...")
        
        content = checker.download_vless_file(DEFAULT_URL)
        all_links = checker.extract_vless_links(content)
        logger.info(f"Найдено {len(all_links)} ссылок")
        
        filtered_links = checker.filter_links(all_links)
        logger.info(f"Отфильтровано {len(filtered_links)} ссылок (security=reality, port=443)")
        
        if not filtered_links:
            logger.error("Нет ссылок для проверки!")
            return
        
        workers = min(STAGE1_MAX_WORKERS, len(filtered_links))
        working_links = checker.check_links_real(filtered_links, max_workers=workers)
        
        if not working_links:
            logger.error("Нет рабочих ссылок!")
            return
        
        checker.save_working_links(working_links)
        
        logger.info("="*60)
        logger.info("✅ ЭТАП 1 ЗАВЕРШЕН")
        logger.info(f"📁 30 лучших ссылок сохранены в: {WORKING_LINKS_FILE}")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        checker.cleanup()

if __name__ == "__main__":
    main()
