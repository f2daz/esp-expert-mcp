# Memory and code size

## Memory types (overview)

| Type | Use | Attribute / capability |
|---|---|---|
| **IRAM** | Code that must run with the flash cache disabled (IRAM-safe ISRs, flash-concurrent paths) | `IRAM_ATTR`, `MALLOC_CAP_EXEC` (not available with memory protection enabled, see 6.0) |
| **DRAM** | Data, stacks, heap (internal) | `DRAM_ATTR` (constants for IRAM-safe code), `MALLOC_CAP_INTERNAL` |
| **RTC FAST/SLOW** (LP RAM) | Data that survives deep sleep, deep-sleep wake stub | `RTC_DATA_ATTR`, `RTC_NOINIT_ATTR`, `RTC_FAST_ATTR`, `MALLOC_CAP_RTCRAM` |
| **PSRAM** (external) | Large buffers, frame buffers, TLS/Wi-Fi buffers | `MALLOC_CAP_SPIRAM`, `EXT_RAM_BSS_ATTR`, `EXT_RAM_NOINIT_ATTR` |
| **Flash (cache-mapped)** | Code (`.text`) and constants (`.rodata`), read-only | default |

- Exact sizes and address ranges per chip come from `chip_info` or the TRM. Don't quote numbers from memory.
- On ESP32, parts of IRAM are only accessible 32-bit (`MALLOC_CAP_32BIT`), so no byte access there.
- `__NOINIT_ATTR` / `RTC_NOINIT_ATTR`: survives a software reset (not power loss). Useful for crash counters.

## Heap API (`esp_heap_caps.h`)

```c
size_t free_int   = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
size_t min_int    = heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL);  /* low-water mark since boot */
size_t largest    = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
ESP_LOGI(TAG, "int free=%u min=%u largest=%u", (unsigned)free_int, (unsigned)min_int, (unsigned)largest);
heap_caps_print_heap_info(MALLOC_CAP_8BIT);          /* detail when needed */

uint8_t *dma = heap_caps_malloc(len, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
uint8_t *big = heap_caps_malloc(512 * 1024, MALLOC_CAP_SPIRAM);
if (dma == NULL || big == NULL) { free(dma); free(big); return ESP_ERR_NO_MEM; }
```

- Common capabilities: `MALLOC_CAP_DEFAULT`, `MALLOC_CAP_8BIT`, `MALLOC_CAP_32BIT`, `MALLOC_CAP_INTERNAL`, `MALLOC_CAP_SPIRAM`, `MALLOC_CAP_DMA`, `MALLOC_CAP_RTCRAM`, `MALLOC_CAP_EXEC`.
- `heap_caps_free()` and `free()` are interchangeable.
- `heap_caps_aligned_alloc()` for alignment requirements (DMA, cache lines).
- Global view: `esp_get_free_heap_size()`, `esp_get_minimum_free_heap_size()`.

## Fragmentation

- Symptom: plenty of total free heap, yet `malloc` of a large block fails (e.g. TLS handshake, OTA buffer). The indicator is `heap_caps_get_largest_free_block` vs. `free_size`.
- Countermeasures: allocate large, long-lived buffers **early at boot**, static buffers or pools instead of churn in hot paths, avoid `realloc` growth, move large buffers to PSRAM, reuse TLS/HTTP clients instead of creating new ones each time.
- Log free/min/largest periodically (e.g. every 60 s) in field firmware. That is the most important diagnostic value for creeping leaks.

## Stack

- ESP-IDF stack sizes are in **bytes** (see `rtos.md`).
- Measure: `uxTaskGetStackHighWaterMark(handle)`. Overview of all tasks: `vTaskList()` / `uxTaskGetSystemState()` (needs `CONFIG_FREERTOS_USE_TRACE_FACILITY`, for `vTaskList` also `CONFIG_FREERTOS_USE_STATS_FORMATTING_FUNCTIONS`).
- Overflow detection: `CONFIG_FREERTOS_CHECK_STACKOVERFLOW_CANARY`, `CONFIG_FREERTOS_WATCHPOINT_END_OF_STACK`. On RISC-V targets, hardware stack guard (`CONFIG_ESP_SYSTEM_HW_STACK_GUARD`). Buffer overflows within a frame: `CONFIG_COMPILER_STACK_CHECK_MODE_*` ("Stack smashing protect failure").
- No large arrays on the stack. Task stacks in PSRAM are possible (`xTaskCreateWithCaps`), but not with flash-concurrent code and not for DMA.

## PSRAM (external RAM)

- Enable: `CONFIG_SPIRAM`. **Mode must match the module:** `CONFIG_SPIRAM_MODE` Quad or Octal (octal PSRAM e.g. on S3 modules "…R8"). Octal flash separately via `CONFIG_ESPTOOLPY_OCT_FLASH`. Wrong mode → PSRAM init fails at boot.
- Speed: `CONFIG_SPIRAM_SPEED` (octal on S3 up to 120 MHz with restrictions, see "Flash and PSRAM configuration").
- Integration via `CONFIG_SPIRAM_USE`:
  - *Integrate RAM into memory map* (addressing only),
  - *Add RAM to heap_caps allocator* (only `MALLOC_CAP_SPIRAM`),
  - *Make RAM allocatable using malloc()* (default). `CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL` sets the size threshold below which `malloc` stays internal.
- `CONFIG_SPIRAM_ALLOW_BSS_SEG_EXTERNAL_MEMORY` + `EXT_RAM_BSS_ATTR` on static, zero-initialised variables moves BSS to PSRAM. The same option also moves BSS of lwIP, net80211, wpa_supplicant and Bluedroid. `EXT_RAM_NOINIT_ATTR` for uninitialised data.
- `CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP`: Wi-Fi/lwIP buffers preferably in PSRAM.
- `CONFIG_SPIRAM_IGNORE_NOTFOUND`: boot continues without PSRAM instead of aborting (useful for mixed hardware, but then check at runtime).
- **Pins:** PSRAM occupies extra GPIOs (e.g. ESP32 GPIO16/17, S3 octal additional ones). Use `pin_check`.
- PSRAM is slower than internal RAM and is **not accessible while the flash cache is disabled**. No IRAM-safe ISR data in PSRAM.

## DMA capability

- `MALLOC_CAP_DMA` **excludes PSRAM**. For SPI/I2S/LCD/… buffers: `heap_caps_malloc(n, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL)` or static with `DMA_ATTR`.
- ESP32-S2: no DMA from/to PSRAM in ESP-IDF. ESP32-S3: possible in hardware, but DMA descriptors never in PSRAM and bandwidth is limited. Chips with EDMA: `MALLOC_CAP_SPIRAM | MALLOC_CAP_DMA`, where the allocator handles alignment.
- Stack buffers for DMA are discouraged (at least `WORD_ALIGNED_ATTR`, never with PSRAM stacks).
- Buffer lifetime: queued transactions (`spi_device_queue_trans`, I2S, RMT) need the buffer until completion.

## Analysing size

```sh
idf.py size               # summary: DRAM/IRAM/flash usage
idf.py size-components    # per component/library
idf.py size-files         # per object file
idf.py size --format json2 > size.json   # IDF 6.0: json2 instead of json; --legacy removed
```

The tools parse the linker map file (`build/<project>.map`). Keep comparisons between two builds (before/after) in the PR.

## Reducing code size

- `CONFIG_COMPILER_OPTIMIZATION` → *Optimize for size (-Os)*. In some cases `-O2` is even smaller (per docs).
- LTO: `CONFIG_COMPILER_LTO_LINKTIME` (+ compile time per component). Increases stack usage, not for components with their own linker fragments.
- Assertions: `CONFIG_COMPILER_OPTIMIZATION_ASSERTION_LEVEL` → *Silent*. `CONFIG_COMPILER_OPTIMIZATION_CHECKS_SILENT`. Both make field diagnosis harder.
- Logging: lower `CONFIG_LOG_DEFAULT_LEVEL` or `CONFIG_LOG_MAXIMUM_LEVEL` (strings drop out of the binary). Disabling `CONFIG_LOG_DYNAMIC_LEVEL_CONTROL`/`CONFIG_LOG_TAG_LEVEL_IMPL` if not needed. Component logs such as `CONFIG_BT_NIMBLE_LOG_LEVEL`.
- **libc:** from **IDF 6.0, Picolibc is the default** (smaller printf family). Newlib selectable via `CONFIG_LIBC_NEWLIB`, then `CONFIG_LIBC_NEWLIB_NANO_FORMAT` (no 64-bit integers/C99 formats in printf). Older IDF versions: Newlib is the default; the nano option was called `CONFIG_NEWLIB_NANO_FORMAT` in earlier releases (exact rename version: verify).
- Features: disable IPv6, unused mbedTLS cipher suites, the bundle "full" variant (common CA list), BT Classic, unused Wi-Fi features (WPS, Enterprise, …).
- **Unused components:** `set(COMPONENTS main)` or `idf_build_set_property(MINIMAL_BUILD ON)` in the project `CMakeLists.txt` builds only `main` plus its dependencies (then declare `REQUIRES` fully). Optional components like `esp_psram` or `espcoredump` must then be listed explicitly.

## Heap debugging

- **Heap poisoning:** `CONFIG_HEAP_POISONING_LIGHT` (canaries at block boundaries) or `..._COMPREHENSIVE` (additionally fills freed/new memory, catches use-after-free, slower).
- Narrow down corruption: sprinkle `heap_caps_check_integrity_all(true)` around the suspect code. With a known address, a watchpoint: `esp_cpu_set_watchpoint(0, addr, 4, ESP_WATCHPOINT_STORE)` (per CPU) or JTAG.
- Failed allocations: `heap_caps_register_failed_alloc_callback(cb)` logs size, caps and caller.
- **Heap tracing** (`CONFIG_HEAP_TRACING_STANDALONE` or `..._TOHOST`):

```c
#include "esp_heap_trace.h"
#define NREC 100
static heap_trace_record_t s_rec[NREC];            /* in internal RAM */
ESP_ERROR_CHECK(heap_trace_init_standalone(s_rec, NREC));
ESP_ERROR_CHECK(heap_trace_start(HEAP_TRACE_LEAKS));
suspected_leak();
ESP_ERROR_CHECK(heap_trace_stop());
heap_trace_dump();
```

- Per-task heap statistics: `CONFIG_HEAP_TASK_TRACKING` (`heap_caps_print_single_task_stat_overview`).
- The stack trace shown with "CORRUPT HEAP" shows the **symptom**, rarely the cause.

## Sources

- Memory types: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/memory-types.html
- Heap allocation & capabilities: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/mem_alloc.html
- Heap debugging: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/heap_debug.html
- External RAM (ESP32-S3): https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/external-ram.html
- Flash and PSRAM configuration (S3): https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/flash_psram_config.html
- Minimizing binary size: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/performance/size.html
- Build system (COMPONENTS, MINIMAL_BUILD): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/build-system.html
- Migration 6.0 system (Picolibc, MALLOC_CAP_EXEC): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/system.html
- Migration 6.0 tools (`idf.py size`): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/tools.html
