#!/bin/bash
# ============================================================
# ЗАПУСК ПОЛНОГО ЦИКЛА (ЭТАПЫ 1 + 2)
# ============================================================

LOG_FILE="/var/log/vless_full.log"

echo "========================================" >> $LOG_FILE
echo "Запуск полного цикла: $(date)" >> $LOG_FILE
echo "========================================" >> $LOG_FILE

cd /root/vless_checker

python3 /root/vless_checker/vless_checker.py >> $LOG_FILE 2>&1
python3 /root/vless_checker/server_tester.py >> $LOG_FILE 2>&1

echo "========================================" >> $LOG_FILE
echo "Завершено: $(date)" >> $LOG_FILE
echo "" >> $LOG_FILE
