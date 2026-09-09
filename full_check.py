#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import logging
import time
import os

LOG_FILE = "/var/log/vless_full.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE)
    ]
)
logger = logging.getLogger(__name__)

def run_script(script: str, description: str) -> bool:
    logger.info("="*60)
    logger.info(f"🚀 {description}")
    logger.info("="*60)
    
    if not os.path.exists(script):
        logger.error(f"❌ Скрипт {script} не найден!")
        return False
    
    try:
        result = subprocess.run(
            ['python3', script],
            capture_output=True,
            text=True
        )
        
        if result.stdout:
            logger.info(result.stdout)
        
        if result.stderr:
            logger.error(result.stderr)
        
        if result.returncode == 0:
            logger.info(f"✅ {description} завершен успешно")
            return True
        else:
            logger.error(f"❌ {description} завершен с ошибкой (код {result.returncode})")
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске {description}: {e}")
        return False

def main():
    logger.info("="*60)
    logger.info("🔄 ПОЛНЫЙ ЦИКЛ (vless_checker → server_tester)")
    logger.info("="*60)
    logger.info(f"Время начала: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)
    
    start_time = time.time()
    
    # ЭТАП 1: Сбор пула ссылок (создаёт working_links.txt)
    if not run_script('/root/vless_checker/vless_checker.py', 'Этап 1: сбор пула ссылок'):
        logger.error("❌ Критическая ошибка на ЭТАПЕ 1. Прерывание.")
        sys.exit(1)
    
    # ЭТАП 2: Тестирование пула (создаёт stable_links.txt)
    if not run_script('/root/vless_checker/server_tester.py', 'Этап 2: тестирование пула → ТОП-10'):
        logger.error("❌ Критическая ошибка на ЭТАПЕ 2. Прерывание.")
        sys.exit(1)
    
    # ЭТАП 3: УДАЛЁН — обновление 3x-ui теперь делает Observer
    
    elapsed = time.time() - start_time
    
    logger.info("="*60)
    logger.info("✅ ВСЕ ЭТАПЫ ВЫПОЛНЕНЫ УСПЕШНО")
    logger.info("="*60)
    logger.info(f"⏱️ Общее время: {elapsed/60:.1f} минут")
    logger.info(f"📁 Результат: /root/vless_checker/stable_links.txt")
    logger.info("="*60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n🛑 Прервано пользователем")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Непредвиденная ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
