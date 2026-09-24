"""esp_err_t-Lookup.

Quelle ist die Tabelle esp_err_to_name.c aus ESP-IDF – bevorzugt aus der lokalen
Installation ($IDF_PATH, damit sie zur genutzten Version passt), sonst aus dem
GitHub-Repo (master). Ein kleiner Offline-Fallback deckt die häufigsten Codes ab.
"""

from __future__ import annotations

import os
import re
import urllib.request

# Ab master (v6.1+) wird die Tabelle zur Link-Zeit erzeugt; release/v6.0 enthält sie noch als Quelltext.
REMOTE = "https://raw.githubusercontent.com/espressif/esp-idf/release/v6.0/components/esp_common/src/esp_err_to_name.c"
LOCAL_REL = "components/esp_common/src/esp_err_to_name.c"

FALLBACK = {
    -1: "ESP_FAIL", 0: "ESP_OK",
    0x101: "ESP_ERR_NO_MEM", 0x102: "ESP_ERR_INVALID_ARG", 0x103: "ESP_ERR_INVALID_STATE",
    0x104: "ESP_ERR_INVALID_SIZE", 0x105: "ESP_ERR_NOT_FOUND", 0x106: "ESP_ERR_NOT_SUPPORTED",
    0x107: "ESP_ERR_TIMEOUT", 0x108: "ESP_ERR_INVALID_RESPONSE", 0x109: "ESP_ERR_INVALID_CRC",
    0x10A: "ESP_ERR_INVALID_VERSION", 0x10B: "ESP_ERR_INVALID_MAC", 0x10C: "ESP_ERR_NOT_FINISHED",
    0x1101: "ESP_ERR_NVS_NOT_INITIALIZED", 0x1102: "ESP_ERR_NVS_NOT_FOUND",
    0x1105: "ESP_ERR_NVS_NOT_ENOUGH_SPACE", 0x110D: "ESP_ERR_NVS_NO_FREE_PAGES",
    0x1110: "ESP_ERR_NVS_NEW_VERSION_FOUND",
    0x3001: "ESP_ERR_WIFI_NOT_INIT", 0x3002: "ESP_ERR_WIFI_NOT_STARTED",
}

HINTS = {
    "ESP_ERR_NVS_NO_FREE_PAGES": "NVS-Partition voll oder Layout geändert: nvs_flash_erase() und erneut nvs_flash_init() (Standardmuster in IDF-Beispielen).",
    "ESP_ERR_NVS_NEW_VERSION_FOUND": "NVS mit neuerem Format beschrieben: nvs_flash_erase() + nvs_flash_init().",
    "ESP_ERR_NVS_NOT_INITIALIZED": "nvs_flash_init() fehlt oder schlug fehl – vor Wi-Fi/BLE aufrufen.",
    "ESP_ERR_NO_MEM": "Heap erschöpft oder fragmentiert – heap_caps_get_largest_free_block() prüfen.",
    "ESP_ERR_INVALID_STATE": "Treiber/Stack im falschen Zustand (doppelt initialisiert, nicht gestartet, falsche Reihenfolge).",
    "ESP_ERR_TIMEOUT": "Gerät antwortet nicht – Verdrahtung, Pull-ups, Takt, Adresse, Timeout-Wert prüfen.",
    "ESP_ERR_WIFI_NOT_INIT": "esp_wifi_init() fehlt.",
    "ESP_ERR_WIFI_NOT_STARTED": "esp_wifi_start() fehlt oder wurde noch nicht abgeschlossen.",
}

_cache: dict[int, str] | None = None
_desc: dict[str, str] = {}
_source: str | None = None


def _parse(text: str) -> dict[int, str]:
    table = {}
    # ERR_TBL_IT(ESP_ERR_NO_MEM),  /* 257 0x101 Out of memory */
    for m in re.finditer(r"ERR_TBL_IT\((\w+)\),\s*/\*\s*(-?\d+)\s+(?:-?0x[0-9a-fA-F]+\s+)?(.*?)\s*\*/", text, re.S):
        table[int(m.group(2))] = m.group(1)
        _desc[m.group(1)] = " ".join(m.group(3).split())
    return table


def _load() -> tuple[dict[int, str], str]:
    global _cache, _source
    if _cache is not None:
        return _cache, _source or ""
    idf = os.environ.get("IDF_PATH")
    if idf and os.path.isfile(os.path.join(idf, LOCAL_REL)):
        with open(os.path.join(idf, LOCAL_REL), encoding="utf-8") as fh:
            _cache, _source = _parse(fh.read()), f"lokal: {idf}"
    else:
        try:
            with urllib.request.urlopen(REMOTE, timeout=10) as r:
                _cache, _source = _parse(r.read().decode()), "GitHub espressif/esp-idf@release/v6.0"
        except OSError:
            _cache, _source = {}, ""
    if not _cache:
        _cache, _source = dict(FALLBACK), "Offline-Fallback (Auswahl)"
    return _cache, _source


def lookup(code: str | int) -> dict:
    table, source = _load()
    if isinstance(code, str):
        c = code.strip()
        if not re.fullmatch(r"-?(0x[0-9a-fA-F]+|\d+)", c):
            name = c.upper()
            hits = {v: k for k, v in table.items() if name in v}
            return {"query": code, "matches": {k: hex(v) for k, v in hits.items()}, "source": source}
        value = int(c, 16) if "x" in c.lower() else int(c)
    else:
        value = code
    name = table.get(value)
    res = {"code": value, "hex": hex(value), "name": name, "description": _desc.get(name or ""), "source": source}
    if name is None:
        res["note"] = "Code nicht in der Tabelle – ggf. komponentenspezifisch (mbedTLS, lwIP errno) oder negativer HTTP-/TLS-Fehler."
    elif name in HINTS:
        res["hint"] = HINTS[name]
    return res
