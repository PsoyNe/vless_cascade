#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sqlite3
import os
import sys
import time
import logging
import subprocess
import signal
import socket
import socks
import ssl
import re
import tempfile
import shutil
from urllib.parse import unquote
from datetime import datetime
from typing import List, Tuple, Optional, Dict
import threading
import random

from observer_config import *

# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Файловый обработчик (всегда)
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(file_handler)

# Консольный обработчик — ТОЛЬКО при ручном запуске (с терминалом)
if sys.stdout.isatty():
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S'))
    logger.addHandler(console_handler)

# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def parse_vless_link(link: str) -> dict:
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
    """Создает конфиг Xray из vless ссылки"""
    params = parse_vless_link(link)
    if not params or 'host' not in params:
        raise ValueError("Неверный формат vless ссылки")
    
    uuid = params['uuid']
    host = params['host']
    port = params['port']
    
    reality_settings = {
        "serverName": params['params'].get('sni', host),
        "fingerprint": params['params'].get('fp', 'chrome'),
        "publicKey": params['params'].get('pbk', ''),
        "shortId": params['params'].get('sid', ''),
        "spiderX": "",
        "mldsa65Verify": ""
    }
    
    spx = params['params'].get('spx', '')
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
                        "encryption": params['params'].get('encryption', 'none'),
                        "flow": params['params'].get('flow', ''),
                        "level": 0
                    }]
                }]
            },
            "streamSettings": {
                "network": params['params'].get('type', 'tcp'),
                "security": params['params'].get('security', 'reality'),
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
    """Запускает Xray с конфигом"""
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

def test_link_through_xray(link: str, proxy_port: int, timeout: int = TEST_TIMEOUT) -> Tuple[bool, float, int]:
    """
    ЛЁГКАЯ проверка ссылки через реальный запуск Xray
    Отправляет HEAD запрос к google.com/generate_204
    Возвращает: (успех, время_в_мс, размер_ответа)
    """
    temp_dir = tempfile.mkdtemp(prefix="observer_test_")
    process = None
    s = None
    
    try:
        # Создаём конфиг
        config = create_xray_config(link, proxy_port)
        config_path = os.path.join(temp_dir, "config.json")
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        # Запускаем Xray
        process = start_xray(config_path)
        
        # Даём время на запуск (1.5 сек)
        time.sleep(1.5)
        
        # Проверяем через прокси (HEAD запрос)
        start_time = time.time()
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, "127.0.0.1", proxy_port)
        s.settimeout(timeout)
        
        s.connect((TEST_HOST, TEST_PORT))
        
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        ssl_sock = context.wrap_socket(s, server_hostname=TEST_HOST)
        s = ssl_sock
        
        # HEAD запрос (без тела)
        request = f"HEAD {TEST_PATH} HTTP/1.1\r\nHost: {TEST_HOST}\r\nConnection: close\r\n\r\n".encode()
        s.send(request)
        
        # Читаем только заголовки (первые 1024 байта)
        response = s.recv(TEST_BUFFER_SIZE)
        elapsed = (time.time() - start_time) * 1000
        
        # Проверяем статус 204 или 200
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
        if process:
            try:
                process.terminate()
                time.sleep(0.5)
                if process.poll() is None:
                    process.kill()
            except:
                pass
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

def create_outbound_config(link: str, name: str) -> dict:
    parsed = parse_vless_link(link)
    if not parsed:
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

def reload_xray():
    try:
        result = subprocess.run(['pgrep', '-f', 'xray-linux-arm32'], capture_output=True, text=True)
        if result.returncode == 0:
            pid = result.stdout.strip()
            os.kill(int(pid), signal.SIGHUP)
            logger.info(f"✅ SIGHUP отправлен Xray (PID: {pid})")
            return True
    except Exception as e:
        logger.error(f"❌ Ошибка SIGHUP: {e}")
    try:
        subprocess.run(['systemctl', 'restart', 'x-ui'], check=True)
        logger.info("✅ x-ui перезапущен через systemctl")
        return True
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

        self.proxy_port = 10808
        self.trigger_file = "/tmp/vless_observer_trigger"
        self.quarantine_trigger = "/tmp/vless_quarantine_trigger"
        self.dead_links = set()  # Мёртвые ссылки (временный карантин в памяти)
        
    def load_links(self):
        if not os.path.exists(LINKS_FILE):
            logger.warning(f"⚠️ Файл {LINKS_FILE} не найден! Ожидание...")
            return False
        
        with open(LINKS_FILE, 'r') as f:
            self.links = [line.strip() for line in f if line.strip().startswith('vless://')]
        
        if len(self.links) < 5:
            logger.warning(f"⚠️ В файле меньше 5 ссылок: {len(self.links)}. Ожидание...")
            return False
        
        logger.info(f"✅ Загружено {len(self.links)} ссылок")
        return True
    
    def wait_for_links(self):
        logger.info("⏳ Ожидание появления ссылок в stable_links.txt...")
        self.waiting_for_links = True
        
        while self.waiting_for_links:
            if os.path.exists(LINKS_FILE):
                with open(LINKS_FILE, 'r') as f:
                    self.links = [line.strip() for line in f if line.strip().startswith('vless://')]
                
                if len(self.links) >= 5:
                    logger.info(f"✅ Появилось {len(self.links)} ссылок. Продолжаем работу.")
                    self.waiting_for_links = False
                    return True
            
            logger.info(f"⏳ Ссылок пока нет ({len(self.links) if self.links else 0}), проверка через 60 секунд...")
            time.sleep(60)
        
        return False
    
    def reload_pool_from_file(self):
        logger.info("🔄 Перезагрузка резервного пула из файла...")
        
        if not os.path.exists(LINKS_FILE):
            logger.error("❌ Файл со ссылками не найден!")
            return False
        
        try:
            with open(LINKS_FILE, 'r') as f:
                all_links = [line.strip() for line in f if line.strip().startswith('vless://')]
            
            if not all_links:
                logger.error("❌ В файле нет ссылок!")
                return False
            
            current = self.primary
            available = [l for l in all_links if l != current]
            
            if not available:
                logger.error("❌ Нет доступных ссылок кроме основной!")
                return False
            
            self.backup_pool = []
            for link in available[:4]:
                parsed = parse_vless_link(link)
                if parsed:
                    self.backup_pool.append({
                        'link': link,
                        'host': parsed['host'],
                        'alive': True,
                        'ping': 0
                    })
            
            logger.info(f"✅ Резервный пул обновлён: {len(self.backup_pool)} ссылок")
            for item in self.backup_pool:
                logger.info(f"  - {item['host']}")
            
            self.last_pool_refill_time = time.time()
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка перезагрузки пула: {e}")
            return False
    
    def update_pool_from_file(self):
        """Периодическое обновление пула из файла (каждые 6 часов)"""
        current_time = time.time()
        
        if current_time - self.last_pool_update_time < POOL_UPDATE_INTERVAL:
            return
        
        logger.info("🔄 Периодическое обновление пула из файла...")
        
        # Очищаем список мёртвых ссылок при обновлении пула
        self.dead_links.clear()
        logger.info("🧹 Список мёртвых ссылок очищен")
        
        if not os.path.exists(LINKS_FILE):
            logger.warning("⚠️ Файл stable_links.txt не найден для обновления")
            self.last_pool_update_time = current_time
            return
        
        try:
            with open(LINKS_FILE, 'r') as f:
                all_links = [line.strip() for line in f if line.strip().startswith('vless://')]
            
            if len(all_links) < 5:
                logger.warning(f"⚠️ В файле меньше 5 ссылок: {len(all_links)}. Обновление отложено")
                self.last_pool_update_time = current_time
                return
            
            new_links = all_links[:5]
            
            if self.primary in new_links:
                current_primary = self.primary
                logger.info(f"📋 Основная ссылка {parse_vless_link(current_primary)['host']} остаётся")
            else:
                current_primary = new_links[0]
                logger.info(f"🔄 Основная ссылка не найдена в файле. Устанавливаем: {parse_vless_link(current_primary)['host']}")
                if update_3xui_outbound(current_primary, OUTBOUND_NAME):
                    reload_xray()
                    self.primary = current_primary
            
            self.backup_pool = []
            for link in new_links:
                if link == current_primary:
                    continue
                parsed = parse_vless_link(link)
                if parsed:
                    self.backup_pool.append({
                        'link': link,
                        'host': parsed['host'],
                        'alive': True,
                        'ping': 0
                    })
                    if len(self.backup_pool) >= 4:
                        break
            
            logger.info(f"✅ Резервный пул обновлён: {len(self.backup_pool)} ссылок")
            for item in self.backup_pool:
                logger.info(f"  - {item['host']}")
            
            self.log_status(force=True)
            self.last_pool_update_time = current_time
            
        except Exception as e:
            logger.error(f"❌ Ошибка обновления пула: {e}")
            self.last_pool_update_time = current_time
    
    def init_pool(self):
        self.primary = self.links[0]
        self.backup_pool = []
        
        for link in self.links[1:5]:
            parsed = parse_vless_link(link)
            if parsed:
                self.backup_pool.append({
                    'link': link,
                    'host': parsed['host'],
                    'alive': True,
                    'ping': 0
                })
        
        primary_host = parse_vless_link(self.primary)['host']
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
    
    def log_status(self, force: bool = False):
        current_time = time.time()
        primary_host = parse_vless_link(self.primary)['host']
        
        alive_count = len([item for item in self.backup_pool if item.get('alive', False)])
        state = f"OK | {primary_host} | резерв: {alive_count}/{len(self.backup_pool)} живых | перекл: {self.switch_count}"
        
        if force or state != self.last_state or (current_time - self.last_log_time) >= 60:
            logger.info(state)
            self.last_state = state
            self.last_log_time = current_time
            self.last_primary_host = primary_host
    
    def test_backup_pool(self):
        if not self.backup_pool:
            return
        
        self.backup_check_counter += 1
        
        dead_links = []
        
        for item in self.backup_pool:
            # Проверяем через реальный запуск Xray
            is_working, ping, size = test_link_through_xray(
                item['link'], 
                self.proxy_port, 
                timeout=TEST_TIMEOUT
            )
            
            if is_working:
                item['alive'] = True
                item['ping'] = ping
            else:
                item['alive'] = False
                item['ping'] = 0
                dead_links.append(item['link'])
                logger.warning(f"⚠️ Резервная ссылка {item['host']} мертва!")
        
        # Удаляем мёртвые ссылки из резерва
        if dead_links:
            self.backup_pool = [item for item in self.backup_pool if item['link'] not in dead_links]
            # Добавляем мёртвые ссылки в список (чтобы не добавлять обратно)
            self.dead_links.update(dead_links)
            logger.warning(f"⚠️ Удалено {len(dead_links)} мёртвых резервных ссылок, добавлены в чёрный список")
            
            # Пополняем пул (НО исключая мёртвые)
            if len(self.backup_pool) < BACKUP_POOL_SIZE:
                self.refill_pool_excluding_dead()
        
        self.backup_pool.sort(key=lambda x: (not x.get('alive', False), x.get('ping', 9999)))
        
        alive_count = len([item for item in self.backup_pool if item.get('alive', False)])
        if alive_count == 0 and len(self.backup_pool) > 0:
            logger.warning("⚠️ Все резервные ссылки мертвы! Пополнение пула...")
            self.refill_pool_excluding_dead()
    
    def refill_pool_excluding_dead(self):
        """Пополняет резервный пул из файла, исключая мёртвые ссылки"""
        if not os.path.exists(LINKS_FILE):
            return
        
        try:
            with open(LINKS_FILE, 'r') as f:
                all_links = [line.strip() for line in f if line.strip().startswith('vless://')]
            
            if not all_links:
                return
            
            current = self.primary
            existing_links = [item['link'] for item in self.backup_pool]
            
            # Исключаем: основную, уже существующие в резерве, мёртвые
            available = [
                l for l in all_links 
                if l != current 
                and l not in existing_links 
                and l not in self.dead_links
            ]
            
            if not available:
                return
            
            for link in available[:BACKUP_POOL_SIZE - len(self.backup_pool)]:
                parsed = parse_vless_link(link)
                if parsed:
                    self.backup_pool.append({
                        'link': link,
                        'host': parsed['host'],
                        'alive': True,
                        'ping': 0
                    })
                    logger.info(f"➕ Добавлена новая резервная ссылка: {parsed['host']}")
            
            self.last_pool_refill_time = time.time()
            
        except Exception as e:
            logger.error(f"❌ Ошибка пополнения пула: {e}")
    
    def check_trigger_file(self):
        if os.path.exists(self.trigger_file):
            try:
                os.remove(self.trigger_file)
                logger.warning(f"⚠️ ТРИГГЕР: Обнаружен файл {self.trigger_file} — ИМИТАЦИЯ 2 ОТКАЗОВ СРАЗУ!")
                self.primary_stats['fail_count'] = FAILURES_TO_SWITCH
                return True
            except Exception as e:
                logger.error(f"Ошибка удаления триггер-файла: {e}")
        return False
    
    def check_quarantine_trigger(self):
        if os.path.exists(self.quarantine_trigger):
            try:
                os.remove(self.quarantine_trigger)
                logger.warning(f"⚠️ КАРАНТИН: Обнаружен файл {self.quarantine_trigger}")
                self.move_primary_to_quarantine()
                return True
            except Exception as e:
                logger.error(f"Ошибка удаления триггера карантина: {e}")
        return False
    
    def move_primary_to_quarantine(self):
        if not self.primary:
            logger.warning("Нет основной ссылки для помещения в карантин")
            return
        
        old_primary = self.primary
        old_host = parse_vless_link(old_primary)['host']
        
        logger.warning(f"🛑 КАРАНТИН: Основная ссылка {old_host} отправляется в карантин")
        
        # Добавляем в список мёртвых
        self.dead_links.add(old_primary)
        
        # Удаляем из резерва
        self.backup_pool = [item for item in self.backup_pool if item['link'] != old_primary]
        self.switch_to_backup()
    
    def test_primary(self):
        # Проверяем триггер карантина
        if self.check_quarantine_trigger():
            return
        
        # Проверяем обычный триггер
        if self.check_trigger_file():
            logger.warning(f"❌ ИМИТАЦИЯ 2 ОТКАЗОВ: переключение...")
            self.switch_to_backup()
            self.log_status(force=True)
            return
        
        # Реальная проверка через запуск Xray
        is_working, ping, size = test_link_through_xray(
            self.primary, 
            self.proxy_port, 
            timeout=TEST_TIMEOUT
        )
        
        if is_working:
            self.primary_stats['success_count'] += 1
            self.primary_stats['fail_count'] = 0
            self.critical_error_logged = False
            logger.debug(f"✅ Основная ссылка работает (пинг: {ping:.0f}мс)")
        else:
            self.primary_stats['fail_count'] += 1
            logger.warning(f"❌ Отказ основной ссылки ({self.primary_stats['fail_count']}/{FAILURES_TO_SWITCH})")
            
            if self.primary_stats['fail_count'] >= FAILURES_TO_SWITCH:
                self.switch_to_backup()
                self.log_status(force=True)
    
    def switch_to_backup(self):
        alive_backups = [item for item in self.backup_pool if item.get('alive', False)]
        
        if not alive_backups:
            logger.warning("⚠️ Нет живых резервных ссылок! Пополнение пула...")
            self.refill_pool_excluding_dead()
            alive_backups = [item for item in self.backup_pool if item.get('alive', False)]
            
            if not alive_backups:
                if not self.critical_error_logged:
                    logger.critical("🔴 КРИТИЧЕСКАЯ ОШИБКА: НЕТ РАБОЧИХ ССЫЛОК В РЕЗЕРВЕ!")
                    logger.critical(f"Последняя рабочая ссылка: {parse_vless_link(self.primary)['host']}")
                    self.critical_error_logged = True
                return
        
        backup = alive_backups[0]
        new_primary = backup['link']
        old_primary = self.primary
        old_host = parse_vless_link(old_primary)['host']
        new_host = parse_vless_link(new_primary)['host']
        
        logger.warning(f"⚠️ ПЕРЕКЛЮЧЕНИЕ: {old_host} → {new_host}")
        
        if update_3xui_outbound(new_primary, OUTBOUND_NAME):
            reload_xray()
            self.primary = new_primary
            self.backup_pool = [item for item in self.backup_pool if item['link'] != new_primary]
            self.switch_count += 1
            self.primary_stats['fail_count'] = 0
            self.critical_error_logged = False
            
            self.refill_pool_excluding_dead()
            
            logger.info(f"✅ Переключение выполнено (№{self.switch_count})")
            self.log_status(force=True)
        else:
            logger.error("❌ Не удалось переключить")
            if len(alive_backups) > 1:
                self.backup_pool = [item for item in self.backup_pool if item['link'] != new_primary]
                logger.info("🔄 Пробуем следующую резервную ссылку...")
                self.switch_to_backup()
    
    def run(self):
        logger.info("="*50)
        logger.info("🚀 VLESS OBSERVER")
        logger.info("="*50)
        
        while not self.load_links():
            if not self.wait_for_links():
                logger.error("❌ Не удалось дождаться ссылок. Перезапуск ожидания...")
                time.sleep(60)
        
        self.init_pool()
        
        logger.info(f"Проверка: {CHECK_INTERVAL_PRIMARY}с | Переключение: {FAILURES_TO_SWITCH} отказа")
        logger.info(f"Обновление пула: каждые {POOL_UPDATE_INTERVAL//3600} часов (мёртвые ссылки забываются)")
        logger.info(f"Тестовый хост: {TEST_HOST}{TEST_PATH} (HEAD запрос)")
        logger.info(f"Триггер-файл: {self.trigger_file} (создайте для имитации отказа)")
        logger.info(f"Карантин-триггер: {self.quarantine_trigger} (создайте для отправки ссылки в карантин)")
        logger.info("="*50)
        
        last_backup_check = time.time()
        
        try:
            test_iterations = 0
            while True:
                test_iterations += 1
                self.test_primary()
                self.log_status()
                
                if time.time() - last_backup_check >= CHECK_INTERVAL_BACKUP:
                    self.test_backup_pool()
                    last_backup_check = time.time()
                
                self.update_pool_from_file()
                
                time.sleep(CHECK_INTERVAL_PRIMARY)
                
        except KeyboardInterrupt:
            logger.info("\n🛑 Остановлен пользователем")
        
        logger.info("="*50)
        logger.info(f"📊 ИТОГИ: переключений: {self.switch_count} | основная: {parse_vless_link(self.primary)['host']}")
        logger.info("="*50)

if __name__ == "__main__":
    observer = VlessObserver()
    observer.run()
