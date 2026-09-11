#!/bin/bash
# ============================================================
# ЗАПУСК VLESS OBSERVER (вручную, для отладки)
# ============================================================
# Для боевой работы используйте systemd:
#   systemctl start vless_observer
# ============================================================

LOG_FILE="/var/log/vless_observer.log"

echo "========================================" >> $LOG_FILE
echo "Запуск Observer вручную: $(date)" >> $LOG_FILE
echo "========================================" >> $LOG_FILE

cd /root/vless_observer

python3 /root/vless_observer/observer.py >> $LOG_FILE 2>&1

echo "========================================" >> $LOG_FILE
echo "Остановлен: $(date)" >> $LOG_FILE
echo "" >> $LOG_FILE
