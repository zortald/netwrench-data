#!/usr/bin/env python3
"""Проверяет userscripts.json перед публикацией.

Запуск: python3 validate-userscripts.py [файл]
Ненулевой код возврата — файл публиковать нельзя.
"""
import json
import re
import sys

SCHEMA = 1
ENTRY_KEYS = {"id", "name", "description", "author", "matches", "url"}
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MATCH = re.compile(r"^(\*|https?)://[^/]+(/.*)?$|^<all_urls>$")


def check_entry(index, entry, seen, errors):
    where = f"entries[{index}]"
    if not isinstance(entry, dict):
        errors.append(f"{where}: не объект")
        return
    missing = ENTRY_KEYS - set(entry)
    extra = set(entry) - ENTRY_KEYS
    if missing:
        errors.append(f"{where}: нет полей {sorted(missing)}")
    if extra:
        errors.append(f"{where}: лишние поля {sorted(extra)}")
    if missing:
        return

    if not isinstance(entry["id"], str) or not ID.match(entry["id"]):
        errors.append(f"{where}: id должен быть строкой вида my-script")
    elif entry["id"] in seen:
        errors.append(f"{where}: id {entry['id']} уже встречался")
    else:
        seen.add(entry["id"])

    for field in ("name", "description", "author"):
        if not isinstance(entry[field], str) or not entry[field].strip():
            errors.append(f"{where}: {field} должен быть непустой строкой")

    # Только https: скачанное выполняется на странице, где у техника открыта
    # сессия, а телефон при этом часто сидит в чужой сети.
    url = entry["url"]
    if not isinstance(url, str) or not url.startswith("https://"):
        errors.append(f"{where}: url должен начинаться с https://")
    elif not url.endswith(".user.js"):
        errors.append(f"{where}: url должен указывать на файл .user.js")

    matches = entry["matches"]
    if not isinstance(matches, list) or not matches:
        errors.append(f"{where}: matches должен быть непустым списком")
        return
    for pattern in matches:
        if not isinstance(pattern, str) or not MATCH.match(pattern):
            errors.append(f"{where}: непонятный шаблон {pattern!r}")


def main(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    errors = []
    if data.get("schema") != SCHEMA:
        errors.append(f"schema должен быть {SCHEMA}")
    if not isinstance(data.get("version"), int):
        errors.append("version должен быть целым числом")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(data.get("updated", ""))):
        errors.append("updated должен быть датой ГГГГ-ММ-ДД")

    entries = data.get("entries")
    if not isinstance(entries, list):
        errors.append("entries должен быть списком")
        entries = []

    seen = set()
    for index, entry in enumerate(entries):
        check_entry(index, entry, seen, errors)

    if errors:
        for error in errors:
            print("ОШИБКА:", error)
        return 1
    print(f"OK: {len(entries)} запис(ь/и/ей)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "userscripts.json"))
