# Arduino-Core (ESP32 und ESP8266)

Aktuelle Core-Versionen und die zugrunde liegende ESP-IDF-Version über `framework_versions` holen. API-Details über Context7 `/espressif/arduino-esp32` oder https://docs.espressif.com/projects/arduino-esp32/ prüfen.

## arduino-esp32 Core 3.x – Grundlagen

- Core 3.0 basiert auf ESP-IDF 5.1 (2.x auf IDF 4.4). Spätere 3.x-Releases nutzen neuere IDF-5.x-Stände; der Master-Zweig prüft beim Build als ESP-IDF-Komponente einen Bereich von IDF 5.3 bis 6.1 (Stand Master, prüfen). Die konkrete Zuordnung Core ↔ IDF über `framework_versions`.
- Arduino läuft als FreeRTOS-Task (`loopTask`); `setup()`/`loop()` laufen auf einem Task, nicht „bare metal“. Alle ESP-IDF-APIs sind nutzbar (`#include "esp_log.h"` usw.).
- Beispiele < 3.0 sind laut Migration Guide nicht mehr kompatibel – bei Code aus Foren/Bibliotheken immer Core-Version klären.

## API-Änderungen 2.x → 3.0

### LEDC (PWM) – jetzt pinbasiert

| 2.x (entfernt) | ab 3.0 |
|---|---|
| `ledcSetup(ch, freq, res)` + `ledcAttachPin(pin, ch)` | `ledcAttach(pin, freq, res)` (Kanal automatisch) |
| – | `ledcAttachChannel(pin, freq, res, ch)` (Kanal explizit) |
| `ledcWrite(channel, duty)` | `ledcWrite(pin, duty)` |
| `ledcDetachPin(pin)` | `ledcDetach(pin)` |
| `ledcWriteTone(channel, f)` | `ledcWriteTone(pin, f)` |

```cpp
constexpr uint8_t LED = 5;
void setup() {
  if (!ledcAttach(LED, 5000, 12)) { /* Fehler: Pin/Frequenz/Auflösung */ }
}
void loop() { ledcWrite(LED, 2048); }   // 50 % bei 12 Bit
```
- Kanäle mit gleicher Frequenz/Auflösung teilen sich ggf. einen Timer – unterschiedliche Kanalnummern garantieren keine unabhängigen Frequenzen.

### Timer

```cpp
hw_timer_t *timer = nullptr;
volatile uint32_t ticks = 0;
void ARDUINO_ISR_ATTR onTimer() { ticks++; }

void setup() {
  timer = timerBegin(1000000);                 // ab 3.0: nur Frequenz in Hz (1 MHz)
  timerAttachInterrupt(timer, &onTimer);       // ab 3.0: kein edge-Parameter
  timerAlarm(timer, 500000, true, 0);          // 500 ms, autoreload, 0 = unbegrenzt
}
```
- Entfernt: `timerAlarmWrite`, `timerAlarmEnable` (in `timerAlarm` zusammengefasst); `timerBegin(num, div, up)` gibt es nicht mehr.

### ADC

- `analogReadMilliVolts(pin)` liefert kalibrierte mV (nutzt intern ADC-oneshot + Kalibrierung).
- Entfernt: `analogSetClockDiv`, `adcAttachPin`, `analogSetVRefPin`.
- `hallRead()` entfernt (Hall-Sensor nicht mehr unterstützt).

### Weitere Änderungen (Auswahl)

- **Wi-Fi/Netzwerk:** neue `Network`-Bibliothek; Events über `Network.onEvent(cb, ARDUINO_EVENT_…)` bzw. `WiFi.onEvent(...)`. Event-IDs `ARDUINO_EVENT_WIFI_STA_GOT_IP`, `ARDUINO_EVENT_WIFI_STA_DISCONNECTED` usw. (die alten `SYSTEM_EVENT_*` stammen aus Core 1.x – prüfen, falls Altcode).
- `WiFiClient::flush()` leert den Empfangspuffer nicht mehr → `clear()`. `WiFiServer::available()` deprecated → `accept()`.
- **BLE:** Rückgabe `String` statt `std::string`; `BLEScan::start()`/`getResults()` liefern `BLEScanResults*`.
- **HardwareSerial:** `setPins()` jetzt vor `begin()` möglich; Enum-Typen für `setMode`/`setHwFlowCtrlMode`; Standardpins UART1/UART2 auf ESP32 geändert – Pins immer explizit setzen.
- **I2S** komplett neu (auf neuem IDF-Treiber); **RMT** API neu (`rmtInit` mit Richtung und Frequenz); `sigmaDeltaSetup/Read` entfernt.

```cpp
#include <WiFi.h>
void onGotIp(arduino_event_id_t e, arduino_event_info_t info) {
  Serial.printf("IP: %s\n", IPAddress(info.got_ip.ip_info.ip.addr).toString().c_str());
}
void setup() {
  Serial.begin(115200);
  WiFi.onEvent(onGotIp, ARDUINO_EVENT_WIFI_STA_GOT_IP);
  WiFi.begin(WIFI_SSID, WIFI_PASS);   // aus nicht eingechecktem secrets.h
}
```
Event-Callbacks laufen im Kontext eines System-Tasks – dort nichts Blockierendes tun, Arbeit an eigenen Task/Queue übergeben.

### USB CDC On Boot (S2/S3/C3/C6 …)

- Menüoption `CDCOnBoot`: `cdc` = `Serial` ist der native USB-Port, `default` = `Serial` ist UART0.
- Compile-Defines: `ARDUINO_USB_CDC_ON_BOOT=1`, `ARDUINO_USB_MODE=1` (Hardware-CDC/JTAG) bzw. `0` (TinyUSB/OTG; auf S2 fest 0).
- Mit CDC On Boot erscheint nach Reset kurz kein Port; frühe Ausgaben gehen verloren → `while (!Serial && millis() < 3000) {}` in `setup()`.
- Symptom „keine Ausgabe im Monitor“ auf S3-Boards: fast immer falscher `CDCOnBoot`/`USBMode` oder falscher Port.

## arduino-cli-Workflow

```bash
arduino-cli config init
arduino-cli config add board_manager.additional_urls \
  https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32            # Version pinnen: esp32:esp32@<version>
arduino-cli board listall esp32                  # FQBNs
arduino-cli board details -b esp32:esp32:esp32s3 # alle Menüoptionen und Werte
arduino-cli board list                           # angeschlossene Ports
```
Dev-/Pre-Release-Index: `https://espressif.github.io/arduino-esp32/package_esp32_dev_index.json`.

FQBN mit Optionen (Werte immer mit `board details` prüfen, sie sind boardspezifisch):

```bash
FQBN="esp32:esp32:esp32s3:CDCOnBoot=cdc,USBMode=hwcdc,PSRAM=opi,FlashSize=16M,PartitionScheme=app3M_fat9M_16MB,DebugLevel=info"
arduino-cli compile --fqbn "$FQBN" --export-binaries .
arduino-cli upload  --fqbn "$FQBN" -p /dev/cu.usbmodem1101 .   # vorher bestätigen lassen
arduino-cli monitor -p /dev/cu.usbmodem1101 -c baudrate=115200
```
- Häufige Optionen: `PSRAM` (`disabled`/`enabled`/`opi` auf S3), `PartitionScheme` (`default`, `huge_app`, `min_spiffs`, `no_ota`, `custom` …), `FlashSize` (`4M`, `8M`, `16M`), `FlashMode` (`qio`, `dio`, `opi` …), `DebugLevel` (`none` … `verbose`), `UploadMode`.
- Eigene Partitionstabelle: `partitions.csv` im Sketch-Ordner wird automatisch statt der vordefinierten verwendet; vorher mit `partition_validate` prüfen.

### sketch.yaml – reproduzierbare Builds

```yaml
default_profile: s3
profiles:
  s3:
    fqbn: esp32:esp32:esp32s3:CDCOnBoot=cdc,PSRAM=opi,PartitionScheme=min_spiffs
    platforms:
      - platform: esp32:esp32 (3.x.y)          # exakte Version eintragen
        platform_index_url: https://espressif.github.io/arduino-esp32/package_esp32_index.json
    libraries:
      - PubSubClient (2.8)
      - dir: ../libs/mein_treiber
    port: /dev/cu.usbmodem1101
```
- Bauen mit `arduino-cli compile --profile s3` (`-m s3`); mit `default_profile` reicht `arduino-cli compile`.
- Pflichtfelder: `fqbn`, `platforms`. Versionen in Klammern pinnen – sonst sind Builds nicht reproduzierbar.

## ESP8266-Arduino-Core

- Boardverwalter-URL: `https://arduino.esp8266.com/stable/package_esp8266com_index.json`, Paket `esp8266:esp8266`.
- FQBNs: `esp8266:esp8266:d1_mini` (LOLIN/WEMOS D1 R2 & mini), `esp8266:esp8266:nodemcuv2` (NodeMCU 1.0, ESP-12E), `esp8266:esp8266:generic`, `esp8266:esp8266:esp8285`.
- Wichtige Optionen: `eesz` (Flash-Layout, z. B. `4M2M` = 4 MB mit 2 MB FS), `xtal` (`80`/`160` MHz), `mmu` (Cache/IRAM-Aufteilung), `ip` (lwIP-Variante), `dbg`/`lvl` (Debug-Port/-Level).
  ```bash
  arduino-cli compile --fqbn esp8266:esp8266:d1_mini:eesz=4M2M,xtal=160 .
  ```
- Kein FreeRTOS, Soft-WDT, kleiner Heap – Details in `references/esp8266.md`.

## Arduino als ESP-IDF-Komponente

```bash
idf.py add-dependency "espressif/arduino-esp32^3"   # Version zum IDF passend wählen
```
- Kompatible IDF-Versionen prüft das `CMakeLists.txt` der Komponente beim Build (Abbruch mit „Arduino-esp32 can be used with ESP-IDF versions between …“).
- Mit `CONFIG_AUTOSTART_ARDUINO=y` werden `setup()`/`loop()` wie gewohnt aufgerufen; sonst eigenes `app_main()`:
  ```cpp
  #include "Arduino.h"
  extern "C" void app_main() {
    initArduino();
    Serial.begin(115200);
    while (true) { /* ... */ vTaskDelay(pdMS_TO_TICKS(10)); }
  }
  ```
- Arduino verlangt `CONFIG_FREERTOS_HZ=1000` (Build bricht sonst ab) – in `sdkconfig.defaults` setzen.
- Beim direkten Nutzen der IDF-BLE-APIs `#include "esp32-hal-alloc-ble-mem.h"` einbinden, sonst gibt `initArduino()` BLE-Speicher frei.

## Typische Fehler

| Symptom | Ursache / Maßnahme |
|---|---|
| `'ledcSetup' was not declared` | Code für Core 2.x → auf `ledcAttach`/`ledcWrite(pin, …)` umstellen |
| `too many/few arguments to timerBegin` | Timer-API 3.0 (nur Frequenz) |
| `Sketch too big` | Größeres `PartitionScheme` (`huge_app`, `min_spiffs`) oder Code verkleinern |
| Keine serielle Ausgabe (S2/S3/C3) | `CDCOnBoot`, `USBMode`, richtigen Port prüfen |
| PSRAM wird nicht erkannt | `PSRAM=opi` vs. `enabled` passend zum Modul (N16R8 = Octal); `psramFound()` |
| Boot-Loop nach Flash mit OPI-PSRAM/Flash | falscher `FlashMode`/`PSRAM`; Modulbezeichnung prüfen |
| `A fatal error occurred: Failed to connect` | Bootmodus/Kabel/Port – siehe `references/flashing-and-serial.md` |
| Bibliothek kompiliert nicht mehr | Bibliothek setzt 2.x-API oder IDF-4.4-Header voraus → neuere Version oder Alternative |
| Guru Meditation im Wi-Fi-Callback | Blockierender Code im Event-Kontext; in Task auslagern |
| Brownout-Reset beim Wi-Fi-Start | Versorgung zu schwach (USB-Kabel/Regler); nicht Brownout-Detector abschalten |

Crash-Logs mit `serial_log_analyze` und der ELF aus `--export-binaries`/Build-Ordner auswerten.

## Quellen

- https://docs.espressif.com/projects/arduino-esp32/en/latest/migration_guides/2.x_to_3.0.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/ledc.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/timer.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/adc.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/network.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/esp-idf_component.html
- https://github.com/espressif/arduino-esp32/blob/master/boards.txt (Menüoptionen)
- https://github.com/espressif/arduino-esp32/blob/master/CMakeLists.txt (IDF-Versionsprüfung)
- https://arduino.github.io/arduino-cli/latest/sketch-project-file/
- https://arduino-esp8266.readthedocs.io/en/latest/installing.html
- https://github.com/esp8266/Arduino/blob/master/boards.txt
