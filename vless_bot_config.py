#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ============================================================
# КОНФИГУРАЦИЯ ДЛЯ VLESS BOT
# ============================================================
#
# Telegram-бот для управления observer'ом через файлы-триггеры.
# Отдельная служба vless_bot.service, независима от vless_observer.
#
# ВАЖНО: бот НЕ трогает observer, vless_common, triggers.
# Общение — только через /tmp/vless_* файлы.
#
# Связь с Telegram идёт через SOCKS5-прокси (порт 1080, inbound
# 3x-ui "mixed"), который работает на текущей primary-ссылке,
# подготовленной observer'ом. Без прокси Telegram в РФ недоступен.
# ============================================================

import os

# -------------------- TELEGRAM --------------------
# Токен бота — получить у @BotFather.
TELEGRAM_BOT_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"

# Chat ID пользователя, которому разрешено управлять ботом.
# Только этот ID может отправлять команды. Остальные игнорируются.
# Узнать свой chat_id можно у @userinfobot.
TELEGRAM_CHAT_ID = 0    # заменить на свой (int)

# Прокси для доступа к api.telegram.org (РФ блокирует).
#
# Используется SOCKS5-inbound 3x-ui на порту 1080 ("mixed").
# Без авторизации (auth: noauth).
#
# Если вдруг SOCKS5 не заработает — можно переключить на
# "http://127.0.0.1:1080" (protocol "mixed" принимает оба),
# aiogram v3 умеет и то, и другое через AiohttpSession.
TELEGRAM_PROXY = "socks5://127.0.0.1:1080"

# Ретраи подключения к Telegram при старте и при сетевых ошибках.
# Observer может ещё не успеть поднять Xray — бот должен терпеливо
# ждать.
TELEGRAM_CONNECT_RETRY_INTERVAL = 10    # сек между попытками
TELEGRAM_CONNECT_MAX_ATTEMPTS = 0       # 0 = бесконечно

# -------------------- ПУТИ --------------------
# Рабочая директория бота (логи, стейт, если понадобится).
WORK_DIR = "/root/vless_bot"

# Файл лога.
LOG_FILE = "/var/log/vless_bot.log"

# -------------------- ТРИГГЕРЫ --------------------
# Директория, где observer ждёт триггеры. Должна совпадать с
# тем, что использует observer (в triggers.py — жёстко /tmp).
TRIGGER_DIR = "/tmp"

# Максимальный возраст триггера (сек). Должен совпадать с
# TRIGGER_MAX_AGE в observer_config.py. Если observer не успел
# обработать триггер за это время — он его удалит без выполнения.
TRIGGER_MAX_AGE = 30

# Сколько ждать появления response-файла. Ставим чуть меньше
# TRIGGER_MAX_AGE, чтобы observer успел обработать триггер и
# записать ответ, даже если мы создали его в самом конце окна.
RESPONSE_WAIT_TIMEOUT = 27

# Как часто проверять появление response-файла (сек).
RESPONSE_POLL_INTERVAL = 0.3

# -------------------- ЧЕКЕР (локальная информация) --------------------
# Файл, который наполняет vless_checker.py. Бот его только читает —
# чтобы показать в /status количество ссылок и свежесть обновления.
CHECKER_LINKS_FILE = "/root/vless_checker/working_links.txt"

# Порог свежести файла (часы). Чекер запускается по cron 4 раза
# в сутки (01:00, 07:00, 13:00, 19:00) — раз в 6 часов. Если файл
# не обновлялся дольше порога — показываем ⚠️ «давно не обновлялся».
CHECKER_STALE_HOURS = 6

# -------------------- ЛОГИРОВАНИЕ --------------------
# Логировать ли полное тело JSON-ответа observer'а.
# Полезно для отладки, но раздувает лог. По умолчанию — выключено.
LOG_RESPONSE_BODY = False

# Ротация логов (как у observer'а).
LOG_ROTATION_WHEN = "midnight"
LOG_ROTATION_INTERVAL = 1
LOG_ROTATION_BACKUPS = 7
LOG_ROTATION_UTCFORMAT = "%Y-%m-%d"

# -------------------- ФОРМАТИРОВАНИЕ TELEGRAM --------------------
# parse_mode для сообщений. "HTML" безопаснее Markdown.
PARSE_MODE = "HTML"

# Лимит длины сообщения Telegram — 4096. Ставим с запасом,
# чтобы укладываться с учётом тегов и эмодзи.
MAX_MESSAGE_LENGTH = 4000

# -------------------- КНОПКИ --------------------
# Включить inline-клавиатуры под сообщениями.
ENABLE_INLINE_KEYBOARDS = True

# -------------------- СЛУЖБА --------------------
SERVICE_NAME = "vless_bot"
SERVICE_DESCRIPTION = "VLESS Bot - Telegram control for VLESS Observer"
SERVICE_FILE = "/etc/systemd/system/vless_bot.service"
