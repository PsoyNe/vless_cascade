#!/bin/bash
# ============================================================
# ЗАПУСК ЭТАПА 1
# ============================================================

LOG_FILE="/var/log/stage1.log"

echo "========================================" >> $LOG_FILE
echo "Запуск этапа 1: $(date)" >> $LOG_FILE
echo "========================================" >> $LOG_FILE

cd /root/vless_checker

python3 /root/vless_checker/vless_checker.py >> $LOG_FILE 2>&1

echo "========================================" >> $LOG_FILE
echo "Завершено: $(date)" >> $LOG_FILE
echo "" >> $LOG_FILE
