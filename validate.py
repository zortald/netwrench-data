#!/usr/bin/env python3
"""Проверяет router-defaults.json перед публикацией.

Запуск: python3 validate.py [файл]
Ненулевой код возврата — файл публиковать нельзя.
"""
import json
import re
import sys

STATES = {"fixed", "setup_required", "passwordless", "unknown"}
HOST = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}|[a-z0-9][a-z0-9.-]*\.[a-z]{2,})$", re.I)


def check(path):
    errors = []
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)

    if doc.get("schema") != 1:
        errors.append("schema должен быть 1")
    if not isinstance(doc.get("version"), int) or doc["version"] < 1:
        errors.append("version должен быть целым >= 1")

    entries = doc.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("entries пуст")
        return errors, doc

    seen_ids = set()
    seen_generic = set()
    for index, entry in enumerate(entries):
        where = entry.get("id") or f"#{index}"

        entry_id = entry.get("id")
        if not entry_id:
            errors.append(f"{where}: нет id")
        elif entry_id in seen_ids:
            errors.append(f"{where}: id повторяется")
        else:
            seen_ids.add(entry_id)

        vendor = entry.get("vendor")
        if not vendor:
            errors.append(f"{where}: нет vendor")

        state = entry.get("state")
        if state not in STATES:
            errors.append(f"{where}: state={state!r}, допустимы {sorted(STATES)}")

        addresses = entry.get("addresses")
        if not isinstance(addresses, list) or not addresses:
            errors.append(f"{where}: addresses пуст")
        else:
            for address in addresses:
                if not HOST.match(str(address)):
                    errors.append(f"{where}: адрес {address!r} не похож на IP или имя хоста")

        credentials = entry.get("credentials")
        if not isinstance(credentials, list):
            errors.append(f"{where}: credentials должен быть списком")
        else:
            for pair in credentials:
                if not isinstance(pair, dict) or "user" not in pair or "password" not in pair:
                    errors.append(f"{where}: пара учётных данных без user/password")
            # При setup_required/unknown готового пароля не существует, но
            # известный логин — полезный факт, он несётся как password: null.
            if state in {"setup_required", "unknown"}:
                for pair in credentials:
                    if isinstance(pair, dict) and pair.get("password") is not None:
                        errors.append(f"{where}: state={state} не может нести готовый пароль")
            if not credentials and state == "fixed":
                errors.append(f"{where}: state=fixed без учётных данных")

        note = entry.get("note")
        if note is not None:
            if not isinstance(note, dict) or set(note) != {"ru", "en"}:
                errors.append(f"{where}: note должен быть объектом с ru и en")

        # Порядок подбора: запись без models — запасная, она обязана идти
        # после всех записей своего вендора с моделями.
        if vendor:
            if "models" not in entry:
                seen_generic.add(vendor)
            elif vendor in seen_generic:
                errors.append(f"{where}: запись с models стоит ниже общей записи вендора")

    return errors, doc


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "router-defaults.json"
    errors, doc = check(path)
    if errors:
        print(f"{path}: {len(errors)} проблем")
        for error in errors:
            print("  -", error)
        return 1
    entries = doc["entries"]
    vendors = {entry["vendor"] for entry in entries}
    verified = sum(1 for entry in entries if entry.get("verified"))
    print(f"{path}: ok — version {doc['version']}, {len(entries)} записей, "
          f"{len(vendors)} вендоров, {verified} подтверждены живьём")
    return 0


if __name__ == "__main__":
    sys.exit(main())
