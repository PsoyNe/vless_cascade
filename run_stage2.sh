#!/bin/bash
# ============================================================
# ЗАПУСК ЭТАПА 2 + 3
# ============================================================

LOG_FILE="/var/log/stage2.log"

echo "========================================" >> $LOG_FILE
echo "Запуск этапа 2: $(date)" >> $LOG_FILE
echo "========================================" >> $LOG_FILE

cd /root/vless_checker

python3 /root/vless_checker/server_tester.py >> $LOG_FILE 2>&1
python3 /root/vless_checker/update_db.py >> $LOG_FILE 2>&1

echo "========================================" >> $LOG_FILE
echo "Завершено: $(date)" >> $LOG_FILE
echo "" >> $LOG_FILE
