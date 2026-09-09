#!/usr/bin/env python3
"""Проверяет router-defaults.json перед публикацией.

Запуск: python3 validate.py [файл]
Ненулевой код возврата — файл публиковать нельзя.
"""
import json
import re
import sys

SCHEMA = 2
HOST = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}|[a-z0-9][a-z0-9.-]*\.[a-z]{2,})$", re.I)
ACCESS_TYPES = {"http", "https", "ssh", "telnet", "api", "api-tls", "winbox"}
AUTH_KEYS = {
    "usernameField", "username", "usernameCreated",
    "password", "passwordCreated", "passwordOnLabel", "wizardBlocks",
}


def check_auth(where, auth, errors):
    if not isinstance(auth, dict):
        errors.append(f"{where}: нет объекта auth")
        return
    missing = AUTH_KEYS - set(auth)
    extra = set(auth) - AUTH_KEYS
    if missing:
        errors.append(f"{where}: в auth нет полей {sorted(missing)}")
    if extra:
        errors.append(f"{where}: в auth лишние поля {sorted(extra)}")
    if missing:
        return

    for flag in ("usernameField", "usernameCreated", "passwordCreated",
                 "passwordOnLabel", "wizardBlocks"):
        if not isinstance(auth[flag], bool):
            errors.append(f"{where}: auth.{flag} должен быть true/false")

    # Нет поля логина — значит и логина нет.
    if not auth["usernameField"]:
        if auth["username"] is not None:
            errors.append(f"{where}: usernameField=false, но задан username")
        if auth["usernameCreated"]:
            errors.append(f"{where}: usernameField=false, но usernameCreated=true")

    # Придуманного пользователем значения в базе быть не может.
    if auth["usernameCreated"] and auth["username"] is not None:
        errors.append(f"{where}: usernameCreated=true, но username задан")
    if auth["passwordCreated"] and auth["password"] is not None:
        errors.append(f"{where}: passwordCreated=true, но password задан")
    # passwordOnLabel уживается с заводской парой: у розничного экземпляра
    # работает admin/admin, у провайдерской прошивки того же вендора пароль
    # напечатан на наклейке. Оба факта верны и оба нужны технику.
    if auth["passwordCreated"] and auth["passwordOnLabel"]:
        errors.append(f"{where}: пароль не может одновременно создаваться и быть на наклейке")


def check_access(where, access, errors):
    if not isinstance(access, list) or not access:
        errors.append(f"{where}: access пуст")
        return
    seen = set()
    for item in access:
        if not isinstance(item, dict):
            errors.append(f"{where}: элемент access не объект")
            continue
        kind, port = item.get("type"), item.get("port")
        if kind not in ACCESS_TYPES:
            errors.append(f"{where}: access.type={kind!r}, допустимы {sorted(ACCESS_TYPES)}")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            errors.append(f"{where}: access.port={port!r} вне диапазона")
        if not isinstance(item.get("enabled"), bool):
            errors.append(f"{where}: access.enabled должен быть true/false")
        key = (kind, port)
        if key in seen:
            errors.append(f"{where}: служба {kind}:{port} повторяется")
        seen.add(key)
    if not any(i.get("type") in ("http", "https") for i in access if isinstance(i, dict)):
        errors.append(f"{where}: нет веб-интерфейса в access")


def check(path):
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)

    errors = []
    if doc.get("schema") != SCHEMA:
        errors.append(f"schema должен быть {SCHEMA}")
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

        addresses = entry.get("addresses")
        if not isinstance(addresses, list) or not addresses:
            errors.append(f"{where}: addresses пуст")
        else:
            for address in addresses:
                if not HOST.match(str(address)):
                    errors.append(f"{where}: адрес {address!r} не похож на IP или имя хоста")

        check_access(where, entry.get("access"), errors)
        check_auth(where, entry.get("auth"), errors)

        reset = entry.get("factoryReset")
        if reset is not None:
            if not isinstance(reset, dict) or not reset:
                errors.append(f"{where}: factoryReset пуст")
            else:
                hold = reset.get("holdSeconds")
                if hold is not None and (not isinstance(hold, int) or hold <= 0):
                    errors.append(f"{where}: factoryReset.holdSeconds должен быть целым > 0")

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
    ready = sum(1 for e in entries if e["auth"]["password"] is not None)
    print(f"{path}: ok — schema {doc['schema']}, version {doc['version']}, "
          f"{len(entries)} записей, {len({e['vendor'] for e in entries})} вендоров")
    print(f"  готовая пара: {ready} | подтверждены живьём: "
          f"{sum(1 for e in entries if e.get('verified'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
