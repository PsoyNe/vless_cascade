#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sqlite3
import os
import subprocess
import sys
import time
import logging
import re
from urllib.parse import unquote

from vless_check_config import *

# ============================================================
# ЭТАП 3: ОБНОВЛЕНИЕ 3X-UI (update_db.py)
# ============================================================

DB_PATH = "/etc/x-ui/x-ui.db"
LINKS_FILE = STABLE_LINKS_10_FILE
LOG_FILE = "/var/log/vless_update_db.log"

OUTBOUND_NAMES = ["vless_1", "vless_2", "vless_3", "vless_4", "vless_5",
                  "vless_6", "vless_7", "vless_8", "vless_9", "vless_10"]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

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
        logger.error(f"Ошибка парсинга ссылки: {e}")
        return None

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

def update_outbounds() -> bool:
    logger.info("="*60)
    logger.info("🔄 ОБНОВЛЕНИЕ OUTBOUND'ОВ В 3X-UI (SQLITE)")
    logger.info("="*60)
    
    if not os.path.exists(LINKS_FILE):
        logger.error(f"❌ Файл {LINKS_FILE} не найден!")
        return False
    
    try:
        with open(LINKS_FILE, 'r') as f:
            links = [line.strip() for line in f if line.strip().startswith('vless://')]
    except Exception as e:
        logger.error(f"Ошибка чтения файла: {e}")
        return False
    
    if not links:
        logger.error("Нет ссылок для обновления")
        return False
    
    logger.info(f"✅ Найдено {len(links)} ссылок в файле")
    
    if not os.path.exists(DB_PATH):
        logger.error(f"❌ База данных {DB_PATH} не найдена!")
        return False
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT value FROM settings WHERE key = 'xrayTemplateConfig'")
        row = cursor.fetchone()
        
        if not row:
            logger.error("xrayTemplateConfig не найден в settings!")
            conn.close()
            return False
        
        config = json.loads(row[0])
        logger.info("✅ Текущий конфиг получен")
        
        outbounds = config.get('outbounds', [])
        logger.info(f"✅ Найдено {len(outbounds)} outbound'ов в конфиге")
        
        for o in outbounds:
            if o.get('tag', '').startswith('vless_'):
                settings = o.get('settings', {})
                addr = settings.get('address', 'unknown')
                logger.info(f"   Текущий {o.get('tag')} -> {addr}")
        
        updated_count = 0
        added_count = 0
        
        for i, link in enumerate(links[:STAGE2_TARGET_COUNT]):
            name = OUTBOUND_NAMES[i] if i < len(OUTBOUND_NAMES) else f"vless_{i+1}"
            new_outbound = create_outbound_config(link, name)
            if not new_outbound:
                logger.warning(f"   ⚠️ Не удалось распарсить {name}")
                continue
            
            found = False
            for j, outbound in enumerate(outbounds):
                if outbound.get('tag') == name:
                    outbounds[j] = new_outbound
                    found = True
                    updated_count += 1
                    logger.info(f"   ✅ Обновлен {name} -> {new_outbound['settings']['address']}")
                    break
            
            if not found:
                outbounds.append(new_outbound)
                added_count += 1
                logger.info(f"   ➕ Добавлен {name} -> {new_outbound['settings']['address']}")
        
        config['outbounds'] = outbounds
        
        routing = config.get('routing', {})
        for balancer in routing.get('balancers', []):
            if balancer.get('tag') == 'Balance1':
                selector = [f"vless_{i+1}" for i in range(STAGE2_TARGET_COUNT)]
                balancer['selector'] = selector
                logger.info(f"   ✅ Обновлен балансировщик Balance1: {len(selector)} outbound'ов")
        
        if 'observatory' in config:
            observatory = config['observatory']
            if observatory.get('subjectSelector'):
                subjectSelector = [f"vless_{i+1}" for i in range(STAGE2_TARGET_COUNT)]
                observatory['subjectSelector'] = subjectSelector
                logger.info(f"   ✅ Обновлен observatory: {len(subjectSelector)} outbound'ов")
        
        new_config_json = json.dumps(config, indent=2)
        
        cursor.execute(
            "UPDATE settings SET value = ? WHERE key = 'xrayTemplateConfig'",
            (new_config_json,)
        )
        
        conn.commit()
        conn.close()
        
        logger.info("✅ База данных обновлена")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    
    logger.info("\n🔄 Перезапуск x-ui...")
    
    try:
        result = subprocess.run(['systemctl', 'stop', 'x-ui'], capture_output=True, check=False)
        if result.returncode == 0:
            logger.info("   ✅ x-ui остановлен")
        else:
            logger.warning("   ⚠️ Не удалось остановить x-ui")
        
        time.sleep(1)
        
        result = subprocess.run(['systemctl', 'start', 'x-ui'], capture_output=True, check=False)
        if result.returncode == 0:
            logger.info("   ✅ x-ui запущен")
        else:
            logger.warning("   ⚠️ Не удалось запустить x-ui")
        
        time.sleep(2)
        
    except Exception as e:
        logger.error(f"❌ Ошибка при перезапуске: {e}")
        logger.info("   Попробуйте вручную: systemctl restart x-ui")
    
    logger.info("\n" + "="*60)
    logger.info(f"📊 ИТОГИ:")
    logger.info(f"   Обновлено: {updated_count} outbound'ов")
    logger.info(f"   Добавлено: {added_count} outbound'ов")
    logger.info("="*60)
    
    return True

def main():
    try:
        success = update_outbounds()
        if success:
            logger.info("✅ Обновление выполнено успешно")
            sys.exit(0)
        else:
            logger.error("❌ Обновление завершилось с ошибкой")
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\n🛑 Прервано пользователем")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Непредвиденная ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
