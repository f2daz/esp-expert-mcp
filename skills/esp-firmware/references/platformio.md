# PlatformIO

Have the project checked with `platformio_analyze` (platform, pinning, partitions, flags). Current platform/core versions via `framework_versions`.

## Platforms for Espressif

| Platform | `platform =` | Status |
|---|---|---|
| Official (PlatformIO) | `espressif32` | Arduino framework only core **2.x**; Arduino core 3.x is not officially supported (per the community discussion, verify before use) |
| pioarduino (community) | `https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip` | Arduino core **3.x** + current ESP-IDF 5.x; newer chips (C5, C6, H2, P4 …) |
| ESP8266 | `espressif8266` | Arduino ESP8266 core or ESP8266_RTOS_SDK |

- For new ESP32 Arduino projects, **pioarduino** is therefore effectively required if core 3.x is needed. According to the README, board definitions there are not fixed by the maintainers – PRs against `develop`.
- Which core/IDF version a pioarduino release contains is stated in the release notes (https://github.com/pioarduino/platform-espressif32/releases) – do not guess.

### Version pinning (mandatory for reproducible builds)

```ini
; official platform: pin the version
platform = espressif32@6.x.y
; pioarduino: a specific release instead of "stable"
platform = https://github.com/pioarduino/platform-espressif32/releases/download/<tag>/platform-espressif32.zip
; pin libraries
lib_deps =
    knolleary/PubSubClient@^2.8
    bblanchon/ArduinoJson@7.x.y
```
- The `stable` URL and unversioned `lib_deps` change unnoticed → the build eventually breaks or behaves differently.
- Override the framework package with `platform_packages` only when necessary and documented.

## platformio.ini – structure

```ini
[platformio]
default_envs = s3

[env]                                   ; shared settings
framework = arduino
monitor_speed = 115200
monitor_filters = esp32_exception_decoder, time
build_flags =
    -DCORE_DEBUG_LEVEL=3                ; 0 none … 5 verbose
lib_deps =
    knolleary/PubSubClient@^2.8

[env:s3]
platform = https://github.com/pioarduino/platform-espressif32/releases/download/<tag>/platform-espressif32.zip
board = esp32-s3-devkitc-1
board_build.mcu = esp32s3
board_build.flash_mode = qio
board_upload.flash_size = 16MB
board_build.partitions = partitions_16mb_ota.csv
board_build.filesystem = littlefs
build_flags =
    ${env.build_flags}
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_CDC_ON_BOOT=1
    -DARDUINO_USB_MODE=1
upload_port = /dev/cu.usbmodem1101
monitor_port = /dev/cu.usbmodem1101

[env:s3_debug]
extends = env:s3
build_type = debug
build_flags =
    ${env:s3.build_flags}
    -DCORE_DEBUG_LEVEL=5
```

### board_build.* / board_upload.*

| Option | Meaning |
|---|---|
| `board_build.partitions` | Partition CSV (project path or name from the framework); check with `partition_validate` |
| `board_build.filesystem` | `spiffs` (default), `littlefs`, `fatfs` – must match the code and the partition |
| `board_build.flash_mode` | `qio`, `qout`, `dio`, `dout` (OPI modules: check the board definition) |
| `board_build.f_flash` | Flash clock, e.g. `80000000L` |
| `board_build.f_cpu` | CPU clock, e.g. `240000000L` |
| `board_build.mcu` | Chip, e.g. `esp32s3` (normally from the board JSON) |
| `board_build.embed_files` / `embed_txtfiles` | Embed files in the firmware |
| `board_upload.flash_size` | Flash size, e.g. `16MB` – adjust to the actual module |
| `board_upload.maximum_size` | Max. app size (must match the app partition) |
| `board_build.arduino.memory_type` | e.g. `qio_opi` for S3 with octal PSRAM (verify) |

- The board JSON often only describes the devkit with 4 MB/without PSRAM – for N8R8/N16R8 modules, set flash size, PSRAM and memory type yourself.

### build_flags (selection)

- `-DBOARD_HAS_PSRAM` – enable PSRAM in the Arduino core (for ESP32-WROVER/S3-R modules).
- `-DCORE_DEBUG_LEVEL=0…5` – Arduino log output (`log_e` … `log_v`).
- `-DARDUINO_USB_CDC_ON_BOOT=1` – `Serial` on native USB (S2/S3/C3/C6).
- `-DARDUINO_USB_MODE=1` – hardware CDC/JTAG instead of TinyUSB (S3).
- Warnings: use `build_unflags = -Werror=…` only selectively; better to fix the warnings.
- Do not check secrets into `platformio.ini`; use `-DWIFI_PASS=\"${sysenv.WIFI_PASS}\"` or a local, ignored `secrets.ini` via `extra_configs`.

## Commands

| Command | Purpose |
|---|---|
| `pio run` / `pio run -e s3` | Build (all or one env) |
| `pio run -e s3 -t upload` | Flash (get confirmation) |
| `pio run -e s3 -t upload --upload-port /dev/cu.usbmodem1101` | with port |
| `pio run -e s3 -t buildfs` / `-t uploadfs` | Build / flash filesystem image (overwrites FS contents) |
| `pio run -e s3 -t erase` | **Erase flash completely** – only after approval |
| `pio run -e s3 -t clean` | Delete the env's build directory |
| `pio run -e idf -t menuconfig` | menuconfig (framework `espidf` only) |
| `pio run -e s3 -t size` | Size overview (verify the target is available per platform) |
| `pio device list` | Serial ports |
| `pio device monitor -e s3` | Monitor with filters from the env |
| `pio check -e s3` | Static analysis (cppcheck/clang-tidy) |
| `pio test -e s3` | Unit tests (Unity) on target or `native` |
| `pio pkg update` | Update packages – breaks pinning, use deliberately |

- Monitor filters: `esp32_exception_decoder` and `esp8266_exception_decoder` decode backtraces against the ELF of the built env – only correct if exactly this firmware is running. Others: `time`, `log2file`, `default`, `direct`.
- The ELF is located at `.pio/build/<env>/firmware.elf` – use it for `serial_log_analyze`.

## ESP-IDF framework under PlatformIO

```ini
[env:idf]
platform = espressif32@6.x.y
framework = espidf
board = esp32-c6-devkitc-1
board_build.partitions = partitions.csv
board_build.cmake_extra_args =
    -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.prod"
```
- Project structure as in ESP-IDF: `src/` (instead of `main/`) with its own `CMakeLists.txt`, top-level `CMakeLists.txt`, optional `components/`.
- PlatformIO generates **`sdkconfig.<env>`** per env (e.g. `sdkconfig.idf`). This file is generated; the source of truth is `sdkconfig.defaults`. Custom path: `board_build.esp-idf.sdkconfig_path`.
- The IDF version depends on the platform version – before an IDF migration, check which IDF version the platform ships (`framework_versions`, platform release notes).
- `idf_component.yml` in `src/` is evaluated by the Component Manager (verify, per platform version).
- Arduino + ESP-IDF together: `framework = arduino, espidf` (pioarduino; observe the Arduino core's sdkconfig requirements, including `CONFIG_FREERTOS_HZ=1000`).

## Multiple envs

- `[env]` for shared settings, `extends = env:base` for variants; `${env:base.build_flags}` to extend instead of overwrite.
- Typical: one env per board/chip, plus `_debug`/`_release`, possibly `native` for host tests.
- Set `default_envs`, otherwise `pio run` builds all envs.
- Source selection per env: `build_src_filter = +<*> -<board_b/>`.

## ESP8266 under PlatformIO

```ini
[env:d1_mini]
platform = espressif8266@4.x.y
board = d1_mini
framework = arduino
board_build.filesystem = littlefs
board_build.ldscript = eagle.flash.4m2m.ld   ; 4 MB, 2 MB FS
monitor_filters = esp8266_exception_decoder
```

## Common errors

| Symptom | Cause / action |
|---|---|
| `ledcAttach`/`timerAlarm` unknown | Official platform with core 2.x → pioarduino with core 3.x or code on the 2.x API |
| Build suddenly different/failing without code changes | Unversioned platform/`lib_deps` → pin them |
| `Error: Unknown board ID` | Board not in the platform used (e.g. new chips only in pioarduino) |
| Firmware does not fit (`region … overflowed`) | Partition/`board_upload.maximum_size` too small; `-t size` |
| Filesystem empty/`mount failed` | `board_build.filesystem` does not match the code (`LittleFS` vs. `SPIFFS`) or `uploadfs` missing |
| PSRAM not available | `-DBOARD_HAS_PSRAM` missing or wrong memory type (quad vs. octal) |
| Monitor shows nothing (S3) | CDC flags, port; new port name after reset |
| sdkconfig change has no effect | Old `sdkconfig.<env>` → delete, `-t clean`, rebuild |
| Backtrace decoded incorrectly | Running firmware ≠ ELF of the env |
| Two platforms mixed | `.pio/` and `~/.platformio/packages` conflicts → `pio run -t clean`, check packages |

## Sources

- https://docs.platformio.org/en/latest/platforms/espressif32.html
- https://docs.platformio.org/en/latest/platforms/espressif8266.html
- https://docs.platformio.org/en/latest/projectconf/index.html
- https://docs.platformio.org/en/latest/core/userguide/device/cmd_monitor.html
- https://github.com/pioarduino/platform-espressif32
- https://github.com/pioarduino/platform-espressif32/releases
- https://github.com/espressif/arduino-esp32/discussions/10039
- https://community.platformio.org/t/esp32-arduino-core-3-x-and-platformio-status/42008
