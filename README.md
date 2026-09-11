# VLESS CASCADE

**Каскадный VPN без аренды серверов.** Комбайн по сбору рабочих VLESS-ссылок и их автоматическому обновлению в панели 3x-ui.

[![Telegram](https://img.shields.io/badge/Telegram-@PsoyNe-blue?logo=telegram)](https://t.me/PsoyNe)

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

```
/root/
├── vless_checker/                 # Этап 1: сбор рабочих ссылок
│   ├── vless_check_config.py      # Конфигурация
│   ├── vless_checker.py           # Сборщик 30 лучших ссылок
│   ├── server_tester.py           # Резервный этап 2 (не используется observer'ом)
│   ├── run_stage1.sh              # Обёртка для запуска этапа 1
│   ├── run_stage2.sh              # Обёртка для запуска этапа 2
│   ├── run_full_check.sh          # Полный цикл (этап 1 + этап 2)
│   ├── working_links.txt          # 30 рабочих ссылок (создаётся)
│   ├── stable_links.txt           # 10 стабильных ссылок (создаётся этапом 2)
│   └── quarantine_links.txt       # Карантин (создаётся observer'ом)
│
└── vless_observer/                # Observer: держит соединение живым
    ├── observer_config.py         # Конфигурация
    ├── observer.py                # Трёхпоточный наблюдатель
    ├── show_logs.sh               # Меню просмотра логов и триггеров
    └── run_observer.sh            # Обёртка для ручного запуска
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
- Настроит cron на этап 1 (01:00, 07:00, 13:00, 19:00).
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
0 1,7,13,19 * * * /usr/bin/python3 /root/vless_checker/vless_checker.py >> /var/log/vless_checker_cron.log 2>&1
```

Можно изменить на 6 раз в сутки:

```cron
0 2,6,10,14,18,22 * * * /usr/bin/python3 /root/vless_checker/vless_checker.py >> /var/log/vless_checker_cron.log 2>&1
```

### Observer

```bash
systemctl status vless_observer    # статус
systemctl restart vless_observer   # перезапуск
systemctl stop vless_observer      # остановка (SIGTERM, graceful)
systemctl start vless_observer
