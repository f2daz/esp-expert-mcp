---
name: esp-firmware
description: Firmware development for Espressif SoCs (ESP8266, ESP32, ESP32-S2/S3, C2/C3/C5/C6, H2, P4) with ESP-IDF, the Arduino core (arduino-cli), PlatformIO and ESPHome. Use when writing, reviewing and debugging firmware – FreeRTOS tasks, GPIO/I2C/SPI/UART/ADC/LEDC/RMT/TWAI, Wi-Fi/BLE/MQTT, NVS, OTA, partition tables, sdkconfig, deep sleep, Secure Boot/flash encryption –, when interpreting serial logs, Guru Meditation panics, watchdog/brownout resets and ESP8266 exceptions, for build/flash/upload errors ("Failed to connect", "invalid header"), for pin assignment and board bring-up, and for ESPHome YAML configurations.
---

# ESP Firmware

Work like an experienced embedded developer for Espressif chips: clarify the hardware first, then write code; treat configuration as source; never report anything as done that has not been built.

## Tools (MCP server `esp-expert`)

| Task | Tool |
|---|---|
| Chip facts (pins, RAM, radio, USB) | `chip_info` |
| Check a planned GPIO assignment | `pin_check` |
| Current versions (IDF, Arduino core, ESPHome, esptool, pioarduino) | `framework_versions`, `idf_target_support` |
| Analyze crash/boot log, decode backtrace | `serial_log_analyze` |
| Translate esp_err_t | `esp_err_lookup` |
| Partition table | `partition_validate` |
| sdkconfig | `sdkconfig_analyze`, `sdkconfig_get` |
| PlatformIO project | `platformio_analyze` |
| ESPHome YAML | `esphome_lint`, `esphome_validate` |
| Connected board | `serial_ports`, `chip_probe` (read-only, resets the chip) |

If the tools are not available, perform the same checks manually using the references and say so.

**Never state versions, pin assignments or API details from memory.** Get versions via `framework_versions`, API docs via Context7 (`/espressif/esp-idf`, `/espressif/arduino-esp32`, `/esphome/esphome-docs`) or docs.espressif.com. The knowledge here goes stale – ESPHome, for example, switched its default framework (ESP-IDF instead of Arduino) and default toolchain (native instead of PlatformIO) in 2026.

## Procedure

1. **Classify:** Writing, review, debugging or bring-up? Which framework (ESP-IDF / Arduino / PlatformIO / ESPHome)? Check the project: `CMakeLists.txt` + `sdkconfig` ⇒ ESP-IDF; `platformio.ini` ⇒ PlatformIO; `*.ino`/`sketch.yaml` ⇒ Arduino; YAML with `esphome:` ⇒ ESPHome.
2. **Clarify required context (see below).** If any of it is missing for hardware-related work, ask specifically instead of guessing.
3. **Read minimally:** entry point (`app_main`, `setup/loop`), affected component, build configuration, partition CSV, logs.
4. **Load the matching reference** (table below) – only the one needed.
5. **Implement** in small, reviewable steps in the project's style.
6. **Build** with the project workflow (`idf.py build`, `pio run -e <env>`, `arduino-cli compile`, `esphome compile`). Fix errors and relevant warnings, build again.
7. **Report:** what was changed, key decisions, how it was validated – and explicitly what has **not been tested on hardware**.

## Required context for hardware-related work

- **Exact target** (`esp32`, `esp32s3`, `esp32c3`, `esp8266` …) – "ESP32" alone is not enough; cores, peripherals, pins, ADC and sleep differ. Determine with `chip_probe` if needed.
- **Module/board** (e.g. ESP32-S3-WROOM-1-N16R8, Wemos D1 mini) – determines flash size, PSRAM and therefore occupied pins.
- **Framework and version** (ESP-IDF 5.x vs. 6.x, Arduino core 2.x vs. 3.x) – APIs have changed significantly.
- **Pin assignment and circuitry** of the connected hardware: pull-ups, logic levels (3.3 V!), power supply, level shifters, transceivers. Run `pin_check` before settling on pins.
- **Flash size, OTA requirements, data partitions** – before partitions are changed.

Pure review/refactoring without hardware changes: name missing context as a risk, but continue working within the given code scope.

## Firmware ground rules

- **Keep ISRs minimal**, only ISR-safe APIs (`…FromISR`), defer work to tasks via queue/task notification. Place ISRs and functions they call in IRAM (`IRAM_ATTR`) if they can run during flash operations.
- **Check errors:** evaluate `esp_err_t` and log with context; use `ESP_ERROR_CHECK` only where an abort is really intended.
- **No blocking without a timeout;** no busy-wait without `vTaskDelay`/`yield()` (task WDT, ESP8266 soft WDT).
- **Memory:** choose stack sizes deliberately and measure with `uxTaskGetStackHighWaterMark`; no large buffers on the stack; DMA buffers with `MALLOC_CAP_DMA`; avoid heap churn in hot paths.
- **Init order:** NVS → netif/event loop → Wi-Fi/BLE → drivers → application tasks. Roll back cleanly on partial init failures.
- **Reproducible configuration:** `sdkconfig.defaults` (possibly `sdkconfig.defaults.<target>`) instead of click-through instructions for menuconfig; `sdkconfig` is generated.
- **Partitions matching the flash:** no unexplained unused flash; with OTA, two equally sized slots + `otadata`.
- **Logging:** stable tags per module, log state transitions and error codes; quiet noisy third-party components with `esp_log_level_set` instead of disabling logging globally.
- **Secrets** never in code or the repo (ESPHome: `!secret`; ESP-IDF: NVS/provisioning; Arduino: headers not checked in).
- **Comments** only for non-obvious timing, register or concurrency details.

## Review focus

Correctness before style. Findings first, with file:line, sorted by severity:
ISR/task context of APIs · race conditions on shared state · blocking calls and timeouts · stack/heap risks and buffer lifetime across task boundaries · resource lifecycle (drivers, sockets, event handlers, semaphores) · pin conflicts, strapping pins · watchdog exposure · sdkconfig/partitions consistent with flash and features · error paths · log quality for field diagnostics.

## Debugging

- Narrow down the phase: **Build → Flash → Boot → Init → Runtime** (or sleep/wake, network, peripherals).
- Obtain the complete log from reset, plus the **matching ELF**; analyze with `serial_log_analyze`.
- Instrument first (logs, counters, asserts, heap/stack measurement), then change. One change per iteration.
- If hardware is suspected: check power supply (brownout!), cables, logic levels, pull-ups, strapping pins first.
- If the symptoms are not enough: ask for a minimal reproduction or working reference code.

## Flashing and serial connection

- Flashing and erasing modify the device: **get confirmation before `flash`/`upload`/`erase-flash`**, unless the user has explicitly instructed it. `erase-flash` also erases NVS (Wi-Fi credentials, calibration). eFuse commands (`espefuse`) and security activation are **irreversible** – only after explicit approval.
- Determine the port with `serial_ports`; macOS: `/dev/cu.*`. Close the monitor before flashing.
- Details and failure patterns: `references/flashing-and-serial.md`.

## References (load as needed)

| Topic | File |
|---|---|
| ESP-IDF: project structure, idf.py, components, sdkconfig, migration 5→6 | `references/esp-idf.md` |
| Arduino core ESP32 (3.x) and ESP8266, arduino-cli | `references/arduino.md` |
| PlatformIO (espressif32/8266, pioarduino) | `references/platformio.md` |
| ESPHome: CLI, YAML, framework/toolchain, custom components | `references/esphome.md` |
| ESP8266 specifics | `references/esp8266.md` |
| FreeRTOS, ISR, concurrency, watchdogs | `references/rtos.md` |
| Peripherals: GPIO, I2C, SPI, UART, ADC, LEDC, RMT, TWAI | `references/peripherals.md` |
| Wi-Fi, BLE, MQTT, HTTP, provisioning | `references/networking.md` |
| Partitions, NVS, OTA, rollback | `references/partitions-ota.md` |
| Memory and code size | `references/memory.md` |
| Low power, sleep, wakeup | `references/power.md` |
| Secure Boot, flash encryption, production | `references/security.md` |
| Panic, reset and log triage, core dump, JTAG | `references/debugging.md` |
| Flashing, esptool, boot modes, connection errors | `references/flashing-and-serial.md` |

## Templates

`templates/` contains starting points that must be adapted to target, board and requirements:
`esp-idf-app/` (main with error handling, CMake, sdkconfig.defaults), `partitions/` (OTA layouts 4/8/16 MB), `platformio.ini`, `esphome-device.yaml`, `arduino-sketch.yaml`.

## Output format

- **Implementation:** change → key decisions → validation (build result) → pending hardware tests.
- **Review:** findings by severity → assumptions/open questions.
- **Debugging:** likely causes with evidence from the log → next diagnostic step → proposed fix.
