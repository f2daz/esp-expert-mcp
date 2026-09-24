# Arduino core (ESP32 and ESP8266)

Get current core versions and the underlying ESP-IDF version via `framework_versions`. Check API details via Context7 `/espressif/arduino-esp32` or https://docs.espressif.com/projects/arduino-esp32/.

## arduino-esp32 core 3.x – basics

- Core 3.0 is based on ESP-IDF 5.1 (2.x on IDF 4.4). Later 3.x releases use newer IDF 5.x versions; when built as an ESP-IDF component, the master branch checks for a range of IDF 5.3 to 6.1 (as of master, verify). Get the exact core ↔ IDF mapping via `framework_versions`.
- Arduino runs as a FreeRTOS task (`loopTask`); `setup()`/`loop()` run on a task, not "bare metal". All ESP-IDF APIs are usable (`#include "esp_log.h"` etc.).
- According to the migration guide, examples < 3.0 are no longer compatible – always clarify the core version for code from forums/libraries.

## API changes 2.x → 3.0

### LEDC (PWM) – now pin-based

| 2.x (removed) | from 3.0 |
|---|---|
| `ledcSetup(ch, freq, res)` + `ledcAttachPin(pin, ch)` | `ledcAttach(pin, freq, res)` (channel assigned automatically) |
| – | `ledcAttachChannel(pin, freq, res, ch)` (explicit channel) |
| `ledcWrite(channel, duty)` | `ledcWrite(pin, duty)` |
| `ledcDetachPin(pin)` | `ledcDetach(pin)` |
| `ledcWriteTone(channel, f)` | `ledcWriteTone(pin, f)` |

```cpp
constexpr uint8_t LED = 5;
void setup() {
  if (!ledcAttach(LED, 5000, 12)) { /* error: pin/frequency/resolution */ }
}
void loop() { ledcWrite(LED, 2048); }   // 50 % at 12 bits
```
- Channels with the same frequency/resolution may share a timer – different channel numbers do not guarantee independent frequencies.

### Timer

```cpp
hw_timer_t *timer = nullptr;
volatile uint32_t ticks = 0;
void ARDUINO_ISR_ATTR onTimer() { ticks++; }

void setup() {
  timer = timerBegin(1000000);                 // from 3.0: frequency in Hz only (1 MHz)
  timerAttachInterrupt(timer, &onTimer);       // from 3.0: no edge parameter
  timerAlarm(timer, 500000, true, 0);          // 500 ms, autoreload, 0 = unlimited
}
```
- Removed: `timerAlarmWrite`, `timerAlarmEnable` (merged into `timerAlarm`); `timerBegin(num, div, up)` no longer exists.

### ADC

- `analogReadMilliVolts(pin)` returns calibrated mV (internally uses ADC oneshot + calibration).
- Removed: `analogSetClockDiv`, `adcAttachPin`, `analogSetVRefPin`.
- `hallRead()` removed (Hall sensor no longer supported).

### Other changes (selection)

- **Wi-Fi/network:** new `Network` library; events via `Network.onEvent(cb, ARDUINO_EVENT_…)` or `WiFi.onEvent(...)`. Event IDs `ARDUINO_EVENT_WIFI_STA_GOT_IP`, `ARDUINO_EVENT_WIFI_STA_DISCONNECTED` etc. (the old `SYSTEM_EVENT_*` date from core 1.x – verify for legacy code).
- `WiFiClient::flush()` no longer clears the receive buffer → `clear()`. `WiFiServer::available()` deprecated → `accept()`.
- **BLE:** returns `String` instead of `std::string`; `BLEScan::start()`/`getResults()` return `BLEScanResults*`.
- **HardwareSerial:** `setPins()` now possible before `begin()`; enum types for `setMode`/`setHwFlowCtrlMode`; default pins for UART1/UART2 on ESP32 changed – always set pins explicitly.
- **I2S** completely new (on the new IDF driver); **RMT** API new (`rmtInit` with direction and frequency); `sigmaDeltaSetup/Read` removed.

```cpp
#include <WiFi.h>
void onGotIp(arduino_event_id_t e, arduino_event_info_t info) {
  Serial.printf("IP: %s\n", IPAddress(info.got_ip.ip_info.ip.addr).toString().c_str());
}
void setup() {
  Serial.begin(115200);
  WiFi.onEvent(onGotIp, ARDUINO_EVENT_WIFI_STA_GOT_IP);
  WiFi.begin(WIFI_SSID, WIFI_PASS);   // from a secrets.h that is not checked in
}
```
Event callbacks run in the context of a system task – do nothing blocking there, hand work off to your own task/queue.

### USB CDC On Boot (S2/S3/C3/C6 …)

- Menu option `CDCOnBoot`: `cdc` = `Serial` is the native USB port, `default` = `Serial` is UART0.
- Compile defines: `ARDUINO_USB_CDC_ON_BOOT=1`, `ARDUINO_USB_MODE=1` (hardware CDC/JTAG) or `0` (TinyUSB/OTG; fixed to 0 on S2).
- With CDC On Boot, no port is present briefly after reset; early output is lost → `while (!Serial && millis() < 3000) {}` in `setup()`.
- Symptom "no output in the monitor" on S3 boards: almost always wrong `CDCOnBoot`/`USBMode` or wrong port.

## arduino-cli workflow

```bash
arduino-cli config init
arduino-cli config add board_manager.additional_urls \
  https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32            # pin the version: esp32:esp32@<version>
arduino-cli board listall esp32                  # FQBNs
arduino-cli board details -b esp32:esp32:esp32s3 # all menu options and values
arduino-cli board list                           # connected ports
```
Dev/pre-release index: `https://espressif.github.io/arduino-esp32/package_esp32_dev_index.json`.

FQBN with options (always check values with `board details`, they are board-specific):

```bash
FQBN="esp32:esp32:esp32s3:CDCOnBoot=cdc,USBMode=hwcdc,PSRAM=opi,FlashSize=16M,PartitionScheme=app3M_fat9M_16MB,DebugLevel=info"
arduino-cli compile --fqbn "$FQBN" --export-binaries .
arduino-cli upload  --fqbn "$FQBN" -p /dev/cu.usbmodem1101 .   # get confirmation first
arduino-cli monitor -p /dev/cu.usbmodem1101 -c baudrate=115200
```
- Common options: `PSRAM` (`disabled`/`enabled`/`opi` on S3), `PartitionScheme` (`default`, `huge_app`, `min_spiffs`, `no_ota`, `custom` …), `FlashSize` (`4M`, `8M`, `16M`), `FlashMode` (`qio`, `dio`, `opi` …), `DebugLevel` (`none` … `verbose`), `UploadMode`.
- Custom partition table: a `partitions.csv` in the sketch folder is used automatically instead of the predefined one; check it with `partition_validate` first.

### sketch.yaml – reproducible builds

```yaml
default_profile: s3
profiles:
  s3:
    fqbn: esp32:esp32:esp32s3:CDCOnBoot=cdc,PSRAM=opi,PartitionScheme=min_spiffs
    platforms:
      - platform: esp32:esp32 (3.x.y)          # enter the exact version
        platform_index_url: https://espressif.github.io/arduino-esp32/package_esp32_index.json
    libraries:
      - PubSubClient (2.8)
      - dir: ../libs/my_driver
    port: /dev/cu.usbmodem1101
```
- Build with `arduino-cli compile --profile s3` (`-m s3`); with `default_profile`, `arduino-cli compile` is enough.
- Required fields: `fqbn`, `platforms`. Pin versions in parentheses – otherwise builds are not reproducible.

## ESP8266 Arduino core

- Board manager URL: `https://arduino.esp8266.com/stable/package_esp8266com_index.json`, package `esp8266:esp8266`.
- FQBNs: `esp8266:esp8266:d1_mini` (LOLIN/WEMOS D1 R2 & mini), `esp8266:esp8266:nodemcuv2` (NodeMCU 1.0, ESP-12E), `esp8266:esp8266:generic`, `esp8266:esp8266:esp8285`.
- Important options: `eesz` (flash layout, e.g. `4M2M` = 4 MB with 2 MB FS), `xtal` (`80`/`160` MHz), `mmu` (cache/IRAM split), `ip` (lwIP variant), `dbg`/`lvl` (debug port/level).
  ```bash
  arduino-cli compile --fqbn esp8266:esp8266:d1_mini:eesz=4M2M,xtal=160 .
  ```
- No FreeRTOS, soft WDT, small heap – details in `references/esp8266.md`.

## Arduino as an ESP-IDF component

```bash
idf.py add-dependency "espressif/arduino-esp32^3"   # choose a version matching the IDF
```
- The component's `CMakeLists.txt` checks for compatible IDF versions during the build (aborts with "Arduino-esp32 can be used with ESP-IDF versions between …").
- With `CONFIG_AUTOSTART_ARDUINO=y`, `setup()`/`loop()` are called as usual; otherwise write your own `app_main()`:
  ```cpp
  #include "Arduino.h"
  extern "C" void app_main() {
    initArduino();
    Serial.begin(115200);
    while (true) { /* ... */ vTaskDelay(pdMS_TO_TICKS(10)); }
  }
  ```
- Arduino requires `CONFIG_FREERTOS_HZ=1000` (otherwise the build aborts) – set it in `sdkconfig.defaults`.
- When using the IDF BLE APIs directly, include `#include "esp32-hal-alloc-ble-mem.h"`, otherwise `initArduino()` releases the BLE memory.

## Common errors

| Symptom | Cause / action |
|---|---|
| `'ledcSetup' was not declared` | Code for core 2.x → switch to `ledcAttach`/`ledcWrite(pin, …)` |
| `too many/few arguments to timerBegin` | Timer API 3.0 (frequency only) |
| `Sketch too big` | Larger `PartitionScheme` (`huge_app`, `min_spiffs`) or reduce code size |
| No serial output (S2/S3/C3) | Check `CDCOnBoot`, `USBMode`, correct port |
| PSRAM not detected | `PSRAM=opi` vs. `enabled` matching the module (N16R8 = octal); `psramFound()` |
| Boot loop after flashing with OPI PSRAM/flash | Wrong `FlashMode`/`PSRAM`; check the module designation |
| `A fatal error occurred: Failed to connect` | Boot mode/cable/port – see `references/flashing-and-serial.md` |
| Library no longer compiles | Library assumes the 2.x API or IDF 4.4 headers → newer version or alternative |
| Guru Meditation in Wi-Fi callback | Blocking code in event context; move it to a task |
| Brownout reset at Wi-Fi start | Power supply too weak (USB cable/regulator); do not disable the brownout detector |

Analyze crash logs with `serial_log_analyze` and the ELF from `--export-binaries`/the build folder.

## Sources

- https://docs.espressif.com/projects/arduino-esp32/en/latest/migration_guides/2.x_to_3.0.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/ledc.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/timer.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/adc.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/network.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/esp-idf_component.html
- https://github.com/espressif/arduino-esp32/blob/master/boards.txt (menu options)
- https://github.com/espressif/arduino-esp32/blob/master/CMakeLists.txt (IDF version check)
- https://arduino.github.io/arduino-cli/latest/sketch-project-file/
- https://arduino-esp8266.readthedocs.io/en/latest/installing.html
- https://github.com/esp8266/Arduino/blob/master/boards.txt
