# ESP-IDF

Offizielles Framework von Espressif (C, CMake, FreeRTOS). Versionen nie aus dem Gedächtnis nennen – `framework_versions` bzw. `idf_target_support` (welcher Chip ab welcher IDF-Version) nutzen.

## Projektstruktur

```
projekt/
├── CMakeLists.txt            # Top-Level, drei Pflichtzeilen
├── sdkconfig.defaults        # eingecheckt: gewünschte Abweichungen vom Default
├── sdkconfig.defaults.esp32s3 # optional, zusätzlich geladen, wenn Target = esp32s3
├── sdkconfig                 # generiert – nicht als Quelle pflegen
├── partitions.csv            # optional, via CONFIG_PARTITION_TABLE_CUSTOM
├── dependencies.lock         # vom Component Manager erzeugt
├── main/
│   ├── CMakeLists.txt
│   ├── idf_component.yml     # Abhängigkeiten aus der Component Registry
│   └── main.c                # void app_main(void)
├── components/<name>/        # projekteigene Komponenten
│   ├── CMakeLists.txt
│   ├── include/<name>.h
│   └── <name>.c
└── managed_components/       # vom Component Manager geladen – nicht editieren
```

Top-Level `CMakeLists.txt` (Reihenfolge ist Pflicht):

```cmake
cmake_minimum_required(VERSION 3.22)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(mein_projekt)
```

Komponenten-`CMakeLists.txt`:

```cmake
idf_component_register(SRCS "sensor.c"
                       INCLUDE_DIRS "include"
                       REQUIRES esp_driver_i2c      # öffentlich (im Header gebraucht)
                       PRIV_REQUIRES esp_timer)     # nur intern
```

- `REQUIRES` nur, was die öffentlichen Header brauchen; alles andere `PRIV_REQUIRES`.
- Ab IDF 6.0 zieht die Sammelkomponente `driver` die `esp_driver_*`-Komponenten nicht mehr öffentlich mit – Treiber explizit angeben (z. B. `esp_driver_gpio`, `esp_driver_uart`, `esp_driver_i2c`).

### sdkconfig.defaults

- Nur Abweichungen eintragen, eine Option pro Zeile: `CONFIG_FREERTOS_HZ=1000`.
- `sdkconfig.defaults.<target>` wird **zusätzlich** geladen, aber nur wenn `sdkconfig.defaults` existiert.
- Mehrere Dateien: `idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.prod" build`.
- Nach Änderung an den Defaults wirkt nichts, solange ein altes `sdkconfig` existiert – `sdkconfig` löschen oder `idf.py fullclean`/`set-target`.
- Aus einer per menuconfig erarbeiteten Konfiguration Defaults erzeugen: `idf.py save-defconfig`.
- Prüfen mit `sdkconfig_analyze` / einzelne Werte mit `sdkconfig_get`.

## idf.py – wichtige Befehle

| Befehl | Zweck |
|---|---|
| `idf.py set-target esp32s3` | Target setzen; **löscht Build und sdkconfig** |
| `idf.py menuconfig` | Konfiguration interaktiv (danach `save-defconfig`) |
| `idf.py build` | Bauen |
| `idf.py -p /dev/cu.usbmodem1101 flash monitor` | Flashen und Monitor (Bestätigung einholen) |
| `idf.py -p PORT -b 921600 flash` | Mit höherer Baudrate |
| `idf.py -p PORT app-flash` | Nur App-Partition |
| `idf.py monitor` | Serieller Monitor mit Adressdekodierung |
| `idf.py size` / `size-components` / `size-files` | Speicherbelegung gesamt / je Komponente / je Datei |
| `idf.py clean` / `fullclean` | Build-Output / komplettes Build-Verzeichnis löschen |
| `idf.py reconfigure` | CMake neu ausführen (z. B. nach neuer Komponente) |
| `idf.py save-defconfig` | Minimale `sdkconfig.defaults` aus aktueller Konfiguration |
| `idf.py create-project NAME` | Neues Projekt |
| `idf.py create-component NAME` | Neue Komponente (in `components/` ausführen; Zielverzeichnis-Option prüfen) |
| `idf.py add-dependency "espressif/led_strip^3"` | Abhängigkeit in `main/idf_component.yml` eintragen |
| `idf.py update-dependencies` | Abhängigkeiten neu auflösen |
| `idf.py -p PORT erase-flash` | **Ganzen Flash löschen** inkl. NVS – nur nach Freigabe |
| `idf.py -p PORT coredump-info` | Core-Dump aus Flash lesen und auswerten |
| `idf.py -p PORT coredump-debug` | Core-Dump in GDB öffnen |

- Ab IDF 6.0: `idf.py size --legacy` entfernt; `--format json` heißt jetzt `--format json2`.
- Ab IDF 6.0: alle `idf.py efuse*`-Befehle brauchen explizit `--port`/`ESPPORT`. eFuse-Befehle sind irreversibel.
- Port-Vorgabe per Umgebungsvariable: `ESPPORT`, Baudrate `ESPBAUD`.

## IDF Monitor – Tasten

| Taste | Funktion |
|---|---|
| `Ctrl+]` | Monitor beenden |
| `Ctrl+T` `Ctrl+R` | Target per RTS zurücksetzen |
| `Ctrl+T` `Ctrl+F` | Projekt bauen und flashen |
| `Ctrl+T` `Ctrl+A` | Nur App bauen und flashen |
| `Ctrl+T` `Ctrl+P` | In Bootloader resetten (App anhalten) |
| `Ctrl+T` `Ctrl+Y` | Log-Ausgabe pausieren/fortsetzen |
| `Ctrl+T` `Ctrl+L` | Log in Datei an/aus |
| `Ctrl+T` `Ctrl+I` | Zeitstempel an/aus |
| `Ctrl+T` `Ctrl+H` | Alle Tastenkürzel anzeigen |

- Der Monitor dekodiert Code-Adressen und Backtraces automatisch gegen die ELF des Projekts (abschaltbar: `--disable-address-decoding`). Nur mit der **exakt passenden ELF** sinnvoll; sonst `serial_log_analyze` mit ELF verwenden.

## Component Manager

`main/idf_component.yml`:

```yaml
dependencies:
  idf: ">=5.3"                      # IDF-Versionsbedingung
  espressif/led_strip: "^3"         # Registry, SemVer-Bereich
  espressif/mqtt: "*"               # ab IDF 6.0 nicht mehr im IDF enthalten
  my_driver:
    git: https://github.com/org/repo.git
    path: components/my_driver
    version: v1.2.0                 # Tag/Commit pinnen, keinen Branch
  local_lib:
    path: ../shared/local_lib
  espressif/button:
    override_path: ../patched_button
  esp_tinyusb:
    version: "^1"
    rules:
      - if: "target in [esp32s2, esp32s3, esp32p4]"
```

- Registry: https://components.espressif.com/
- `managed_components/` und `dependencies.lock` nicht von Hand ändern. `dependencies.lock` einchecken, wenn reproduzierbare Builds gewünscht sind (Projektentscheidung; Doku schreibt es nicht vor).
- Nach Änderungen am Manifest: `idf.py reconfigure` oder `build`.

## Installation

- **Ab IDF 6.0: ESP-IDF Installation Manager (EIM)**, GUI oder CLI.
  macOS: `brew tap espressif/eim` → `brew install eim` (CLI) bzw. `brew install --cask eim-gui`.
  `eim install` (neueste stabile), `eim install -i v5.5.x` (bestimmte Version), `eim wizard` (interaktiv).
  Aktivierung der Umgebung erfolgt über von EIM erzeugte Aktivierungsskripte (Pfad/Name prüfen, `eim --help`).
- **Legacy (Versionen vor 6.0):**
  ```bash
  git clone --recursive https://github.com/espressif/esp-idf.git
  cd esp-idf && ./install.sh esp32,esp32s3
  . ./export.sh          # in jeder neuen Shell
  ```
- Ab IDF 6.0 Mindestanforderungen: Python ≥ 3.10, CMake ≥ 3.22.1.
- Mehrere IDF-Versionen parallel sind üblich – immer prüfen, welche `IDF_PATH` aktiv ist (`idf.py --version`).

## Migration ESP-IDF 5.x → 6.x

Offizieller Guide (vor jeder Migration lesen, es gibt auch 6.0→6.1 und 6.1→6.2):
https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/

### Treiber (Peripherals)

In **6.0 entfernt** (Legacy-Treiber), Ersatz:

| Alt (entfernt) | Neu |
|---|---|
| `driver/adc.h` | `esp_adc/adc_oneshot.h`, `adc_continuous.h`, `adc_cali.h` |
| `driver/timer.h` (Timer Group) | `driver/gptimer.h` |
| `driver/i2s.h` | `driver/i2s_std.h`, `i2s_pdm.h`, `i2s_tdm.h` |
| `driver/mcpwm.h` | `driver/mcpwm_prelude.h` |
| `driver/pcnt.h` | `driver/pulse_cnt.h` |
| `driver/rmt.h` | `driver/rmt_tx.h`, `rmt_rx.h`, `rmt_encoder.h` |
| `driver/dac.h` | `driver/dac_oneshot.h`, `dac_continuous.h`, `dac_cosine.h` |
| `driver/sigmadelta.h` | `driver/sdm.h` |

- **I2C Legacy (`driver/i2c.h`)**: in 6.0 **EOL, Entfernung in 7.0 geplant**. Warnung temporär mit `CONFIG_I2C_SUPPRESS_DEPRECATE_WARN` unterdrückbar – trotzdem auf `driver/i2c_master.h` / `i2c_slave.h` migrieren. Alter und neuer I2C-Treiber dürfen nicht gemischt werden.
- UART: `UART_FIFO_LEN` → `UART_HW_FIFO_LEN`. LEDC: `ledc_timer_set()` entfernt. GPIO: `gpio_uninstall_isr_service()` liefert jetzt `esp_err_t`.
- 6.1: `uart_set/get_wakeup_threshold()` deprecated → `uart_wakeup_setup()` (`driver/uart_wakeup.h`).

Neue I2C-Master-API (seit IDF 5.2 verfügbar – prüfen; für neuen Code ab 6.0 der einzig zukunftssichere Weg):

```c
#include "driver/i2c_master.h"

i2c_master_bus_config_t bus_cfg = {
    .i2c_port = I2C_NUM_0,
    .sda_io_num = GPIO_NUM_8,
    .scl_io_num = GPIO_NUM_9,
    .clk_source = I2C_CLK_SRC_DEFAULT,
    .glitch_ignore_cnt = 7,
    .flags.enable_internal_pullup = true,   // ersetzt keine externen Pull-ups
};
i2c_master_bus_handle_t bus;
ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));

i2c_device_config_t dev_cfg = {
    .dev_addr_length = I2C_ADDR_BIT_LEN_7,
    .device_address = 0x76,
    .scl_speed_hz = 400000,
};
i2c_master_dev_handle_t dev;
ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev_cfg, &dev));

uint8_t reg = 0xD0, id;
esp_err_t err = i2c_master_transmit_receive(dev, &reg, 1, &id, 1, 100 /* ms */);
```

ADC oneshot (statt `adc1_get_raw`):

```c
#include "esp_adc/adc_oneshot.h"

adc_oneshot_unit_handle_t adc;
adc_oneshot_unit_init_cfg_t ucfg = { .unit_id = ADC_UNIT_1 };
ESP_ERROR_CHECK(adc_oneshot_new_unit(&ucfg, &adc));
adc_oneshot_chan_cfg_t ccfg = { .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT };
ESP_ERROR_CHECK(adc_oneshot_config_channel(adc, ADC_CHANNEL_2, &ccfg));
int raw;
ESP_ERROR_CHECK(adc_oneshot_read(adc, ADC_CHANNEL_2, &raw));   // nicht aus ISR
```
Kalibrierung in mV über `adc_cali_create_scheme_curve_fitting()` bzw. `..._line_fitting()` – je nach Chip (`ADC_CALI_SCHEME_*_SUPPORTED`).

### System, Toolchain, Build

- **LibC: Newlib → Picolibc** als Standard (ab 6.0); `stdin/stdout/stderr` global, nicht mehr pro Task. Newlib optional via `CONFIG_LIBC_NEWLIB`.
- **GCC 14.2 → 15.1** (6.0): neue Warnungen; **Standard-Warnungen gelten als Fehler**. Notbehelf `CONFIG_COMPILER_DISABLE_GCC15_WARNINGS` – besser Code korrigieren.
- Linker bricht bei Orphan Sections mit Fehler ab. Globale Konstruktoren laufen jetzt in aufsteigender Reihenfolge.
- Kconfig: esp-idf-kconfig v3 (eigene Kconfig-Dateien ggf. anpassen).
- **FreeRTOS** entfernt: `xTaskGetAffinity`, `xTaskGetIdleTaskHandleForCPU`, `xTaskGetCurrentTaskHandleForCPU`, `xQueueGenericReceive`, `vTaskDelayUntil` → `xTaskGetCoreID`, `xTaskGetIdleTaskHandleForCore`, `xQueueReceive`, `xTaskDelayUntil`. FreeRTOS-Code liegt standardmäßig im Flash statt IRAM (`CONFIG_FREERTOS_IN_IRAM` zum Zurückstellen). Ring Buffer ebenso (`CONFIG_RINGBUF_IN_IRAM`).
- Sleep: `esp_sleep_get_wakeup_causes()` ersetzt `esp_sleep_get_wakeup_cause()`; `esp_deep_sleep_enable_gpio_wakeup()` → `esp_sleep_enable_gpio_wakeup_on_hp_periph_powerdown()`.
- Core Dump: nur noch ELF-Format, SHA256 statt CRC32.

### Netzwerk und Protokolle

- **ESP-MQTT** aus IDF entfernt → Komponente `espressif/mqtt` (API `mqtt_client.h` unverändert).
- **`json`** (cJSON) entfernt → `espressif/cjson`.
- ESP-TLS: wolfSSL-Support entfernt; `esp_tls_conn_http_new()` → `..._sync()`/`..._async()`.
- HTTP-Server: WebSocket-URI-Handler wird beim Handshake nicht mehr aufgerufen (ab 6.0.1) → `ws_post_handshake_cb`.
- LwIP: `sntp.h` → `esp_sntp.h`; alte Ping-API entfernt → `ping/ping_sock.h`; TCP/IP-Task heißt `tcpip` statt `tiT`.
- ESP-NETIF: `esp_netif_next()` entfernt → `esp_netif_find_if()` o. ä. Ethernet-PHY-Treiber ausgelagert (`esp-eth-drivers`).

### Vorgehen bei Migration

1. Migration Guides aller übersprungenen Minor-Versionen durchgehen.
2. `idf.py fullclean`, dann bauen und Fehler/Warnungen einzeln abarbeiten.
3. Entfernte Komponenten per `idf.py add-dependency` nachziehen.
4. `sdkconfig.defaults` gegen umbenannte Optionen prüfen (`sdkconfig_analyze`); Build meldet veraltete Optionen.
5. Timing-kritische ISRs prüfen (FreeRTOS/Ringbuffer jetzt im Flash).

## Support-Zeiträume

Nicht aus dem Gedächtnis beantworten – aktuelle Übersicht:
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/versions.html
- https://github.com/espressif/esp-idf/blob/master/SUPPORT_POLICY.md

## Quellen

- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/ (6.0: peripherals, system, toolchain, tools, build-system, networking, protocols; 6.1: peripherals)
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/build-system.html
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/tools/idf-py.html
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/tools/idf-monitor.html
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/tools/idf-component-manager.html
- https://docs.espressif.com/projects/idf-component-manager/en/latest/reference/manifest_file.html
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/get-started/macos-setup.html
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/get-started/linux-macos-setup-legacy.html
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/i2c.html
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/adc/adc_oneshot.html
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32/versions.html
