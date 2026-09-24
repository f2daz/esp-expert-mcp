# esp-expert

A Claude Code plugin for firmware development on Espressif chips (ESP8266, ESP32, ESP32-S2/S3, C2/C3/C5/C6, H2, P4). It has two parts:

- **Skill `esp-firmware`**: the working method (clarify the hardware first, treat configuration as source code, only report "done" after a successful build) plus reference guides for ESP-IDF, the Arduino core, PlatformIO, ESPHome, ESP8266, FreeRTOS, peripherals, networking, OTA, memory, low power, security, debugging and flashing. Also includes templates.
- **MCP server `esp-expert`** (Python, MCP SDK 2.x): deterministic check tools. Anything that changes over time (versions, error tables) is queried live, not guessed.

## Tools

| Tool | Purpose |
|---|---|
| `chip_info` | SoC facts: cores, RAM, radio, USB, strapping/flash/input-only pins, ADC, touch, RTC GPIO, with sources |
| `pin_check` | Checks a planned GPIO assignment: flash/PSRAM pins, strapping pins, input-only pins, USB, UART0, ADC2 with Wi-Fi, duplicate use |
| `partition_validate` | Partition CSV: alignment, overlaps, OTA layout, otadata/NVS sizes, flash size, headroom for the app binary |
| `serial_log_analyze` | Reset reason, Guru Meditation, EXCCAUSE/MCAUSE, stack overflow, WDT, brownout, ESP8266 exceptions; decodes the backtrace via addr2line |
| `esp_err_lookup` | esp_err_t → name and description (from the local `$IDF_PATH` or the ESP-IDF repo) |
| `sdkconfig_analyze` / `sdkconfig_get` | Summary, risky settings, drift from `sdkconfig.defaults` |
| `platformio_analyze` | `platformio.ini`: environments, platform source and pinning, board → chip, partitions, build artifacts |
| `esphome_lint` / `esphome_validate` | Static check of ESPHome YAML, or full validation via `esphome config` |
| `serial_ports` / `chip_probe` | Serial ports with USB bridge detection; chip, flash size and MAC via esptool (read-only) |
| `framework_versions` / `idf_target_support` | Current releases (GitHub, sorted by version number) and which ESP-IDF versions support which target |

The server deliberately cannot write to devices (no flash, erase or eFuse). That is done in the shell with `idf.py`, `pio`, `arduino-cli`, `esphome` or `esptool`, and the skill asks for confirmation first.

## Installation

Requires [uv](https://docs.astral.sh/uv/). uv installs Python ≥ 3.11 itself if needed.

Inside Claude Code:

```
/plugin marketplace add f2daz/esp-expert-mcp
/plugin install esp-expert@esp-expert
```

From a local clone, pass the path to the cloned folder instead, for example:

```
/plugin marketplace add ~/code/esp-expert-mcp
```

To try it for one session without installing:

```bash
git clone https://github.com/f2daz/esp-expert-mcp
claude --plugin-dir ./esp-expert-mcp
```

To run only the MCP server, for example in Claude Desktop or another MCP client:

```json
{
  "mcpServers": {
    "esp-expert": {
      "command": "uv",
      "args": ["run", "--quiet", "--directory", "/path/to/esp-expert-mcp/server", "esp-expert-mcp"]
    }
  }
}
```

Optional environment variables:
- `IDF_PATH`: take error codes from your installed ESP-IDF version.
- `GITHUB_TOKEN`: raise the GitHub rate limit for `framework_versions`.

Optional tools on your machine:
- `esptool` for `chip_probe`
- `esphome` (or `uvx`) for `esphome_validate`
- an Espressif toolchain (`xtensa-esp-elf-addr2line`, `riscv32-esp-elf-addr2line`, or `xtensa-lx106-elf-addr2line` for ESP8266) for backtrace decoding. The server looks for it on `PATH` and under `~/.espressif/tools`, `~/.platformio/packages` and the Arduino15 folders.

## Development

```bash
cd server
uv run --group dev pytest        # tests
claude plugin validate ..        # check the manifests
```

Chip data lives in `server/src/esp_expert_mcp/data/chips.json`. It was compiled from the ESP-IDF "GPIO & RTC GPIO" pages and the Espressif datasheets; each chip lists its sources in `sources`.
- Where the datasheet and the IDF docs disagree (strapping pins of ESP32-C5 and ESP32-H2), both versions are recorded.
- The ESP32-P4 datasheet is still a pre-release.

Corrections with a source are welcome.

## Credits

Inspired by [adamlipecz/esp32-firmware-engineer-skill](https://github.com/adamlipecz/esp32-firmware-engineer-skill) (ESP-IDF, strict blocking rules), [onigetoc/esp32-skill](https://github.com/onigetoc/esp32-skill) (Arduino CLI workflow) and the [ESPHome docs](https://esphome.io/install/getting-started/). Neither repository has a license, so only structure and topics were used as ideas; all text and code here are written from scratch.

## License

[MIT](LICENSE): free to use, including commercially, as long as the license notice is kept.
