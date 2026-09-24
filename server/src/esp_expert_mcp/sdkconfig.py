"""Auswertung von sdkconfig / sdkconfig.defaults (ESP-IDF, auch Arduino-as-component, ESPHome-IDF-Builds)."""

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
    """Gibt {KEY: wert} zurück; 'is not set' wird als None abgelegt. Strings ohne Anführungszeichen."""
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
        add("warning", "Flash-Encryption im DEVELOPMENT-Modus – für Serie RELEASE-Modus nutzen (eFuses werden dann endgültig gebrannt).")
    if _on(cfg, "CONFIG_SECURE_BOOT") and not _on(cfg, "CONFIG_SECURE_BOOT_V2_ENABLED"):
        add("warning", "Secure Boot aktiv, aber nicht V2 – V2 (RSA-PSS/ECDSA) verwenden, sofern das Target es unterstützt.")
    if _on(cfg, "CONFIG_SECURE_FLASH_ENC_ENABLED") and not _on(cfg, "CONFIG_NVS_ENCRYPTION"):
        add("info", "Flash-Encryption ohne NVS-Encryption – NVS-Inhalte (z. B. Wi-Fi-Credentials) liegen sonst unverschlüsselt.")
    if cfg.get("CONFIG_ESP_BROWNOUT_DET") is None and "CONFIG_ESP_BROWNOUT_DET" in cfg:
        add("warning", "Brownout-Detektor deaktiviert – verdeckt Versorgungsprobleme statt sie zu lösen.")
    if cfg.get("CONFIG_ESP_TASK_WDT_EN") is None and "CONFIG_ESP_TASK_WDT_EN" in cfg:
        add("warning", "Task-Watchdog deaktiviert – Hänger werden nicht mehr erkannt.")
    if _on(cfg, "CONFIG_COMPILER_OPTIMIZATION_DEBUG"):
        add("info", "Optimierung -Og (Debug): größeres, langsameres Binary – für Release auf SIZE oder PERF stellen.")
    if cfg.get("CONFIG_LOG_DEFAULT_LEVEL") in ("4", "5"):
        add("info", "Default-Loglevel DEBUG/VERBOSE – kostet Flash und Laufzeit; für Release auf INFO/WARN senken.")
    if _on(cfg, "CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH"):
        add("info", "Core-Dump in Flash aktiv – Partition 'coredump' (data, coredump) muss in der Partitionstabelle existieren.")
    if _on(cfg, "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE"):
        add("info", "App-Rollback aktiv – neue Firmware muss esp_ota_mark_app_valid_cancel_rollback() aufrufen, sonst Rückfall nach Reset.")
    if _on(cfg, "CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK") and not _on(cfg, "CONFIG_SECURE_BOOT"):
        add("warning", "Anti-Rollback ohne Secure Boot bietet kaum Schutz.")
    try:
        hz = int(cfg.get("CONFIG_FREERTOS_HZ") or 0)
        if hz and hz != 1000 and hz != 100:
            add("info", f"FreeRTOS-Tick {hz} Hz – pdMS_TO_TICKS rundet; kurze Delays prüfen.")
        if hz == 100:
            add("info", "FreeRTOS-Tick 100 Hz: vTaskDelay(pdMS_TO_TICKS(x)) mit x < 10 ergibt 0 Ticks.")
    except ValueError:
        pass
    try:
        stack = int(cfg.get("CONFIG_ESP_MAIN_TASK_STACK_SIZE") or 0)
        if stack and stack < 3584:
            add("warning", f"Main-Task-Stack nur {stack} B – bei Logging/printf/JSON schnell zu knapp.")
    except ValueError:
        pass
    if cfg.get("CONFIG_PARTITION_TABLE_CUSTOM") == "y":
        add("info", f"Eigene Partitionstabelle: {cfg.get('CONFIG_PARTITION_TABLE_CUSTOM_FILENAME')} – mit partition_validate prüfen.")

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
                drift.append({"key": k, "defaults": v, "sdkconfig": "(fehlt – Option existiert evtl. nicht für dieses Target/diese IDF-Version)"})
    return {
        "summary": summary,
        "findings": findings,
        "partition_csv_path": csv_path,
        "defaults_file": defaults_path,
        "defaults_drift": drift,
        "hint": "Reproduzierbare Änderungen gehören in sdkconfig.defaults (ggf. sdkconfig.defaults.<target>); sdkconfig ist generiert.",
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
            out[key] = matches if matches else "(nicht vorhanden)"
    return out
