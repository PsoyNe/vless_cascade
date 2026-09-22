#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VLESS Bot — точка входа.

Что здесь:
  1. Настройка логирования с ротацией (как у observer'а).
  2. Инициализация aiogram Bot с SOCKS5-прокси (Telegram в РФ
     заблокирован, ходим через локальный Xray на 127.0.0.1:1080).
  3. Retry-цикл подключения к Telegram: observer может ещё не
     успеть поднять Xray / primary-ссылку, ждём.
  4. set_my_commands — меню команд по кнопке "/" в Telegram.
  5. Регистрация роутера и запуск long-polling.

Никакой логики команд здесь нет — всё в bot_handlers.py.
"""

import asyncio
import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import BotCommand

import vless_bot_config as cfg
from bot_handlers import router


# ============================================================
# ЛОГИРОВАНИЕ
# ============================================================

def setup_logging() -> None:
    """Настраивает логирование в файл (с ротацией) и stdout."""
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Файловый хендлер с ротацией
    file_handler = TimedRotatingFileHandler(
        cfg.LOG_FILE,
        when=cfg.LOG_ROTATION_WHEN,
        interval=cfg.LOG_ROTATION_INTERVAL,
        backupCount=cfg.LOG_ROTATION_BACKUPS,
        utc=False,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # Консольный хендлер — для systemd journal
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Чуть приглушаем слишком болтливые логгеры aiogram/aiohttp
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ============================================================
# ПОСТРОЕНИЕ BOT С ПРОКСИ
# ============================================================

def build_bot() -> Bot:
    """
    Создаёт Bot с AiohttpSession, настроенной на SOCKS5-прокси
    (127.0.0.1:1080).

    aiogram v3 умеет прокси через AiohttpSession(proxy=...),
    если установлен aiohttp-socks. Схема socks5:// и http://
    определяются по URL автоматически.

    Таймауты: ставим умеренные — при рестарте Xray связь пропадает
    на пару секунд, aiogram должен пережить это без падения.
    """
    session = AiohttpSession(
        proxy=cfg.TELEGRAM_PROXY,
        timeout=30,  # общий таймаут на запрос, сек
    )
    bot = Bot(token=cfg.TELEGRAM_BOT_TOKEN, session=session)
    return bot


# ============================================================
# МЕНЮ КОМАНД
# ============================================================

async def setup_commands(bot: Bot) -> None:
    """
    Регистрирует меню команд (кнопка "/" в Telegram).
    Вызывается после успешного подключения.
    """
    commands = [
        BotCommand(command="status",    description="📡 Статус observer"),
        BotCommand(command="links",     description="🔗 Список всех ссылок"),
        BotCommand(command="switch",    description="🔀 На следующую живую"),
        BotCommand(command="geo",       description="🌍 На страну (напр. /geo DE)"),
        BotCommand(command="pick",      description="🎯 На host (напр. /pick 1.2.3.4)"),
        BotCommand(command="ignore",    description="🚫 В карантин (напр. /ignore 1.2.3.4)"),
        BotCommand(command="unignore",  description="✅ Из карантина"),
        BotCommand(command="reload",    description="🔄 Перечитать файл ссылок"),
        BotCommand(command="help",      description="❓ Справка"),
    ]
    await bot.set_my_commands(commands)
    logger.info("✅ Меню команд зарегистрировано")


# ============================================================
# RETRY-ЦИКЛ ПОДКЛЮЧЕНИЯ
# ============================================================

async def wait_for_telegram(bot: Bot) -> None:
    """
    Ждёт, пока Telegram станет доступен через прокси.

    Причина: observer мог ещё не поднять Xray/primary-ссылку,
    или только что перезапустился после переключения. В этот
    момент порт 1080 недоступен, api.telegram.org не отвечает.

    Логика: пробуем get_me() до успеха. При ошибке спим
    TELEGRAM_CONNECT_RETRY_INTERVAL и пробуем снова.
    TELEGRAM_CONNECT_MAX_ATTEMPTS=0 → бесконечно.
    """
    attempt = 0
    max_attempts = cfg.TELEGRAM_CONNECT_MAX_ATTEMPTS

    while True:
        attempt += 1
        try:
            me = await bot.get_me()
            logger.info(
                f"✅ Подключение к Telegram установлено: "
                f"@{me.username} (id={me.id})"
            )
            return
        except TelegramNetworkError as e:
            logger.warning(
                f"⏳ Telegram недоступен (попытка {attempt}): {e}. "
                f"Повтор через {cfg.TELEGRAM_CONNECT_RETRY_INTERVAL} сек..."
            )
        except Exception as e:
            logger.error(
                f"❌ Ошибка подключения к Telegram (попытка {attempt}): "
                f"{type(e).__name__}: {e}"
            )

        if max_attempts and attempt >= max_attempts:
            logger.error(
                f"❌ Превышено число попыток подключения ({max_attempts}). "
                f"Выход."
            )
            raise SystemExit(1)

        await asyncio.sleep(cfg.TELEGRAM_CONNECT_RETRY_INTERVAL)


# ============================================================
# ЗАПУСК
# ============================================================

async def main_async() -> None:
    """Основная async-логика запуска."""
    logger.info("=" * 60)
    logger.info("🚀 Запуск VLESS Bot")
    logger.info(f"   Прокси: {cfg.TELEGRAM_PROXY}")
    logger.info(f"   Chat ID: {cfg.TELEGRAM_CHAT_ID}")
    logger.info(f"   Лог: {cfg.LOG_FILE}")
    logger.info("=" * 60)

    bot = build_bot()
    dp = Dispatcher()
    dp.include_router(router)

    # 1. Ждём Telegram (может ещё не быть через прокси)
    await wait_for_telegram(bot)

    # 2. Регистрируем меню команд
    try:
        await setup_commands(bot)
    except Exception as e:
        logger.error(f"Не удалось зарегистрировать меню команд: {e}")
        # Не критично — продолжаем без меню.

    # 3. Запускаем polling.
    #    drop_pending_updates=True — на случай, если бот был выключен
    #    и в Telegram накопились старые апдейты: не обрабатываем их.
    try:
        logger.info("📡 Запуск polling...")
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        await bot.session.close()
        logger.info("🛑 Бот остановлен")


def main() -> None:
    """Синхронная точка входа."""
    setup_logging()

    # Проверка конфига — базовая
    if not cfg.TELEGRAM_BOT_TOKEN or cfg.TELEGRAM_BOT_TOKEN.startswith("PASTE_"):
        logger.error(
            "❌ TELEGRAM_BOT_TOKEN не задан. "
            "Открой vless_bot_config.py и впиши токен (или запусти install_bot.sh)."
        )
        sys.exit(1)
    if not cfg.TELEGRAM_CHAT_ID:
        logger.error(
            "❌ TELEGRAM_CHAT_ID не задан. "
            "Открой vless_bot_config.py и впиши chat_id (или запусти install_bot.sh)."
        )
        sys.exit(1)

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("⌨️ Прервано пользователем (Ctrl+C)")
    except SystemExit:
        raise
    except Exception as e:
        logger.critical(f"💥 Фатальная ошибка: {type(e).__name__}: {e}",
                        exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
