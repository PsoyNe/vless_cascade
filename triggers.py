#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль триггеров VLESS Observer.

Позволяет управлять observer'ом через файлы-триггеры в /tmp/.
Используется Telegram-ботом (или вручную).

Формат триггеров:
    /tmp/vless_status_trigger           — запрос статуса
    /tmp/vless_links_trigger            — запрос списка ссылок
    /tmp/vless_switch_trigger           — переключиться на следующую живую
    /tmp/vless_geo_DE                   — переключиться на страну DE
    /tmp/vless_pick_46.28.69.53         — переключиться на конкретный host
    /tmp/vless_ignore_46.28.69.53       — отправить в карантин
    /tmp/vless_unignore_46.28.69.53     — убрать из карантина
    /tmp/vless_reload_trigger           — перечитать working_links.txt

Ответы:
    /tmp/vless_<action>_response        — JSON с результатом

Использование (из observer.py):
    from triggers import check_and_handle, cleanup_triggers_on_startup

    # при старте observer:
    cleanup_triggers_on_startup()

    # в test_primary:
    if check_and_handle(self):
        return   # триггер обработан
"""

import os
import re
import json
import time
import glob
import logging
from typing import Optional

import observer_config as _cfg
from vless_common import (
    parse_vless_link,
    extract_geo_from_link,
    format_host_with_geo,
    link_base,
    read_links_file,
    test_link_through_xray,
    update_3xui_outbound,
    reload_xray,
)

logger = logging.getLogger(__name__)

TRIGGER_MAX_AGE = getattr(_cfg, 'TRIGGER_MAX_AGE', 30)
BACKUP_TEST_TIMEOUT = getattr(_cfg, 'BACKUP_TEST_TIMEOUT', 4)
PROXY_PORT_BACKUP = getattr(_cfg, 'PROXY_PORT_BACKUP', 10809)
BACKUP_POOL_SIZE = getattr(_cfg, 'BACKUP_POOL_SIZE', 4)
OUTBOUND_NAME = getattr(_cfg, 'OUTBOUND_NAME', 'vless_obs')
LINKS_FILE = getattr(_cfg, 'LINKS_FILE', '/root/vless_checker/working_links.txt')
DEFAULT_QUARANTINE_FILE = getattr(_cfg, 'QUARANTINE_FILE', '/root/vless_checker/quarantine_links.txt')


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ
# ============================================================

def is_trigger_fresh(path: str) -> bool:
    """Проверяет, что триггер не старше TRIGGER_MAX_AGE."""
    try:
        mtime = os.path.getmtime(path)
        age = time.time() - mtime
        return age <= TRIGGER_MAX_AGE
    except Exception:
        return False


def write_response(action: str, ok: bool,
                    data: Optional[dict] = None,
                    error: Optional[str] = None):
    """Пишет JSON-ответ в /tmp/vless_<action>_response."""
    response_path = f"/tmp/vless_{action}_response"
    response = {
        "ok": ok,
        "action": action,
        "timestamp": time.time(),
    }
    if data is not None:
        response["data"] = data
    if error is not None:
        response["error"] = error

    try:
        with open(response_path, 'w', encoding='utf-8') as f:
            json.dump(response, f, ensure_ascii=False, indent=2)
        logger.info(f"📤 Записан ответ: {response_path}")
    except Exception as e:
        logger.error(f"❌ Не удалось записать ответ {response_path}: {e}")


def _link_info(link: str) -> dict:
    """
    Формирует объект с информацией о ссылке:
        {link, host, country}
    """
    parsed = parse_vless_link(link)
    host = parsed['host'] if parsed else 'unknown'
    country = extract_geo_from_link(link)
    return {
        'link': link,
        'host': host,
        'country': country,
    }


def cleanup_triggers_on_startup():
    """Удаляет все старые триггеры и ответы при старте observer."""
    count = 0
    patterns = [
        "/tmp/vless_status_trigger",
        "/tmp/vless_links_trigger",
        "/tmp/vless_switch_trigger",
        "/tmp/vless_reload_trigger",
        "/tmp/vless_geo_*",
        "/tmp/vless_pick_*",
        "/tmp/vless_ignore_*",
        "/tmp/vless_unignore_*",
        "/tmp/vless_*_response",
    ]
    for pattern in patterns:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
                logger.info(f"🧹 Удалён старый файл при старте: {f}")
                count += 1
            except Exception:
                pass
    if count == 0:
        logger.info("🧹 Старых триггеров не найдено")


# ============================================================
# ОБРАБОТЧИКИ
# ============================================================

def handle_status(observer) -> None:
    """Запрос статуса observer'а."""
    with observer.primary_lock:
        primary = observer.primary

    primary_display = format_host_with_geo(primary) if primary else 'NONE [N/A]'

    with observer.pool_lock:
        alive_count = len([i for i in observer.backup_pool if i.get('alive', False)])
        total_backup = len(observer.backup_pool)
        backup_hosts = [
            {
                'host': item['host'],
                'country': item.get('country', 'N/A'),
                'ping': item.get('ping', 0),
                'alive': item.get('alive', False),
            }
            for item in observer.backup_pool
        ]

    with observer.deferred_lock:
        deferred_count = len(observer.deferred_links)

    with observer.stats_lock:
        switch_count = observer.switch_count
        fail_count = observer.primary_stats['fail_count']
        success_count = observer.primary_stats['success_count']

    with observer.dead_links_lock:
        dead_count = len(observer.dead_links)

    data = {
        'primary': primary_display,
        'primary_fail_count': fail_count,
        'primary_success_count': success_count,
        'backup_alive': alive_count,
        'backup_total': total_backup,
        'backup_hosts': backup_hosts,
        'deferred_count': deferred_count,
        'dead_count': dead_count,
        'switch_count': switch_count,
    }

    write_response('status', True, data=data)
    logger.info(f"✅ Обработан триггер: status")


def handle_links(observer) -> None:
    """Список всех ссылок observer'а."""
    with observer.primary_lock:
        primary = observer.primary

    with observer.pool_lock:
        backup_links = [
            {
                'link': item['link'],
                'host': item['host'],
                'country': item.get('country', 'N/A'),
                'ping': item.get('ping', 0),
                'alive': item.get('alive', False),
            }
            for item in observer.backup_pool
        ]

    current_time = time.time()

    with observer.deferred_lock:
        deferred_items = []
        for link, info in observer.deferred_links.items():
            deferred_at = info.get('deferred_at', current_time)
            deferred_min = int((current_time - deferred_at) / 60)
            item = _link_info(link)
            item['deferred_min'] = deferred_min
            deferred_items.append(item)

    with observer.dead_links_lock:
        dead_items = [
            _link_info(link)
            for link in observer.dead_links
        ]

    quarantine = []
    try:
        qfile = getattr(observer, 'quarantine_file', DEFAULT_QUARANTINE_FILE)
        if os.path.exists(qfile):
            with open(qfile, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('vless://'):
                        quarantine.append(_link_info(line))
    except Exception as e:
        logger.warning(f"Не удалось прочитать карантин: {e}")

    data = {
        'primary': _link_info(primary) if primary else None,
        'backup': backup_links,
        'deferred': deferred_items,
        'dead': dead_items,
        'quarantine': quarantine,
    }

    write_response('links', True, data=data)
    logger.info(f"✅ Обработан триггер: links")


def handle_switch(observer) -> None:
    """Принудительное переключение на следующую живую из резерва."""
    with observer.primary_lock:
        old_primary = observer.primary

    old_display = format_host_with_geo(old_primary) if old_primary else 'NONE [N/A]'

    logger.info(f"🔀 Триггер: switch — принудительное переключение")

    with observer.stats_lock:
        observer.primary_stats['fail_count'] = 0

    observer.switch_to_backup()

    with observer.primary_lock:
        new_primary = observer.primary

    new_display = format_host_with_geo(new_primary) if new_primary else 'NONE [N/A]'

    if old_primary == new_primary:
        write_response('switch', False,
                       error="Не удалось переключиться (нет живых резервных)")
        logger.warning(f"❌ Триггер switch: переключение не выполнено")
    else:
        write_response('switch', True, data={
            'old_primary': old_display,
            'new_primary': new_display,
        })
        logger.info(f"✅ Обработан триггер: switch ({old_display} → {new_display})")


def handle_geo(observer, country: str) -> None:
    """Переключение на конкретную страну."""
    country = country.upper()
    action = f'geo_{country}'

    if not re.match(r'^[A-Z]{2}$', country):
        write_response(action, False, error=f"Невалидный код страны: {country}")
        logger.warning(f"❌ Триггер {action}: невалидный код")
        return

    logger.info(f"🌍 Триггер: {action} — переключение на страну {country}")

    all_links = read_links_file(LINKS_FILE)
    candidates = [l for l in all_links if extract_geo_from_link(l) == country]

    if not candidates:
        write_response(action, False, error=f"Нет ссылок для страны {country}")
        logger.warning(f"❌ Триггер {action}: нет ссылок")
        return

    found = None
    for link in candidates:
        with observer.primary_lock:
            current = observer.primary
        if link == current:
            continue

        logger.info(f"🔎 Проверяем {format_host_with_geo(link)}...")
        is_working, ping, _ = test_link_through_xray(
            link, PROXY_PORT_BACKUP, timeout=BACKUP_TEST_TIMEOUT
        )

        if is_working:
            found = link
            logger.info(f"✅ Найдена живая {country}: {format_host_with_geo(link)}")
            break

    if not found:
        write_response(action, False, error=f"Все ссылки для страны {country} мертвы")
        logger.warning(f"❌ Триггер {action}: все ссылки мертвы")
        return

    with observer.primary_lock:
        old_primary = observer.primary

    old_display = format_host_with_geo(old_primary) if old_primary else 'NONE [N/A]'
    new_display = format_host_with_geo(found)

    if update_3xui_outbound(found, OUTBOUND_NAME):
        if reload_xray():
            with observer.primary_lock:
                observer.primary = found

            with observer.stats_lock:
                observer.switch_count += 1
                observer.primary_stats['fail_count'] = 0

            observer._add_to_recently_primary(old_primary)

            write_response(action, True, data={
                'old_primary': old_display,
                'new_primary': new_display,
                'country': country,
            })
            logger.info(f"✅ Обработан триггер: {action} ({old_display} → {new_display})")
        else:
            write_response(action, False, error="x-ui не перезапустился")
            logger.error(f"❌ Триггер {action}: x-ui не перезапустился")
    else:
        write_response(action, False, error="Не удалось обновить outbound")
        logger.error(f"❌ Триггер {action}: outbound не обновлён")


def handle_pick(observer, host: str) -> None:
    """Переключение на конкретный host."""
    action = f'pick_{host}'
    logger.info(f"🎯 Триггер: {action}")

    all_links = read_links_file(LINKS_FILE)

    target = None
    for link in all_links:
        parsed = parse_vless_link(link)
        if parsed and parsed['host'] == host:
            target = link
            break

    if not target:
        write_response(action, False, error=f"Ссылка с host {host} не найдена")
        logger.warning(f"❌ Триггер {action}: не найдена")
        return

    logger.info(f"🔎 Проверяем {format_host_with_geo(target)}...")
    is_working, ping, _ = test_link_through_xray(
        target, PROXY_PORT_BACKUP, timeout=BACKUP_TEST_TIMEOUT
    )

    if not is_working:
        write_response(action, False, error=f"Ссылка {host} мертва")
        logger.warning(f"❌ Триггер {action}: мертва")
        return

    with observer.primary_lock:
        old_primary = observer.primary

    old_display = format_host_with_geo(old_primary) if old_primary else 'NONE [N/A]'
    new_display = format_host_with_geo(target)

    if update_3xui_outbound(target, OUTBOUND_NAME):
        if reload_xray():
            with observer.primary_lock:
                observer.primary = target

            with observer.stats_lock:
                observer.switch_count += 1
                observer.primary_stats['fail_count'] = 0

            observer._add_to_recently_primary(old_primary)

            write_response(action, True, data={
                'old_primary': old_display,
                'new_primary': new_display,
                'host': host,
            })
            logger.info(f"✅ Обработан триггер: {action} ({old_display} → {new_display})")
        else:
            write_response(action, False, error="x-ui не перезапустился")
    else:
        write_response(action, False, error="outbound не обновлён")


def handle_ignore(observer, host: str) -> None:
    """Отправить ссылку в карантин."""
    action = f'ignore_{host}'
    logger.info(f"🚫 Триггер: {action}")

    all_links = read_links_file(LINKS_FILE)

    target = None
    for link in all_links:
        parsed = parse_vless_link(link)
        if parsed and parsed['host'] == host:
            target = link
            break

    if not target:
        write_response(action, False, error=f"Ссылка с host {host} не найдена")
        return

    # Пишем в карантин
    try:
        qfile = getattr(observer, 'quarantine_file', DEFAULT_QUARANTINE_FILE)
        os.makedirs(os.path.dirname(qfile), exist_ok=True)
        with open(qfile, 'a', encoding='utf-8') as f:
            f.write(f"{target}\n")
        logger.info(f"✅ {host} добавлен в карантин")
    except Exception as e:
        write_response(action, False, error=f"Ошибка записи в карантин: {e}")
        return

    # Если это текущая основная — переключаемся
    with observer.primary_lock:
        old_primary = observer.primary

    old_parsed = parse_vless_link(old_primary) if old_primary else None
    if old_parsed and old_parsed['host'] == host:
        logger.warning(f"⚠️ {host} — текущая основная, переключаемся...")
        with observer.dead_links_lock:
            observer.dead_links.add(old_primary)
        with observer.pool_lock:
            observer.backup_pool = [i for i in observer.backup_pool if i['link'] != old_primary]
        observer.switch_to_backup()

    # Убираем из резерва
    with observer.pool_lock:
        observer.backup_pool = [
            i for i in observer.backup_pool
            if (parse_vless_link(i['link']) or {}).get('host') != host
        ]

    write_response(action, True, data={'host': host})
    logger.info(f"✅ Обработан триггер: {action}")


def handle_unignore(observer, host: str) -> None:
    """Убрать ссылку из карантина."""
    action = f'unignore_{host}'
    logger.info(f"✅ Триггер: {action}")

    qfile = getattr(observer, 'quarantine_file', DEFAULT_QUARANTINE_FILE)

    if not os.path.exists(qfile):
        write_response(action, False, error="Карантин пуст")
        return

    removed = []
    kept = []

    try:
        with open(qfile, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line.startswith('vless://'):
                    continue
                parsed = parse_vless_link(line)
                if parsed and parsed['host'] == host:
                    removed.append(line)
                else:
                    kept.append(line)

        if not removed:
            write_response(action, False, error=f"Ссылка {host} не найдена в карантине")
            return

        with open(qfile, 'w', encoding='utf-8') as f:
            for line in kept:
                f.write(f"{line}\n")

        logger.info(f"✅ {host} удалён из карантина ({len(removed)} записей)")

    except Exception as e:
        write_response(action, False, error=f"Ошибка: {e}")
        return

    with observer.dead_links_lock:
        for link in removed:
            observer.dead_links.discard(link)

    write_response(action, True, data={
        'host': host,
        'removed_count': len(removed),
    })
    logger.info(f"✅ Обработан триггер: {action}")


def handle_reload(observer) -> None:
    """Перечитать working_links.txt."""
    action = 'reload'
    logger.info(f"🔄 Триггер: {action}")

    new_links = read_links_file(LINKS_FILE)

    old_count = len(observer.links)
    observer.links = new_links

    logger.info(f"📥 Файл перечитан: {old_count} → {len(new_links)} ссылок")

    with observer.pool_lock:
        need_refill = len(observer.backup_pool) < BACKUP_POOL_SIZE
    if need_refill:
        observer._fill_backup_pool_checked()

    with observer.pool_lock:
        total_backup = len(observer.backup_pool)
        alive_count = len([i for i in observer.backup_pool if i.get('alive', False)])

    write_response(action, True, data={
        'old_count': old_count,
        'new_count': len(new_links),
        'backup_alive': alive_count,
        'backup_total': total_backup,
    })
    logger.info(f"✅ Обработан триггер: {action}")


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def _process_simple_trigger(observer, path: str, action: str) -> bool:
    """Обрабатывает простой триггер. True — был обработан."""
    if not is_trigger_fresh(path):
        logger.warning(f"⚠️ Устаревший триггер {path} — удаляем")
        try:
            os.remove(path)
        except Exception:
            pass
        return False

    logger.info(f"🔔 Обнаружен триггер: {path}")

    try:
        os.remove(path)
    except Exception as e:
        logger.error(f"Ошибка удаления триггера: {e}")
        return False

    try:
        if action == "status":
            handle_status(observer)
        elif action == "links":
            handle_links(observer)
        elif action == "switch":
            handle_switch(observer)
        elif action == "reload":
            handle_reload(observer)
        return True
    except Exception as e:
        logger.error(f"Ошибка обработки триггера {action}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        write_response(action, False, error=str(e))
        return True


def _process_pattern_trigger(observer, path: str, prefix: str, handler) -> bool:
    """Обрабатывает триггер по шаблону (geo_XX, pick_HOST, ...)."""
    if path.endswith("_response"):
        return False

    if not is_trigger_fresh(path):
        logger.warning(f"⚠️ Устаревший триггер {path} — удаляем")
        try:
            os.remove(path)
        except Exception:
            pass
        return False

    param = path.replace(prefix, "").strip()
    logger.info(f"🔔 Обнаружен триггер: {path} (параметр: {param})")

    try:
        os.remove(path)
    except Exception:
        return False

    try:
        handler(observer, param)
    except Exception as e:
        logger.error(f"Ошибка обработки {path}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        action = f"{prefix.split('/tmp/vless_')[1].rstrip('_')}_{param}"
        write_response(action, False, error=str(e))
    return True


def check_and_handle(observer) -> bool:
    """
    Проверяет наличие триггеров и обрабатывает ПЕРВЫЙ найденный.

    Возвращает:
        True  — триггер был обработан
        False — триггеров нет
    """
    simple = [
        ("/tmp/vless_status_trigger", "status"),
        ("/tmp/vless_links_trigger", "links"),
        ("/tmp/vless_switch_trigger", "switch"),
        ("/tmp/vless_reload_trigger", "reload"),
    ]
    for path, action in simple:
        if os.path.exists(path):
            if _process_simple_trigger(observer, path, action):
                return True

    for path in glob.glob("/tmp/vless_geo_*"):
        if _process_pattern_trigger(observer, path, "/tmp/vless_geo_", handle_geo):
            return True

    for path in glob.glob("/tmp/vless_pick_*"):
        if _process_pattern_trigger(observer, path, "/tmp/vless_pick_", handle_pick):
            return True

    for path in glob.glob("/tmp/vless_ignore_*"):
        if _process_pattern_trigger(observer, path, "/tmp/vless_ignore_", handle_ignore):
            return True

    for path in glob.glob("/tmp/vless_unignore_*"):
        if _process_pattern_trigger(observer, path, "/tmp/vless_unignore_", handle_unignore):
            return True

    return False
