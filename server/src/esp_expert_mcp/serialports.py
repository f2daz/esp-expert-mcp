"""Serielle Ports erkennen und (nur lesend) per esptool identifizieren."""

from __future__ import annotations

import re
import shutil
import subprocess

from serial.tools import list_ports

# VID:PID → Bridge-Chip. Nur gesicherte Zuordnungen; Rest wird als "unbekannt" gemeldet.
USB_BRIDGES = {
    (0x10C4, 0xEA60): "Silicon Labs CP210x",
    (0x1A86, 0x7523): "WCH CH340/CH341",
    (0x1A86, 0x55D4): "WCH CH9102",
    (0x0403, 0x6001): "FTDI FT232R",
    (0x0403, 0x6010): "FTDI FT2232 (z. B. ESP-Prog: Kanal A = JTAG, Kanal B = UART)",
    (0x0403, 0x6015): "FTDI FT231X",
    (0x067B, 0x2303): "Prolific PL2303",
    (0x303A, 0x1001): "Espressif USB-Serial/JTAG (native USB von ESP32-C3/C6/H2/S3/…)",
}
ESPRESSIF_VID = 0x303A


def list_serial() -> dict:
    ports = []
    for p in list_ports.comports():
        entry = {
            "device": p.device,
            "description": p.description,
            "manufacturer": p.manufacturer,
            "serial_number": p.serial_number,
            "vid_pid": f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else None,
        }
        if p.vid is not None:
            bridge = USB_BRIDGES.get((p.vid, p.pid))
            if not bridge and p.vid == ESPRESSIF_VID:
                bridge = f"Espressif native USB (PID {p.pid:04X}) – z. B. TinyUSB-CDC oder ROM-Download-Modus"
            entry["bridge"] = bridge or "unbekannt"
            entry["likely_esp"] = bridge is not None
        ports.append(entry)
    # macOS listet jedes Gerät als /dev/tty.* und /dev/cu.* – cu.* ist für esptool/Monitor richtig.
    notes = []
    if any(p["device"].startswith("/dev/tty.") for p in ports):
        notes.append("macOS: für esptool/Monitor /dev/cu.* statt /dev/tty.* verwenden.")
    if not any(p.get("likely_esp") for p in ports):
        notes.append("Kein bekannter ESP-USB-Bridge gefunden. Datenkabel (nicht nur Ladekabel)? Treiber (CH340/CP210x) installiert? "
                     "Linux: Benutzer in Gruppe dialout/uucp.")
    return {"ports": [p for p in ports if not p["device"].startswith("/dev/tty.")] or ports, "notes": notes}


def _esptool_cmd() -> list[str] | None:
    for name in ("esptool", "esptool.py"):
        if path := shutil.which(name):
            return [path]
    return None


def probe(port: str, baud: int = 115200) -> dict:
    """Liest Chip-Typ, Revision, Features, MAC und Flash-Größe. Schreibt nichts, setzt den Chip aber zurück."""
    cmd = _esptool_cmd()
    if not cmd:
        return {"error": "esptool nicht gefunden. Installieren: 'pipx install esptool' oder 'uv tool install esptool'."}
    out = {}
    for sub in (("flash-id", "flash_id"),):
        text = ""
        for variant in sub:
            try:
                r = subprocess.run([*cmd, "--port", port, "--baud", str(baud), variant],
                                   capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired:
                return {"error": "Zeitüberschreitung – Board im Download-Modus? (BOOT halten, EN kurz drücken)"}
            text = r.stdout + r.stderr
            if "invalid choice" not in text and "No such command" not in text:
                break
        out["raw"] = text[-4000:]
    t = out["raw"]
    for key, rx in {
        "esptool_version": r"esptool(?:\.py)? v?([\d.]+\w*)",
        "chip": r"Chip is ([^\n]+)|Chip type:\s*([^\n]+)",
        "features": r"Features:\s*([^\n]+)",
        "crystal": r"Crystal is ([^\n]+)|Crystal frequency:\s*([^\n]+)",
        "mac": r"MAC:\s*([0-9a-fA-F:]{17})",
        "flash_size": r"Detected flash size:\s*(\S+)",
        "flash_manufacturer": r"Manufacturer:\s*(\S+)",
        "flash_device": r"Device:\s*(\S+)",
        "psram": r"Embedded PSRAM[^\n]*|(\d+MB) PSRAM",
    }.items():
        m = re.search(rx, t)
        if m:
            out[key] = next((g for g in m.groups() if g), m.group(0)).strip()
    if "Failed to connect" in t or "Timed out waiting for packet header" in t:
        out["hint"] = ("Keine Verbindung: Download-Modus manuell erzwingen (BOOT/IO0 halten, EN/RST kurz drücken), "
                       "anderes Kabel/Port, Monitor schließen, --baud 115200. Bei native USB nach Reset neuen Port suchen.")
    if "Permission denied" in t or "could not open port" in t:
        out["hint"] = "Port belegt (Monitor offen?) oder fehlende Rechte (Linux: dialout-Gruppe)."
    out["note"] = "Der Chip wurde für die Abfrage zurückgesetzt; es wurde nichts geschrieben."
    return out
