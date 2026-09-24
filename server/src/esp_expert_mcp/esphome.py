"""ESPHome YAML: static lint (platform, pins, security, known breaking changes)
and – if installed – validation via `esphome config`."""

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
        add("error", f"No platform section found ({', '.join(PLATFORMS)}).")
    if "esphome" not in cfg:
        add("error", "Required section 'esphome:' (name) is missing.")

    if re.search(r"^packages:\s*!include", text, re.M):
        add("error", "Since ESPHome 2026.7, 'packages: !include x.yaml' must be written as a list: 'packages: [!include x.yaml]'.")
    if isinstance(cfg.get("esp32"), dict):
        e = cfg["esp32"]
        fw = (e.get("framework") or {}).get("type") if isinstance(e.get("framework"), dict) else None
        if fw is None:
            add("info", "No framework.type set – since 2026.1 ESPHome defaults to ESP-IDF (previously Arduino). "
                        "Arduino-only components (e.g. fastled_*, neopixelbus) then need a replacement or 'type: arduino'.")
        if e.get("toolchain") == "platformio":
            add("info", "toolchain: platformio – since 2026.7 the native ESP-IDF toolchain is the default.")
    for comp in ("fastled_clockless", "fastled_spi", "neopixelbus"):
        if re.search(rf"platform:\s*{comp}\b", text):
            add("warning", f"{comp} is Arduino-only – under ESP-IDF use esp32_rmt_led_strip or spi_led_strip.")

    wifi = cfg.get("wifi")
    if isinstance(wifi, dict):
        for k in ("ssid", "password"):
            v = wifi.get(k)
            if isinstance(v, str) and not (isinstance(v, _Tagged) and v.tag == "!secret"):
                add("warning", f"wifi.{k} is in plaintext – move it to secrets.yaml (!secret).")
        ap = wifi.get("ap")
        if ap is not None and not (isinstance(ap, dict) and ap.get("password")):
            add("warning", "Fallback AP without password – anyone in range can configure the device.")
    if "api" in cfg:
        api = cfg.get("api") or {}
        if not (isinstance(api, dict) and isinstance(api.get("encryption"), dict) and api["encryption"].get("key")):
            add("warning", "api without encryption.key – connection to Home Assistant is unencrypted.")
    ota = cfg.get("ota")
    if ota is None:
        add("info", "No 'ota:' – updates only possible via USB.")
    else:
        entries = ota if isinstance(ota, list) else [ota]
        esph = [o for o in entries if isinstance(o, dict) and o.get("platform", "esphome") == "esphome"]
        if any("encryption" in o for o in esph):
            pass  # from ESPHome 2026.9: encrypted; without its own key it uses the api key
        elif any(o.get("password") for o in esph):
            add("info", "OTA with password: from ESPHome 2026.9 'encryption:' is recommended instead of 'password' "
                        "(uses the api key, encrypts the image; both together are not allowed).")
        elif esph:
            add("warning", "OTA unsecured – anyone on the network can upload firmware. "
                           "Set 'encryption:' (from 2026.9) or at least 'password'.")
    if "web_server" in cfg:
        ws = cfg.get("web_server") or {}
        if isinstance(ws, dict) and ws.get("version") == 1:
            add("info", "web_server version 1 is deprecated (removal announced for 2027.1).")
        if not (isinstance(ws, dict) and ws.get("auth")):
            add("info", "web_server without auth.")
    logger = cfg.get("logger")
    if platform == "esp8266" and isinstance(logger, dict) and logger.get("baud_rate", 115200) != 0:
        uart = cfg.get("uart")
        if uart:
            add("warning", "ESP8266 with uart: and an active logger on UART0 – set 'logger: baud_rate: 0' or change hardware_uart.")

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
        add("info", f"Pin check not available for platform {platform or '?'}.")

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
    """Runs `esphome config <file>` (full schema validation incl. !secret/!include)."""
    cmd = None
    if exe := shutil.which("esphome"):
        cmd = [exe]
    elif use_uvx and (uvx := shutil.which("uvx")):
        cmd = [uvx, "esphome"]
    if not cmd:
        return {"available": False,
                "hint": "ESPHome CLI not found. Install: 'uv tool install esphome' or 'pipx install esphome' "
                        "(Python ≥ 3.12). Alternatively use_uvx=true (loads ESPHome temporarily)."}
    try:
        r = subprocess.run([*cmd, "config", os.path.basename(path)], cwd=os.path.dirname(os.path.abspath(path)),
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"available": True, "error": "Timeout during 'esphome config'."}
    out = (r.stdout + r.stderr)
    # Do not return secrets: ESPHome masks them in its output; additionally truncate password/key lines.
    out = re.sub(r"(?im)^(\s*(password|key|ssid|api_password|ota_password)\s*:).*$", r"\1 ***", out)
    return {"available": True, "ok": r.returncode == 0, "exit_code": r.returncode, "output": out[-12000:]}
