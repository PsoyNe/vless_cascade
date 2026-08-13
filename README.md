# VLESS CHECKER — комбайн по сбору рабочих ссылок и автообновлению в панели 3x-ui
В качестве сервера используется NanoPi Neo (512Мб) в связке с домашним Keenetic(для DDNS, можно и другой роутер и другой сервис DDNS)

📋 Инструкция по установке
Шаг 1. Базовая настройка системы
bash
sudo apt update && sudo apt upgrade -y
Шаг 2. Установка 3x-ui
bash
bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)
Шаг 3. Создание Outbound'ов в панели 3x-ui
Откройте веб-панель, создайте 10 outbound'ов:

vless_1, vless_2, ..., vless_10

Протокол: vless

Шаг 4. Установка VLESS Checker
bash
wget -qO- https://raw.githubusercontent.com/PsoyNe/vless_cascade/refs/heads/main/install.sh | bash
Шаг 5. Первый ручной запуск (через nohup)
bash
cd /root/vless_checker && nohup python3 full_check.py >> /var/log/vless_full.log 2>&1 &
tail -f /var/log/vless_full.log
Шаг 6. Добавление задания в cron
bash
crontab -e
Добавьте строку:

bash
# VLESS CHECKER — полный цикл каждую ночь в 2:00
0 2 * * * /root/vless_checker/run_full_check.sh
Шаг 7. Проверка
bash
crontab -l | grep vless_checker
Готово! 🚀
