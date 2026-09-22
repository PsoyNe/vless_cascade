#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Клиент для общения с observer'ом через файлы-триггеры.

Бот создаёт /tmp/vless_<action>_trigger (или /tmp/vless_<action>_<param>),
observer раз в 5 сек проверяет /tmp/, обрабатывает ОДИН триггер за цикл
и пишет ответ в /tmp/vless_<action>_response в формате JSON.

Особенности, которые здесь учтены:
  1. Свежесть триггера. Observer удаляет триггер старше TRIGGER_MAX_AGE
     (30 сек) БЕЗ выполнения. Мы ждём ответ не дольше RESPONSE_WAIT_TIMEOUT
     (27 сек) — чуть меньше, чтобы успеть.
  2. Один триггер за раз. Observer обрабатывает по одному за цикл.
     Если команд несколько — они встанут в очередь. Мы это не блокируем,
     но и не пытаемся параллелить.
  3. Старые response-файлы. Если при старте observer'а в /tmp/ остался
     старый response — его могли удалить. Мы перед созданием триггера
     всегда чистим старый response для этого action.
  4. Имя action в ответе. Для /tmp/vless_geo_DE ответ пишется в
     /tmp/vless_geo_DE_response, а в JSON поле action = "geo_DE".

Все функции — async. Возвращают dict вида:
    {"ok": True,  "action": "...", "timestamp": ..., "data": {...}}
    {"ok": False, "action": "...", "error": "..."}
При таймауте/ошибке связи:
    {"ok": False, "action": "...", "error": "Observer не отвечает (...)"}
"""

import os
import json
import time
import asyncio
import logging
from typing import Optional

import vless_bot_config as cfg

logger = logging.getLogger(__name__)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ
# ============================================================

def _trigger_path(action: str) -> str:
    """Путь к файлу-триггеру для action ('status', 'geo_DE', ...)."""
    return os.path.join(cfg.TRIGGER_DIR, f"vless_{action}_trigger")


def _pattern_trigger_path(prefix: str, param: str) -> str:
    """
    Путь к файлу-триггеру с параметром.
    Например: prefix='geo_', param='DE' → /tmp/vless_geo_DE
    """
    return os.path.join(cfg.TRIGGER_DIR, f"vless_{prefix}{param}")


def _response_path(action: str) -> str:
    """Путь к файлу-ответу для action ('status', 'geo_DE', ...)."""
    return os.path.join(cfg.TRIGGER_DIR, f"vless_{action}_response")


def _safe_remove(path: str) -> None:
    """Удаляет файл, игнорируя ошибки."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"Не удалось удалить {path}: {e}")


def _create_trigger_file(path: str) -> None:
    """
    Создаёт пустой файл-триггер.

    Пытаемся писать атомарно: создаём временный и переименовываем.
    Это важно, потому что observer проверяет mtime — если он увидит
    файл в момент, когда мы ещё его создаём, mtime может быть
    некорректным.
    """
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.write("")
    os.rename(tmp_path, path)


# ============================================================
# ЯДРО: ОТПРАВКА ТРИГГЕРА И ОЖИДАНИЕ ОТВЕТА
# ============================================================

async def _wait_for_response(
    action: str,
    timeout: float = None,
    poll_interval: float = None,
) -> Optional[dict]:
    """
    Ждёт появления response-файла и читает его.

    Возвращает dict с распарсенным JSON или None при таймауте.
    """
    if timeout is None:
        timeout = cfg.RESPONSE_WAIT_TIMEOUT
    if poll_interval is None:
        poll_interval = cfg.RESPONSE_POLL_INTERVAL

    response_path = _response_path(action)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if os.path.exists(response_path):
            # Небольшая пауза, чтобы observer точно дописал файл.
            await asyncio.sleep(0.05)
            try:
                with open(response_path, 'r', encoding='utf-8') as f:
                    raw = f.read()
                _safe_remove(response_path)

                if not raw.strip():
                    logger.warning(f"Пустой response для {action}")
                    return None

                data = json.loads(raw)
                return data
            except json.JSONDecodeError as e:
                logger.error(f"Битый JSON в {response_path}: {e}")
                _safe_remove(response_path)
                return None
            except Exception as e:
                logger.error(f"Ошибка чтения {response_path}: {e}")
                _safe_remove(response_path)
                return None

        await asyncio.sleep(poll_interval)

    # Таймаут — чистим response, если появился
    _safe_remove(response_path)
    return None


async def _request(
    action: str,
    trigger_path: str,
    timeout: float = None,
) -> dict:
    """
    Общая логика: создать триггер → ждать ответ → вернуть dict.

    action — имя action для response-файла (например, 'status', 'geo_DE').
    trigger_path — путь к создаваемому триггеру.
    """
    # 1. Чистим старый response, если остался
    _safe_remove(_response_path(action))

    # 2. Создаём триггер
    try:
        _create_trigger_file(trigger_path)
    except Exception as e:
        logger.error(f"Не удалось создать триггер {trigger_path}: {e}")
        return {
            "ok": False,
            "action": action,
            "error": f"Не удалось создать триггер: {e}",
        }

    logger.info(f"→ Триггер создан: {trigger_path} (action={action})")

    # 3. Ждём ответ
    response = await _wait_for_response(action, timeout=timeout)

    if response is None:
        _safe_remove(trigger_path)
        msg = f"Observer не отвечает (> {timeout or cfg.RESPONSE_WAIT_TIMEOUT} сек)"
        logger.warning(f"✗ {action}: {msg}")
        return {
            "ok": False,
            "action": action,
            "error": msg,
        }

    if cfg.LOG_RESPONSE_BODY:
        logger.info(f"← Ответ на {action}: {json.dumps(response, ensure_ascii=False)}")

    return response


# ============================================================
# ПУБЛИЧНЫЕ ФУНКЦИИ — КОМАНДЫ БОТА
# ============================================================

async def request_status(timeout: float = None) -> dict:
    """Запрос статуса observer'а."""
    return await _request(
        action="status",
        trigger_path=_trigger_path("status"),
        timeout=timeout,
    )


async def request_links(timeout: float = None) -> dict:
    """Запрос списка всех ссылок observer'а."""
    return await _request(
        action="links",
        trigger_path=_trigger_path("links"),
        timeout=timeout,
    )


async def request_switch(timeout: float = None) -> dict:
    """Принудительное переключение на следующую живую из резерва."""
    return await _request(
        action="switch",
        trigger_path=_trigger_path("switch"),
        timeout=timeout,
    )


async def request_reload(timeout: float = None) -> dict:
    """Перечитать working_links.txt."""
    return await _request(
        action="reload",
        trigger_path=_trigger_path("reload"),
        timeout=timeout,
    )


async def request_geo(country: str, timeout: float = None) -> dict:
    """
    Переключение на страну.
    country — код ISO 3166-1 alpha-2, например 'DE', 'NL'.
    """
    country = country.upper()
    action = f"geo_{country}"
    return await _request(
        action=action,
        trigger_path=_pattern_trigger_path("geo_", country),
        timeout=timeout,
    )


async def request_pick(host: str, timeout: float = None) -> dict:
    """Переключение на конкретный host."""
    action = f"pick_{host}"
    return await _request(
        action=action,
        trigger_path=_pattern_trigger_path("pick_", host),
        timeout=timeout,
    )


async def request_ignore(host: str, timeout: float = None) -> dict:
    """Отправить ссылку в карантин."""
    action = f"ignore_{host}"
    return await _request(
        action=action,
        trigger_path=_pattern_trigger_path("ignore_", host),
        timeout=timeout,
    )


async def request_unignore(host: str, timeout: float = None) -> dict:
    """Убрать ссылку из карантина."""
    action = f"unignore_{host}"
    return await _request(
        action=action,
        trigger_path=_pattern_trigger_path("unignore_", host),
        timeout=timeout,
    )
