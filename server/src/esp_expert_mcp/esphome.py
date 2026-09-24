"""ESPHome-YAML: statischer Lint (Plattform, Pins, Sicherheit, bekannte Breaking Changes)
und – falls installiert – Validierung per `esphome config`."""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import yaml

from . import chips

PLATFORMS = ("esp32", "esp8266", "rp2040", "bk72xx", "rtl87xx", "ln882x", "libretiny", "nrf52", "host")
PIN_KEY_RE = re.compile(r"^(pin|.*_pin|sda|scl|pin_a|pin_b|pins)$")
EXPANDER_KEYS = {"pcf8574", "mcp23xxx", "mcp23017", "mcp23008", "mcp23s17", "sx1509", "pca9554", "pca6416a",
                 "xl9535", "tca9555", "sn74hc595", "sn74hc165", "ch422g", "pi4ioe5v6408"}


class _Tagged(str):
    tag = ""


class _Loader(yaml.SafeLoader):
    pass


def _any_tag(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        v = _Tagged(loader.construct_scalar(node))
    elif isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    else:
        return loader.construct_mapping(node, deep=True)
    v.tag = "!" + tag_suffix
    return v


_Loader.add_multi_constructor("!", _any_tag)


def _variant(cfg: dict) -> str | None:
    if "esp8266" in cfg:
        return "esp8266"
    e = cfg.get("esp32")
    if not isinstance(e, dict):
        return None
    if v := e.get("variant"):
        return chips.normalize_chip(str(v))
    board = str(e.get("board", "")).lower()
    for key in ("s31", "s3", "s2", "c61", "c6", "c5", "c3", "c2", "h2", "p4"):
        if f"-{key}" in board or f"{key}-" in board or board.startswith(f"esp32{key}"):
            return f"esp32{key}"
    return "esp32"


def _walk_pins(node, path: str, out: list, in_expander: bool = False):
    if isinstance(node, dict):
        expander = in_expander or any(k in EXPANDER_KEYS for k in node)
        for k, v in node.items():
            p = f"{path}.{k}" if path else str(k)
            if PIN_KEY_RE.match(str(k)) and not expander:
                if isinstance(v, dict):
                    if not any(ek in v for ek in EXPANDER_KEYS) and "number" in v:
                        mode = v.get("mode")
                        mode_s = " ".join(mode) if isinstance(mode, list) else (
                            " ".join(kk for kk, vv in mode.items() if vv) if isinstance(mode, dict) else str(mode or ""))
                        out.append({"gpio": v["number"], "path": p, "mode": mode_s})
                elif isinstance(v, list):
                    for i, item in enumerate(v):
                        if isinstance(item, (int, str)):
                            out.append({"gpio": item, "path": f"{p}[{i}]", "mode": ""})
                elif isinstance(v, (int, str)):
                    out.append({"gpio": v, "path": p, "mode": ""})
            else:
                _walk_pins(v, p, out, expander)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk_pins(item, f"{path}[{i}]", out, in_expander)


def _usage(path: str, mode: str) -> str:
    pl, ml = path.lower(), mode.lower()
    if "output" in ml:
        return "output"
    if "input" in ml:
        return "input"
    if re.search(r"(^|\.)sensor\[\d+\]\.pin$", pl) or "adc" in pl:
        return "adc"
    if re.search(r"binary_sensor\[\d+\]\.pin", pl):
        return "input"
    if re.search(r"(switch|output|light)\[\d+\]\.pin", pl) or any(t in pl for t in ("tx_pin", "sda", "scl", "clk", "mosi", "cs_pin", "dc_pin", "reset_pin")):
        return "output"
    return ""


def lint(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    findings: list[dict] = []

    def add(level: str, msg: str) -> None:
        findings.append({"level": level, "message": msg})

    try:
        cfg = yaml.load(text, Loader=_Loader) or {}
    except yaml.YAMLError as e:
        return {"valid_yaml": False, "error": str(e)}

    platform = next((p for p in PLATFORMS if p in cfg), None)
    variant = _variant(cfg)
    if not platform:
        add("error", f"Keine Plattform-Sektion gefunden ({', '.join(PLATFORMS)}).")
    if "esphome" not in cfg:
        add("error", "Pflichtsektion 'esphome:' (name) fehlt.")

    if re.search(r"^packages:\s*!include", text, re.M):
        add("error", "Seit ESPHome 2026.7 muss 'packages: !include x.yaml' als Liste geschrieben werden: 'packages: [!include x.yaml]'.")
    if isinstance(cfg.get("esp32"), dict):
        e = cfg["esp32"]
        fw = (e.get("framework") or {}).get("type") if isinstance(e.get("framework"), dict) else None
        if fw is None:
            add("info", "Kein framework.type gesetzt – ESPHome nutzt seit 2026.1 ESP-IDF als Standard (vorher Arduino). "
                        "Arduino-only-Komponenten (z. B. fastled_*, neopixelbus) brauchen dann Ersatz oder 'type: arduino'.")
        if e.get("toolchain") == "platformio":
            add("info", "toolchain: platformio – seit 2026.7 ist die native ESP-IDF-Toolchain Standard.")
    for comp in ("fastled_clockless", "fastled_spi", "neopixelbus"):
        if re.search(rf"platform:\s*{comp}\b", text):
            add("warning", f"{comp} ist Arduino-only – unter ESP-IDF esp32_rmt_led_strip bzw. spi_led_strip verwenden.")

    wifi = cfg.get("wifi")
    if isinstance(wifi, dict):
        for k in ("ssid", "password"):
            v = wifi.get(k)
            if isinstance(v, str) and not (isinstance(v, _Tagged) and v.tag == "!secret"):
                add("warning", f"wifi.{k} steht im Klartext – in secrets.yaml auslagern (!secret).")
        ap = wifi.get("ap")
        if ap is not None and not (isinstance(ap, dict) and ap.get("password")):
            add("warning", "Fallback-AP ohne Passwort – jeder in Reichweite kann das Gerät konfigurieren.")
    if "api" in cfg:
        api = cfg.get("api") or {}
        if not (isinstance(api, dict) and isinstance(api.get("encryption"), dict) and api["encryption"].get("key")):
            add("warning", "api ohne encryption.key – Verbindung zu Home Assistant unverschlüsselt.")
    ota = cfg.get("ota")
    if ota is None:
        add("info", "Kein 'ota:' – Updates nur per USB möglich.")
    else:
        entries = ota if isinstance(ota, list) else [ota]
        esph = [o for o in entries if isinstance(o, dict) and o.get("platform", "esphome") == "esphome"]
        if any("encryption" in o for o in esph):
            pass  # ab ESPHome 2026.9: verschlüsselt, nutzt ohne eigenen key den api-Schlüssel
        elif any(o.get("password") for o in esph):
            add("info", "OTA mit Passwort: ab ESPHome 2026.9 empfohlen 'encryption:' statt 'password' "
                        "(nutzt den api-Schlüssel, verschlüsselt das Image; beides zusammen nicht zulässig).")
        elif esph:
            add("warning", "OTA ohne Absicherung – jeder im Netz kann Firmware aufspielen. "
                           "'encryption:' (ab 2026.9) oder mindestens 'password' setzen.")
    if "web_server" in cfg:
        ws = cfg.get("web_server") or {}
        if isinstance(ws, dict) and ws.get("version") == 1:
            add("info", "web_server version 1 ist abgekündigt (Entfernung für 2027.1 angekündigt).")
        if not (isinstance(ws, dict) and ws.get("auth")):
            add("info", "web_server ohne auth.")
    logger = cfg.get("logger")
    if platform == "esp8266" and isinstance(logger, dict) and logger.get("baud_rate", 115200) != 0:
        uart = cfg.get("uart")
        if uart:
            add("warning", "ESP8266 mit uart: und aktivem Logger auf UART0 – 'logger: baud_rate: 0' setzen oder hardware_uart umstellen.")

    pins: list[dict] = []
    _walk_pins(cfg, "", pins)
    pin_report = None
    if variant and pins and variant in chips.load():
        pin_report = chips.check_pins(
            variant,
            [{"gpio": p["gpio"], "usage": _usage(p["path"], p["mode"]), "label": p["path"]} for p in pins],
            uses_wifi="wifi" in cfg,
        )
    elif pins:
        add("info", f"Pin-Prüfung für Plattform {platform or '?'} nicht verfügbar.")

    return {
        "valid_yaml": True,
        "platform": platform,
        "variant": variant,
        "board": (cfg.get(platform) or {}).get("board") if platform and isinstance(cfg.get(platform), dict) else None,
        "findings": findings,
        "pins_found": len(pins),
        "pin_check": pin_report,
    }


def validate(path: str, use_uvx: bool = False) -> dict:
    """Führt `esphome config <datei>` aus (volle Schema-Validierung inkl. !secret/!include)."""
    cmd = None
    if exe := shutil.which("esphome"):
        cmd = [exe]
    elif use_uvx and (uvx := shutil.which("uvx")):
        cmd = [uvx, "esphome"]
    if not cmd:
        return {"available": False,
                "hint": "ESPHome-CLI nicht gefunden. Installation: 'uv tool install esphome' oder 'pipx install esphome' "
                        "(Python ≥ 3.12). Alternativ use_uvx=true (lädt ESPHome temporär)."}
    try:
        r = subprocess.run([*cmd, "config", os.path.basename(path)], cwd=os.path.dirname(os.path.abspath(path)),
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"available": True, "error": "Zeitüberschreitung bei 'esphome config'."}
    out = (r.stdout + r.stderr)
    # Secrets nicht zurückgeben: ESPHome maskiert sie in der Ausgabe, zusätzlich Passwort-/Key-Zeilen kappen.
    out = re.sub(r"(?im)^(\s*(password|key|ssid|api_password|ota_password)\s*:).*$", r"\1 ***", out)
    return {"available": True, "ok": r.returncode == 0, "exit_code": r.returncode, "output": out[-12000:]}
