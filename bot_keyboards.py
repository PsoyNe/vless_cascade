#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Inline-клавиатуры для Telegram-бота.

Здесь только построение клавиатур — никакой логики обработки.
Callback-данные имеют префикс "cmd:", чтобы в handlers легко
отличить их от других callback'ов (если появятся).

Клавиатуры:
  - main_menu_keyboard()      — под /help и /start
  - status_keyboard()          — под /status
  - links_keyboard()           — под /links
  - switch_result_keyboard()   — под результатами /switch, /geo, /pick
  - error_keyboard()           — под сообщениями об ошибках
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import vless_bot_config as cfg


# ============================================================
# ВСПОМОГАТЕЛЬНОЕ
# ============================================================

def _btn(text: str, action: str) -> InlineKeyboardButton:
    """
    Кнопка с callback_data вида 'cmd:<action>'.
    action — то, что handlers распознают (status, links, switch, ...).
    """
    return InlineKeyboardButton(text=text, callback_data=f"cmd:{action}")


def _kb(rows) -> InlineKeyboardMarkup:
    """Собирает InlineKeyboardMarkup из списка списков кнопок."""
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Главное меню. Показывается под /help и /start.
    Все команды без аргументов — кнопками.
    """
    if not cfg.ENABLE_INLINE_KEYBOARDS:
        return None

    return _kb([
        [_btn("📡 Статус", "status"), _btn("🔗 Ссылки", "links")],
        [_btn("🔀 Switch", "switch"), _btn("🔄 Reload", "reload")],
    ])


def status_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура под /status.
    Основные действия: обновить статус, переключиться, посмотреть ссылки.
    """
    if not cfg.ENABLE_INLINE_KEYBOARDS:
        return None

    return _kb([
        [_btn("🔄 Обновить", "status"), _btn("🔀 Switch", "switch")],
        [_btn("🔗 Ссылки", "links")],
    ])


def links_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура под /links.
    Из списка ссылок удобно вернуться к статусу или переключиться.
    """
    if not cfg.ENABLE_INLINE_KEYBOARDS:
        return None

    return _kb([
        [_btn("📡 Статус", "status"), _btn("🔀 Switch", "switch")],
    ])


def switch_result_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура под результатами /switch, /geo, /pick.
    После переключения логично посмотреть новый статус.
    """
    if not cfg.ENABLE_INLINE_KEYBOARDS:
        return None

    return _kb([
        [_btn("📡 Статус", "status"), _btn("🔗 Ссылки", "links")],
    ])


def error_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура под сообщениями об ошибках.
    Даём пользователю быстрый доступ к статусу и меню.
    """
    if not cfg.ENABLE_INLINE_KEYBOARDS:
        return None

    return _kb([
        [_btn("📡 Статус", "status"), _btn("❓ Help", "help")],
    ])
