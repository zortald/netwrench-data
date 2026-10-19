#!/usr/bin/env python3
"""Проверяет router-catalog.json перед публикацией.

Запуск: python3 validate_catalog.py [файл]
Ненулевой код возврата — файл публиковать нельзя.
"""
import json
import sys

SCHEMA = 1
TYPES = {"router", "ap", "modem", "extender"}
BANDS = {"2.4", "5", "6"}
GENERATIONS = {"legacy", "wifi4", "wifi5", "wifi6", "wifi7"}
PORT_KEYS = {"100m", "1g", "2.5g", "5g", "10g", "sfp", "sfp+"}
FACTS = {"bands", "ports", "detachableAntennas", "externalAntennas", "status", "availableAsOf", "fccId"}
ORIGINS = {"toh", "manual", "verified"}
STATUSES = {"available", "discontinued"}


def check_device(d, errors):
    where = d.get("id", "<без id>")
    for field in ("id", "vendor", "model", "type", "sources", "origin"):
        if field not in d:
            errors.append(f"{where}: нет поля {field}")
    if d.get("type") not in TYPES:
        errors.append(f"{where}: type {d.get('type')!r} не из {sorted(TYPES)}")

    sources = d.get("sources") or []
    if not sources or not all(isinstance(s, str) and s.startswith("https://") for s in sources):
        errors.append(f"{where}: у записи нет https-источника")

    # Каждый факт — с источником, и источник — один из известных.
    origin = d.get("origin") or {}
    for fact in FACTS & set(d):
        if origin.get(fact) not in ORIGINS:
            errors.append(f"{where}: у факта {fact} нет источника в origin")
    for fact in set(origin) - FACTS:
        errors.append(f"{where}: origin называет неизвестный факт {fact}")
    for fact in set(origin) - set(d):
        errors.append(f"{where}: origin называет факт {fact}, которого нет в записи")

    bands = d.get("bands")
    if bands is not None:
        if not isinstance(bands, dict) or set(bands) - BANDS:
            errors.append(f"{where}: bands — только {sorted(BANDS)}")
        elif set(bands.values()) - GENERATIONS:
            errors.append(f"{where}: в bands неизвестное поколение")

    ports = d.get("ports")
    if ports is not None:
        if not isinstance(ports, dict) or set(ports) != PORT_KEYS:
            errors.append(f"{where}: ports должен перечислять ровно {sorted(PORT_KEYS)}")
        elif not all(isinstance(v, int) and v >= 0 for v in ports.values()):
            errors.append(f"{where}: в ports не целые неотрицательные числа")

    for field in ("detachableAntennas", "externalAntennas", "availableAsOf"):
        if field in d and not (isinstance(d[field], int) and d[field] >= 0):
            errors.append(f"{where}: {field} должен быть целым неотрицательным")
    if "status" in d and d["status"] not in STATUSES:
        errors.append(f"{where}: status {d['status']!r} не из {sorted(STATUSES)}")


def main(path):
    data = json.load(open(path, encoding="utf-8"))
    errors = []
    if data.get("schema") != SCHEMA:
        errors.append(f"schema должна быть {SCHEMA}")
    if not isinstance(data.get("version"), int) or data["version"] < 1:
        errors.append("version — целое число от 1")
    if data.get("license") != "CC BY-SA 4.0":
        errors.append("license должна быть CC BY-SA 4.0: в файле данные ToH")
    if not data.get("attribution"):
        errors.append("нет attribution")

    devices = data.get("devices") or []
    ids = [d.get("id") for d in devices]
    for dup in {i for i in ids if ids.count(i) > 1}:
        errors.append(f"id {dup} повторяется")
    for d in devices:
        check_device(d, errors)

    for e in errors:
        print("ОШИБКА:", e)
    print(f"{path}: {len(devices)} устройств, ошибок: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "router-catalog.json"))
