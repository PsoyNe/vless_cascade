#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import signal
import logging
import logging.handlers
import threading
from typing import List, Tuple, Optional, Dict

from observer_config import *

from vless_common import (
    parse_vless_link,
    extract_geo_from_link,
    format_host_with_geo,
    link_base,
    validate_reality_params,
    read_links_file,
    test_link_through_xray,
    test_link_double_check,
    test_link_deep,
    update_3xui_outbound,
    reload_xray,
)

from triggers import (
    check_and_handle,
    cleanup_triggers_on_startup,
)


# ============================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_FILE,
    when=LOG_ROTATION_WHEN,
    interval=LOG_ROTATION_INTERVAL,
    backupCount=LOG_ROTATION_BACKUPS,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S'))
file_handler.suffix = LOG_ROTATION_UTCFORMAT
logger.addHandler(file_handler)

if sys.stdout.isatty():
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S'))
    logger.addHandler(console_handler)

# Логгер для vless_common и triggers — чтобы их сообщения тоже шли сюда
for mod_name in ('vless_common', 'triggers'):
    mod_logger = logging.getLogger(mod_name)
    mod_logger.setLevel(logging.INFO)
    mod_logger.addHandler(file_handler)
    if sys.stdout.isatty():
        mod_logger.addHandler(console_handler)


# ============================================================
# ГЛОБАЛЬНЫЙ ФЛАГ ОСТАНОВКИ
# ============================================================
_shutdown_requested = threading.Event()


def _handle_sigterm(signum, frame):
    logger.info(f"🛑 Получен сигнал {signum} — завершаем работу...")
    _shutdown_requested.set()


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


# ============================================================
# ПРИОРИТЕТНАЯ СТРАНА
# ============================================================

def _normalize_preferred_country() -> str:
    """
    Возвращает валидный код приоритетной страны или '' (нет приоритета).
    Невалидный код игнорируется с предупреждением в лог.
    """
    raw = getattr(__import__('observer_config'), 'PREFERRED_COUNTRY', '')
    if not raw:
        return ''
    raw = str(raw).strip().upper()
    if not raw:
        return ''
    import re
    if re.match(r'^[A-Z]{2}$', raw):
        return raw
    logger.warning(f"⚠️ PREFERRED_COUNTRY='{raw}' — невалидный код страны, приоритет отключён")
    return ''


PREFERRED_COUNTRY = _normalize_preferred_country()

# Устойчивое чтение параметров двойной проверки
BACKUP_CHECK_ATTEMPTS = getattr(sys.modules['observer_config'], 'BACKUP_CHECK_ATTEMPTS', 2)


# ============================================================
# ОСНОВНОЙ КЛАСС
# ============================================================

class VlessObserver:
    def __init__(self):
        self.links = []
        self.primary = None
        self.backup_pool = []

        self.primary_lock = threading.Lock()
        self.pool_lock = threading.Lock()
        self.deferred_lock = threading.Lock()
        self.stats_lock = threading.Lock()
        self.dead_links_lock = threading.Lock()
        self.recently_primary_lock = threading.Lock()

        self.primary_stats = {'fail_count': 0, 'success_count': 0}
        self.switch_count = 0

        self.last_log_time = 0
        self.last_state = ""
        self.last_primary_host = ""
        self.critical_error_logged = False
        self.backup_check_counter = 0
        self.last_pool_refill_time = 0
        self.last_pool_update_time = 0
        self.waiting_for_links = False

        self.trigger_file = "/tmp/vless_observer_trigger"
        self.quarantine_trigger = "/tmp/vless_quarantine_trigger"
        self.deep_check_trigger = "/tmp/vless_deep_check_trigger"
        self.quarantine_file = "/root/vless_checker/quarantine_links.txt"

        self.deferred_links = {}
        self.dead_links = set()
        self.recently_primary = {}

        self.switching = threading.Event()

    # --------------------------------------------------------
    # Загрузка и инициализация
    # --------------------------------------------------------

    def load_links(self) -> bool:
        self.links = read_links_file(LINKS_FILE)
        if not self.links:
            logger.warning(f"⚠️ Файл {LINKS_FILE} пуст или не найден! Ожидание...")
            return False
        if len(self.links) < 2:
            logger.warning(f"⚠️ В файле меньше 2 ссылок: {len(self.links)}. Ожидание...")
            return False
        logger.info(f"✅ Загружено {len(self.links)} ссылок")
        return True

    def wait_for_links(self) -> bool:
        logger.info("⏳ Ожидание появления ссылок в рабочем файле...")
        self.waiting_for_links = True

        while self.waiting_for_links and not _shutdown_requested.is_set():
            links = read_links_file(LINKS_FILE)
            if len(links) >= 2:
                self.links = links
                logger.info(f"✅ Появилось {len(self.links)} ссылок. Продолжаем работу.")
                self.waiting_for_links = False
                return True

            logger.info(f"⏳ Ссылок пока нет ({len(links)}), проверка через 60 секунд...")
            for _ in range(60):
                if _shutdown_requested.is_set():
                    return False
                time.sleep(1)

        return False

    def load_quarantine(self) -> set:
        quarantine = set()
        try:
            if os.path.exists(self.quarantine_file):
                with open(self.quarantine_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        link = line.strip()
                        if link.startswith('vless://'):
                            quarantine.add(link_base(link))
        except Exception as e:
            logger.error(f"Ошибка загрузки карантина: {e}")
        return quarantine

    def _add_to_deferred(self, link: str):
        current_time = time.time()
        with self.deferred_lock:
            self.deferred_links[link] = {
                'deferred_at': current_time,
                'last_checked_at': current_time,
            }

    def _add_to_recently_primary(self, link: str):
        if not link:
            return
        current_time = time.time()
        with self.recently_primary_lock:
            self.recently_primary[link] = current_time

    def _cleanup_recently_primary(self):
        current_time = time.time()
        with self.recently_primary_lock:
            expired = [
                link for link, ts in self.recently_primary.items()
                if current_time - ts >= RECENTLY_PRIMARY_COOLDOWN
            ]
            for link in expired:
                del self.recently_primary[link]

    def _sort_links_by_preferred(self, links: List[str]) -> List[str]:
        """
        Сортирует ссылки так, чтобы ссылки с PREFERRED_COUNTRY шли первыми.
        Если PREFERRED_COUNTRY пуст — возвращает как есть.
        """
        if not PREFERRED_COUNTRY:
            return links

        preferred = []
        others = []
        for link in links:
            geo = extract_geo_from_link(link)
            if geo == PREFERRED_COUNTRY:
                preferred.append(link)
            else:
                others.append(link)

        if preferred:
            logger.info(f"⭐ Приоритет {PREFERRED_COUNTRY}: {len(preferred)} ссылок из {len(links)}")
        else:
            logger.warning(f"⚠️ Приоритет {PREFERRED_COUNTRY}: ссылок с этой страной нет, используем все")

        return preferred + others

    def _find_working_primary(self) -> Optional[str]:
        """Перебирает ссылки и возвращает первую живую (с учётом приоритета)."""
        total = len(self.links)

        sorted_links = self._sort_links_by_preferred(self.links)

        logger.info(f"🔍 Проверяем ссылки при старте (до первой живой, максимум {total})...")

        for i, link in enumerate(sorted_links, 1):
            if _shutdown_requested.is_set():
                return None

            parsed = parse_vless_link(link)
            if not parsed:
                with self.dead_links_lock:
                    self.dead_links.add(link)
                logger.warning(f"⚠️ [{i}/{total}] Не удалось распарсить ссылку")
                continue

            display = format_host_with_geo(link)

            ok, reason = validate_reality_params(parsed['params'])
            if not ok:
                with self.dead_links_lock:
                    self.dead_links.add(link)
                logger.warning(f"⚠️ [{i}/{total}] {display} — невалидная Reality: {reason}")
                continue

            logger.info(f"🔎 [{i}/{total}] Проверяем {display}...")

            is_working, ping, _ = test_link_through_xray(
                link,
                PROXY_PORT_PRIMARY,
                timeout=TEST_TIMEOUT,
                shutdown_event=_shutdown_requested
            )

            if is_working:
                logger.info(f"✅ [{i}/{total}] {display} живая! Пинг: {ping:.0f}мс — будет основной")
                return link
            else:
                with self.dead_links_lock:
                    self.dead_links.add(link)
                logger.warning(f"❌ [{i}/{total}] {display} мертва — пропускаем")

        return None

    def _get_candidates_from_file(self) -> List[str]:
        """Возвращает кандидатов на резерв из файла (с приоритетом)."""
        all_links = read_links_file(LINKS_FILE)
        if not all_links:
            return []

        self._cleanup_recently_primary()
        quarantine = self.load_quarantine()

        with self.primary_lock:
            current_primary = self.primary
        current_primary_base = link_base(current_primary) if current_primary else None

        with self.pool_lock:
            pool_links = set(item['link'] for item in self.backup_pool)

        with self.deferred_lock:
            deferred_set = set(self.deferred_links.keys())

        with self.dead_links_lock:
            dead_set = set(self.dead_links)

        with self.recently_primary_lock:
            recent_set = set(self.recently_primary.keys())

        candidates = []
        seen_bases = set()

        for link in all_links:
            l_base = link_base(link)

            if l_base == current_primary_base:
                continue
            if link in pool_links:
                continue
            if link in deferred_set or link in dead_set:
                continue
            if link in recent_set:
                continue
            if l_base in quarantine:
                continue
            if l_base in seen_bases:
                continue

            seen_bases.add(l_base)
            candidates.append(link)

        return self._sort_links_by_preferred(candidates)

    def _fill_backup_pool_checked(self):
        """Пополняет backup_pool ЖИВЫМИ ссылками (с двойной проверкой)."""
        with self.pool_lock:
            current_size = len(self.backup_pool)
        need = BACKUP_POOL_SIZE - current_size

        if need <= 0:
            return

        logger.info(f"🔍 Пополняем резерв (нужно: {need}, в пуле: {current_size}/{BACKUP_POOL_SIZE})...")

        candidates = self._get_candidates_from_file()
        if not candidates:
            logger.warning("⚠️ Нет кандидатов для пополнения резерва")
            return

        logger.info(f"📋 Кандидатов из файла: {len(candidates)}")

        added = 0
        checked = 0

        for link in candidates:
            if _shutdown_requested.is_set():
                return

            with self.pool_lock:
                if len(self.backup_pool) >= BACKUP_POOL_SIZE:
                    break

            checked += 1
            parsed = parse_vless_link(link)
            if not parsed:
                with self.dead_links_lock:
                    self.dead_links.add(link)
                continue

            display = format_host_with_geo(link)
            country = extract_geo_from_link(link)

            ok, reason = validate_reality_params(parsed['params'])
            if not ok:
                with self.dead_links_lock:
                    self.dead_links.add(link)
                continue

            logger.info(f"🔎 Проверяем кандидата [{checked}]: {display} "
                        f"({BACKUP_CHECK_ATTEMPTS} проверок, интервал {BACKUP_CHECK_INTERVAL}с)...")

            is_working, ping = test_link_double_check(
                link,
                PROXY_PORT_BACKUP,
                shutdown_event=_shutdown_requested
            )

            if is_working:
                with self.pool_lock:
                    self.backup_pool.append({
                        'link': link,
                        'host': parsed['host'],
                        'country': country,
                        'alive': True,
                        'ping': ping
                    })
                added += 1
                logger.info(f"✅ {display} живая — в резерв [{current_size + added}/{BACKUP_POOL_SIZE}] (пинг: {ping:.0f}мс)")
            else:
                self._add_to_deferred(link)
                logger.warning(f"❌ {display} не прошла {BACKUP_CHECK_ATTEMPTS} проверок — в deferred")

        if added > 0:
            logger.info(f"✅ Резерв пополнен: +{added} (проверено кандидатов: {checked})")
        else:
            logger.warning(f"⚠️ Не удалось пополнить резерв (проверено кандидатов: {checked})")

    def _fill_backup_pool_startup(self):
        """Пополняет backup_pool при СТАРТЕ (с двойной проверкой)."""
        with self.pool_lock:
            current_size = len(self.backup_pool)
        need = BACKUP_POOL_SIZE - current_size

        if need <= 0:
            return

        logger.info(f"🔍 Набираем резерв (цель: {BACKUP_POOL_SIZE})...")

        candidates = self._get_candidates_from_file()
        if not candidates:
            logger.warning("⚠️ Нет кандидатов для резерва")
            return

        added = 0
        checked = 0

        for link in candidates:
            if _shutdown_requested.is_set():
                return

            with self.pool_lock:
                if len(self.backup_pool) >= BACKUP_POOL_SIZE:
                    break

            checked += 1
            parsed = parse_vless_link(link)
            if not parsed:
                with self.dead_links_lock:
                    self.dead_links.add(link)
                continue

            display = format_host_with_geo(link)
            country = extract_geo_from_link(link)

            ok, reason = validate_reality_params(parsed['params'])
            if not ok:
                with self.dead_links_lock:
                    self.dead_links.add(link)
                continue

            logger.info(f"🔎 Резерв [{added + 1}/{BACKUP_POOL_SIZE}] проверяем {display} "
                        f"({BACKUP_CHECK_ATTEMPTS} проверок, интервал {BACKUP_CHECK_INTERVAL}с)...")

            is_working, ping = test_link_double_check(
                link,
                PROXY_PORT_BACKUP,
                shutdown_event=_shutdown_requested
            )

            if is_working:
                with self.pool_lock:
                    self.backup_pool.append({
                        'link': link,
                        'host': parsed['host'],
                        'country': country,
                        'alive': True,
                        'ping': ping
                    })
                added += 1
                logger.info(f"✅ Резерв [{added}/{BACKUP_POOL_SIZE}] {display} (пинг: {ping:.0f}мс)")
            else:
                self._add_to_deferred(link)
                logger.warning(f"❌ Резерв {display} не прошла {BACKUP_CHECK_ATTEMPTS} проверок — в deferred")

        if added < BACKUP_POOL_SIZE:
            logger.warning(f"⚠️ Набрано только {added}/{BACKUP_POOL_SIZE} резервных. "
                          f"Проверено кандидатов: {checked}.")

    def init_pool(self) -> bool:
        primary = self._find_working_primary()

        if not primary:
            logger.critical("🔴 НЕТ РАБОЧИХ ССЫЛОК в файле! Все проверенные — мертвы.")
            logger.critical("Ждём обновления от чекера (cron)...")
            return False

        with self.primary_lock:
            self.primary = primary

        primary_display = format_host_with_geo(primary)

        logger.info(f"📝 Устанавливаем основную в outbound: {primary_display}")

        if not update_3xui_outbound(self.primary, OUTBOUND_NAME):
            logger.error("❌ Не удалось обновить outbound.")

        if not reload_xray():
            logger.error("❌ Не удалось перезапустить x-ui.")

        self._fill_backup_pool_startup()

        with self.pool_lock:
            total_backup = len(self.backup_pool)
            alive_count = len([item for item in self.backup_pool if item.get('alive', False)])
        with self.deferred_lock:
            deferred_count = len(self.deferred_links)
        with self.dead_links_lock:
            dead_count = len(self.dead_links)

        logger.info(f"✅ Основная: {primary_display}")
        logger.info(f"✅ Резерв: {alive_count}/{total_backup}")
        logger.info(f"⏸️ В deferred: {deferred_count}")
        logger.info(f"🗑️ Помечено мёртвыми: {dead_count}")

        self.last_primary_host = primary_display
        self.last_state = f"OK | основная: {primary_display} | резерв: {alive_count}/{total_backup}"
        self.last_log_time = time.time()
        self.critical_error_logged = False
        self.last_pool_refill_time = time.time()
        self.last_pool_update_time = time.time()

        return True

    # --------------------------------------------------------
    # Логирование статуса
    # --------------------------------------------------------

    def log_status(self, force: bool = False):
        current_time = time.time()

        with self.primary_lock:
            primary = self.primary
        if primary:
            primary_display = format_host_with_geo(primary)
        else:
            primary_display = 'NONE [N/A]'

        with self.pool_lock:
            alive_count = len([item for item in self.backup_pool if item.get('alive', False)])
            total_backup = len(self.backup_pool)

        with self.deferred_lock:
            deferred_count = len(self.deferred_links)

        with self.stats_lock:
            switch_count = self.switch_count
            fail_count = self.primary_stats['fail_count']

        state = f"OK | {primary_display}"

        if fail_count > 0:
            state += f" | отказов: {fail_count}/{FAILURES_TO_SWITCH}"

        state += f" | резерв: {alive_count}/{total_backup} живых"
        state += f" | отложено: {deferred_count}"
        state += f" | перекл: {switch_count}"

        if force or state != self.last_state or (current_time - self.last_log_time) >= 60:
            logger.info(state)
            self.last_state = state
            self.last_log_time = current_time
            self.last_primary_host = primary_display

    # --------------------------------------------------------
    # ПОТОК 1: проверка основной ссылки
    # --------------------------------------------------------

    def primary_loop(self):
        logger.info("▶️ Поток 1 (основная) запущен")

        while not _shutdown_requested.is_set():
            try:
                self.test_primary()
                self.log_status()
            except Exception as e:
                logger.error(f"❌ Ошибка в потоке основной: {e}")
                import traceback
                logger.error(traceback.format_exc())

            for _ in range(CHECK_INTERVAL_PRIMARY):
                if _shutdown_requested.is_set():
                    break
                time.sleep(1)

        logger.info("⏹️ Поток 1 (основная) завершён")

    def test_primary(self):
        # --- Триггеры (команды от бота) ---
        try:
            if check_and_handle(self):
                return
        except Exception as e:
            logger.error(f"❌ Ошибка обработки триггеров: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # --- Старые триггеры (совместимость) ---
        if self.check_deep_check_trigger():
            return
        if self.check_quarantine_trigger():
            return
        if self.check_trigger_file():
            logger.warning(f"❌ ИМИТАЦИЯ 2 ОТКАЗОВ: переключение...")
            self.switch_to_backup()
            self.log_status(force=True)
            return

        # --- Обычная проверка ---
        with self.primary_lock:
            primary = self.primary

        is_working, ping, size = test_link_through_xray(
            primary,
            PROXY_PORT_PRIMARY,
            timeout=TEST_TIMEOUT,
            shutdown_event=_shutdown_requested
        )

        if is_working:
            with self.stats_lock:
                self.primary_stats['success_count'] += 1
                self.primary_stats['fail_count'] = 0
            self.critical_error_logged = False
            logger.debug(f"✅ Основная ссылка работает (пинг: {ping:.0f}мс)")
        else:
            with self.stats_lock:
                self.primary_stats['fail_count'] += 1
                fail_count = self.primary_stats['fail_count']

            logger.warning(f"❌ Отказ основной ссылки ({fail_count}/{FAILURES_TO_SWITCH})")

            if fail_count >= FAILURES_TO_SWITCH:
                self.switch_to_backup()
                self.log_status(force=True)

    # --------------------------------------------------------
    # ПОТОК 2: проверка резерва
    # --------------------------------------------------------

    def backup_loop(self):
        logger.info("▶️ Поток 2 (резерв) запущен")

        first_run = True

        while not _shutdown_requested.is_set():
            try:
                if not first_run:
                    for _ in range(CHECK_INTERVAL_BACKUP):
                        if _shutdown_requested.is_set():
                            break
                        time.sleep(1)

                if _shutdown_requested.is_set():
                    break

                if self.switching.is_set():
                    logger.info("⏸️ Поток 2 ждёт завершения переключения...")
                    self.switching.wait(timeout=30)

                self.test_backup_pool()
                self.log_status()
                first_run = False

            except Exception as e:
                logger.error(f"❌ Ошибка в потоке резерва: {e}")
                import traceback
                logger.error(traceback.format_exc())

        logger.info("⏹️ Поток 2 (резерв) завершён")

    def test_backup_pool(self):
        with self.pool_lock:
            backup_snapshot = list(self.backup_pool)

        if not backup_snapshot:
            self._fill_backup_pool_checked()
            return

        self.backup_check_counter += 1

        dead_links = []
        ping_updates = {}

        for item in backup_snapshot:
            if _shutdown_requested.is_set():
                break

            is_working, ping, size = test_link_through_xray(
                item['link'],
                PROXY_PORT_BACKUP,
                timeout=BACKUP_TEST_TIMEOUT,
                shutdown_event=_shutdown_requested
            )

            display = f"{item['host']} [{item.get('country', 'N/A')}]"

            if is_working:
                ping_updates[item['link']] = (True, ping)
            else:
                ping_updates[item['link']] = (False, 0)
                dead_links.append(item['link'])
                logger.warning(f"⚠️ Резервная ссылка {display} мертва! Откладываем на 10 минут")

        with self.pool_lock:
            for item in self.backup_pool:
                if item['link'] in ping_updates:
                    alive, ping = ping_updates[item['link']]
                    item['alive'] = alive
                    item['ping'] = ping

            if dead_links:
                self.backup_pool = [item for item in self.backup_pool if item['link'] not in dead_links]

        if dead_links:
            for link in dead_links:
                self._add_to_deferred(link)

            logger.warning(f"⚠️ Отложено {len(dead_links)} ссылок")

            with self.pool_lock:
                need_refill = len(self.backup_pool) < BACKUP_POOL_SIZE
            if need_refill:
                self._fill_backup_pool_checked()

        with self.pool_lock:
            self.backup_pool.sort(key=lambda x: (not x.get('alive', False), x.get('ping', 9999)))
            alive_count = len([item for item in self.backup_pool if item.get('alive', False)])
            total = len(self.backup_pool)

        if alive_count == 0 and total > 0:
            logger.warning("⚠️ Все резервные ссылки мертвы! Пополнение пула...")
            self._fill_backup_pool_checked()

    # --------------------------------------------------------
    # ПОТОК 3: отложенные + обновление пула
    # --------------------------------------------------------

    def maintenance_loop(self):
        logger.info("▶️ Поток 3 (deferred + pool update) запущен")

        last_deferred_check = 0
        last_pool_update = 0

        while not _shutdown_requested.is_set():
            try:
                current_time = time.time()

                if current_time - last_deferred_check >= CHECK_INTERVAL_DEFERRED:
                    self.check_deferred_links()
                    last_deferred_check = current_time

                if current_time - last_pool_update >= CHECK_INTERVAL_POOL_UPDATE:
                    self.update_pool_from_file()
                    last_pool_update = current_time

            except Exception as e:
                logger.error(f"❌ Ошибка в потоке maintenance: {e}")
                import traceback
                logger.error(traceback.format_exc())

            for _ in range(CHECK_INTERVAL_DEFERRED):
                if _shutdown_requested.is_set():
                    break
                time.sleep(1)

        logger.info("⏹️ Поток 3 (deferred + pool update) завершён")

    def check_deferred_links(self):
        with self.deferred_lock:
            if not self.deferred_links:
                return
            current_time = time.time()
            to_check = []
            to_delete = []
            original = dict(self.deferred_links)

        for link, info in original.items():
            deferred_at = info['deferred_at']
            last_checked_at = info['last_checked_at']

            total_elapsed = current_time - deferred_at
            since_last_check = current_time - last_checked_at

            if total_elapsed >= DEAD_LINK_DELETE_AFTER:
                to_delete.append(link)
            elif since_last_check >= DEAD_LINK_RETRY_INTERVAL:
                to_check.append(link)

        if to_delete:
            with self.deferred_lock:
                for link in to_delete:
                    if link in self.deferred_links:
                        del self.deferred_links[link]

            for link in to_delete:
                with self.dead_links_lock:
                    self.dead_links.add(link)
                display = format_host_with_geo(link)
                logger.warning(f"🗑️ Ссылка {display} не ожила за 2 часа — удалена из пула")

        if to_check:
            logger.info(f"🔄 Проверяем {len(to_check)} отложенных ссылок...")

            for link in to_check:
                if _shutdown_requested.is_set():
                    break

                is_working, ping, size = test_link_through_xray(
                    link,
                    PROXY_PORT_DEFERRED,
                    timeout=DEFERRED_TEST_TIMEOUT,
                    shutdown_event=_shutdown_requested
                )

                parsed = parse_vless_link(link)
                display = format_host_with_geo(link)
                country = extract_geo_from_link(link)

                with self.deferred_lock:
                    info = self.deferred_links.get(link)
                    if info is None:
                        continue
                    total_elapsed_min = int((current_time - info['deferred_at']) / 60)

                if is_working:
                    with self.deferred_lock:
                        if link in self.deferred_links:
                            del self.deferred_links[link]

                    with self.dead_links_lock:
                        self.dead_links.discard(link)

                    logger.info(f"✅ Отложенная ссылка {display} ожила! Пинг: {ping:.0f}мс (была в отложенных {total_elapsed_min} мин)")

                    with self.pool_lock:
                        existing_links = [item['link'] for item in self.backup_pool]
                        if link not in existing_links and len(self.backup_pool) < BACKUP_POOL_SIZE:
                            self.backup_pool.append({
                                'link': link,
                                'host': parsed['host'] if parsed else 'unknown',
                                'country': country,
                                'alive': True,
                                'ping': ping
                            })
                            logger.info(f"➕ Ссылка {display} возвращена в резерв")
                        else:
                            logger.info(f"↩️ Ссылка {display} ожила, но пул полный — возвращена в общий оборот")
                else:
                    with self.deferred_lock:
                        if link in self.deferred_links:
                            self.deferred_links[link]['last_checked_at'] = time.time()

                    logger.warning(f"❌ Отложенная ссылка {display} всё ещё мертва ({total_elapsed_min} мин в deferred)")

    def update_pool_from_file(self):
        current_time = time.time()
        if current_time - self.last_pool_update_time < POOL_UPDATE_INTERVAL:
            return

        new_links = read_links_file(LINKS_FILE)
        if len(new_links) >= 2:
            old_count = len(self.links)
            self.links = new_links
            if old_count != len(new_links):
                logger.info(f"📥 Файл перечитан: {old_count} → {len(new_links)} ссылок")

        self.last_pool_update_time = current_time

    # --------------------------------------------------------
    # Старые триггеры (совместимость)
    # --------------------------------------------------------

    def check_trigger_file(self) -> bool:
        if os.path.exists(self.trigger_file):
            try:
                os.remove(self.trigger_file)
                logger.warning(f"⚠️ ТРИГГЕР: имитация отказов")
                with self.stats_lock:
                    self.primary_stats['fail_count'] = FAILURES_TO_SWITCH
                return True
            except Exception as e:
                logger.error(f"Ошибка удаления триггер-файла: {e}")
        return False

    def check_quarantine_trigger(self) -> bool:
        if os.path.exists(self.quarantine_trigger):
            try:
                os.remove(self.quarantine_trigger)
                logger.warning(f"⚠️ КАРАНТИН триггер")
                self.move_primary_to_quarantine()
                return True
            except Exception as e:
                logger.error(f"Ошибка удаления триггера карантина: {e}")
        return False

    def check_deep_check_trigger(self) -> bool:
        if os.path.exists(self.deep_check_trigger):
            try:
                os.remove(self.deep_check_trigger)
                logger.warning(f"⚠️ ГЛУБОКАЯ ПРОВЕРКА триггер")
                self.perform_deep_check()
                return True
            except Exception as e:
                logger.error(f"Ошибка удаления триггера глубокой проверки: {e}")
        return False

    def perform_deep_check(self):
        with self.primary_lock:
            primary = self.primary

        if not primary:
            logger.warning("Нет основной ссылки для глубокой проверки")
            return

        primary_display = format_host_with_geo(primary)
        logger.info(f"🔍 ГЛУБОКАЯ ПРОВЕРКА: {primary_display}")

        logger.info(f"  Шаг 1: Google...")
        google_ok, google_ping, _ = test_link_through_xray(
            primary, PROXY_PORT_PRIMARY, timeout=TEST_TIMEOUT,
            shutdown_event=_shutdown_requested
        )
        if google_ok:
            logger.info(f"  ✅ Google доступен ({google_ping:.0f}мс)")
        else:
            logger.warning(f"  ❌ Google НЕдоступен")

        logger.info(f"  Шаг 2: Запрещённые ресурсы...")
        deep_ok, deep_ping, deep_host = test_link_deep(
            primary, PROXY_PORT_PRIMARY, timeout=DEEP_CHECK_TIMEOUT,
            shutdown_event=_shutdown_requested
        )
        if deep_ok:
            logger.info(f"  ✅ Запрещённый доступен: {deep_host} ({deep_ping:.0f}мс)")
        else:
            logger.warning(f"  ❌ Ни один запрещённый НЕдоступен")

        if google_ok and not deep_ok:
            logger.warning(f"  ⚠️ ССЫЛКА РАБОТАЕТ ТОЛЬКО НА GOOGLE!")
            logger.warning(f"  🛑 Отправляем в карантин...")
            self.move_primary_to_quarantine()
        elif google_ok and deep_ok:
            logger.info(f"  ✅ Ссылка работает нормально")
        elif not google_ok:
            logger.warning(f"  ⚠️ Ссылка не работает даже на Google")
            with self.stats_lock:
                self.primary_stats['fail_count'] += 1
                fail_count = self.primary_stats['fail_count']
            if fail_count >= FAILURES_TO_SWITCH:
                self.switch_to_backup()

    def move_primary_to_quarantine(self):
        with self.primary_lock:
            old_primary = self.primary

        if not old_primary:
            logger.warning("Нет основной ссылки")
            return

        old_display = format_host_with_geo(old_primary)

        logger.warning(f"🛑 КАРАНТИН: {old_display}")

        try:
            os.makedirs(os.path.dirname(self.quarantine_file), exist_ok=True)
            with open(self.quarantine_file, 'a', encoding='utf-8') as f:
                f.write(f"{old_primary}\n")
            logger.info(f"✅ Ссылка добавлена в карантин")
        except Exception as e:
            logger.error(f"❌ Ошибка записи в карантин: {e}")

        with self.dead_links_lock:
            self.dead_links.add(old_primary)

        with self.pool_lock:
            self.backup_pool = [item for item in self.backup_pool if item['link'] != old_primary]
        self.switch_to_backup()

    # --------------------------------------------------------
    # Переключение на резерв
    # --------------------------------------------------------

    def switch_to_backup(self):
        self.switching.set()

        try:
            self._switch_to_backup_impl()
        finally:
            self.switching.clear()

    def _switch_to_backup_impl(self):
        tried_links = set()
        max_attempts = BACKUP_POOL_SIZE + 2

        for attempt in range(max_attempts):
            if _shutdown_requested.is_set():
                logger.info("🛑 shutdown во время переключения — прерываем")
                return

            with self.pool_lock:
                alive_backups = [
                    item for item in self.backup_pool
                    if item.get('alive', False) and item['link'] not in tried_links
                ]

            if not alive_backups:
                logger.warning("⚠️ Нет живых резервных! Пополняем пул...")
                self._fill_backup_pool_checked()

                with self.pool_lock:
                    alive_backups = [
                        item for item in self.backup_pool
                        if item.get('alive', False) and item['link'] not in tried_links
                    ]

                if not alive_backups:
                    if not self.critical_error_logged:
                        with self.primary_lock:
                            primary = self.primary
                        last_display = format_host_with_geo(primary) if primary else 'NONE [N/A]'
                        logger.critical("🔴 КРИТИЧЕСКАЯ ОШИБКА: НЕТ РАБОЧИХ ССЫЛОК В РЕЗЕРВЕ!")
                        logger.critical(f"Последняя рабочая: {last_display}")
                        self.critical_error_logged = True
                    return

            backup = alive_backups[0]
            new_primary = backup['link']
            new_display = format_host_with_geo(new_primary)

            # ПРОВЕРКА ПЕРЕД ПЕРЕКЛЮЧЕНИЕМ: убедимся, что ссылка жива прямо сейчас
            logger.info(f"🔎 Проверка перед переключением: {new_display}...")
            is_working, ping, _ = test_link_through_xray(
                new_primary,
                PROXY_PORT_BACKUP,
                timeout=BACKUP_TEST_TIMEOUT,
                shutdown_event=_shutdown_requested
            )

            if not is_working:
                logger.warning(f"⚠️ {new_display} мертва при проверке перед переключением — в deferred")
                self._add_to_deferred(new_primary)
                with self.pool_lock:
                    self.backup_pool = [item for item in self.backup_pool if item['link'] != new_primary]
                tried_links.add(new_primary)
                continue

            logger.info(f"✅ {new_display} жива (пинг: {ping:.0f}мс) — переключаемся")

            with self.primary_lock:
                old_primary = self.primary

            old_display = format_host_with_geo(old_primary) if old_primary else 'NONE [N/A]'

            logger.warning(f"⚠️ ПЕРЕКЛЮЧЕНИЕ: {old_display} → {new_display}")

            if update_3xui_outbound(new_primary, OUTBOUND_NAME):
                if reload_xray():
                    with self.primary_lock:
                        self.primary = new_primary

                    with self.pool_lock:
                        self.backup_pool = [item for item in self.backup_pool if item['link'] != new_primary]

                    with self.stats_lock:
                        self.switch_count += 1
                        self.primary_stats['fail_count'] = 0

                    self.critical_error_logged = False

                    if old_primary:
                        self._add_to_recently_primary(old_primary)
                        logger.info(f"⏸️ {old_display} в recently_primary на {RECENTLY_PRIMARY_COOLDOWN}с")

                    self._fill_backup_pool_checked()

                    logger.info(f"✅ Переключение выполнено (№{self.switch_count})")
                    self.log_status(force=True)
                    return
                else:
                    logger.error("❌ x-ui не перезапустился — пробуем следующую")
                    tried_links.add(new_primary)
            else:
                logger.error("❌ Не удалось обновить outbound — пробуем следующую")
                tried_links.add(new_primary)

        logger.error("❌ Все попытки переключения исчерпаны")

    # --------------------------------------------------------
    # Запуск
    # --------------------------------------------------------

    def run(self):
        logger.info("="*50)
        logger.info("🚀 VLESS OBSERVER (multi-threaded)")
        logger.info("="*50)

        cleanup_triggers_on_startup()

        while True:
            if _shutdown_requested.is_set():
                return

            if not self.load_links():
                if not self.wait_for_links():
                    if _shutdown_requested.is_set():
                        return
                    logger.error("❌ Не удалось дождаться ссылок")
                    time.sleep(60)
                continue

            if self.init_pool():
                break
            else:
                logger.info("⏳ Ждём обновления файла от чекера (проверка каждые 60 сек)...")
                for _ in range(60):
                    if _shutdown_requested.is_set():
                        return
                    time.sleep(1)
                continue

        logger.info(f"Порты: primary={PROXY_PORT_PRIMARY}, backup={PROXY_PORT_BACKUP}, deferred={PROXY_PORT_DEFERRED}")
        logger.info(f"Проверка основной: каждые {CHECK_INTERVAL_PRIMARY}с (timeout {TEST_TIMEOUT}с)")
        logger.info(f"Проверка резерва: каждые {CHECK_INTERVAL_BACKUP}с (timeout {BACKUP_TEST_TIMEOUT}с)")
        logger.info(f"Двойная проверка резерва: {BACKUP_CHECK_ATTEMPTS} раз, интервал {BACKUP_CHECK_INTERVAL}с")
        logger.info(f"Проверка перед переключением: включена")
        logger.info(f"Проверка deferred: каждые {CHECK_INTERVAL_DEFERRED}с")
        logger.info(f"Перепроверка отложенных: раз в {DEAD_LINK_RETRY_INTERVAL//60} минут")
        logger.info(f"Удаление отложенных: через {DEAD_LINK_DELETE_AFTER//60} минут")
        logger.info(f"Обновление пула: каждые {CHECK_INTERVAL_POOL_UPDATE}с")
        logger.info(f"Переключение: после {FAILURES_TO_SWITCH} отказов подряд")
        logger.info(f"Защита от круговорота: {RECENTLY_PRIMARY_COOLDOWN}с")

        if PREFERRED_COUNTRY:
            logger.info(f"⭐ Приоритетная страна: {PREFERRED_COUNTRY}")
        else:
            logger.info(f"Приоритетная страна: не задана")

        logger.info(f"Триггеры: включены (TRIGGER_MAX_AGE={TRIGGER_MAX_AGE}с)")
        logger.info(f"Источник ссылок: {LINKS_FILE}")
        logger.info("="*50)

        threads = [
            threading.Thread(target=self.primary_loop, name="Primary", daemon=False),
            threading.Thread(target=self.backup_loop, name="Backup", daemon=False),
            threading.Thread(target=self.maintenance_loop, name="Maintenance", daemon=False),
        ]

        for t in threads:
            t.start()

        try:
            while not _shutdown_requested.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n🛑 Остановлен пользователем")
            _shutdown_requested.set()

        for t in threads:
            t.join(timeout=CHECK_INTERVAL_BACKUP + 10)

        with self.primary_lock:
            primary = self.primary
        final_display = format_host_with_geo(primary) if primary else 'NONE [N/A]'

        with self.stats_lock:
            switch_count = self.switch_count

        logger.info("="*50)
        logger.info(f"📊 ИТОГИ: переключений: {switch_count} | основная: {final_display}")
        logger.info("="*50)


if __name__ == "__main__":
    observer = VlessObserver()
    observer.run()
