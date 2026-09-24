# PlatformIO

Projekt mit `platformio_analyze` prüfen lassen (Plattform, Pinning, Partitionen, Flags). Aktuelle Plattform-/Core-Versionen über `framework_versions`.

## Plattformen für Espressif

| Plattform | `platform =` | Stand |
|---|---|---|
| Offiziell (PlatformIO) | `espressif32` | Arduino-Framework nur Core **2.x**; Arduino Core 3.x wird offiziell nicht unterstützt (Stand der Community-Diskussion, vor Einsatz prüfen) |
| pioarduino (Community) | `https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip` | Arduino Core **3.x** + aktuelles ESP-IDF 5.x; neuere Chips (C5, C6, H2, P4 …) |
| ESP8266 | `espressif8266` | Arduino-ESP8266-Core bzw. ESP8266_RTOS_SDK |

- Für neue ESP32-Arduino-Projekte ist damit faktisch **pioarduino** nötig, wenn Core 3.x gebraucht wird. Board-Definitionen dort werden laut README nicht von den Maintainern repariert – PRs gegen `develop`.
- Welche Core-/IDF-Version eine pioarduino-Release enthält, steht in den Release Notes (https://github.com/pioarduino/platform-espressif32/releases) – nicht raten.

### Versionspinning (Pflicht für reproduzierbare Builds)

```ini
; offizielle Plattform: Version pinnen
platform = espressif32@6.x.y
; pioarduino: konkretes Release statt "stable"
platform = https://github.com/pioarduino/platform-espressif32/releases/download/<tag>/platform-espressif32.zip
; Bibliotheken pinnen
lib_deps =
    knolleary/PubSubClient@^2.8
    bblanchon/ArduinoJson@7.x.y
```
- `stable`-URL und unversionierte `lib_deps` ändern sich unbemerkt → Build bricht irgendwann oder verhält sich anders.
- Framework-Paket gezielt überschreiben mit `platform_packages` nur, wenn nötig und dokumentiert.

## platformio.ini – Aufbau

```ini
[platformio]
default_envs = s3

[env]                                   ; gemeinsame Einstellungen
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

| Option | Bedeutung |
|---|---|
| `board_build.partitions` | Partitions-CSV (Projektpfad oder Name aus dem Framework); mit `partition_validate` prüfen |
| `board_build.filesystem` | `spiffs` (Default), `littlefs`, `fatfs` – muss zum Code und zur Partition passen |
| `board_build.flash_mode` | `qio`, `qout`, `dio`, `dout` (OPI-Module: Board-Definition prüfen) |
| `board_build.f_flash` | Flash-Takt, z. B. `80000000L` |
| `board_build.f_cpu` | CPU-Takt, z. B. `240000000L` |
| `board_build.mcu` | Chip, z. B. `esp32s3` (normalerweise aus Board-JSON) |
| `board_build.embed_files` / `embed_txtfiles` | Dateien in die Firmware einbetten |
| `board_upload.flash_size` | Flash-Größe, z. B. `16MB` – an reales Modul anpassen |
| `board_upload.maximum_size` | Max. App-Größe (muss zur App-Partition passen) |
| `board_build.arduino.memory_type` | z. B. `qio_opi` für S3 mit Octal-PSRAM (prüfen) |

- Board-JSON beschreibt oft nur das Devkit mit 4 MB/ohne PSRAM – bei N8R8/N16R8-Modulen Flash-Größe, PSRAM und Speichertyp selbst setzen.

### build_flags (Auswahl)

- `-DBOARD_HAS_PSRAM` – PSRAM im Arduino-Core aktivieren (bei ESP32-WROVER/S3-R-Modulen).
- `-DCORE_DEBUG_LEVEL=0…5` – Arduino-Logausgabe (`log_e` … `log_v`).
- `-DARDUINO_USB_CDC_ON_BOOT=1` – `Serial` auf nativem USB (S2/S3/C3/C6).
- `-DARDUINO_USB_MODE=1` – Hardware-CDC/JTAG statt TinyUSB (S3).
- Warnungen: `build_unflags = -Werror=…` nur gezielt; Warnungen lieber beheben.
- Secrets nicht in `platformio.ini` einchecken; `-DWIFI_PASS=\"${sysenv.WIFI_PASS}\"` oder eine lokale, ignorierte `secrets.ini` via `extra_configs`.

## Befehle

| Befehl | Zweck |
|---|---|
| `pio run` / `pio run -e s3` | Bauen (alle bzw. ein Env) |
| `pio run -e s3 -t upload` | Flashen (bestätigen lassen) |
| `pio run -e s3 -t upload --upload-port /dev/cu.usbmodem1101` | mit Port |
| `pio run -e s3 -t buildfs` / `-t uploadfs` | Dateisystem-Image bauen / flashen (überschreibt FS-Inhalt) |
| `pio run -e s3 -t erase` | **Flash komplett löschen** – nur nach Freigabe |
| `pio run -e s3 -t clean` | Build-Verzeichnis des Envs löschen |
| `pio run -e idf -t menuconfig` | menuconfig (nur Framework `espidf`) |
| `pio run -e s3 -t size` | Größenübersicht (prüfen, ob Target je Plattform verfügbar) |
| `pio device list` | Serielle Ports |
| `pio device monitor -e s3` | Monitor mit Filtern aus dem Env |
| `pio check -e s3` | Statische Analyse (cppcheck/clang-tidy) |
| `pio test -e s3` | Unit-Tests (Unity) auf Target oder `native` |
| `pio pkg update` | Pakete aktualisieren – bricht Pinning, bewusst einsetzen |

- Monitorfilter: `esp32_exception_decoder` bzw. `esp8266_exception_decoder` dekodieren Backtraces gegen die ELF des gebauten Envs – nur korrekt, wenn genau diese Firmware läuft. Weitere: `time`, `log2file`, `default`, `direct`.
- ELF liegt unter `.pio/build/<env>/firmware.elf` – für `serial_log_analyze` verwenden.

## ESP-IDF-Framework unter PlatformIO

```ini
[env:idf]
platform = espressif32@6.x.y
framework = espidf
board = esp32-c6-devkitc-1
board_build.partitions = partitions.csv
board_build.cmake_extra_args =
    -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.prod"
```
- Projektstruktur wie ESP-IDF: `src/` (statt `main/`) mit eigenem `CMakeLists.txt`, Top-Level-`CMakeLists.txt`, optional `components/`.
- PlatformIO erzeugt je Env **`sdkconfig.<env>`** (z. B. `sdkconfig.idf`). Diese Datei ist generiert; Quelle der Wahrheit ist `sdkconfig.defaults`. Eigener Pfad: `board_build.esp-idf.sdkconfig_path`.
- IDF-Version hängt an der Plattformversion – vor IDF-Migration prüfen, welche IDF-Version die Plattform liefert (`framework_versions`, Plattform-Release-Notes).
- `idf_component.yml` in `src/` wird vom Component Manager ausgewertet (prüfen, je Plattformversion).
- Arduino + ESP-IDF gemeinsam: `framework = arduino, espidf` (pioarduino; sdkconfig-Anforderungen des Arduino-Cores beachten, u. a. `CONFIG_FREERTOS_HZ=1000`).

## Mehrere Envs

- `[env]` für Gemeinsames, `extends = env:basis` für Varianten; `${env:basis.build_flags}` zum Erweitern statt Überschreiben.
- Typisch: je Board/Chip ein Env, zusätzlich `_debug`/`_release`, ggf. `native` für Host-Tests.
- `default_envs` setzen, sonst baut `pio run` alle Envs.
- Quellauswahl je Env: `build_src_filter = +<*> -<board_b/>`.

## ESP8266 unter PlatformIO

```ini
[env:d1_mini]
platform = espressif8266@4.x.y
board = d1_mini
framework = arduino
board_build.filesystem = littlefs
board_build.ldscript = eagle.flash.4m2m.ld   ; 4 MB, 2 MB FS
monitor_filters = esp8266_exception_decoder
```

## Typische Fehler

| Symptom | Ursache / Maßnahme |
|---|---|
| `ledcAttach`/`timerAlarm` unbekannt | Offizielle Plattform mit Core 2.x → pioarduino mit Core 3.x oder Code auf 2.x-API |
| Build plötzlich anders/fehlerhaft ohne Codeänderung | Unversionierte Plattform/`lib_deps` → pinnen |
| `Error: Unknown board ID` | Board nicht in der verwendeten Plattform (z. B. neue Chips nur in pioarduino) |
| Firmware passt nicht (`region … overflowed`) | Partition/`board_upload.maximum_size` zu klein; `-t size` |
| Dateisystem leer/`mount failed` | `board_build.filesystem` passt nicht zum Code (`LittleFS` vs. `SPIFFS`) oder `uploadfs` fehlt |
| PSRAM nicht verfügbar | `-DBOARD_HAS_PSRAM` fehlt bzw. falscher Speichertyp (Quad vs. Octal) |
| Monitor zeigt nichts (S3) | CDC-Flags, Port; nach Reset neuer Port-Name |
| sdkconfig-Änderung wirkt nicht | altes `sdkconfig.<env>` → löschen, `-t clean`, neu bauen |
| Backtrace falsch dekodiert | laufende Firmware ≠ ELF des Envs |
| Zwei Plattformen gemischt | `.pio/` und `~/.platformio/packages` Konflikte → `pio run -t clean`, Pakete prüfen |

## Quellen

- https://docs.platformio.org/en/latest/platforms/espressif32.html
- https://docs.platformio.org/en/latest/platforms/espressif8266.html
- https://docs.platformio.org/en/latest/projectconf/index.html
- https://docs.platformio.org/en/latest/core/userguide/device/cmd_monitor.html
- https://github.com/pioarduino/platform-espressif32
- https://github.com/pioarduino/platform-espressif32/releases
- https://github.com/espressif/arduino-esp32/discussions/10039
- https://community.platformio.org/t/esp32-arduino-core-3-x-and-platformio-status/42008
