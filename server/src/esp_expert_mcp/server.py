"""MCP-Server „esp-expert“: deterministische Werkzeuge für ESP32/ESP8266-Firmware."""

from __future__ import annotations

import os
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from . import chips, errcodes, esphome, panic, partitions, platformio, sdkconfig, serialports, versions

INSTRUCTIONS = """\
Werkzeuge für ESP32-/ESP8266-Firmware (ESP-IDF, Arduino, PlatformIO, ESPHome).
- Vor Hardware-Code: chip_info + pin_check für die geplante Belegung.
- Versionen nie aus dem Gedächtnis nennen: framework_versions / idf_target_support.
- Panics/Resets: serial_log_analyze mit vollständigem Log und passender ELF.
- Partitionen: partition_validate; sdkconfig: sdkconfig_analyze.
- PlatformIO: platformio_analyze liefert Chip, Partitions-CSV und ELF-Pfade für die übrigen Tools.
- ESPHome-YAML: esphome_lint (statisch), esphome_validate (echte Schema-Prüfung, wenn CLI vorhanden).
- serial_ports/chip_probe lesen nur; Flashen läuft bewusst nicht über diesen Server.
"""

mcp = MCPServer("esp-expert", instructions=INSTRUCTIONS, version="0.1.0")

RO = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
RO_NET = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)


def _read(path: str) -> str:
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        return fh.read()


@mcp.tool(annotations=RO)
def chip_info(
    chip: Annotated[str | None, Field(description="z. B. esp32, esp32s3, esp32c3, esp32c6, esp8266; leer = Übersicht")] = None,
) -> dict:
    """Hardware-Stammdaten eines SoC: Kerne, RAM, Funk, USB, Strapping-/Flash-/Input-only-Pins, ADC, Touch, RTC-GPIO, Stolpersteine, Quellen."""
    return chips.chip_info(chip)


@mcp.tool(annotations=RO)
def pin_check(
    chip: Annotated[str, Field(description="Target, z. B. esp32s3")],
    pins: Annotated[list[dict], Field(description='Liste [{"gpio": 4 | "GPIO4" | "D2", "usage": "output|input|adc|i2c|spi|uart|pwm|touch", "label": "LED"}]')],
    uses_wifi: Annotated[bool, Field(description="Wi-Fi aktiv? (ADC2-Konflikt auf ESP32)")] = True,
    psram: Annotated[str | None, Field(description="PSRAM des Moduls: 'none', 'quad' (z. B. ESP32-WROVER) oder 'octal' (ESP32-S3 R8/N16R8); leer = unbekannt")] = None,
    native_usb: Annotated[bool | None, Field(description="Wird die native USB-Schnittstelle genutzt?")] = None,
) -> dict:
    """Prüft eine geplante GPIO-Belegung gegen Chip-Einschränkungen (existiert, Flash/PSRAM, Strapping, Input-only, USB, UART0, ADC2+Wi-Fi, Doppelbelegung)."""
    return chips.check_pins(chip, pins, uses_wifi, psram, native_usb)


@mcp.tool(annotations=RO)
def partition_validate(
    csv_text: Annotated[str | None, Field(description="Inhalt der partitions.csv")] = None,
    csv_path: Annotated[str | None, Field(description="alternativ Pfad zur CSV")] = None,
    flash_size: Annotated[str | None, Field(description="z. B. 4MB, 8MB, 16MB")] = None,
    target: Annotated[str | None, Field(description="Target für Bootloader-Offset, z. B. esp32s3")] = None,
    table_offset: Annotated[str | None, Field(description="CONFIG_PARTITION_TABLE_OFFSET, Standard 0x8000")] = None,
    app_bin_size: Annotated[int | None, Field(description="Größe des App-Binaries in Byte (build/<app>.bin) für Reserve-Prüfung")] = None,
) -> dict:
    """Validiert eine ESP-IDF-Partitionstabelle: Ausrichtung, Überlappung, OTA-Layout, otadata/NVS-Größen, Flash-Größe, Reserve."""
    if not csv_text and not csv_path:
        return {"error": "csv_text oder csv_path angeben."}
    return partitions.validate(csv_text or _read(csv_path), flash_size, target, table_offset, app_bin_size)


@mcp.tool(annotations=RO)
def serial_log_analyze(
    log: Annotated[str | None, Field(description="Serial-Log (möglichst ab Reset)")] = None,
    log_path: Annotated[str | None, Field(description="alternativ Pfad zu einer Logdatei")] = None,
    elf: Annotated[str | None, Field(description="Pfad zur passenden ELF zum Auflösen des Backtraces")] = None,
    arch: Annotated[Literal["xtensa", "riscv", "lx106"] | None, Field(description="Architektur für addr2line; sonst automatisch")] = None,
) -> dict:
    """Analysiert Boot-/Crash-Logs: Reset-Grund, Guru Meditation, EXCCAUSE/MCAUSE, Stack-Overflow, WDT, Brownout, ESP_ERROR_CHECK, ESP8266-Exceptions; dekodiert Backtrace per addr2line."""
    if not log and not log_path:
        return {"error": "log oder log_path angeben."}
    return panic.analyze(log or _read(log_path), os.path.expanduser(elf) if elf else None, arch)


@mcp.tool(annotations=RO_NET)
def esp_err_lookup(
    code: Annotated[str, Field(description="esp_err_t als Hex (0x1101), Dezimal oder Namensteil (NVS_NO_FREE)")],
) -> dict:
    """Übersetzt esp_err_t-Codes in Namen und Beschreibung (Tabelle aus lokalem $IDF_PATH oder ESP-IDF-Repo)."""
    return errcodes.lookup(code)


@mcp.tool(annotations=RO)
def sdkconfig_analyze(
    sdkconfig_path: Annotated[str, Field(description="Pfad zu sdkconfig")],
    defaults_path: Annotated[str | None, Field(description="Pfad zu sdkconfig.defaults (sonst automatisch daneben)")] = None,
) -> dict:
    """Fasst ein sdkconfig zusammen (Target, Flash, PSRAM, Log, WDT, Security, OTA) und meldet riskante Einstellungen sowie Abweichungen zu sdkconfig.defaults."""
    return sdkconfig.analyze(os.path.expanduser(sdkconfig_path), os.path.expanduser(defaults_path) if defaults_path else None)


@mcp.tool(annotations=RO)
def sdkconfig_get(
    sdkconfig_path: Annotated[str, Field(description="Pfad zu sdkconfig")],
    keys: Annotated[list[str], Field(description="CONFIG_-Schlüssel oder Teilnamen, z. B. ['SPIRAM', 'CONFIG_FREERTOS_HZ']")],
) -> dict:
    """Liest gezielt Werte aus einem sdkconfig (Teilnamen liefern alle passenden Schlüssel)."""
    return sdkconfig.get(os.path.expanduser(sdkconfig_path), keys)


@mcp.tool(annotations=RO)
def serial_ports() -> dict:
    """Listet serielle Ports mit USB-VID/PID und erkennt typische ESP-Bridges (CP210x, CH340, CH9102, FTDI, Espressif USB-Serial/JTAG)."""
    return serialports.list_serial()


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
def chip_probe(
    port: Annotated[str, Field(description="z. B. /dev/cu.usbserial-0001, /dev/ttyUSB0, COM5")],
    baud: Annotated[int, Field(description="Baudrate für esptool")] = 115200,
) -> dict:
    """Identifiziert das angeschlossene Board per esptool (Chip, Revision, Features, MAC, Flash-Größe). Schreibt nichts, setzt den Chip aber zurück."""
    return serialports.probe(port, baud)


@mcp.tool(annotations=RO_NET)
def framework_versions(
    component: Annotated[str | None, Field(description=f"{sorted(versions.REPOS)} oder 'owner/repo'; leer = Überblick")] = None,
    include_prerelease: bool = False,
) -> dict:
    """Aktuelle Releases live von GitHub (ESP-IDF-Linien, arduino-esp32, ESP8266-Core, ESPHome, esptool, pioarduino …), semantisch sortiert."""
    if not component:
        return versions.overview()
    return versions.releases(component, include_prerelease)


@mcp.tool(annotations=RO_NET)
def idf_target_support(
    target: Annotated[str | None, Field(description="z. B. esp32c5; leer = alle Versionen")] = None,
) -> dict:
    """Welche ESP-IDF-Versionen welches Target unterstützen (Espressif-Index idf_versions.json)."""
    return versions.idf_targets(target)


@mcp.tool(annotations=RO)
def esphome_lint(
    yaml_path: Annotated[str, Field(description="Pfad zur ESPHome-Gerätekonfiguration")],
) -> dict:
    """Statische Prüfung einer ESPHome-YAML: Plattform/Variante, Pin-Belegung gegen Chipdaten, Klartext-Secrets, API/OTA-Absicherung, Framework-Hinweise, bekannte Breaking Changes."""
    return esphome.lint(os.path.expanduser(yaml_path))


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
def esphome_validate(
    yaml_path: Annotated[str, Field(description="Pfad zur ESPHome-Gerätekonfiguration")],
    use_uvx: Annotated[bool, Field(description="ESPHome per uvx temporär laden, falls nicht installiert")] = False,
) -> dict:
    """Vollständige Schema-Validierung per `esphome config` (benötigt ESPHome-CLI oder uvx). Secrets werden in der Ausgabe maskiert."""
    return esphome.validate(os.path.expanduser(yaml_path), use_uvx)


@mcp.tool(annotations=RO)
def platformio_analyze(
    ini_path: Annotated[str, Field(description="Pfad zu platformio.ini")],
) -> dict:
    """Wertet platformio.ini aus: Environments, Plattform-Quelle (Registry/pioarduino, gepinnt?), Board→Chip, Framework, Partitionen, Baudraten, lib_deps, Build-Artefakte (ELF/BIN/sdkconfig)."""
    return platformio.analyze(os.path.expanduser(ini_path))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
