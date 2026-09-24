"""Evaluation of platformio.ini (espressif32/espressif8266, also pioarduino)."""

from __future__ import annotations

import configparser
import os
import re

BOARD_CHIP_HINTS = (("s31", "esp32s31"), ("s3", "esp32s3"), ("s2", "esp32s2"), ("c61", "esp32c61"), ("c6", "esp32c6"),
                    ("c5", "esp32c5"), ("c3", "esp32c3"), ("c2", "esp32c2"), ("h2", "esp32h2"), ("p4", "esp32p4"))


def _chip(platform: str, board: str) -> str | None:
    if "espressif8266" in platform:
        return "esp8266"
    if "espressif32" not in platform:
        return None
    b = board.lower()
    for key, chip in BOARD_CHIP_HINTS:
        if re.search(rf"(^|[-_]|esp32){key}([-_]|$)", b):
            return chip
    return "esp32 (check board definition: board_build.mcu)"


def _platform_source(platform: str) -> str:
    p = platform.strip()
    if "pioarduino" in p:
        return "pioarduino (community, Arduino core 3.x / current ESP-IDF)"
    if p.startswith(("http", "git", "file:")):
        return "URL/Git – version pinned via the URL"
    if re.search(r"@\s*[~^]?\d", p) or re.search(r"espressif(32|8266)@", p):
        return "PlatformIO registry, version pinned"
    return "PlatformIO registry, NOT pinned"


def _split(v: str) -> list[str]:
    return [x.strip() for x in re.split(r"[\n,]", v or "") if x.strip() and not x.strip().startswith(";")]


def analyze(ini_path: str) -> dict:
    root = os.path.dirname(os.path.abspath(ini_path))
    cp = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation(), inline_comment_prefixes=(";", "#"),
                                   strict=False)
    cp.optionxform = str
    try:
        cp.read(ini_path, encoding="utf-8")
    except configparser.Error as e:
        return {"error": f"platformio.ini not readable: {e}"}

    def val(sec: str, key: str, default: str = "") -> str:
        try:
            return cp.get(sec, key, fallback=None) or (cp.get("env", key, fallback=default) if cp.has_section("env") else default)
        except configparser.Error:
            return cp.get(sec, key, raw=True, fallback=default)

    default_envs = _split(cp.get("platformio", "default_envs", fallback=""))
    envs = []
    for sec in cp.sections():
        if not sec.startswith("env:"):
            continue
        name = sec[4:]
        platform, board, framework = val(sec, "platform"), val(sec, "board"), val(sec, "framework")
        findings = []

        def add(level: str, msg: str) -> None:
            findings.append({"level": level, "message": msg})

        src = _platform_source(platform)
        if "NOT pinned" in src:
            add("warning", "platform without version – builds are not reproducible (e.g. 'platform = espressif32@6.x.y' or a pioarduino release URL).")
        if "espressif32" in platform and "pioarduino" not in platform and "arduino" in framework:
            add("info", "The official platformio/espressif32 ships Arduino core 2.x. For core 3.x use the pioarduino platform "
                        "(current release via framework_versions('pioarduino-espressif32')).")
        libs = _split(val(sec, "lib_deps"))
        unpinned = [l for l in libs if "@" not in l and not l.startswith(("http", "git", "file:", "symlink:"))]
        if unpinned:
            add("warning", f"lib_deps without version: {unpinned} – pin with '@^x.y.z'.")
        filters = _split(val(sec, "monitor_filters"))
        if "espressif" in platform and not any("exception_decoder" in f for f in filters):
            add("info", "monitor_filters = esp32_exception_decoder (or esp8266_exception_decoder) decodes backtraces live.")
        partitions = val(sec, "board_build.partitions")
        part_path = None
        if partitions:
            cand = os.path.join(root, partitions)
            if os.path.isfile(cand):
                part_path = cand
            elif not partitions.endswith(".csv") or "/" not in partitions:
                add("info", f"Partition table {partitions!r} probably comes from the framework (not in the project).")
            else:
                add("error", f"board_build.partitions refers to missing file {partitions}.")
        build_dir = os.path.join(root, ".pio", "build", name)
        artifacts = {k: p for k, p in {
            "elf": os.path.join(build_dir, "firmware.elf"),
            "bin": os.path.join(build_dir, "firmware.bin"),
            "partitions_bin": os.path.join(build_dir, "partitions.bin"),
        }.items() if os.path.isfile(p)}
        if "espidf" in framework:
            sdk = os.path.join(root, f"sdkconfig.{name}")
            if os.path.isfile(sdk):
                artifacts["sdkconfig"] = sdk
        envs.append({
            "env": name,
            "default": name in default_envs if default_envs else None,
            "platform": platform, "platform_source": src,
            "board": board, "chip": _chip(platform, board), "framework": framework,
            "mcu_override": val(sec, "board_build.mcu") or None,
            "flash_size": val(sec, "board_upload.flash_size") or None,
            "flash_mode": val(sec, "board_build.flash_mode") or None,
            "psram_flags": [f for f in _split(val(sec, "build_flags")) if "PSRAM" in f.upper()] or None,
            "build_flags": _split(val(sec, "build_flags")),
            "partitions": partitions or None, "partitions_path": part_path,
            "upload_port": val(sec, "upload_port") or None, "upload_speed": val(sec, "upload_speed") or None,
            "monitor_speed": val(sec, "monitor_speed") or None,
            "lib_deps": libs,
            "artifacts": artifacts,
            "findings": findings,
        })
    if not envs:
        return {"error": "No [env:…] section found."}
    return {
        "project_dir": root,
        "default_envs": default_envs,
        "environments": envs,
        "commands": {
            "build": "pio run -e <env>", "upload": "pio run -e <env> -t upload", "monitor": "pio device monitor -e <env>",
            "clean": "pio run -e <env> -t clean", "menuconfig (ESP-IDF)": "pio run -e <env> -t menuconfig",
            "size": "pio run -e <env> -t size", "static-check": "pio check -e <env>",
        },
        "next": "partitions_path → partition_validate, artifacts.elf → serial_log_analyze, artifacts.sdkconfig → sdkconfig_analyze.",
    }
