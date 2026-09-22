#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Обработчики команд и callback'ов Telegram-бота.

Логика:
  1. Фильтр авторизации — только TELEGRAM_CHAT_ID может управлять.
     Остальные игнорируются молча.
  2. Команды без аргументов: /status, /links, /switch, /reload, /help, /start.
  3. Команды с аргументами: /geo XX, /pick host, /ignore host, /unignore host.
  4. Callback'и от inline-кнопок (callback_data = "cmd:<action>").
  5. Сериализация запросов к observer'у через asyncio.Lock — потому
     что observer обрабатывает ОДИН триггер за цикл (раз в 5 сек).
     Параллельные запросы растянулись бы и создали очередь из триггеров.

Никакой отправки сообщений об ошибках неавторизованным — по ТЗ
игнорируем молча.
"""

import os
import re
import asyncio
import logging
from datetime import datetime

from aiogram import Router, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery

import vless_bot_config as cfg
import bot_observer_client as client
import bot_formatters as fmt
import bot_keyboards as kb

logger = logging.getLogger(__name__)

router = Router(name="vless_bot")

# Глобальный лок: один запрос к observer'у за раз.
_observer_lock = asyncio.Lock()


# ============================================================
# ЛОКАЛЬНАЯ ИНФОРМАЦИЯ О ЧЕКЕРЕ
# ============================================================

# Путь к файлу, который наполняет vless_checker.py.
# Бот его только читает — для отображения в /status.
_CHECKER_FILE = "/root/vless_checker/working_links.txt"

# Порог свежести файла (часы). Чекер запускается по cron 4 раза
# в сутки (01:00, 07:00, 13:00, 19:00) — раз в 6 часов. Если файл
# не обновлялся дольше порога — показываем ⚠️.
_CHECKER_STALE_HOURS = 6


def _humanize_age(seconds: float) -> str:
    """
    Превращает «сколько секунд назад» в человекочитаемую строку:
    '5 сек', '12 мин', '3 ч 15 мин', '2 д 4 ч'.
    """
    if seconds < 0:
        seconds = 0
    seconds = int(seconds)

    if seconds < 60:
        return f"{seconds} сек"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} мин"

    hours = minutes // 60
    rem_minutes = minutes % 60
    if hours < 24:
        if rem_minutes:
            return f"{hours} ч {rem_minutes} мин"
        return f"{hours} ч"

    days = hours // 24
    rem_hours = hours % 24
    if rem_hours:
        return f"{days} д {rem_hours} ч"
    return f"{days} д"


def _read_checker_info() -> dict:
    """
    Читает working_links.txt: количество ссылок и свежесть.

    Возвращает dict:
      {
        "exists": bool,
        "count": int | None,
        "age_str": str | None,   # '2 ч 15 мин'
        "fresh": bool | None,    # None если файла нет
      }

    Никогда не бросает исключение — при ошибке возвращает
    безопасный результат.
    """
    path = _CHECKER_FILE

    if not os.path.exists(path):
        return {
            "exists": False,
            "count": None,
            "age_str": None,
            "fresh": None,
        }

    # Количество непустых строк
    count = None
    try:
        c = 0
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if line.strip():
                    c += 1
        count = c
    except Exception as e:
        logger.warning(f"Не удалось прочитать {path}: {e}")

    # Свежесть по mtime
    age_str = None
    fresh = None
    try:
        mtime = os.path.getmtime(path)
        age_seconds = datetime.now().timestamp() - mtime
        age_str = _humanize_age(age_seconds)
        fresh = age_seconds < _CHECKER_STALE_HOURS * 3600
    except Exception as e:
        logger.warning(f"Не удалось получить mtime {path}: {e}")

    return {
        "exists": True,
        "count": count,
        "age_str": age_str,
        "fresh": fresh,
    }


# ============================================================
# АВТОРИЗАЦИЯ
# ============================================================

def _is_authorized(message: Message) -> bool:
    """Только TELEGRAM_CHAT_ID может управлять ботом."""
    return message.chat.id == cfg.TELEGRAM_CHAT_ID


def _is_authorized_cb(callback: CallbackQuery) -> bool:
    """То же для callback'ов."""
    if not callback.message:
        return False
    return callback.message.chat.id == cfg.TELEGRAM_CHAT_ID


# ============================================================
# ВСПОМОГАТЕЛЬНОЕ
# ============================================================

# Валидация аргументов
_COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9._\-]+$")    # домен или IP, без порта и схемы


def _parse_args(command_object: CommandObject) -> str:
    """Возвращает строку аргументов команды (после имени), stripped."""
    if not command_object or not command_object.args:
        return ""
    return command_object.args.strip()


def _short_action_name(response: dict) -> str:
    """Человекочитаемое имя команды для сообщения об ошибке."""
    action = response.get("action", "?")
    if action.startswith("geo_"):
        return f"Переключение на страну {action[4:]}"
    if action.startswith("pick_"):
        return f"Переключение на host {action[5:]}"
    if action.startswith("ignore_"):
        return f"Карантин {action[7:]}"
    if action.startswith("unignore_"):
        return f"Из карантина {action[9:]}"
    mapping = {
        "status": "Статус",
        "links": "Ссылки",
        "switch": "Switch",
        "reload": "Reload",
    }
    return mapping.get(action, action)


async def _send_status(message_or_bot, chat_id: int, response: dict, bot: Bot = None):
    """
    Универсальная отправка /status: подмешивает локальную инфу
    о чекере и шлёт через нужный канал (message или bot).
    """
    checker = _read_checker_info()
    text = fmt.format_status(response, checker=checker)
    markup = kb.status_keyboard()

    if bot is not None:
        await bot.send_message(chat_id, text,
                               parse_mode=cfg.PARSE_MODE,
                               reply_markup=markup)
    else:
        await message_or_bot.answer(text,
                                    parse_mode=cfg.PARSE_MODE,
                                    reply_markup=markup)


# ============================================================
# ОБЩИЙ ОБРАБОТЧИК РЕЗУЛЬТАТА
# ============================================================

async def _handle_response(message: Message, response: dict):
    """
    Универсальная обработка ответа observer'а для команд
    switch/geo/pick/ignore/unignore/reload.
    """
    if not response.get("ok"):
        await message.answer(
            fmt.format_error(response),
            parse_mode=cfg.PARSE_MODE,
            reply_markup=kb.error_keyboard(),
        )
        return

    action = response.get("action", "")

    if action == "switch":
        text = fmt.format_switch_result(response, "Переключение")
        markup = kb.switch_result_keyboard()
    elif action.startswith("geo_"):
        country = action[4:]
        text = fmt.format_switch_result(response, f"Переключение на страну {country}")
        markup = kb.switch_result_keyboard()
    elif action.startswith("pick_"):
        host = action[5:]
        text = fmt.format_switch_result(response, f"Переключение на host {host}")
        markup = kb.switch_result_keyboard()
    elif action.startswith("ignore_"):
        text = fmt.format_ignore_result(response)
        markup = kb.status_keyboard()
    elif action.startswith("unignore_"):
        text = fmt.format_unignore_result(response)
        markup = kb.status_keyboard()
    elif action == "reload":
        text = fmt.format_reload_result(response)
        markup = kb.status_keyboard()
    else:
        text = f"✅ <b>{_short_action_name(response)}</b>"
        markup = kb.status_keyboard()

    await message.answer(text, parse_mode=cfg.PARSE_MODE, reply_markup=markup)


# ============================================================
# КОМАНДЫ БЕЗ АРГУМЕНТОВ
# ============================================================

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not _is_authorized(message):
        logger.debug(f"Игнор /start от chat_id={message.chat.id}")
        return

    logger.info(f"/start от chat_id={message.chat.id}")
    await message.answer(
        fmt.format_help(),
        parse_mode=cfg.PARSE_MODE,
        reply_markup=kb.main_menu_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    if not _is_authorized(message):
        return

    logger.info(f"/help от chat_id={message.chat.id}")
    await message.answer(
        fmt.format_help(),
        parse_mode=cfg.PARSE_MODE,
        reply_markup=kb.main_menu_keyboard(),
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    if not _is_authorized(message):
        return

    logger.info(f"/status от chat_id={message.chat.id}")

    async with _observer_lock:
        response = await client.request_status()

    if not response.get("ok"):
        await message.answer(
            fmt.format_error(response),
            parse_mode=cfg.PARSE_MODE,
            reply_markup=kb.error_keyboard(),
        )
        return

    await _send_status(message, message.chat.id, response)


@router.message(Command("links"))
async def cmd_links(message: Message):
    if not _is_authorized(message):
        return

    logger.info(f"/links от chat_id={message.chat.id}")

    async with _observer_lock:
        response = await client.request_links()

    if not response.get("ok"):
        await message.answer(
            fmt.format_error(response),
            parse_mode=cfg.PARSE_MODE,
            reply_markup=kb.error_keyboard(),
        )
        return

    parts = fmt.format_links(response)
    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        markup = kb.links_keyboard() if is_last else None
        await message.answer(part, parse_mode=cfg.PARSE_MODE, reply_markup=markup)


@router.message(Command("switch"))
async def cmd_switch(message: Message):
    if not _is_authorized(message):
        return

    logger.info(f"/switch от chat_id={message.chat.id}")

    warn_msg = await message.answer(
        fmt.format_switch_warning(),
        parse_mode=cfg.PARSE_MODE,
    )

    async with _observer_lock:
        response = await client.request_switch()

    try:
        await warn_msg.delete()
    except Exception:
        pass

    await _handle_response(message, response)


@router.message(Command("reload"))
async def cmd_reload(message: Message):
    if not _is_authorized(message):
        return

    logger.info(f"/reload от chat_id={message.chat.id}")

    async with _observer_lock:
        response = await client.request_reload()

    await _handle_response(message, response)


# ============================================================
# КОМАНДЫ С АРГУМЕНТАМИ
# ============================================================

@router.message(Command("geo"))
async def cmd_geo(message: Message, command: CommandObject):
    if not _is_authorized(message):
        return

    arg = _parse_args(command)
    logger.info(f"/geo {arg} от chat_id={message.chat.id}")

    if not _COUNTRY_RE.match(arg):
        await message.answer(
            fmt.format_invalid_argument(
                "geo", arg,
                "Ожидается двухбуквенный код страны, например: /geo DE"
            ),
            parse_mode=cfg.PARSE_MODE,
            reply_markup=kb.error_keyboard(),
        )
        return

    country = arg.upper()

    warn_msg = await message.answer(
        fmt.format_switch_warning(),
        parse_mode=cfg.PARSE_MODE,
    )

    async with _observer_lock:
        response = await client.request_geo(country)

    try:
        await warn_msg.delete()
    except Exception:
        pass

    await _handle_response(message, response)


@router.message(Command("pick"))
async def cmd_pick(message: Message, command: CommandObject):
    if not _is_authorized(message):
        return

    arg = _parse_args(command)
    logger.info(f"/pick {arg} от chat_id={message.chat.id}")

    if not arg or not _HOST_RE.match(arg):
        await message.answer(
            fmt.format_invalid_argument(
                "pick", arg,
                "Ожидается host (домен или IP), например: /pick 1.2.3.4"
            ),
            parse_mode=cfg.PARSE_MODE,
            reply_markup=kb.error_keyboard(),
        )
        return

    warn_msg = await message.answer(
        fmt.format_switch_warning(),
        parse_mode=cfg.PARSE_MODE,
    )

    async with _observer_lock:
        response = await client.request_pick(arg)

    try:
        await warn_msg.delete()
    except Exception:
        pass

    await _handle_response(message, response)


@router.message(Command("ignore"))
async def cmd_ignore(message: Message, command: CommandObject):
    if not _is_authorized(message):
        return

    arg = _parse_args(command)
    logger.info(f"/ignore {arg} от chat_id={message.chat.id}")

    if not arg or not _HOST_RE.match(arg):
        await message.answer(
            fmt.format_invalid_argument(
                "ignore", arg,
                "Ожидается host (домен или IP), например: /ignore 1.2.3.4"
            ),
            parse_mode=cfg.PARSE_MODE,
            reply_markup=kb.error_keyboard(),
        )
        return

    async with _observer_lock:
        response = await client.request_ignore(arg)

    await _handle_response(message, response)


@router.message(Command("unignore"))
async def cmd_unignore(message: Message, command: CommandObject):
    if not _is_authorized(message):
        return

    arg = _parse_args(command)
    logger.info(f"/unignore {arg} от chat_id={message.chat.id}")

    if not arg or not _HOST_RE.match(arg):
        await message.answer(
            fmt.format_invalid_argument(
                "unignore", arg,
                "Ожидается host (домен или IP), например: /unignore 1.2.3.4"
            ),
            parse_mode=cfg.PARSE_MODE,
            reply_markup=kb.error_keyboard(),
        )
        return

    async with _observer_lock:
        response = await client.request_unignore(arg)

    await _handle_response(message, response)


# ============================================================
# CALLBACK'И (INLINE-КНОПКИ)
# ============================================================

@router.callback_query(lambda c: c.data and c.data.startswith("cmd:"))
async def on_callback(callback: CallbackQuery, bot: Bot):
    if not _is_authorized_cb(callback):
        await callback.answer()
        return

    action = callback.data[len("cmd:"):]
    chat_id = callback.message.chat.id
    logger.info(f"callback '{action}' от chat_id={chat_id}")

    await callback.answer()

    if action == "help":
        await bot.send_message(
            chat_id,
            fmt.format_help(),
            parse_mode=cfg.PARSE_MODE,
            reply_markup=kb.main_menu_keyboard(),
        )
        return

    if action == "status":
        async with _observer_lock:
            response = await client.request_status()
        if not response.get("ok"):
            await bot.send_message(
                chat_id,
                fmt.format_error(response),
                parse_mode=cfg.PARSE_MODE,
                reply_markup=kb.error_keyboard(),
            )
            return
        await _send_status(None, chat_id, response, bot=bot)
        return

    if action == "links":
        async with _observer_lock:
            response = await client.request_links()
        if not response.get("ok"):
            await bot.send_message(
                chat_id,
                fmt.format_error(response),
                parse_mode=cfg.PARSE_MODE,
                reply_markup=kb.error_keyboard(),
            )
            return
        parts = fmt.format_links(response)
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            markup = kb.links_keyboard() if is_last else None
            await bot.send_message(
                chat_id, part, parse_mode=cfg.PARSE_MODE, reply_markup=markup
            )
        return

    if action == "switch":
        warn = await bot.send_message(
            chat_id,
            fmt.format_switch_warning(),
            parse_mode=cfg.PARSE_MODE,
        )
        async with _observer_lock:
            response = await client.request_switch()
        try:
            await warn.delete()
        except Exception:
            pass
        if not response.get("ok"):
            await bot.send_message(
                chat_id,
                fmt.format_error(response),
                parse_mode=cfg.PARSE_MODE,
                reply_markup=kb.error_keyboard(),
            )
            return
        await bot.send_message(
            chat_id,
            fmt.format_switch_result(response, "Переключение"),
            parse_mode=cfg.PARSE_MODE,
            reply_markup=kb.switch_result_keyboard(),
        )
        return

    if action == "reload":
        async with _observer_lock:
            response = await client.request_reload()
        if not response.get("ok"):
            await bot.send_message(
                chat_id,
                fmt.format_error(response),
                parse_mode=cfg.PARSE_MODE,
                reply_markup=kb.error_keyboard(),
            )
            return
        await bot.send_message(
            chat_id,
            fmt.format_reload_result(response),
            parse_mode=cfg.PARSE_MODE,
            reply_markup=kb.status_keyboard(),
        )
        return

    logger.warning(f"Неизвестный callback action: {action}")


# ============================================================
# НЕИЗВЕСТНЫЕ КОМАНДЫ / СООБЩЕНИЯ
# ============================================================

@router.message(Command(re.compile(r".*")))
async def cmd_unknown(message: Message):
    """
    Ловит любую команду, которая не была обработана выше.
    """
    if not _is_authorized(message):
        return

    known = {"start", "help", "status", "links", "switch", "reload",
             "geo", "pick", "ignore", "unignore"}
    text = message.text or ""
    if text.startswith("/"):
        cmd = text.split()[0][1:].split("@")[0]
        if cmd in known:
            return

    logger.debug(f"Неизвестная команда: {text!r}")
    await message.answer(
        fmt.format_unknown_command(text),
        parse_mode=cfg.PARSE_MODE,
        reply_markup=kb.error_keyboard(),
    )
