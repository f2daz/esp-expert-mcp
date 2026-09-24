"""Chip-Stammdaten (data/chips.json, aus Espressif-Datenblättern/ESP-IDF-Doku) und Pin-Prüfung."""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources

ALIASES = {
    "esp32-s2": "esp32s2", "esp32-s3": "esp32s3", "esp32-c2": "esp32c2", "esp32-c3": "esp32c3",
    "esp32-c5": "esp32c5", "esp32-c6": "esp32c6", "esp32-h2": "esp32h2", "esp32-p4": "esp32p4",
    "esp8285": "esp8266", "esp-12f": "esp8266", "esp-12e": "esp8266", "esp01": "esp8266",
    "esp32-wroom-32": "esp32", "esp32-wrover": "esp32",
}

# Wemos D1 mini / NodeMCU v2 Pin-Beschriftungen → GPIO
ESP8266_BOARD_PINS = {"D0": 16, "D1": 5, "D2": 4, "D3": 0, "D4": 2, "D5": 14, "D6": 12, "D7": 13, "D8": 15,
                      "RX": 3, "TX": 1, "SD2": 9, "SD3": 10, "A0": 17}

OUTPUT_USAGES = {"output", "pwm", "ledc", "i2c", "sda", "scl", "spi", "mosi", "sclk", "clk", "cs", "tx",
                 "led", "relay", "rmt", "onewire", "dac", "i2s", "can", "twai"}


@cache
def load() -> dict:
    with resources.files(__package__).joinpath("data/chips.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def normalize_chip(chip: str) -> str:
    c = chip.strip().lower()
    c = ALIASES.get(c, c).replace("-", "").replace("_", "")
    return c


def chip_info(chip: str | None = None) -> dict:
    data = load()
    if not chip:
        return {"chips": {k: {"name": v.get("name"), "cpu": v.get("cpu"), "wireless": v.get("wireless")}
                          for k, v in data.items() if not k.startswith("_")},
                "meta": data.get("_meta")}
    c = normalize_chip(chip)
    if c not in data:
        return {"error": f"Unbekannter Chip {chip!r}. Bekannt: {[k for k in data if not k.startswith('_')]}"}
    return {c: data[c], "meta": data.get("_meta")}


def parse_pin(value, chip: str) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip().upper()
    if chip == "esp8266" and s in ESP8266_BOARD_PINS:
        return ESP8266_BOARD_PINS[s]
    m = re.fullmatch(r"(?:GPIO|IO|P)?(\d{1,2})", s)
    return int(m.group(1)) if m else None


def _as_ints(d: dict | list | None) -> set[int]:
    if not d:
        return set()
    if isinstance(d, dict):
        return {int(k) for k in d}
    return {int(x) for x in d}


def check_pins(chip: str, pins: list[dict], uses_wifi: bool = True, psram: str | None = None,
               native_usb: bool | None = None) -> dict:
    """pins: [{"gpio": 5 | "GPIO5" | "D1", "usage": "output|input|adc|i2c|…", "label": "…"}]"""
    c = normalize_chip(chip)
    data = load()
    if c not in data:
        return {"error": f"Unbekannter Chip {chip!r}."}
    info = data[c]
    lo, hi = info.get("gpio_range") or [0, 0]
    missing = set(info.get("gpio_missing") or [])
    strapping = {int(k): v for k, v in (info.get("strapping_pins") or {}).items()}
    flash = {int(k): v for k, v in (info.get("flash_psram_pins") or {}).items()}
    octal = {int(k): v for k, v in (info.get("conditional_pins") or {}).items()}
    input_only = _as_ints(info.get("input_only_pins"))
    usb = {int(k): v for k, v in (info.get("usb_pins") or {}).items()}
    jtag = {int(k): v for k, v in (info.get("jtag_pins") or {}).items()}
    uart0 = info.get("uart0_default") or {}
    adc = info.get("adc") or {}
    adc1 = _as_ints(adc.get("adc1"))
    adc2 = _as_ints(adc.get("adc2"))

    results, used = [], {}
    for entry in pins:
        raw = entry.get("gpio")
        usage = str(entry.get("usage", "")).lower()
        label = entry.get("label") or usage or "?"
        g = parse_pin(raw, c)
        issues: list[dict] = []

        def add(level: str, msg: str) -> None:
            issues.append({"level": level, "message": msg})

        if g is None:
            add("error", f"Pin {raw!r} nicht als GPIO lesbar (Port-Expander-Pins bitte separat prüfen).")
            results.append({"gpio": raw, "label": label, "issues": issues})
            continue
        if c == "esp8266" and g == 17:
            if usage not in ("adc", "analog", "input"):
                add("error", "A0/TOUT ist ausschließlich ADC-Eingang.")
            else:
                add("info", "A0/TOUT: Chip-Eingang 0–1,0 V; viele Boards haben einen Spannungsteiler auf 3,3 V – Board prüfen.")
        elif g < lo or g > hi or g in missing:
            add("error", f"GPIO{g} existiert auf {info.get('name', c)} nicht.")
        if g in flash:
            add("error", f"GPIO{g}: {flash[g]} – nicht verwenden.")
        if g in octal and _psram_blocks(c, psram):
            add("error", f"GPIO{g}: {octal[g]}")
        elif g in octal and not psram:
            add("warning", f"GPIO{g}: {octal[g]} – Modul prüfen (psram-Parameter angeben).")
        if g in strapping:
            add("warning", f"GPIO{g} ist Strapping-Pin: {strapping[g]}. Beschaltung darf den Pegel beim Reset nicht verfälschen.")
        if g in input_only and usage in OUTPUT_USAGES:
            add("error", f"GPIO{g} ist nur Eingang (kein Output, keine internen Pull-ups/-downs).")
        elif g in input_only:
            add("info", f"GPIO{g} ist nur Eingang und hat keine internen Pull-ups/-downs.")
        if g in usb and native_usb is not False:
            add("warning", f"GPIO{g} ist USB {usb[g]} – Belegung trennt die native USB-Konsole/Flash-Schnittstelle.")
        if g in jtag:
            add("info", f"GPIO{g} ist JTAG ({jtag[g]}) – bei JTAG-Debugging belegt.")
        if g in (uart0.get("tx"), uart0.get("rx")):
            add("warning", f"GPIO{g} ist UART0 ({'TX' if g == uart0.get('tx') else 'RX'}) – Boot-Log/Konsole/Flashen.")
        if usage in ("adc", "analog"):
            if adc1 or adc2:
                if g not in adc1 | adc2:
                    add("error", f"GPIO{g} ist kein ADC-Pin.")
                elif g in adc2 and adc.get("adc2_wifi_conflict") and uses_wifi:
                    add("error", f"GPIO{g} ist ADC2 – bei aktivem Wi-Fi nicht (zuverlässig) nutzbar. ADC1-Pin wählen.")
        if g in used:
            add("error", f"GPIO{g} ist doppelt belegt (auch: {used[g]}).")
        used[g] = label
        for note in (info.get("pin_notes") or {}).get(str(g), []):
            add("info", note)
        results.append({"gpio": g, "label": label, "usage": usage, "issues": issues})

    worst = "ok"
    for r in results:
        for i in r["issues"]:
            if i["level"] == "error":
                worst = "error"
            elif i["level"] == "warning" and worst != "error":
                worst = "warning"
    return {"chip": c, "status": worst, "pins": results,
            "sources": info.get("sources"),
            "note": "Modul-/Board-spezifische Belegungen (LEDs, Taster, Displays, PSRAM) zusätzlich im Board-Schaltplan prüfen."}


def _psram_blocks(chip: str, psram: str | None) -> bool:
    p = (psram or "").lower()
    if chip == "esp32s3":
        return p in ("octal", "opi", "oct")
    if chip == "esp32":
        return p in ("quad", "yes", "true", "psram", "octal")
    return p not in ("", "none", "no", "false")
