#!/usr/bin/env python3
"""Собирает router-catalog.json из источников в sources/.

Запуск:
    python3 build_catalog.py                # собрать из того, что лежит в sources/
    python3 build_catalog.py --fetch-toh    # сначала обновить снимок ToH

Источники, по возрастанию приоритета (последний перекрывает поле предыдущего):
    sources/toh.json       — снимок OpenWrt Table of Hardware (CC BY-SA 4.0);
    sources/manual.json    — факты со страниц производителей, у каждой записи URL;
    sources/verified.json  — то, что видели на стенде своими глазами.

У каждого поля итоговой записи в origin указано, из какого источника оно взято.
Поле, которого источник не сообщил, в запись не попадает: неизвестно — не ноль.
"""
import argparse
import datetime
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "sources"
OUT = ROOT / "router-catalog.json"
TOH_URL = "https://openwrt.org/toh.json"
SCHEMA = 1

# Только то, что NetWrench может увидеть шлюзом или точкой доступа.
TOH_TYPES = {
    "WiFi Router": "router",
    "Router": "router",
    "Travel Router": "router",
    "Travel Router - Battery powered": "router",
    "WiFi AP": "ap",
    "Modem": "modem",
    "Range Extender": "extender",
}

# Бренд в том написании, в каком его отдаёт детектор (RouterDetector.detectVendor).
VENDOR_NAMES = {
    "netgear": "Netgear",
    "zyxel": "Zyxel",
    "mercusys": "Mercusys",
    "tp-link": "TP-Link",
    "d-link": "D-Link",
    "asus": "ASUS",
    "mikrotik": "MikroTik",
    "keenetic": "Keenetic",
    "tenda": "Tenda",
    "netis": "netis",
    "xiaomi": "Xiaomi",
    "huawei": "Huawei",
    "zte": "ZTE",
    "ubiquiti": "Ubiquiti",
    "totolink": "Totolink",
}

PORT_FIELDS = {
    "100m": "ethernet100mports",
    "1g": "ethernet1gports",
    "2.5g": "ethernet2_5gports",
    "5g": "ethernet5gports",
    "10g": "ethernet10gports",
    "sfp": "sfp_ports",
    "sfp+": "sfp_plus_ports",
}
TOH_COLUMNS = [
    "deviceid", "brand", "model", "version", "devicetype", "availability",
    "wlan24ghz", "wlan50ghz", "detachableantennas", "fccid", *PORT_FIELDS.values(),
    # Характеристики для Pro-карточки.
    "cpu", "cpucores", "cpumhz", "rammb", "flashmb", "wlancomments", "comments",
    "supportedsincerel", "supportedcurrentrel", "powersupply",
    "oemdevicehomepageurl", "firmwareoemstockurl", "outdoor", "modem", "usbports", "vlan",
]
FACT_FIELDS = (
    "bands", "ports", "detachableAntennas", "externalAntennas", "status", "availableAsOf", "fccId",
    "cpu", "cpuCores", "cpuMhz", "ramMb", "flashMb", "mimo", "openwrtSince", "openwrtCurrent",
    "powerSupply", "oemUrl", "firmwareUrl", "outdoor", "modem", "usb", "vlan",
)


def vendor_name(raw):
    if not raw:
        return None
    return VENDOR_NAMES.get(raw.strip().lower(), raw.strip())


def fetch_toh():
    """Снимает ToH и сохраняет только нужные колонки — источник, а не зеркало."""
    req = urllib.request.Request(TOH_URL, headers={"User-Agent": "netwrench-data catalog builder"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    columns = data["columns"]
    rows = [dict(zip(columns, row)) for row in data["entries"]]
    kept = [{k: r.get(k) for k in TOH_COLUMNS} for r in rows if r.get("devicetype") in TOH_TYPES]
    snapshot = {
        "source": TOH_URL,
        "license": "CC BY-SA 4.0",
        "attribution": "OpenWrt Table of Hardware, https://openwrt.org/toh/start",
        "fetched": datetime.date.today().isoformat(),
        "devices": kept,
    }
    SOURCES.mkdir(exist_ok=True)
    (SOURCES / "toh.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n")
    print(f"toh: {len(kept)} из {len(rows)} устройств сохранено")


def generation(raw):
    """b/g/n → wifi4 … ; '-' — диапазона нет; None — источник не сказал."""
    if raw is None:
        return None
    modes = set(raw.lower().replace(" ", "").split("/"))
    if modes == {"-"} or modes == {""}:
        return "none"
    for mode, gen in (("be", "wifi7"), ("ax", "wifi6"), ("ac", "wifi5"), ("n", "wifi4")):
        if mode in modes:
            return gen
    return "legacy"


def count(raw):
    """'5' → 5, '-' → 0, None и 'more than 20' → неизвестно."""
    if raw is None:
        return None
    raw = str(raw).strip()
    if raw == "-":
        return 0
    return int(raw) if raw.isdigit() else None


def text(raw):
    """Строка ToH без пустых значений-заглушек: '-', '¿', пусто → неизвестно."""
    if raw is None:
        return None
    raw = str(raw).strip()
    return None if raw in ("", "-", "¿") else raw


def yes_no(raw):
    raw = (text(raw) or "").lower()
    return True if raw == "yes" else False if raw == "no" else None


def flash_mb(raw):
    """['32', '128NAND', 'microSD'] → 32: первая встроенная память; карты и eMMC без размера — не она."""
    for item in raw or []:
        m = re.fullmatch(r"(\d+)\s*(NAND|NOR)?", str(item).strip(), re.I)
        if m:
            return int(m.group(1))
    return None


def mimo(raw):
    """'MIMO 2x2:2 on both bands' → '2x2:2'. Только когда в тексте одна схема на всё:
    две разные — это разные диапазоны, а какой где, свободный текст надёжно не говорит."""
    found = {f"{a}x{b}" + (f":{c}" if c else "")
             for a, b, c in re.findall(r"(\d)\s*[xX]\s*(\d)(?::(\d))?", raw or "")}
    return found.pop() if len(found) == 1 else None


def openwrt_release(raw):
    """'25.12.2' или 'EOL'; 'snapshot', 'external image' и прочее — не релиз."""
    raw = text(raw)
    return raw if raw and (raw == "EOL" or re.fullmatch(r"\d+\.\d+(\.\d+)?", raw)) else None


def https_url(raw):
    """Ссылка из ToH, если https; хвостовые обратные слеши и кавычки — опечатки вики."""
    raw = (text(raw) or "").rstrip("\\'\" ")
    return raw if raw.startswith("https://") and " " not in raw else None


def usb(raw):
    """['1x 2.0', '1x µUSB (power)'] → '1x 2.0': только порты под устройства, не питание."""
    ports = [p for p in (text(v) for v in raw or []) if p and re.fullmatch(r"\d+x \d\.\d", p)]
    return ", ".join(ports) if ports else ("none" if raw == ["-"] else None)


FIXED_ANTENNAS = re.compile(
    r"\b(\d+)\s*(?:x\s*)?(?:fixed(?:\s+external)?|non[- ]?deta?t?c?h?able)\b[^.;]{0,20}?antenna", re.I)
INTERNAL_ANTENNAS = re.compile(r"\b(?:internal|pcb|integrated|built[- ]in)\b[^.;]{0,15}?antenna", re.I)
NOT_WIFI = re.compile(r"\b(?:lte|4g|5g nr|gps|gnss)\b", re.I)


def external_antennas(detachable, *notes):
    """Сколько антенн снаружи корпуса, когда комментарий ToH говорит об этом прямо.

    ToH считает только съёмные антенны, и её 0 значит «съёмных нет», а не «антенн
    нет»: у Archer C6 их четыре несъёмных. Комментарий иногда договаривает:
    «4 non-detachable antennas» — это 4 плюс съёмные; «internal antennas» при
    нуле съёмных — снаружи ни одной. Всё, где речь об LTE/GPS-антеннах или где
    сказано и про внутренние, и про внешние, остаётся неизвестным.
    """
    text_ = " ".join(n for n in notes if n)
    if not text_ or NOT_WIFI.search(text_):
        return None
    fixed = {int(n) for n in FIXED_ANTENNAS.findall(text_)}
    internal = INTERNAL_ANTENNAS.search(text_) is not None
    if len(fixed) == 1 and not internal:
        return fixed.pop() + (detachable or 0)
    # Разъём под антенну — значит, наружу её могут вывести: снаружи неизвестно сколько.
    if internal and not fixed and not re.search(r"external|connector", text_, re.I) and not detachable:
        return 0
    return None


def split_model(raw):
    """'RBD53iG-5HacD2HnD (hap ac³)' → модель и псевдонимы; 'TL-WR841N/ND' → ещё TL-WR841ND."""
    raw = raw.strip()
    aliases = [a.strip() for a in re.findall(r"\(([^)]+)\)", raw)]
    base = re.sub(r"\s*\([^)]*\)", "", raw).strip()
    parts = [p.strip() for p in re.split(r"\s*/\s*", base) if p.strip()]
    model, rest = parts[0], parts[1:]
    for part in rest:
        overlap = next((n for n in range(min(len(model), len(part)), 0, -1)
                        if part.lower().startswith(model[-n:].lower())), 0)
        if overlap:
            aliases.append(model[:-overlap] + part)
        elif len(part) >= 3:
            aliases.append(part)
    return model, [a for a in dict.fromkeys(aliases) if a.lower() != model.lower()]


def revisions(raw):
    """['v3 (US) (BR) (EU)'] → ['v3']: регион не меняет железо в части портов и радио."""
    if not raw:
        return []
    return list(dict.fromkeys(re.sub(r"\s*\(.*$", "", v).strip() for v in raw if v and v.strip()))


def toh_entry(row):
    model, aliases = split_model(row["model"] or "")
    bands = {}
    unknown_band = False
    for band, field in (("2.4", "wlan24ghz"), ("5", "wlan50ghz")):
        gen = generation(row.get(field))
        if gen is None:
            unknown_band = True
        elif gen != "none":
            bands[band] = gen
    ports = {key: count(row.get(field)) for key, field in PORT_FIELDS.items()}
    known_ports = {k: v for k, v in ports.items() if v is not None}

    availability = (row.get("availability") or "").strip()
    status = ("discontinued" if availability.lower().startswith("discontinued")
              else "available" if availability.lower().startswith("available") else None)
    as_of = re.search(r"(\d{4})", availability) if status == "available" else None

    fcc = None
    for link in row.get("fccid") or []:
        m = re.search(r"fcc\.io/([A-Z0-9]+)/([A-Z0-9-]+)", link or "", re.I)
        if m:
            fcc = (m.group(1) + m.group(2)).upper()
            break

    entry = {
        "id": "toh:" + row["deviceid"],
        "vendor": vendor_name(row["brand"]),
        "model": model,
        "aliases": aliases,
        "revisions": revisions(row.get("version")),
        "type": TOH_TYPES[row["devicetype"]],
        "bands": None if unknown_band else bands,
        # Порты известны, только если источник назвал каждый вид; иначе сумма соврёт.
        "ports": known_ports if len(known_ports) == len(ports) else None,
        "detachableAntennas": count(row.get("detachableantennas")),
        "externalAntennas": external_antennas(
            count(row.get("detachableantennas")), text(row.get("wlancomments")), text(row.get("comments"))),
        "status": status,
        "availableAsOf": int(as_of.group(1)) if as_of else None,
        "fccId": fcc,
        "cpu": text(row.get("cpu")),
        "cpuCores": count(row.get("cpucores")) or None,
        "cpuMhz": count(row.get("cpumhz")) or None,
        "ramMb": count(row.get("rammb")) or None,
        "flashMb": flash_mb(row.get("flashmb")),
        "mimo": mimo(row.get("wlancomments")),
        "openwrtSince": openwrt_release(row.get("supportedsincerel")),
        "openwrtCurrent": openwrt_release(row.get("supportedcurrentrel")),
        "powerSupply": text(row.get("powersupply")),
        "oemUrl": https_url(row.get("oemdevicehomepageurl")),
        "firmwareUrl": https_url(row.get("firmwareoemstockurl")),
        "outdoor": yes_no(row.get("outdoor")),
        "modem": text(row.get("modem")),
        "usb": usb(row.get("usbports")),
        "vlan": yes_no(row.get("vlan")),
    }
    return entry


def key(entry):
    return (entry["vendor"].lower(), entry["model"].lower(), tuple(r.lower() for r in entry["revisions"]))


def overlay(base, patch, source):
    """Поля из patch перекрывают base; origin запоминает, откуда пришло каждое."""
    merged = dict(base)
    origin = dict(base.get("origin", {}))
    for field in FACT_FIELDS:
        if field in patch:
            merged[field] = patch[field]
            origin[field] = source
    # Написание из патча главнее: ToH пишет «hap ac³», производитель — «hAP ac³».
    aliases = {}
    for a in patch.get("aliases", []) + base.get("aliases", []):
        aliases.setdefault(a.casefold(), a)
    merged["aliases"] = list(aliases.values())
    merged["origin"] = origin
    merged["sources"] = base.get("sources", []) + [s for s in patch.get("sources", []) if s not in base.get("sources", [])]
    return merged


def load(name):
    path = SOURCES / name
    return json.loads(path.read_text()) if path.exists() else None


def build():
    toh = load("toh.json")
    if toh is None:
        sys.exit("нет sources/toh.json — запустите с --fetch-toh")
    entries = {}
    for row in toh["devices"]:
        if not row.get("model") or not row.get("brand"):
            continue
        e = toh_entry(row)
        page = row["deviceid"].split(":")
        e["sources"] = [f"https://openwrt.org/toh/hwdata/{page[0]}/{page[-1]}"]
        e["origin"] = {f: "toh" for f in FACT_FIELDS if e.get(f) is not None}
        entries[key(e)] = e

    for name, source in (("manual.json", "manual"), ("verified.json", "verified")):
        doc = load(name) or {"devices": []}
        for patch in doc["devices"]:
            patch = dict(patch, vendor=vendor_name(patch["vendor"]), revisions=patch.get("revisions", []))
            k = key(patch)
            # Без ревизий запись говорит о модели целиком: ToH разносит ревизии по
            # отдельным записям, и факт, положенный рядом одной лишней записью,
            # не сойдётся с ними — сопоставление берёт поле, только если все
            # ревизии согласны.
            if k not in entries and not patch["revisions"]:
                same = [ek for ek in entries if ek[:2] == k[:2]]
                if same:
                    for ek in same:
                        entries[ek] = overlay(entries[ek], patch, source)
                    continue
            base = entries.get(k) or {
                "id": f"{source}:{patch['vendor'].lower()}:{patch['model'].lower()}".replace(" ", "-"),
                "vendor": patch["vendor"], "model": patch["model"], "aliases": [],
                "revisions": patch["revisions"], "type": patch.get("type", "router"),
                "origin": {}, "sources": [],
            }
            entries[k] = overlay(base, patch, source)

    devices = sorted(entries.values(), key=lambda e: (e["vendor"].lower(), e["model"].lower(), e["revisions"]))
    for e in devices:
        for field in FACT_FIELDS:
            if e.get(field) is None:
                e.pop(field, None)
                e["origin"].pop(field, None)
        if not e["aliases"]:
            e.pop("aliases")
        if not e["revisions"]:
            e.pop("revisions")

    previous = json.loads(OUT.read_text()) if OUT.exists() else {}
    catalog = {
        "schema": SCHEMA,
        "version": previous.get("version", 0) + 1,
        "updated": datetime.date.today().isoformat(),
        "license": "CC BY-SA 4.0",
        "attribution": [
            "OpenWrt Table of Hardware, https://openwrt.org/toh/start (CC BY-SA 4.0), снимок от " + toh["fetched"],
            "Страницы производителей — ссылка у каждой записи в sources",
        ],
        "devices": devices,
    }
    if previous and previous.get("devices") == devices:
        catalog["version"] = previous["version"]
        catalog["updated"] = previous["updated"]
    OUT.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"router-catalog.json: {len(devices)} устройств, version {catalog['version']}, "
          f"{OUT.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch-toh", action="store_true")
    args = parser.parse_args()
    if args.fetch_toh:
        fetch_toh()
    build()
