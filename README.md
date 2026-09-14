# VLESS CASCADE

**Каскадный VPN без аренды серверов.** Комбайн по сбору рабочих VLESS-ссылок и их автоматическому обновлению в панели 3x-ui.

[![Telegram](https://img.shields.io/badge/Telegram-@PsoyNe-blue?logo=telegram)](https://t.me/PsoyNe)
![Version](https://img.shields.io/badge/version-1.0.0-green)

---

## 📖 О проекте

Система для организации каскадного VPN на собственном сервере (например, NanoPi Neo) с панелью **3x-ui**.

**Идея:**

- Берём бесплатные VLESS-ссылки из открытых источников (по умолчанию — [ebrasha/free-v2ray-public-list](https://github.com/ebrasha/free-v2ray-public-list)).
- Проверяем их на **реальное соединение** (не пинг, а полноценный HTTPS-запрос через Xray).
- Автоматически подставляем самую стабильную ссылку в outbound панели 3x-ui.
- Держим 4 резервные ссылки наготове.
- При падении основной ссылки — **мгновенно** переключаемся на резервную.

**Что даёт:**

- Не нужно арендовать VPS.
- Не нужно покупать подписку на VPN.
- Нужен только роутер с DDNS (например, Keenetic) и мини-сервер (NanoPi Neo, Raspberry Pi, Orange Pi).
- Устройства в локальной сети выходят в интернет через каскад.

---

## 📂 Структура проекта

### На GitHub

```
vless_cascade/
├── VERSION                    # Текущая версия
├── CHANGELOG.md               # История изменений
├── install.sh                 # Установщик
├── update.sh                  # Обновлятор
├── README.md                  # Этот файл
├── vless_check_config.py      # Конфиг чекера
├── vless_checker.py           # Этап 1: сбор ссылок
├── server_tester.py           # Этап 2 (резервный)
├── run_stage1.sh              # Обёртка этапа 1
├── run_stage2.sh              # Обёртка этапа 2
├── run_full_check.sh          # Полный цикл
├── observer_config.py         # Конфиг observer'а
├── observer.py                # Observer: трёхпоточный
├── show_logs.sh               # Меню логов
└── run_observer.sh            # Ручной запуск observer'а
```

### На сервере после установки

```
/root/
├── .vless_cascade_version     # Установленная версия
├── update.sh                  # Копия скрипта обновления
├── vless_backup_*/            # Бэкапы (5 последних)
│
├── vless_checker/             # Этап 1
│   ├── vless_check_config.py
│   ├── vless_checker.py
│   ├── server_tester.py
│   ├── run_stage1.sh
│   ├── run_stage2.sh
│   ├── run_full_check.sh
│   ├── working_links.txt      # Данные (30 ссылок)
│   ├── stable_links.txt       # Данные (10 ссылок)
│   └── quarantine_links.txt   # Данные (карантин)
│
└── vless_observer/            # Observer
    ├── observer_config.py
    ├── observer.py
    ├── show_logs.sh
    └── run_observer.sh
```

---

## 🔄 Как это работает

### Этап 1: сбор ссылок (`vless_checker.py`)

1. Скачивает список VLESS-ссылок с GitHub.
2. Фильтрует по признакам из конфига:
   - `security=reality`
   - `port=443`
   - уникальные хосты (без дубликатов)
3. Прогоняет каждую ссылку через реальный Xray-тест (HTTPS-запрос на `check.torproject.org`).
4. Отбирает **30 лучших по пингу**.
5. Сохраняет в `working_links.txt`.

**Запуск:** по cron 4 раза в сутки (**01:00, 07:00, 13:00, 19:00**).

**Защита от двойного запуска:** через `flock`. Если предыдущий прогон ещё работает — новый не запустится.

### Observer: удержание связи (`observer.py`)

Работает как systemd-служба в фоне. **Три потока:**

| Поток | Что делает | Интервал |
|-------|-----------|----------|
| **Primary** | Проверяет основную ссылку | каждые 5 сек |
| **Backup** | Проверяет 4 резервные ссылки | каждые 30 сек |
| **Maintenance** | Проверяет отложенные + обновляет пул из файла | 10 мин / 60 сек |

**Ключевые механики:**

- **Переключение:** после 5 отказов подряд основная ссылка заменяется на первую живую из резерва. Обновляется БД 3x-ui, перезапускается Xray.
- **Отложенные (deferred):** мёртвая ссылка уходит в «отложенные» на 10 минут. Потом перепроверяется. Если ожила — возвращается в резерв. Если мертва 2 часа — удаляется.
- **Карантин:** ссылки, которые работают только на Google, но не работают на запрещённые ресурсы, отправляются в `quarantine_links.txt` и больше не используются.
- **Триггеры для отладки:** через файлы в `/tmp/` (см. ниже).

---

## 📋 Требования

- **Железо:** NanoPi Neo (ARMv7), Raspberry Pi, Orange Pi или любой ARM-сервер с Debian.
- **ОС:** Armbian (Debian 13) или аналог.
- **Роутер:** с поддержкой DDNS (например, Keenetic).
- **Панель:** [3x-ui](https://github.com/mhsanaei/3x-ui) — установлена и настроена.

---

## 🚀 Установка

### Шаг 1. Базовая настройка роутера (Keenetic)

1. Зайдите в панель Keenetic → **«Доменное имя»**.
2. Займите свободное имя третьего уровня, например `xxxxx.netcraze.link`.
3. Режим работы — **через облако**.
4. Добавьте **«Доступ к веб-приложениям»**:
   - Имя сервиса: `npi`
   - Получится `npi.xxxxx.netcraze.link`
   - Протокол: **HTTP**, порт **80** (позже поменяем на HTTPS).
5. Пробросьте порт **443** на IP-адрес NanoPi.

### Шаг 2. Базовая настройка NanoPi

```bash
apt update && sudo apt upgrade -y
```

Добейтесь безошибочного обновления. Иногда зарубежные репозитории тормозят — можно обновить через VPN.

### Шаг 3. Установка и настройка 3x-ui

Установите панель по методичке из [этого гайда](https://noname-28.gitbook.io/3x-ui-gaid/nastroika-servera), начиная с вкладки «Настройка сервера».

1. Первый блок кода по файрволу — пропустить.
2. Везде, где `yourdomain.com` — использовать `npi.xxxxx.netcraze.link` из Шага 1.
3. Пройти настройку до конца.
4. На роутере добавить статический маршрут:
   ```bash
   ip host npi.xxxxx.netcraze.link 192.168.1.15
   system configuration save
   ```
5. В Keenetic поменять протокол для `npi.xxxxx.netcraze.link` на **HTTPS**, порт **443**.
6. Зайти в 3x-ui через браузер.
7. Настроить XRAY.
8. Проверить тоннель, создав клиента и подключившись.
9. **Создать outbound `vless_obs`:** Исходящие → добавить VLESS → имя `vless_obs` → вставить любую ссылку во вкладку JSON → импорт.
10. **Создать маршрут:** Маршрутизация → Тэг входящего (созданный в п. 5) → Тэг исходящего `vless_obs` → Сохранить.

### Шаг 4. Установка VLESS CASCADE

```bash
wget -qO- https://raw.githubusercontent.com/PsoyNe/vless_cascade/refs/heads/main/install.sh | bash
```

Скрипт:

- Установит зависимости.
- Скачает чекер и observer в `/root/vless_checker/` и `/root/vless_observer/`.
- Скачает `update.sh` в `/root/update.sh`.
- Сохранит версию в `/root/.vless_cascade_version`.
- Настроит cron на этап 1 (01:00, 07:00, 13:00, 19:00) с защитой `flock`.
- Создаст и запустит systemd-службу `vless_observer`.

### Шаг 5. Первый ручной запуск этапа 1

После установки `working_links.txt` пустой. Нужно дождаться cron **или** запустить вручную:

```bash
cd /root/vless_checker
> /var/log/vless_checker.log
nohup python3 vless_checker.py > /dev/null 2>&1 &
tail -f /var/log/vless_checker.log
```

Ждать **1.5–2 часа** (зависит от провайдера). Появится первая пачка ссылок — observer начнёт работать.

Проверить, что Xray-процессы запускаются и пропадают:

```bash
top
```

Смотреть логи:

```bash
tail -f /var/log/vless_checker.log
```

> **Важно:** не используйте `Ctrl+Z` — это **остановит** процесс, а не завершит. Используйте `Ctrl+C`, если нужно прервать, или `pkill -TERM -f vless_checker.py` для корректной остановки.

### Шаг 6. Проверка observer

```bash
systemctl status vless_observer
tail -f /var/log/vless_observer.log
```

Ожидаемо:

```
🚀 VLESS OBSERVER (multi-threaded)
✅ Загружено 30 ссылок
Установка основной: xxx.xxx.xxx.xxx
Резерв: 4 ссылок
▶️ Поток 1 (основная) запущен
▶️ Поток 2 (резерв) запущен
▶️ Поток 3 (deferred + pool update) запущен
Порты: primary=10808, backup=10809, deferred=10810
```

---

## 🔄 Обновление

### Проверить наличие обновлений

```bash
bash /root/update.sh --check
```

**Что увидишь:**

```
Установленная версия: 1.0.0
Версия на GitHub:     1.1.0
Обновление доступно.
```

Или:

```
Установленная версия: 1.0.0
Версия на GitHub:     1.0.0
✅ У вас последняя версия.
```

### Обновить (с подтверждением)

```bash
bash /root/update.sh
```

**Что произойдёт:**

1. Проверит версию на GitHub.
2. Покажет, что нового в новой версии (из `CHANGELOG.md`).
3. Спросит подтверждение.
4. Создаст бэкап в `/root/vless_backup_YYYYMMDD_HHMMSS/`.
5. Остановит observer.
6. Скачает и обновит все файлы (кроме `working_links.txt`, `stable_links.txt`, `quarantine_links.txt`).
7. Обновит `/root/.vless_cascade_version`.
8. Запустит observer.
9. Проверит, что он работает.

**При успехе:**

```
✅ Версия: 1.0.0 → 1.1.0
📁 Бэкап:  /root/vless_backup_20260914_120000
🔄 Статус службы: active (running)
```

### Обновить без вопросов (для автоматизации)

```bash
bash /root/update.sh --auto
```

Флаг `--auto` — не задаёт вопросов, работает по умолчанию.

> ⚠️ **Не рекомендуется** включать `--auto` в cron. Обновление может сломать систему, а ты узнаешь об этом только утром.

### Откатиться из последнего бэкапа

Если после обновления что-то пошло не так:

```bash
bash /root/update.sh --rollback
```

**Что произойдёт:**

1. Найдёт последний бэкап.
2. Покажет версию из бэкапа.
3. Спросит подтверждение.
4. Остановит observer.
5. Восстановит файлы из бэкапа.
6. Запустит observer.

### Обновление одной командой

Если `update.sh` уже установлен — можно обновляться **без скачивания**:

```bash
wget -qO- https://raw.githubusercontent.com/PsoyNe/vless_cascade/main/update.sh | bash
```

Это **всегда** использует последнюю версию `update.sh` с GitHub, даже если локальная устарела.

### Бэкапы

Бэкапы лежат в `/root/vless_backup_YYYYMMDD_HHMMSS/`. Хранятся **5 последних**.

**Содержимое бэкапа:**

- `vless_checker/` — целиком.
- `vless_observer/` — целиком.
- `vless_observer.service` — systemd-юнит.
- `.vless_cascade_version` — версия на момент бэкапа.

Посмотреть все бэкапы:

```bash
ls -lh /root/vless_backup_*
```

Удалить все бэкапы вручную:

```bash
rm -rf /root/vless_backup_*
```

---

## 🔧 Управление

### Cron

Проверить задание:

```bash
crontab -l | grep vless_checker
```

Изменить расписание:

```bash
crontab -e
```

По умолчанию:

```cron
0 1,7,13,19 * * * /usr/bin/flock -n /var/run/vless_checker.lock /usr/bin/python3 /root/vless_checker/vless_checker.py >> /var/log/vless_checker_cron.log 2>&1
```

Можно изменить на 6 раз в сутки:

```cron
0 2,6,10,14,18,22 * * * /usr/bin/flock -n /var/run/vless_checker.lock /usr/bin/python3 /root/vless_checker/vless_checker.py >> /var/log/vless_checker_cron.log 2>&1
```

> `flock -n` — если предыдущий прогон ещё работает, новый **не запустится**. Это защита от накладок.

### Observer

```bash
systemctl status vless_observer    # статус
systemctl restart vless_observer   # перезапуск
systemctl stop vless_observer      # остановка (SIGTERM, graceful)
systemctl start vless_observer     # запуск
```

### Просмотр логов через меню

```bash
bash /root/vless_observer/show_logs.sh
```

В меню:

- Просмотр логов (Observer, Чекер, cron-обёртка).
- Статистика переключений.
- Очистка логов.
- **Триггеры** — имитация отказа, карантин, глубокая проверка.
- Статус служб и активных процессов.
- Просмотр ротированных архивов логов.

---

## 🧪 Триггеры для отладки

Создайте файл — observer отреагирует в течение 5 секунд.

```bash
touch /tmp/vless_observer_trigger      # имитация 5 отказов → мгновенное переключение
touch /tmp/vless_quarantine_trigger    # отправить основную ссылку в карантин
touch /tmp/vless_deep_check_trigger    # глубокая проверка (Google + запрещённые)
```

Что произойдёт:

- **`vless_observer_trigger`** — observer сделает вид, что основная ссылка упала 5 раз подряд → переключение на резервную. Удобно для тестирования.
- **`vless_quarantine_trigger`** — текущая основная ссылка уйдёт в `quarantine_links.txt` и больше никогда не будет использована. Observer переключится на резерв.
- **`vless_deep_check_trigger`** — observer проверит основную ссылку через Google (204) и через запрещённые ресурсы (instagram.com, facebook.com, check.torproject.org). Если Google OK, а запрещённые — нет, ссылка уйдёт в карантин.

---

## 📊 Логи

```
/var/log/
├── vless_checker.log         # Этап 1 (сбор ссылок)
├── vless_observer.log        # Observer (основной)
└── vless_checker_cron.log    # Обёртка cron (stdout/stderr этапа 1)
```

**Ротация:** каждый лог автоматически ротируется в полночь. Хранится 7 архивов.

Просмотр архивов:

```bash
ls -lh /var/log/vless_observer.log*
```

---

## ⚙️ Конфигурация

### `vless_check_config.py` — этап 1

```python
FILTER_MODE = 'reality_443'      # 'reality_443' | 'reality' | 'port_443' | 'all'
CHECK_MODE = 'until_30'          # 'until_30' | 'all'
STAGE1_WORKING_COUNT = 30        # сколько ссылок сохранять
STAGE1_MAX_WORKERS = 8           # потоков
STAGE1_TIMEOUT = 10              # таймаут на запрос (сек)
```

### `observer_config.py` — observer

```python
LINKS_FILE = "/root/vless_checker/working_links.txt"   # источник ссылок

PROXY_PORT_PRIMARY = 10808       # порт для проверки основной
PROXY_PORT_BACKUP = 10809        # порт для проверки резерва
PROXY_PORT_DEFERRED = 10810      # порт для отложенных

CHECK_INTERVAL_PRIMARY = 5       # проверка основной (сек)
CHECK_INTERVAL_BACKUP = 30       # проверка резерва (сек)
FAILURES_TO_SWITCH = 5           # отказов подряд до переключения
BACKUP_POOL_SIZE = 4             # размер резервного пула

DEAD_LINK_RETRY_INTERVAL = 600   # перепроверка отложенных (10 минут)
DEAD_LINK_DELETE_AFTER = 7200    # удаление мёртвых (2 часа)
```

---

## 🔥 Особенности

1. **Ссылки берутся из открытых источников.** Формат должен совпадать с тем, что отдаёт GitHub.
2. **NanoPi Neo (256/512 МБ)** — оптимальная платформа. Потянет и Raspberry/Orange. Для скоростей >100 Мбит — нужно другое железо.
3. **Тестируется реальный доступ через Xray**, а не просто пинг. По умолчанию — `https://check.torproject.org`.
4. **Фильтр на входе:** только `security=reality` + порт `443`. Такие ссылки живут дольше.
5. **Балансировщик 3x-ui не используется.** Вместо него — собственная обсерватория с контролем ссылки на выходе.
6. **Observer держит 1 основную + 4 резервных.** Остальные 25 из файла — «склад», откуда observer берёт замену.
7. **Три потока в observer** — основная, резерв, обслуживание (deferred + pool). Основная проверяется каждые 5 секунд, независимо от остальных.

---

## 🎁 Бонус: прокси на 1080 порту

В панели 3x-ui можно поднять **входящее соединение `mixed` на порту 1080**. Это даст локальный SOCKS5/HTTP-прокси.

В Keenetic:

1. Настроить подключение к этому прокси (`IP NanoPi`, порт `1080`).
2. Создать политику доступа через этот прокси.
3. Назначить устройствам в сети выход через каскад.

---

## 🌍 Мобильный вариант

Абсолютно не привязан к физическому месту. Если воткнуть в Keenetic 4G-модем — получится **мобильный передвижной сервер** с полноценным каскадом.

---

## 🐛 Известные особенности

- **`резерв: 4/4 живых` сразу после старта observer'а** — это оптимистичное предположение. Через 30 секунд резерв реально проверяется, и статус становится честным.
- **Этап 2 (`server_tester.py`)** работает, но его результат (`stable_links.txt`) observer'ом **не используется**. Оставлен как резервный / для отдельного анализа.

---

## 📜 Лицензия

Свободное использование. Ссылки берутся из открытых источников.

---

## 💬 Контакты

Telegram: [@PsoyNe](https://t.me/PsoyNe)

---

⭐ Если проект оказался полезен — поставьте звезду на GitHub!
