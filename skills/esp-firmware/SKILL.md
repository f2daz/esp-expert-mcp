---
name: esp-firmware
description: Firmwareentwicklung für Espressif-SoCs (ESP8266, ESP32, ESP32-S2/S3, C2/C3/C5/C6, H2, P4) mit ESP-IDF, Arduino-Core (arduino-cli), PlatformIO und ESPHome. Nutzen beim Schreiben, Reviewen und Debuggen von Firmware – FreeRTOS-Tasks, GPIO/I2C/SPI/UART/ADC/LEDC/RMT/TWAI, Wi-Fi/BLE/MQTT, NVS, OTA, Partitionstabellen, sdkconfig, Deep-Sleep, Secure Boot/Flash-Encryption –, beim Interpretieren von Serial-Logs, Guru-Meditation-Panics, Watchdog-/Brownout-Resets und ESP8266-Exceptions, bei Build-/Flash-/Upload-Fehlern („Failed to connect“, „invalid header“), bei Pinbelegung und Board-Bring-up sowie bei ESPHome-YAML-Konfigurationen.
---

# ESP-Firmware

Arbeite wie ein erfahrener Embedded-Entwickler für Espressif-Chips: erst die Hardware klären, dann Code; Konfiguration als Quelltext behandeln; nichts als erledigt melden, was nicht gebaut wurde.

## Werkzeuge (MCP-Server `esp-expert`)

| Aufgabe | Tool |
|---|---|
| Chip-Fakten (Pins, RAM, Funk, USB) | `chip_info` |
| Geplante GPIO-Belegung prüfen | `pin_check` |
| Aktuelle Versionen (IDF, Arduino-Core, ESPHome, esptool, pioarduino) | `framework_versions`, `idf_target_support` |
| Crash-/Boot-Log auswerten, Backtrace dekodieren | `serial_log_analyze` |
| esp_err_t übersetzen | `esp_err_lookup` |
| Partitionstabelle | `partition_validate` |
| sdkconfig | `sdkconfig_analyze`, `sdkconfig_get` |
| PlatformIO-Projekt | `platformio_analyze` |
| ESPHome-YAML | `esphome_lint`, `esphome_validate` |
| Angeschlossenes Board | `serial_ports`, `chip_probe` (liest nur, setzt Chip zurück) |

Stehen die Tools nicht zur Verfügung, dieselben Prüfungen manuell anhand der Referenzen durchführen und das kenntlich machen.

**Versionen, Pinbelegungen und API-Details nie aus dem Gedächtnis behaupten.** Versionen über `framework_versions` holen, API-Doku über Context7 (`/espressif/esp-idf`, `/espressif/arduino-esp32`, `/esphome/esphome-docs`) oder docs.espressif.com. Das Wissen hier veraltet – ESPHome z. B. hat 2026 Standard-Framework (ESP-IDF statt Arduino) und Standard-Toolchain (native statt PlatformIO) gewechselt.

## Vorgehen

1. **Einordnen:** Schreiben, Review, Debugging oder Bring-up? Welches Framework (ESP-IDF / Arduino / PlatformIO / ESPHome)? Im Projekt nachsehen: `CMakeLists.txt` + `sdkconfig` ⇒ ESP-IDF; `platformio.ini` ⇒ PlatformIO; `*.ino`/`sketch.yaml` ⇒ Arduino; YAML mit `esphome:` ⇒ ESPHome.
2. **Pflichtkontext klären (siehe unten).** Fehlt bei hardwarenaher Arbeit etwas davon, gezielt nachfragen statt raten.
3. **Minimal lesen:** Einstiegspunkt (`app_main`, `setup/loop`), betroffene Komponente, Build-Konfiguration, Partitions-CSV, Logs.
4. **Passende Referenz laden** (Tabelle unten) – nur die benötigte.
5. **Umsetzen** in kleinen, reviewbaren Schritten im Stil des Projekts.
6. **Bauen** mit dem Projekt-Workflow (`idf.py build`, `pio run -e <env>`, `arduino-cli compile`, `esphome compile`). Fehler und relevante Warnungen beheben, erneut bauen.
7. **Berichten:** Was geändert wurde, wichtige Entscheidungen, wie validiert – und ausdrücklich, was **nicht auf Hardware geprüft** ist.

## Pflichtkontext bei hardwarenaher Arbeit

- **Exaktes Target** (`esp32`, `esp32s3`, `esp32c3`, `esp8266` …) – „ESP32“ allein reicht nicht; Kerne, Peripherie, Pins, ADC und Sleep unterscheiden sich. Ggf. mit `chip_probe` ermitteln.
- **Modul/Board** (z. B. ESP32-S3-WROOM-1-N16R8, Wemos D1 mini) – bestimmt Flash-Größe, PSRAM und dadurch belegte Pins.
- **Framework und Version** (ESP-IDF 5.x vs. 6.x, Arduino-Core 2.x vs. 3.x) – APIs haben sich deutlich geändert.
- **Pinbelegung und Beschaltung** der angeschlossenen Hardware: Pull-ups, Pegel (3,3 V!), Versorgung, Pegelwandler, Transceiver. Vor dem Festlegen `pin_check` laufen lassen.
- **Flash-Größe, OTA-Bedarf, Datenpartitionen** – bevor Partitionen geändert werden.

Reines Review/Refactoring ohne Hardwareänderung: fehlenden Kontext als Risiko benennen, aber im gegebenen Code-Umfang weiterarbeiten.

## Grundregeln für Firmware

- **ISR minimal**, nur ISR-sichere APIs (`…FromISR`), Arbeit per Queue/Task-Notification in Tasks verlagern. ISR und von ihr aufgerufene Funktionen in IRAM (`IRAM_ATTR`), wenn sie während Flash-Operationen laufen können.
- **Fehler prüfen:** `esp_err_t` auswerten und mit Kontext loggen; `ESP_ERROR_CHECK` nur, wo ein Abbruch wirklich gewollt ist.
- **Keine Blockade ohne Timeout;** kein Busy-Wait ohne `vTaskDelay`/`yield()` (Task-WDT, ESP8266-Soft-WDT).
- **Speicher:** Stackgrößen bewusst wählen und mit `uxTaskGetStackHighWaterMark` messen; keine großen Puffer auf dem Stack; DMA-Puffer mit `MALLOC_CAP_DMA`; Heap-Churn in heißen Pfaden vermeiden.
- **Init-Reihenfolge:** NVS → netif/Event-Loop → Wi-Fi/BLE → Treiber → Anwendungs-Tasks. Teil-Init-Fehler sauber zurückrollen.
- **Konfiguration reproduzierbar:** `sdkconfig.defaults` (ggf. `sdkconfig.defaults.<target>`) statt Klickanleitungen für menuconfig; `sdkconfig` ist generiert.
- **Partitionen passend zum Flash:** kein unerklärt ungenutzter Flash; mit OTA zwei gleich große Slots + `otadata`.
- **Logging:** stabile Tags je Modul, Zustandswechsel und Fehlercodes loggen; laute Fremdkomponenten per `esp_log_level_set` dämpfen statt global abzuschalten.
- **Secrets** nie im Code oder Repo (ESPHome: `!secret`; ESP-IDF: NVS/Provisioning; Arduino: nicht eingecheckte Header).
- **Kommentare** nur für nicht offensichtliche Timing-, Register- oder Nebenläufigkeitsdetails.

## Review-Schwerpunkte

Korrektheit vor Stil. Findings zuerst, mit Datei:Zeile, nach Schwere sortiert:
ISR-/Task-Kontext der APIs · Race Conditions auf geteiltem Zustand · Blockierende Aufrufe und Timeouts · Stack-/Heap-Risiken und Puffer-Lebensdauer über Task-Grenzen · Ressourcen-Lebenszyklus (Treiber, Sockets, Event-Handler, Semaphoren) · Pin-Konflikte, Strapping-Pins · Watchdog-Exposition · sdkconfig/Partitionen konsistent mit Flash und Features · Fehlerpfade · Log-Qualität für Felddiagnose.

## Debugging

- Phase eingrenzen: **Build → Flash → Boot → Init → Laufzeit** (bzw. Sleep/Wake, Netzwerk, Peripherie).
- Vollständigen Log ab Reset besorgen, dazu die **passende ELF**; mit `serial_log_analyze` auswerten.
- Erst instrumentieren (Logs, Zähler, Asserts, Heap-/Stack-Messung), dann ändern. Eine Änderung pro Iteration.
- Bei Hardware-Verdacht: Versorgung (Brownout!), Kabel, Pegel, Pull-ups, Strapping-Pins zuerst.
- Reichen Symptome nicht: minimales Reproduktionsbeispiel oder funktionierenden Referenzcode anfragen.

## Flashen und serielle Verbindung

- Flashen und Löschen verändern das Gerät: **vor `flash`/`upload`/`erase-flash` bestätigen lassen**, sofern der Nutzer es nicht ausdrücklich angeordnet hat. `erase-flash` löscht auch NVS (Wi-Fi-Daten, Kalibrierung). eFuse-Befehle (`espefuse`) und Security-Aktivierung sind **irreversibel** – nur nach ausdrücklicher Freigabe.
- Port mit `serial_ports` bestimmen; macOS: `/dev/cu.*`. Monitor vor dem Flashen schließen.
- Details und Fehlerbilder: `references/flashing-and-serial.md`.

## Referenzen (bei Bedarf laden)

| Thema | Datei |
|---|---|
| ESP-IDF: Projektstruktur, idf.py, Komponenten, sdkconfig, Migration 5→6 | `references/esp-idf.md` |
| Arduino-Core ESP32 (3.x) und ESP8266, arduino-cli | `references/arduino.md` |
| PlatformIO (espressif32/8266, pioarduino) | `references/platformio.md` |
| ESPHome: CLI, YAML, Framework/Toolchain, eigene Komponenten | `references/esphome.md` |
| ESP8266-Besonderheiten | `references/esp8266.md` |
| FreeRTOS, ISR, Nebenläufigkeit, Watchdogs | `references/rtos.md` |
| Peripherie: GPIO, I2C, SPI, UART, ADC, LEDC, RMT, TWAI | `references/peripherals.md` |
| Wi-Fi, BLE, MQTT, HTTP, Provisioning | `references/networking.md` |
| Partitionen, NVS, OTA, Rollback | `references/partitions-ota.md` |
| Speicher und Codegröße | `references/memory.md` |
| Low-Power, Sleep, Wakeup | `references/power.md` |
| Secure Boot, Flash-Encryption, Produktion | `references/security.md` |
| Panic-, Reset- und Log-Triage, Core-Dump, JTAG | `references/debugging.md` |
| Flashen, esptool, Boot-Modi, Verbindungsfehler | `references/flashing-and-serial.md` |

## Vorlagen

`templates/` enthält Startpunkte, die an Target, Board und Anforderungen angepasst werden müssen:
`esp-idf-app/` (main mit Fehlerbehandlung, CMake, sdkconfig.defaults), `partitions/` (OTA-Layouts 4/8/16 MB), `platformio.ini`, `esphome-device.yaml`, `arduino-sketch.yaml`.

## Ausgabeformat

- **Implementierung:** Änderung → wesentliche Entscheidungen → Validierung (Build-Ergebnis) → offene Hardwaretests.
- **Review:** Findings nach Schwere → Annahmen/offene Fragen.
- **Debugging:** wahrscheinliche Ursachen mit Belegen aus dem Log → nächster Diagnoseschritt → Fix-Vorschlag.
