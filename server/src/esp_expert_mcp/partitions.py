"""Parser und Validator für ESP-IDF-Partitionstabellen (CSV).

Die Regeln folgen der ESP-IDF-Doku "Partition Tables" und dem Verhalten von
gen_esp32part.py: App-Partitionen 64-KB-ausgerichtet, Datenpartitionen 4 KB,
fehlende Offsets werden fortlaufend vergeben.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass, field

APP_ALIGN = 0x10000
DATA_ALIGN = 0x1000
PARTITION_TABLE_SIZE = 0x1000
DEFAULT_TABLE_OFFSET = 0x8000

# Offset des Second-Stage-Bootloaders je Target (ESP-IDF, CONFIG_BOOTLOADER_OFFSET_IN_FLASH).
BOOTLOADER_OFFSET = {
    "esp32": 0x1000,
    "esp32s2": 0x1000,
    "esp32s3": 0x0,
    "esp32c2": 0x0,
    "esp32c3": 0x0,
    "esp32c6": 0x0,
    "esp32h2": 0x0,
    "esp32c5": 0x2000,
    "esp32p4": 0x2000,
    "esp32c61": 0x0,
}

APP_SUBTYPES = {"factory", "test"} | {f"ota_{i}" for i in range(16)}
DATA_SUBTYPES = {
    "ota", "phy", "nvs", "coredump", "nvs_keys", "efuse", "undefined",
    "esphttpd", "fat", "spiffs", "littlefs", "tee_ota", "tee_sec_stg",
}
KNOWN_FLAGS = {"encrypted", "readonly"}


@dataclass
class Partition:
    name: str
    type: str
    subtype: str
    offset: int
    size: int
    flags: list[str] = field(default_factory=list)
    line: int = 0
    offset_auto: bool = False

    @property
    def end(self) -> int:
        return self.offset + self.size

    def as_dict(self) -> dict:
        d = asdict(self)
        d["offset"] = hex(self.offset)
        d["size"] = hex(self.size)
        d["size_kb"] = self.size // 1024
        d["end"] = hex(self.end)
        return d


def parse_size(text: str) -> int:
    t = text.strip().upper()
    m = re.fullmatch(r"(0X[0-9A-F]+|\d+)\s*([KM]?)", t)
    if not m:
        raise ValueError(f"Ungültiger Größen-/Offsetwert: {text!r}")
    num, unit = m.groups()
    value = int(num, 16) if num.startswith("0X") else int(num)
    return value * {"": 1, "K": 1024, "M": 1024 * 1024}[unit]


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _is_app(p: Partition) -> bool:
    return p.type == "app" or p.type == "0x00" or p.type == "0"


def validate(
    csv_text: str,
    flash_size: str | None = None,
    target: str | None = None,
    table_offset: str | None = None,
    app_bin_size: int | None = None,
) -> dict:
    """Parst die CSV, vergibt Auto-Offsets und prüft Layout-Regeln."""
    errors: list[str] = []
    warnings: list[str] = []
    info: list[str] = []

    tbl_off = parse_size(table_offset) if table_offset else DEFAULT_TABLE_OFFSET
    cursor = tbl_off + PARTITION_TABLE_SIZE
    parts: list[Partition] = []

    rows = []
    for lineno, raw in enumerate(csv_text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        rows.append((lineno, next(csv.reader(io.StringIO(line), skipinitialspace=True))))

    for lineno, cols in rows:
        cols = [c.strip() for c in cols] + [""] * (6 - len(cols))
        name, ptype, subtype, off_s, size_s, flags_s = cols[:6]
        if not name or not ptype or not size_s:
            errors.append(f"Zeile {lineno}: Name, Type und Size sind Pflicht.")
            continue
        ptype_l = ptype.lower()
        subtype_l = subtype.lower()
        try:
            size = parse_size(size_s)
        except ValueError as e:
            errors.append(f"Zeile {lineno}: {e}")
            continue

        is_app = ptype_l in ("app", "0x00", "0")
        align = APP_ALIGN if is_app else DATA_ALIGN
        auto = not off_s
        if auto:
            offset = _align(cursor, align)
        else:
            try:
                offset = parse_size(off_s)
            except ValueError as e:
                errors.append(f"Zeile {lineno}: {e}")
                continue
        flags = [f.strip().lower() for f in flags_s.split(":") if f.strip()] if flags_s else []
        p = Partition(name, ptype_l, subtype_l, offset, size, flags, lineno, auto)
        parts.append(p)
        cursor = p.end

        # --- Einzelprüfungen ---
        if len(name) > 16:
            errors.append(f"{name}: Name länger als 16 Zeichen.")
        if ptype_l == "app":
            if subtype_l not in APP_SUBTYPES:
                errors.append(f"{name}: unbekannter App-Subtype {subtype!r}.")
        elif ptype_l == "data":
            if subtype_l not in DATA_SUBTYPES and not subtype_l.startswith("0x"):
                warnings.append(f"{name}: unbekannter Data-Subtype {subtype!r} (nur zulässig als Hex-Wert oder bei neuerem ESP-IDF).")
        elif ptype_l.startswith("0x"):
            val = int(ptype_l, 16)
            if not 0x40 <= val <= 0xFE:
                warnings.append(f"{name}: benutzerdefinierter Type {ptype} liegt außerhalb 0x40–0xFE.")
        elif ptype_l in ("bootloader", "partition_table"):
            info.append(f"{name}: Type {ptype_l} erfordert ESP-IDF ≥ 5.3.")
        else:
            errors.append(f"{name}: unbekannter Type {ptype!r}.")

        if offset % align:
            errors.append(f"{name}: Offset {hex(offset)} ist nicht auf {hex(align)} ausgerichtet"
                          f" ({'App' if is_app else 'Data'}-Partition).")
        if is_app and size % APP_ALIGN:
            warnings.append(f"{name}: App-Größe {hex(size)} ist kein Vielfaches von 64 KB.")
        if not is_app and size % DATA_ALIGN:
            errors.append(f"{name}: Größe {hex(size)} ist kein Vielfaches von 4 KB.")
        if offset < tbl_off + PARTITION_TABLE_SIZE:
            errors.append(f"{name}: Offset {hex(offset)} überlappt Bootloader/Partitionstabelle"
                          f" (Tabelle bei {hex(tbl_off)}–{hex(tbl_off + PARTITION_TABLE_SIZE)}).")
        for f in flags:
            if f not in KNOWN_FLAGS:
                warnings.append(f"{name}: unbekanntes Flag {f!r}.")
        if subtype_l == "otadata" or (ptype_l == "data" and subtype_l == "ota"):
            if size != 0x2000:
                errors.append(f"{name}: otadata muss genau 0x2000 (8 KB) groß sein, ist {hex(size)}.")
        if ptype_l == "data" and subtype_l == "nvs" and size < 0x3000:
            errors.append(f"{name}: NVS-Partition kleiner als 0x3000 (12 KB) ist nicht nutzbar.")
        if ptype_l == "data" and subtype_l == "nvs_keys" and "encrypted" not in flags:
            warnings.append(f"{name}: nvs_keys sollte das Flag 'encrypted' tragen.")

    # --- Globale Prüfungen ---
    ordered = sorted(parts, key=lambda p: p.offset)
    for a, b in zip(ordered, ordered[1:]):
        if b.offset < a.end:
            errors.append(f"Überlappung: {a.name} ({hex(a.offset)}–{hex(a.end)}) und {b.name} ({hex(b.offset)}).")
    names = [p.name for p in parts]
    for n in {n for n in names if names.count(n) > 1}:
        errors.append(f"Name {n!r} ist doppelt vergeben.")

    apps = [p for p in parts if _is_app(p)]
    ota_slots = [p for p in apps if p.subtype.startswith("ota_")]
    has_otadata = any(p.type == "data" and p.subtype == "ota" for p in parts)
    if not apps:
        errors.append("Keine App-Partition vorhanden.")
    if ota_slots and not has_otadata:
        errors.append("OTA-Slots vorhanden, aber keine otadata-Partition (data, ota).")
    if has_otadata and len(ota_slots) < 2:
        warnings.append("otadata vorhanden, aber weniger als zwei OTA-Slots – OTA mit Rollback braucht ota_0 und ota_1.")
    if len({p.size for p in ota_slots}) > 1:
        warnings.append("OTA-Slots sind unterschiedlich groß – das kleinste Slot begrenzt jedes Update.")
    if not any(p.subtype == "nvs" for p in parts):
        warnings.append("Keine NVS-Partition – Wi-Fi/BLE und Preferences benötigen NVS.")
    if not any(p.subtype == "phy" for p in parts):
        info.append("Keine phy_init-Partition – nur relevant bei CONFIG_ESP_PHY_INIT_DATA_IN_PARTITION.")

    if target:
        t = target.lower().replace("-", "")
        bl = BOOTLOADER_OFFSET.get(t)
        if bl is None:
            info.append(f"Bootloader-Offset für Target {target!r} unbekannt – bitte in ESP-IDF-Doku prüfen.")
        else:
            space = tbl_off - bl
            if space <= 0:
                errors.append(f"Partitionstabelle ({hex(tbl_off)}) liegt vor/auf dem Bootloader-Offset {hex(bl)}.")
            info.append(f"Bootloader bei {hex(bl)}, Platz bis zur Tabelle: {space // 1024} KB.")
            if tbl_off == DEFAULT_TABLE_OFFSET:
                info.append("Tabellenoffset ist Standard (0x8000). Bei großem Bootloader (Secure Boot, Debug-Log) "
                            "CONFIG_PARTITION_TABLE_OFFSET erhöhen, z. B. auf 0x10000.")

    flash_bytes = None
    if flash_size:
        try:
            flash_bytes = parse_size(flash_size.replace("B", "").replace("b", ""))
        except ValueError as e:
            errors.append(str(e))
    if flash_bytes and parts:
        last_end = max(p.end for p in parts)
        if last_end > flash_bytes:
            errors.append(f"Partitionen enden bei {hex(last_end)} – größer als Flash ({flash_size}).")
        else:
            free = flash_bytes - last_end
            if free >= 0x40000:
                info.append(f"{free // 1024} KB am Flash-Ende ungenutzt – bewusst so gewollt? "
                            "Sonst App-Slots oder Datenpartition vergrößern.")

    if app_bin_size and apps:
        smallest = min(p.size for p in apps)
        headroom = smallest - app_bin_size
        pct = headroom / smallest * 100
        if headroom < 0:
            errors.append(f"App-Binary ({app_bin_size} B) passt nicht in die kleinste App-Partition ({smallest} B).")
        elif pct < 10:
            warnings.append(f"Nur {pct:.1f} % Reserve in der kleinsten App-Partition ({headroom // 1024} KB).")
        else:
            info.append(f"Reserve in der kleinsten App-Partition: {pct:.1f} % ({headroom // 1024} KB).")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "partition_table_offset": hex(tbl_off),
        "partitions": [p.as_dict() for p in parts],
    }
