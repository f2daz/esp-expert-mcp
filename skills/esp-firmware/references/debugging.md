# Debugging: triage, panics, core dump, JTAG, logging

## Triage flow

1. **Narrow down the phase:** Build → Flash → Boot (ROM/2nd-stage bootloader) → Init (`app_main`, drivers, network) → Runtime → Sleep/Wake/OTA.
2. **Get the full log from reset**, including ROM output (`rst:` / `boot:` line) and the **exact ELF** of the running build (same commit, same `sdkconfig`). Without the matching ELF, backtraces are worthless.
3. Analyse with `serial_log_analyze` (panic type, reset reason, decoded backtrace). Translate error codes with `esp_err_lookup`.
4. **Reproduce**, then instrument (logs, counters, heap/stack values, asserts), and only then change code. One change per iteration.
5. Suspected hardware first for resets without a panic: power supply (brownout), cable, strapping pins, levels, pull-ups.

## Reading reset reasons

```c
esp_reset_reason_t r = esp_reset_reason();
ESP_LOGI(TAG, "reset reason: %d", r);
```

| Value | Meaning / next step |
|---|---|
| `ESP_RST_POWERON` | power-on (also after a hard voltage drop) |
| `ESP_RST_EXT` | external reset pin (not applicable on ESP32) |
| `ESP_RST_SW` | `esp_restart()`: who called it? (OTA, own code) |
| `ESP_RST_PANIC` | exception/abort: look at the panic output from the previous boot or the core dump |
| `ESP_RST_INT_WDT` | interrupts masked too long / stuck ISR |
| `ESP_RST_TASK_WDT` | a task did not yield, see `rtos.md` |
| `ESP_RST_WDT` | other watchdogs (RTC/LP WDT, e.g. hang during boot) |
| `ESP_RST_DEEPSLEEP` | normal wakeup from deep sleep |
| `ESP_RST_BROWNOUT` | supply voltage below threshold |
| `ESP_RST_USB`, `ESP_RST_JTAG`, `ESP_RST_SDIO` | reset via USB peripheral / JTAG / SDIO |
| `ESP_RST_EFUSE`, `ESP_RST_PWR_GLITCH`, `ESP_RST_CPU_LOCKUP` | eFuse error, power glitch detected, CPU lockup (double exception) |

Store the reset reason and a crash counter in `RTC_NOINIT_ATTR`/NVS and report them at the next start (field diagnosis).

## Guru Meditation and other fatal errors

**Xtensa (ESP32, S2, S3):**
- `LoadProhibited` / `StoreProhibited`: access to an invalid address. `EXCVADDR` near 0 → NULL pointer (+ struct offset).
- `InstrFetchProhibited`: jump to an invalid address (corrupt function pointer, stack overflow). `PC` is often 0 or garbage.
- `IllegalInstruction`: corrupt code/stack, or a function in flash called while the cache is disabled.
- `IntegerDivideByZero`, `LoadStoreAlignment`, `Unhandled debug exception` (often a stack canary watchpoint), `Double exception`.
- `Cache error` / "Cache access error" (older IDF wording: `Cache disabled but cached memory region accessed`): an IRAM ISR/function touches flash/PSRAM code or data while the cache is disabled during a flash operation, see `rtos.md` (IRAM rules).

**RISC-V (C2, C3, C5, C6, H2, P4):**
- `Illegal instruction`, `Instruction access fault`, `Load access fault`, `Store access fault`, `Load/Store address misaligned`, `Breakpoint` (EBREAK, e.g. `abort()` path), `Memory protection fault`. `MTVAL` holds the faulting address.

**Other panic causes:**
- `Interrupt wdt timeout on CPUx` · `Task watchdog got triggered` (TWDT without panic only logs, unless `trigger_panic`)
- `Stack protection fault` / `Stack canary watchpoint triggered (task)` → increase that task's stack, find large local buffers
- `Stack smashing protect failure!` → buffer overflow in a stack frame
- `CORRUPT HEAP: …` → see `memory.md`, the backtrace shows the symptom
- `abort() was called at PC …` → often `ESP_ERROR_CHECK` failed: the line above shows the file:line and the error code
- `assert failed: …` → file/line directly in the log
- `Brownout detector was triggered` → power supply

**Panic behaviour:** `CONFIG_ESP_SYSTEM_PANIC_PRINT_REBOOT` (default), `..._PRINT_HALT` (for the lab), `..._SILENT_REBOOT`, `..._GDBSTUB` (GDB over UART directly after the panic).

## Decoding backtraces

- `idf.py monitor` decodes addresses automatically when the ELF in `build/` matches. RISC-V: the monitor decodes the stack dump. Alternatively `CONFIG_ESP_SYSTEM_USE_EH_FRAME` builds the backtrace on the device (binary 20–100% larger per docs).
- Manually with the toolchain's `addr2line` (prefix depends on target/toolchain version, e.g. `xtensa-esp32s3-elf-`, `xtensa-esp-elf-` or `riscv32-esp-elf-`):

```sh
xtensa-esp-elf-addr2line -pfiaC -e build/app.elf 0x400d1234 0x400d5678
```

- MCP: `serial_log_analyze` with the log and ELF path.
- "Backtrace: … |<-CORRUPTED": stack overwritten or exception in an interrupt without a frame. Then core dump/JTAG.

## Core dump

- Enable: `CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH` (recommended) or `..._TO_UART` (base64 in the log). Add the `espcoredump` component to REQUIRES if a minimal build is used.
- Partition: `coredump, data, coredump,, 64K` (with flash encryption add `, encrypted`).
- Evaluate:

```sh
idf.py coredump-info                 # reads from flash: registers, call stack, all tasks
idf.py coredump-debug                # GDB session on the dump
idf.py coredump-info -c dump.b64     # saved dump (e.g. from UART or field upload)
```

- For field devices: read the dump at start via `esp_core_dump_image_get()`, upload it, then erase it (`esp_core_dump_image_erase()`).
- **IDF 6.0:** the binary format has been removed, **ELF is mandatory**. Checksum SHA-256 instead of CRC32. `esp_core_dump_partition_and_size_get()` returns `ESP_ERR_NOT_FOUND` for an empty partition.

## JTAG / OpenOCD / GDB

- **Built-in USB-Serial-JTAG** on C3, S3, C5, C6, H2, P4 (per chip: `chip_info`). A USB cable is enough, no adapter. **ESP32-S2** has USB-OTG but no USB-JTAG → external adapter. **ESP32** classic: external adapter (e.g. ESP-Prog, FT2232H-based) on GPIO12–15 (MTDI/MTCK/MTMS/MTDO), and these pins are then unusable.
- Start:

```sh
idf.py openocd          # in terminal 1 (board config is chosen from the target, override if needed)
idf.py gdb              # in terminal 2
```

- Breakpoints are limited by hardware (few HW breakpoints per core), watchpoints are ideal for memory corruption.
- JTAG is disabled permanently with Secure Boot/flash encryption, see `security.md`.
- IDF 6.0: gdbgui is no longer installed via the install script (pipx or `idf.py gdb`).

## App trace / SystemView

- `app_trace` component: fast data transfer over JTAG (or UART on some targets). Use with SEGGER SystemView for task/ISR timelines, useful for latency and priority problems.
- Alternatively, lightweight: timestamps via `esp_timer_get_time()` into a ring buffer, output later.

## Stack and heap diagnostics (short)

- Periodically: `heap_caps_get_free_size`, `heap_caps_get_minimum_free_size`, `heap_caps_get_largest_free_block`, `uxTaskGetStackHighWaterMark` of all critical tasks. Details and tools in `memory.md`.
- `vTaskList()` / `vTaskGetRunTimeStats()` (Kconfig: trace facility, stats formatting, run-time stats) for task states and CPU usage.

## Logging strategy

- One `static const char *TAG = "module";` per module, stable tag names (filterable in the field).
- Levels: `E` = action failed / data loss, `W` = unexpected but handled, `I` = state changes (connected, OTA started), `D`/`V` = development.
- Always log error codes with `esp_err_to_name(err)` and context (which device, which step).
- **Runtime level:** `esp_log_level_set("wifi", ESP_LOG_WARN)`, `esp_log_level_set("*", ESP_LOG_INFO)`. Raising the level at runtime only works up to `CONFIG_LOG_MAXIMUM_LEVEL` (above that, logs are removed at compile time). Requires `CONFIG_LOG_DYNAMIC_LEVEL_CONTROL` (default on) and for per-tag control `CONFIG_LOG_TAG_LEVEL_IMPL`.
- Optionally `CONFIG_LOG_MASTER_LEVEL` for a global switch (`esp_log_set_level_master`).
- No logging in ISRs or critical sections. IDF 6.0: `esp_log_buffer_hex()` removed → `ESP_LOG_BUFFER_HEX()`.
- Bootloader: `CONFIG_BOOTLOADER_LOG_LEVEL` (not adjustable at runtime).
- Arduino: `log_e/w/i/d`, level via "Core Debug Level" / `CORE_DEBUG_LEVEL`.

## Brownout diagnosis

- Symptom: `Brownout detector was triggered`, reset reason `ESP_RST_BROWNOUT`, often exactly at Wi-Fi start/TX, during flashing, or on motor/LED switching.
- Causes: weak USB port/hub, thin/long cable, LDO too weak or high dropout, missing bulk capacitance close to the module, battery with high internal resistance, shared supply with motors/relays.
- Measure: oscilloscope on 3V3 at the module during Wi-Fi start (drop depth and duration). A multimeter does not catch short dips.
- Don't disable the brownout detector as a "fix" (`CONFIG_ESP_BROWNOUT_DET`). Threshold via `CONFIG_ESP_BROWNOUT_DET_LVL_SEL_*` only after a hardware analysis.

## Most common causes (checklist)

1. Stack overflow of a task (TLS, JSON, printf with floats)
2. NULL pointer / use-after-free after a failed init path without error checking
3. `ESP_ERROR_CHECK` on a recoverable error (Wi-Fi/NVS/I2C timeout) → abort
4. Blocking calls in ISR, event handler or timer callback → WDT
5. IRAM rules violated (ISR during flash write) → cache error
6. Heap exhausted/fragmented over time (leak in reconnect paths)
7. Race conditions on dual-core with unprotected shared data
8. Power supply/brownout, strapping pins, missing pull-ups (I2C timeouts)
9. Wrong ELF/`sdkconfig` during analysis, or a stale build flashed
10. Partition/flash size mismatch after a layout change, see `partitions-ota.md`

## Sources

- Fatal errors (per target): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/fatal-errors.html, RISC-V: https://docs.espressif.com/projects/esp-idf/en/latest/esp32c3/api-guides/fatal-errors.html
- Reset reason / system API: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/misc_system_api.html
- Core dump: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/core_dump.html
- JTAG debugging: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/jtag-debugging/index.html
- IDF monitor: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/tools/idf-monitor.html
- App trace: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/app_trace.html
- Logging: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/log.html
- Heap debugging: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/heap_debug.html
- Migration 6.0 system/tools: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/system.html, https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/tools.html
