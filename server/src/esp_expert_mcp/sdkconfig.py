"""Evaluation of sdkconfig / sdkconfig.defaults (ESP-IDF, also Arduino-as-component, ESPHome IDF builds)."""

from __future__ import annotations

import os
import re

LINE_RE = re.compile(r"^(CONFIG_[A-Za-z0-9_]+)=(.*)$")
UNSET_RE = re.compile(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$")

KEY_SETTINGS = {
    "target": "CONFIG_IDF_TARGET",
    "idf_init_version": "CONFIG_IDF_INIT_VERSION",
    "flash_size": "CONFIG_ESPTOOLPY_FLASHSIZE",
    "flash_mode": "CONFIG_ESPTOOLPY_FLASHMODE",
    "flash_freq": "CONFIG_ESPTOOLPY_FLASHFREQ",
    "partition_csv": "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME",
    "partition_offset": "CONFIG_PARTITION_TABLE_OFFSET",
    "cpu_freq_mhz": "CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ",
    "freertos_hz": "CONFIG_FREERTOS_HZ",
    "main_task_stack": "CONFIG_ESP_MAIN_TASK_STACK_SIZE",
    "log_default_level": "CONFIG_LOG_DEFAULT_LEVEL",
    "log_maximum_level": "CONFIG_LOG_MAXIMUM_LEVEL",
    "bootloader_log_level": "CONFIG_BOOTLOADER_LOG_LEVEL",
    "compiler_opt_size": "CONFIG_COMPILER_OPTIMIZATION_SIZE",
    "compiler_opt_perf": "CONFIG_COMPILER_OPTIMIZATION_PERF",
    "compiler_opt_debug": "CONFIG_COMPILER_OPTIMIZATION_DEBUG",
    "psram": "CONFIG_SPIRAM",
    "psram_mode_oct": "CONFIG_SPIRAM_MODE_OCT",
    "task_wdt": "CONFIG_ESP_TASK_WDT_EN",
    "task_wdt_timeout_s": "CONFIG_ESP_TASK_WDT_TIMEOUT_S",
    "int_wdt": "CONFIG_ESP_INT_WDT",
    "brownout": "CONFIG_ESP_BROWNOUT_DET",
    "console_uart": "CONFIG_ESP_CONSOLE_UART_DEFAULT",
    "console_usb_serial_jtag": "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG",
    "console_usb_cdc": "CONFIG_ESP_CONSOLE_USB_CDC",
    "secure_boot": "CONFIG_SECURE_BOOT",
    "secure_boot_v2": "CONFIG_SECURE_BOOT_V2_ENABLED",
    "flash_encryption": "CONFIG_SECURE_FLASH_ENC_ENABLED",
    "flash_enc_dev_mode": "CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT",
    "flash_enc_release_mode": "CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE",
    "nvs_encryption": "CONFIG_NVS_ENCRYPTION",
    "app_rollback": "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE",
    "anti_rollback": "CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK",
    "coredump_flash": "CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH",
    "stack_check": "CONFIG_COMPILER_STACK_CHECK_MODE_NORM",
    "heap_poisoning_comprehensive": "CONFIG_HEAP_POISONING_COMPREHENSIVE",
    "freertos_watchpoint": "CONFIG_FREERTOS_WATCHPOINT_END_OF_STACK",
    "arduino_autostart": "CONFIG_AUTOSTART_ARDUINO",
}


def parse(text: str) -> dict[str, str | None]:
    """Returns {KEY: value}; 'is not set' is stored as None. Strings without quotes."""
    values: dict[str, str | None] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if m := LINE_RE.match(line):
            v = m.group(2)
            values[m.group(1)] = v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v
        elif m := UNSET_RE.match(line):
            values[m.group(1)] = None
    return values


def _on(cfg: dict, key: str) -> bool:
    return cfg.get(key) == "y"


def analyze(sdkconfig_path: str, defaults_path: str | None = None) -> dict:
    with open(sdkconfig_path, encoding="utf-8") as fh:
        cfg = parse(fh.read())
    summary = {name: cfg.get(key) for name, key in KEY_SETTINGS.items() if key in cfg}

    findings: list[dict] = []

    def add(level: str, msg: str) -> None:
        findings.append({"level": level, "message": msg})

    if _on(cfg, "CONFIG_SECURE_FLASH_ENC_ENABLED") and _on(cfg, "CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT"):
        add("warning", "Flash encryption in DEVELOPMENT mode – use RELEASE mode for production (eFuses are then burned permanently).")
    if _on(cfg, "CONFIG_SECURE_BOOT") and not _on(cfg, "CONFIG_SECURE_BOOT_V2_ENABLED"):
        add("warning", "Secure Boot enabled but not V2 – use V2 (RSA-PSS/ECDSA) if the target supports it.")
    if _on(cfg, "CONFIG_SECURE_FLASH_ENC_ENABLED") and not _on(cfg, "CONFIG_NVS_ENCRYPTION"):
        add("info", "Flash encryption without NVS encryption – NVS contents (e.g. Wi-Fi credentials) remain unencrypted.")
    if cfg.get("CONFIG_ESP_BROWNOUT_DET") is None and "CONFIG_ESP_BROWNOUT_DET" in cfg:
        add("warning", "Brownout detector disabled – hides supply problems instead of solving them.")
    if cfg.get("CONFIG_ESP_TASK_WDT_EN") is None and "CONFIG_ESP_TASK_WDT_EN" in cfg:
        add("warning", "Task watchdog disabled – hangs are no longer detected.")
    if _on(cfg, "CONFIG_COMPILER_OPTIMIZATION_DEBUG"):
        add("info", "Optimization -Og (debug): larger, slower binary – set to SIZE or PERF for release.")
    if cfg.get("CONFIG_LOG_DEFAULT_LEVEL") in ("4", "5"):
        add("info", "Default log level DEBUG/VERBOSE – costs flash and runtime; lower to INFO/WARN for release.")
    if _on(cfg, "CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH"):
        add("info", "Core dump to flash enabled – partition 'coredump' (data, coredump) must exist in the partition table.")
    if _on(cfg, "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE"):
        add("info", "App rollback enabled – new firmware must call esp_ota_mark_app_valid_cancel_rollback(), otherwise it rolls back after reset.")
    if _on(cfg, "CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK") and not _on(cfg, "CONFIG_SECURE_BOOT"):
        add("warning", "Anti-rollback without Secure Boot offers little protection.")
    try:
        hz = int(cfg.get("CONFIG_FREERTOS_HZ") or 0)
        if hz and hz != 1000 and hz != 100:
            add("info", f"FreeRTOS tick {hz} Hz – pdMS_TO_TICKS rounds; check short delays.")
        if hz == 100:
            add("info", "FreeRTOS tick 100 Hz: vTaskDelay(pdMS_TO_TICKS(x)) with x < 10 yields 0 ticks.")
    except ValueError:
        pass
    try:
        stack = int(cfg.get("CONFIG_ESP_MAIN_TASK_STACK_SIZE") or 0)
        if stack and stack < 3584:
            add("warning", f"Main task stack only {stack} B – quickly too small with logging/printf/JSON.")
    except ValueError:
        pass
    if cfg.get("CONFIG_PARTITION_TABLE_CUSTOM") == "y":
        add("info", f"Custom partition table: {cfg.get('CONFIG_PARTITION_TABLE_CUSTOM_FILENAME')} – check with partition_validate.")

    csv_path = None
    if cfg.get("CONFIG_PARTITION_TABLE_CUSTOM") == "y" and cfg.get("CONFIG_PARTITION_TABLE_CUSTOM_FILENAME"):
        cand = os.path.join(os.path.dirname(os.path.abspath(sdkconfig_path)), cfg["CONFIG_PARTITION_TABLE_CUSTOM_FILENAME"])
        if os.path.isfile(cand):
            csv_path = cand

    drift = []
    if defaults_path is None:
        cand = os.path.join(os.path.dirname(os.path.abspath(sdkconfig_path)), "sdkconfig.defaults")
        defaults_path = cand if os.path.isfile(cand) else None
    if defaults_path:
        with open(defaults_path, encoding="utf-8") as fh:
            defaults = parse(fh.read())
        for k, v in defaults.items():
            if k in cfg and cfg[k] != v:
                drift.append({"key": k, "defaults": v, "sdkconfig": cfg[k]})
            elif k not in cfg:
                drift.append({"key": k, "defaults": v, "sdkconfig": "(missing – option may not exist for this target/IDF version)"})
    return {
        "summary": summary,
        "findings": findings,
        "partition_csv_path": csv_path,
        "defaults_file": defaults_path,
        "defaults_drift": drift,
        "hint": "Reproducible changes belong in sdkconfig.defaults (or sdkconfig.defaults.<target>); sdkconfig is generated.",
    }


def get(sdkconfig_path: str, keys: list[str]) -> dict:
    with open(sdkconfig_path, encoding="utf-8") as fh:
        cfg = parse(fh.read())
    out = {}
    for k in keys:
        key = k if k.startswith("CONFIG_") else f"CONFIG_{k}"
        if key in cfg:
            out[key] = cfg[key]
        else:
            matches = dict(list({ck: cv for ck, cv in cfg.items() if key[7:].upper() in ck}.items())[:30])
            out[key] = matches if matches else "(not present)"
    return out
