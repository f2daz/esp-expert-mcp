"""Detect serial ports and identify them (read-only) via esptool."""

from __future__ import annotations

import re
import shutil
import subprocess

from serial.tools import list_ports

# VID:PID → bridge chip. Only confirmed mappings; everything else is reported as "unknown".
USB_BRIDGES = {
    (0x10C4, 0xEA60): "Silicon Labs CP210x",
    (0x1A86, 0x7523): "WCH CH340/CH341",
    (0x1A86, 0x55D4): "WCH CH9102",
    (0x0403, 0x6001): "FTDI FT232R",
    (0x0403, 0x6010): "FTDI FT2232 (e.g. ESP-Prog: channel A = JTAG, channel B = UART)",
    (0x0403, 0x6015): "FTDI FT231X",
    (0x067B, 0x2303): "Prolific PL2303",
    (0x303A, 0x1001): "Espressif USB-Serial/JTAG (native USB of ESP32-C3/C6/H2/S3/…)",
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
                bridge = f"Espressif native USB (PID {p.pid:04X}) – e.g. TinyUSB CDC or ROM download mode"
            entry["bridge"] = bridge or "unknown"
            entry["likely_esp"] = bridge is not None
        ports.append(entry)
    # macOS lists every device as /dev/tty.* and /dev/cu.* – cu.* is correct for esptool/monitor.
    notes = []
    if any(p["device"].startswith("/dev/tty.") for p in ports):
        notes.append("macOS: use /dev/cu.* instead of /dev/tty.* for esptool/monitor.")
    if not any(p.get("likely_esp") for p in ports):
        notes.append("No known ESP USB bridge found. Data cable (not a charge-only cable)? Driver (CH340/CP210x) installed? "
                     "Linux: user in group dialout/uucp?")
    return {"ports": [p for p in ports if not p["device"].startswith("/dev/tty.")] or ports, "notes": notes}


def _esptool_cmd() -> list[str] | None:
    for name in ("esptool", "esptool.py"):
        if path := shutil.which(name):
            return [path]
    return None


def probe(port: str, baud: int = 115200) -> dict:
    """Reads chip type, revision, features, MAC and flash size. Writes nothing, but resets the chip."""
    cmd = _esptool_cmd()
    if not cmd:
        return {"error": "esptool not found. Install: 'pipx install esptool' or 'uv tool install esptool'."}
    out = {}
    for sub in (("flash-id", "flash_id"),):
        text = ""
        for variant in sub:
            try:
                r = subprocess.run([*cmd, "--port", port, "--baud", str(baud), variant],
                                   capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired:
                return {"error": "Timeout – is the board in download mode? (hold BOOT, briefly press EN)"}
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
        out["hint"] = ("No connection: force download mode manually (hold BOOT/IO0, briefly press EN/RST), "
                       "try another cable/port, close the monitor, --baud 115200. With native USB, look for a new port after reset.")
    if "Permission denied" in t or "could not open port" in t:
        out["hint"] = "Port busy (monitor open?) or missing permissions (Linux: dialout group)."
    out["note"] = "The chip was reset for the query; nothing was written."
    return out
