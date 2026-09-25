#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Форматирование ответов observer'а в HTML-сообщения Telegram.

Все функции принимают dict — ответ observer'а (JSON) — и возвращают
строку в HTML (parse_mode=HTML). Никакой логики отправки — только
построение текста.

Соглашение:
  - Любые пользовательские данные (host, country, error) экранируются
    через html.escape(), чтобы не сломать разметку.
  - Хосты оборачиваем в <code>...</code> — удобно копировать.
  - Без отступов: всё по левому краю. Галочки/крестики — слева.
  - Эмодзи для визуальной читаемости.
  - Длинные сообщения режем по cfg.MAX_MESSAGE_LENGTH.
"""

import html
from datetime import datetime
from typing import List, Optional

import vless_bot_config as cfg


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ
# ============================================================

def _esc(value) -> str:
    """Экранирует HTML-спецсимволы. None → 'N/A'."""
    if value is None:
        return "N/A"
    return html.escape(str(value))


def _fmt_ts(ts: Optional[float]) -> str:
    """Форматирует unix-timestamp в читаемое время."""
    if not ts:
        return "N/A"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "N/A"


def _fmt_ping(ping) -> Optional[int]:
    """
    Приводит ping к целому числу.
    Возвращает None, если ping отсутствует или не число.
    """
    if ping is None:
        return None
    try:
        return int(round(float(ping)))
    except (ValueError, TypeError):
        return None


def _fmt_deferred_time(deferred_min) -> Optional[str]:
    """
    Форматирует время отложенности (в минутах) в человекочитаемое:
      - < 60 мин     → 'N мин'
      - >= 60 мин    → 'X ч Y мин' (если Y == 0 → 'X ч')
      - >= 1440 мин  → 'X д Y ч'   (на всякий случай)

    Возвращает None, если значение отсутствует или не число.
    """
    if deferred_min is None:
        return None
    try:
        minutes = int(deferred_min)
    except (ValueError, TypeError):
        return None

    if minutes < 0:
        minutes = 0

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


def _truncate(text: str, limit: int = None) -> str:
    """Режет текст по лимиту, добавляя '…'."""
    if limit is None:
        limit = cfg.MAX_MESSAGE_LENGTH
    if len(text) <= limit:
        return text
    return text[:limit - 1] + "…"


def _split_message(text: str, limit: int = None) -> List[str]:
    """
    Режет длинное сообщение на части по границам строк.
    Каждая часть ≤ limit. Используется, если одно сообщение
    не влезает в лимит Telegram.
    """
    if limit is None:
        limit = cfg.MAX_MESSAGE_LENGTH

    if len(text) <= limit:
        return [text]

    parts = []
    current = []
    current_len = 0

    for line in text.split("\n"):
        line_len = len(line) + 1
        if current_len + line_len > limit and current:
            parts.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        parts.append("\n".join(current))

    return parts


# ============================================================
# ОБЩИЕ БЛОКИ
# ============================================================

def format_error(response: dict) -> str:
    """Форматирует ответ с ok=false или ошибку связи."""
    action = _esc(response.get("action", "?"))
    error = _esc(response.get("error", "Неизвестная ошибка"))
    return (
        f"❌ <b>Ошибка</b>\n"
        f"<b>Команда:</b> <code>{action}</code>\n"
        f"<b>Причина:</b> {error}"
    )


# ============================================================
# /status
# ============================================================

def format_status(response: dict,
                  checker: Optional[dict] = None,
                  system: Optional[dict] = None) -> str:
    """
    Форматирует ответ на /status.

    Параметры:
      response — ответ observer'а (JSON).
        Ожидает data:
          primary, primary_fail_count, primary_success_count,
          backup_alive, backup_total,
          backup_hosts: [{host, country, ping, alive}],
          deferred_count, dead_count, switch_count
      checker  — локальная информация о working_links.txt
        (см. bot_handlers._read_checker_info). Может быть None.
      system   — системная информация (CPU)
        (см. bot_handlers._read_system_info). Может быть None.

    Всё по левому краю, без отступов.
    """
    data = response.get("data") or {}

    primary = _esc(data.get("primary", "N/A"))
    fail = data.get("primary_fail_count", 0)
    success = data.get("primary_success_count", 0)
    backup_alive = data.get("backup_alive", 0)
    backup_total = data.get("backup_total", 0)
    backup_hosts = data.get("backup_hosts", []) or []
    deferred = data.get("deferred_count", 0)
    dead = data.get("dead_count", 0)
    switches = data.get("switch_count", 0)

    lines = ["📡 <b>Статус observer</b>", ""]

    # Основная
    lines.append(f"🟢 <b>Основная:</b> <code>{primary}</code>")
    lines.append(f"✅ Успехов: {success}   ❌ Отказов: {fail}")
    lines.append("")

    # Резерв — без отступов, галочки слева
    lines.append(f"🛡 <b>Резерв:</b> {backup_alive}/{backup_total} живых")
    if backup_hosts:
        for item in backup_hosts:
            host = _esc(item.get("host", "?"))
            country = _esc(item.get("country", "N/A"))
            ping = _fmt_ping(item.get("ping"))
            alive = item.get("alive", False)
            mark = "✅" if alive else "❌"

            ping_str = f" — {ping} ms" if ping is not None else ""
            lines.append(f"{mark} <code>{host}</code> [{country}]{ping_str}")
    else:
        lines.append("<i>резерв пуст</i>")
    lines.append("")

    # Счётчики
    lines.append(
        f"⏳ Отложенные: {deferred}   💀 Мёртвые: {dead}   "
        f"🔄 Переключений: {switches}"
    )

    # Локальная информация о чекере
    if checker:
        lines.append("")
        lines.append(_format_checker_block(checker))

    # Системная информация (CPU)
    if system:
        sys_lines = _format_system_block(system)
        if sys_lines:
            lines.append(sys_lines)

    # Время ответа
    lines.append("")
    lines.append(f"🕒 <i>{_fmt_ts(response.get('timestamp'))}</i>")

    return _truncate("\n".join(lines))


def _format_checker_block(checker: dict) -> str:
    """
    Форматирует блок про working_links.txt.
    Ожидает dict от bot_handlers._read_checker_info:
      {exists, count, age_str, fresh}
    """
    if not checker.get("exists"):
        return (
            "📄 <b>Файл ссылок:</b> —\n"
            "🧠 <b>Чекер:</b> ⚠️ файл не найден"
        )

    count = checker.get("count")
    count_str = str(count) if count is not None else "?"

    age_str = checker.get("age_str") or "?"
    fresh = checker.get("fresh")

    if fresh is True:
        status = f"🟢 обновлён {age_str} назад"
    elif fresh is False:
        status = f"⚠️ обновлён {age_str} назад"
    else:
        status = f"⚪ неизвестно ({age_str})"

    return (
        f"📄 <b>Файл ссылок:</b> {count_str}\n"
        f"🧠 <b>Чекер:</b> {status}"
    )


def _format_system_block(system: dict) -> str:
    """
    Форматирует блок с системной информацией.
    Ожидает dict от bot_handlers._read_system_info:
      {psutil, cpu_temp, cpu_load}
    Возвращает пустую строку, если нечего показывать.
    """
    if not system:
        return ""

    psutil_ok = system.get("psutil", False)
    cpu_temp = system.get("cpu_temp")
    cpu_load = system.get("cpu_load")

    # Если psutil нет и данных нет — ничего не показываем.
    if not psutil_ok and cpu_temp is None and cpu_load is None:
        return ""

    parts = []

    if cpu_temp is not None:
        try:
            parts.append(f"🌡 CPU: {int(round(float(cpu_temp)))}°C")
        except (ValueError, TypeError):
            pass

    if cpu_load is not None:
        try:
            parts.append(f"⚡ Загрузка: {int(round(float(cpu_load)))}%")
        except (ValueError, TypeError):
            pass

    return "   ".join(parts)


# ============================================================
# /links
# ============================================================

def _fmt_backup_line(item: dict) -> str:
    """
    Строка для резерва: галочка слева, ping, без отступа.
        ✅ <code>host</code> [CC] — N ms
    """
    host = _esc(item.get("host", "?"))
    country = _esc(item.get("country", "N/A"))
    ping = _fmt_ping(item.get("ping"))
    alive = item.get("alive", False)
    mark = "✅" if alive else "❌"

    ping_str = f" — {ping} ms" if ping is not None else ""
    return f"{mark} <code>{host}</code> [{country}]{ping_str}"


def _fmt_plain_line(item: dict, extra: Optional[str] = None) -> str:
    """
    Строка без галочки и без ping (deferred / dead / quarantine):
        <code>host</code> [CC] [— extra]

    Параметры:
      item  — {host, country}
      extra — необязательный текст в конец (для deferred: '— N мин')
    """
    host = _esc(item.get("host", "?"))
    country = _esc(item.get("country", "N/A"))

    line = f"<code>{host}</code> [{country}]"
    if extra:
        line += f" {extra}"
    return line


def format_links(response: dict) -> List[str]:
    """
    Форматирует ответ на /links.

    Возвращает СПИСОК строк — потому что при большом числе ссылок
    одно сообщение может не влезть в лимит Telegram.

    Всё по левому краю, без отступов. Галочка — только у резерва.

    Ожидает data (формат observer >= 1.0.8):
      primary:    {link, host, country} | None,
      backup:     [{link, host, country, ping, alive}],
      deferred:   [{link, host, country, deferred_min}],
      dead:       [{link, host, country}],
      quarantine: [{link, host, country}]
    """
    data = response.get("data") or {}

    primary = data.get("primary")
    backup = data.get("backup", []) or []
    deferred = data.get("deferred", []) or []
    dead = data.get("dead", []) or []
    quarantine = data.get("quarantine", []) or []

    lines = ["🔗 <b>Ссылки observer</b>", ""]

    # Основная
    lines.append("🟢 <b>Основная:</b>")
    if primary:
        host = _esc(primary.get("host", "?"))
        country = _esc(primary.get("country", "N/A"))
        lines.append(f"<code>{host}</code> [{country}]")
    else:
        lines.append("<i>нет</i>")
    lines.append("")

    # Резерв — галочки слева, ping
    lines.append(f"🛡 <b>Резерв ({len(backup)}):</b>")
    if backup:
        for item in backup:
            lines.append(_fmt_backup_line(item))
    else:
        lines.append("<i>пусто</i>")
    lines.append("")

    # Deferred — с временем
    lines.append(f"⏳ <b>Отложенные ({len(deferred)}):</b>")
    if deferred:
        for item in deferred:
            time_str = _fmt_deferred_time(item.get("deferred_min"))
            extra = f"— {time_str}" if time_str else None
            lines.append(_fmt_plain_line(item, extra=extra))
    else:
        lines.append("<i>пусто</i>")
    lines.append("")

    # Dead
    lines.append(f"💀 <b>Мёртвые ({len(dead)}):</b>")
    if dead:
        for item in dead:
            lines.append(_fmt_plain_line(item))
    else:
        lines.append("<i>пусто</i>")
    lines.append("")

    # Карантин
    lines.append(f"🚫 <b>Карантин ({len(quarantine)}):</b>")
    if quarantine:
        for item in quarantine:
            lines.append(_fmt_plain_line(item))
    else:
        lines.append("<i>пусто</i>")

    # Время
    lines.append("")
    lines.append(f"🕒 <i>{_fmt_ts(response.get('timestamp'))}</i>")

    full = "\n".join(lines)
    return _split_message(full)


# ============================================================
# /switch, /geo, /pick
# ============================================================

def format_switch_result(response: dict, action_label: str) -> str:
    """Форматирует результат переключения (switch / geo / pick)."""
    data = response.get("data") or {}
    old = _esc(data.get("old_primary", "N/A"))
    new = _esc(data.get("new_primary", "N/A"))

    country = data.get("country")
    host = data.get("host")

    lines = [f"🔀 <b>{_esc(action_label)}</b>", ""]
    lines.append(f"<b>Было:</b>  <code>{old}</code>")
    lines.append(f"<b>Стало:</b> <code>{new}</code>")

    if country:
        lines.append(f"<b>Страна:</b> {_esc(country)}")
    if host:
        lines.append(f"<b>Host:</b> <code>{_esc(host)}</code>")

    lines.append("")
    lines.append(f"🕒 <i>{_fmt_ts(response.get('timestamp'))}</i>")

    return _truncate("\n".join(lines))


# ============================================================
# /ignore, /unignore
# ============================================================

def format_ignore_result(response: dict) -> str:
    """Результат /ignore."""
    data = response.get("data") or {}
    host = _esc(data.get("host", "?"))
    return (
        f"🚫 <b>В карантин</b>\n"
        f"<b>Host:</b> <code>{host}</code>\n\n"
        f"🕒 <i>{_fmt_ts(response.get('timestamp'))}</i>"
    )


def format_unignore_result(response: dict) -> str:
    """Результат /unignore."""
    data = response.get("data") or {}
    host = _esc(data.get("host", "?"))
    removed = data.get("removed_count", 0)
    return (
        f"✅ <b>Из карантина</b>\n"
        f"<b>Host:</b> <code>{host}</code>\n"
        f"<b>Удалено записей:</b> {removed}\n\n"
        f"🕒 <i>{_fmt_ts(response.get('timestamp'))}</i>"
    )


# ============================================================
# /reload
# ============================================================

def format_reload_result(response: dict) -> str:
    """Результат /reload."""
    data = response.get("data") or {}
    old_count = data.get("old_count", 0)
    new_count = data.get("new_count", 0)
    backup_alive = data.get("backup_alive", 0)
    backup_total = data.get("backup_total", 0)
    return (
        f"🔄 <b>Файл ссылок перечитан</b>\n\n"
        f"<b>Было ссылок:</b> {old_count}\n"
        f"<b>Стало ссылок:</b> {new_count}\n"
        f"<b>Резерв:</b> {backup_alive}/{backup_total} живых\n\n"
        f"🕒 <i>{_fmt_ts(response.get('timestamp'))}</i>"
    )


# ============================================================
# /help
# ============================================================

def format_help() -> str:
    """Текст справки."""
    return (
        "🤖 <b>VLESS Bot</b> — управление observer'ом\n\n"
        "<b>Команды:</b>\n"
        "📡 /status — статус observer'а\n"
        "🔗 /links — список всех ссылок\n"
        "🔀 /switch — переключиться на следующую живую\n"
        "🌍 /geo XX — переключиться на страну (напр. <code>/geo DE</code>)\n"
        "🎯 /pick host — переключиться на host (напр. <code>/pick 1.2.3.4</code>)\n"
        "🚫 /ignore host — отправить в карантин\n"
        "✅ /unignore host — убрать из карантина\n"
        "🔄 /reload — перечитать файл ссылок\n"
        "❓ /help — эта справка\n\n"
        "<i>Кнопки ниже — для команд без аргументов.</i>"
    )


def format_switch_warning() -> str:
    """Предупреждение о временном разрыве связи с Telegram."""
    return "⏳ <i>Переключаю... (связь с Telegram на пару секунд прервётся)</i>"


def format_unknown_command(text: str) -> str:
    """Ответ на неизвестную команду."""
    safe = _esc(text)
    return (
        f"❓ Неизвестная команда: <code>{safe}</code>\n\n"
        f"Введи /help для списка команд."
    )


def format_invalid_argument(command: str, arg: str, hint: str) -> str:
    """Ответ на невалидный аргумент команды."""
    return (
        f"⚠️ <b>Неверный аргумент</b>\n"
        f"<b>Команда:</b> <code>/{_esc(command)}</code>\n"
        f"<b>Аргумент:</b> <code>{_esc(arg)}</code>\n\n"
        f"{_esc(hint)}"
    )
