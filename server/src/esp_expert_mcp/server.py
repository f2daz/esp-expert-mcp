"""MCP server "esp-expert": deterministic tools for ESP32/ESP8266 firmware."""

from __future__ import annotations

import os
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from . import chips, errcodes, esphome, panic, partitions, platformio, sdkconfig, serialports, versions

INSTRUCTIONS = """\
Tools for ESP32/ESP8266 firmware (ESP-IDF, Arduino, PlatformIO, ESPHome).
- Before writing hardware code: chip_info + pin_check for the planned pin assignment.
- Never quote versions from memory: use framework_versions / idf_target_support.
- Panics/resets: serial_log_analyze with the complete log and the matching ELF.
- Partitions: partition_validate; sdkconfig: sdkconfig_analyze.
- PlatformIO: platformio_analyze returns chip, partition CSV and ELF paths for the other tools.
- ESPHome YAML: esphome_lint (static), esphome_validate (real schema validation if the CLI is available).
- serial_ports/chip_probe are read-only; flashing is intentionally not done through this server.
"""

mcp = MCPServer("esp-expert", instructions=INSTRUCTIONS, version="0.1.0")

RO = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
RO_NET = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)


def _read(path: str) -> str:
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        return fh.read()


@mcp.tool(annotations=RO)
def chip_info(
    chip: Annotated[str | None, Field(description="e.g. esp32, esp32s3, esp32c3, esp32c6, esp8266; empty = overview")] = None,
) -> dict:
    """Hardware reference data for a SoC: cores, RAM, radio, USB, strapping/flash/input-only pins, ADC, touch, RTC GPIO, pitfalls, sources."""
    return chips.chip_info(chip)


@mcp.tool(annotations=RO)
def pin_check(
    chip: Annotated[str, Field(description="Target, e.g. esp32s3")],
    pins: Annotated[list[dict], Field(description='List [{"gpio": 4 | "GPIO4" | "D2", "usage": "output|input|adc|i2c|spi|uart|pwm|touch", "label": "LED"}]')],
    uses_wifi: Annotated[bool, Field(description="Wi-Fi active? (ADC2 conflict on ESP32)")] = True,
    psram: Annotated[str | None, Field(description="Module PSRAM: 'none', 'quad' (e.g. ESP32-WROVER) or 'octal' (ESP32-S3 R8/N16R8); empty = unknown")] = None,
    native_usb: Annotated[bool | None, Field(description="Is the native USB interface used?")] = None,
) -> dict:
    """Checks a planned GPIO assignment against chip constraints (exists, flash/PSRAM, strapping, input-only, USB, UART0, ADC2+Wi-Fi, double assignment)."""
    return chips.check_pins(chip, pins, uses_wifi, psram, native_usb)


@mcp.tool(annotations=RO)
def partition_validate(
    csv_text: Annotated[str | None, Field(description="Contents of partitions.csv")] = None,
    csv_path: Annotated[str | None, Field(description="alternatively, path to the CSV")] = None,
    flash_size: Annotated[str | None, Field(description="e.g. 4MB, 8MB, 16MB")] = None,
    target: Annotated[str | None, Field(description="Target for the bootloader offset, e.g. esp32s3")] = None,
    table_offset: Annotated[str | None, Field(description="CONFIG_PARTITION_TABLE_OFFSET, default 0x8000")] = None,
    app_bin_size: Annotated[int | None, Field(description="Size of the app binary in bytes (build/<app>.bin) for the headroom check")] = None,
) -> dict:
    """Validates an ESP-IDF partition table: alignment, overlap, OTA layout, otadata/NVS sizes, flash size, headroom."""
    if not csv_text and not csv_path:
        return {"error": "Provide csv_text or csv_path."}
    return partitions.validate(csv_text or _read(csv_path), flash_size, target, table_offset, app_bin_size)


@mcp.tool(annotations=RO)
def serial_log_analyze(
    log: Annotated[str | None, Field(description="Serial log (ideally starting at reset)")] = None,
    log_path: Annotated[str | None, Field(description="alternatively, path to a log file")] = None,
    elf: Annotated[str | None, Field(description="Path to the matching ELF for resolving the backtrace")] = None,
    arch: Annotated[Literal["xtensa", "riscv", "lx106"] | None, Field(description="Architecture for addr2line; otherwise auto-detected")] = None,
) -> dict:
    """Analyzes boot/crash logs: reset reason, Guru Meditation, EXCCAUSE/MCAUSE, stack overflow, WDT, brownout, ESP_ERROR_CHECK, ESP8266 exceptions; decodes the backtrace via addr2line."""
    if not log and not log_path:
        return {"error": "Provide log or log_path."}
    return panic.analyze(log or _read(log_path), os.path.expanduser(elf) if elf else None, arch)


@mcp.tool(annotations=RO_NET)
def esp_err_lookup(
    code: Annotated[str, Field(description="esp_err_t as hex (0x1101), decimal or part of the name (NVS_NO_FREE)")],
) -> dict:
    """Translates esp_err_t codes into name and description (table from local $IDF_PATH or the ESP-IDF repo)."""
    return errcodes.lookup(code)


@mcp.tool(annotations=RO)
def sdkconfig_analyze(
    sdkconfig_path: Annotated[str, Field(description="Path to sdkconfig")],
    defaults_path: Annotated[str | None, Field(description="Path to sdkconfig.defaults (otherwise auto-detected next to it)")] = None,
) -> dict:
    """Summarizes an sdkconfig (target, flash, PSRAM, log, WDT, security, OTA) and reports risky settings and deviations from sdkconfig.defaults."""
    return sdkconfig.analyze(os.path.expanduser(sdkconfig_path), os.path.expanduser(defaults_path) if defaults_path else None)


@mcp.tool(annotations=RO)
def sdkconfig_get(
    sdkconfig_path: Annotated[str, Field(description="Path to sdkconfig")],
    keys: Annotated[list[str], Field(description="CONFIG_ keys or partial names, e.g. ['SPIRAM', 'CONFIG_FREERTOS_HZ']")],
) -> dict:
    """Reads specific values from an sdkconfig (partial names return all matching keys)."""
    return sdkconfig.get(os.path.expanduser(sdkconfig_path), keys)


@mcp.tool(annotations=RO)
def serial_ports() -> dict:
    """Lists serial ports with USB VID/PID and detects common ESP bridges (CP210x, CH340, CH9102, FTDI, Espressif USB-Serial/JTAG)."""
    return serialports.list_serial()


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
def chip_probe(
    port: Annotated[str, Field(description="e.g. /dev/cu.usbserial-0001, /dev/ttyUSB0, COM5")],
    baud: Annotated[int, Field(description="Baud rate for esptool")] = 115200,
) -> dict:
    """Identifies the connected board via esptool (chip, revision, features, MAC, flash size). Writes nothing, but resets the chip."""
    return serialports.probe(port, baud)


@mcp.tool(annotations=RO_NET)
def framework_versions(
    component: Annotated[str | None, Field(description=f"{sorted(versions.REPOS)} or 'owner/repo'; empty = overview")] = None,
    include_prerelease: bool = False,
) -> dict:
    """Current releases live from GitHub (ESP-IDF lines, arduino-esp32, ESP8266 core, ESPHome, esptool, pioarduino …), sorted semantically."""
    if not component:
        return versions.overview()
    return versions.releases(component, include_prerelease)


@mcp.tool(annotations=RO_NET)
def idf_target_support(
    target: Annotated[str | None, Field(description="e.g. esp32c5; empty = all versions")] = None,
) -> dict:
    """Which ESP-IDF versions support which target (Espressif index idf_versions.json)."""
    return versions.idf_targets(target)


@mcp.tool(annotations=RO)
def esphome_lint(
    yaml_path: Annotated[str, Field(description="Path to the ESPHome device configuration")],
) -> dict:
    """Static check of an ESPHome YAML: platform/variant, pin assignment against chip data, plaintext secrets, API/OTA security, framework hints, known breaking changes."""
    return esphome.lint(os.path.expanduser(yaml_path))


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
def esphome_validate(
    yaml_path: Annotated[str, Field(description="Path to the ESPHome device configuration")],
    use_uvx: Annotated[bool, Field(description="Load ESPHome temporarily via uvx if not installed")] = False,
) -> dict:
    """Full schema validation via `esphome config` (requires the ESPHome CLI or uvx). Secrets are masked in the output."""
    return esphome.validate(os.path.expanduser(yaml_path), use_uvx)


@mcp.tool(annotations=RO)
def platformio_analyze(
    ini_path: Annotated[str, Field(description="Path to platformio.ini")],
) -> dict:
    """Evaluates platformio.ini: environments, platform source (registry/pioarduino, pinned?), board→chip, framework, partitions, baud rates, lib_deps, build artifacts (ELF/BIN/sdkconfig)."""
    return platformio.analyze(os.path.expanduser(ini_path))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
