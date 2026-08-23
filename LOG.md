## 📋 Проверка логов всех этапов — полные команды и комментарии
### 🔍 Общий лог (полный цикл)
Посмотреть последние 100 строк
```bash
tail -100 /var/log/vless_full.log
```
Смотреть в реальном времени
```bash
tail -f /var/log/vless_full.log
```
Проверить ошибки
```bash
grep -i "error\|fail" /var/log/vless_full.log | tail -20
```
Проверить успешное завершение
```bash
grep "✅" /var/log/vless_full.log | tail -10
```
Комментарий: **vless_full.log** — это главный лог, который собирает вывод всех трёх этапов. Если что-то пошло не так, смотри сюда в первую очередь. Успешное завершение помечается ✅.
### 📊 Лог этапа 1 (vless_checker.py)
Посмотреть последние 100 строк
```bash
tail -100 /var/log/vless_checker.log
```
Смотреть в реальном времени
```bash
tail -f /var/log/vless_checker.log
```
Сколько ссылок найдено и отфильтровано
```bash
grep -E "Найдено|Отфильтровано|Сохранено" /var/log/vless_checker.log
```
Проверить ошибки
```bash
grep -i "error\|fail\|нет рабочих" /var/log/vless_checker.log
```
Лог этапа 1 показывает:
Сколько ссылок скачано из интернета (обычно 30-40 тысяч)
Сколько отфильтровано (security=reality, port=443)
Сколько рабочих найдено
Сохранены ли 30 лучших в working_links.txt

### 📊 Лог этапа 2 (server_tester.py)
Посмотреть последние 100 строк
```bash
tail -100 /var/log/server_test.log
```
Смотреть в реальном времени
```bash
tail -f /var/log/server_test.log
```
Количество стабильных и нестабильных серверов
```bash
grep -E "СТАБИЛЬНАЯ|НЕСТАБИЛЬНАЯ" /var/log/server_test.log | tail -10
```
ТОП-10 результатов
```bash
grep "🏆 ТОП-10" -A 20 /var/log/server_test.log | tail -20
```
Проверить ошибки подключения
```bash
grep -E "ОТКАЗ|Таймаут|error" /var/log/server_test.log | tail -20
```
Лог этапа 2 показывает детальное тестирование каждого сервера из 30:
Каждые 10 секунд — проверка HTTPS-доступа к check.torproject.org
Пинг, время подключения, размер ответа
Итоговый аптайм, средний пинг
Стабильные серверы отмечены ✅, нестабильные ❌
### 📊 Лог этапа 3 (update_db.py)
Посмотреть последние 50 строк
```bash
tail -50 /var/log/vless_update_db.log
```
Смотреть в реальном времени
```bash
tail -f /var/log/vless_update_db.log
```
Проверить обновление outbound'ов
```bash
grep -E "Обновлен|Добавлен" /var/log/vless_update_db.log
```
Проверить перезапуск x-ui
```bash
grep "Перезапуск x-ui" -A 5 /var/log/vless_update_db.log
```
Лог этапа 3 показывает:
Чтение 10 ссылок из stable_links.txt
Обновление outbound'ов vless_1 ... vless_10 в БД 3x-ui
Обновление балансировщика Balance1
Обновление observatory
Перезапуск x-ui
### 📊 Лог run_stage1.sh и run_stage2.sh (если используются)
Лог этапа 1 через bash-скрипт
```bash
tail -50 /var/log/stage1.log
```
Лог этапа 2+3 через bash-скрипт
```bash
tail -50 /var/log/stage2.log
```
### 📋 Быстрая диагностика одной командой
```bash
echo "=== ЭТАП 1 ===" && tail -5 /var/log/vless_checker.log && echo "" && echo "=== ЭТАП 2 ===" && tail -5 /var/log/server_test.log && echo "" && echo "=== ЭТАП 3 ===" && tail -5 /var/log/vless_update_db.log
```
### 📋 Проверка cron (ночной запуск)
Проверить, что cron работал ночью
```bash
grep -i "vless" /var/log/syslog | grep -i "cron" | tail -10
```
Проверить, что скрипт запускался в 2:00
```bash
grep "Запуск полного цикла" /var/log/vless_full.log | tail -5
```
✅ Признаки успешной работы:

✅ ЭТАП 1 ЗАВЕРШЕН	vless_checker.log	Найдено 30 лучших ссылок

✅ СТАБИЛЬНАЯ	server_test.log	Есть серверы с аптаймом > 85%

✅ База данных обновлена	vless_update_db.log	Outbound'ы обновлены

✅ ВСЕ ЭТАПЫ ВЫПОЛНЕНЫ	vless_full.log	Завершено без ошибок

❌ Признаки проблем

Нет рабочих ссылок	vless_checker.log	Проверить интернет, обновить URL

Все серверы нестабильны	server_test.log	Увеличить время теста, сменить хост

Ошибка БД	vless_update_db.log	Проверить x-ui.db, перезапустить x-ui

Cron не сработал	syslog	Проверить права и пути
