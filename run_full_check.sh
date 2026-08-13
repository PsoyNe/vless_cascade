#!/bin/bash
# ============================================================
# ЗАПУСК ПОЛНОГО ЦИКЛА (ЭТАПЫ 1, 2, 3)
# ============================================================

LOG_FILE="/var/log/vless_full.log"

echo "========================================" >> $LOG_FILE
echo "Запуск полного цикла: $(date)" >> $LOG_FILE
echo "========================================" >> $LOG_FILE

cd /root/vless_checker

python3 /root/vless_checker/full_check.py >> $LOG_FILE 2>&1

echo "========================================" >> $LOG_FILE
echo "Завершено: $(date)" >> $LOG_FILE
echo "" >> $LOG_FILE
