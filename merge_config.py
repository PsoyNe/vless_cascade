#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_config.py — умное слияние конфигов VLESS CASCADE.

Добавляет в текущий конфиг параметры из нового конфига, которых там нет.
Существующие параметры НЕ трогает. Спрашивает подтверждение.

Использование:
    python3 merge_config.py <current_config> <new_config> <label> [--auto]

Возвращает:
    0 — параметры добавлены или новых нет
    1 — ошибка
    2 — пользователь отказался

Аргументы:
    current_config — путь к текущему конфигу на сервере
    new_config     — путь к новому конфигу с GitHub (в /tmp)
    label          — имя конфига для вывода (например, "vless_check_config.py")
    --auto         — не спрашивать, пропустить слияние
"""

import sys
import re
from typing import Dict, List, Set, Tuple, Optional


# ============================================================
# ПАРСИНГ КОНФИГА
# ============================================================

KEY_PATTERN = re.compile(r'^[A-Z_][A-Z0-9_]*$')


def extract_keys(path: str) -> Set[str]:
    """
    Возвращает множество ключей простых параметров в файле.
    Простой параметр — строка вида KEY = VALUE на верхнем уровне.
    Многострочные списки/словари тоже считаются — берётся только ключ.
    """
    keys: Set[str] = set()

    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                # Пропускаем пустые и комментарии
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                # Пропускаем отступы (продолжение многострочных)
                if line.startswith((' ', '\t')):
                    continue
                # Ищем KEY = VALUE
                if '=' not in stripped:
                    continue
                key = stripped.split('=', 1)[0].strip()
                if KEY_PATTERN.match(key):
                    keys.add(key)
    except Exception:
        pass

    return keys


def extract_params(path: str) -> Dict[str, List[str]]:
    """
    Возвращает {ключ: [строки]} для всех параметров верхнего уровня.

    Обрабатывает:
    - простые KEY = VALUE
    - многострочные KEY = [ ... ] / KEY = { ... }
    - комментарии перед параметрами (включаются в блок)
    """
    params: Dict[str, List[str]] = {}

    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception:
        return params

    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # Пропускаем пустые строки
        if not line.strip():
            i += 1
            continue

        # Пропускаем комментарии (они не самостоятельны,
        # но могут быть "приклеены" к следующему параметру)
        if line.strip().startswith('#'):
            i += 1
            continue

        # Строка с отступом в начале файла (без родителя) — пропускаем
        if line.startswith((' ', '\t')):
            i += 1
            continue

        # Начало параметра?
        if '=' not in line:
            i += 1
            continue

        key = line.split('=', 1)[0].strip()
        if not KEY_PATTERN.match(key):
            i += 1
            continue

        # Собираем блок строк для этого параметра
        block: List[str] = [line]

        # Считаем баланс скобок, чтобы понять, многострочный ли параметр
        balance = line.count('[') + line.count('{') - line.count(']') - line.count('}')

        if balance > 0:
            # Многострочный — читаем до закрытия
            i += 1
            while i < n and balance > 0:
                block.append(lines[i])
                balance += lines[i].count('[') + lines[i].count('{')
                balance -= lines[i].count(']') + lines[i].count('}')
                i += 1
        else:
            # Простой — уже всё
            i += 1

        params[key] = block

    return params


# ============================================================
# ФОРМАТИРОВАНИЕ
# ============================================================

def format_param_block(key: str, lines: List[str]) -> str:
    """Форматирует блок параметра для показа пользователю."""
    return "".join(lines).rstrip()


def indent_block(text: str, indent: str = "  ") -> str:
    """Добавляет отступ к каждой строке."""
    return "\n".join(indent + line for line in text.split("\n"))


# ============================================================
# СЛИЯНИЕ
# ============================================================

def merge_config(
    current_path: str,
    new_path: str,
    label: str,
    auto_mode: bool = False,
) -> int:
    """
    Сливает конфиги. Возвращает код выхода:
        0 — успех (добавлено или новых нет)
        1 — ошибка
        2 — пользователь отказался
    """
    # Читаем ключи из текущего конфига
    current_keys = extract_keys(current_path)

    if not current_keys:
        print(f"[ERROR] Не удалось прочитать текущий конфиг: {current_path}")
        return 1

    # Читаем параметры из нового конфига
    new_params = extract_params(new_path)

    if not new_params:
        print(f"[WARNING] Новый конфиг пуст или не читается: {new_path}")
        return 0

    # Ищем параметры, которых нет в текущем
    new_only: List[Tuple[str, List[str]]] = []
    for key, lines in new_params.items():
        if key not in current_keys:
            new_only.append((key, lines))

    # Новых параметров нет — выходим тихо
    if not new_only:
        print(f"[OK] {label}: новых параметров нет")
        return 0

    # --- Есть новые параметры ---

    # Собираем текст блока для показа
    preview_lines = []
    for key, lines in new_only:
        preview_lines.append(format_param_block(key, lines))
        preview_lines.append("")

    preview_text = "\n".join(preview_lines).rstrip()

    print()
    print("=" * 60)
    print(f"[WARNING] {label}: найдены новые параметры")
    print("=" * 60)
    print()
    print(preview_text)
    print()
    print("=" * 60)
    print()

    # Режим --auto
    if auto_mode:
        print("[INFO] Режим --auto: слияние пропущено.")
        print(f"[INFO] Новые параметры: {', '.join(k for k, _ in new_only)}")
        print("[INFO] Добавьте их вручную, если требуется.")
        return 0

    # Спрашиваем подтверждение
    try:
        answer = input(f"Добавить эти параметры в {label}? (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        print("[INFO] Отменено пользователем")
        return 2

    if answer not in ('y', 'yes', 'д', 'да'):
        print(f"[INFO] {label}: слияние отменено пользователем")
        return 2

    # Дописываем параметры в конец файла
    try:
        with open(current_path, 'a', encoding='utf-8') as f:
            f.write("\n\n")
            f.write(f"# === AUTO-ADDED (merge at update) ===\n")
            for key, lines in new_only:
                f.write("\n")
                f.write(format_param_block(key, lines))
                f.write("\n")
    except Exception as e:
        print(f"[ERROR] Не удалось записать в {current_path}: {e}")
        return 1

    print(f"[OK] {label}: добавлено параметров: {len(new_only)}")
    print(f"[OK] Добавлено: {', '.join(k for k, _ in new_only)}")
    return 0


# ============================================================
# ТОЧКА ВХОДА
# ============================================================

def main():
    if len(sys.argv) < 4:
        print("Использование: python3 merge_config.py <current> <new> <label> [--auto]")
        sys.exit(1)

    current_path = sys.argv[1]
    new_path = sys.argv[2]
    label = sys.argv[3]
    auto_mode = len(sys.argv) > 4 and sys.argv[4] == '--auto'

    exit_code = merge_config(current_path, new_path, label, auto_mode)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
