# ESPHome

YAML-based firmware for ESP32/ESP8266 (among others), tightly integrated with Home Assistant. ESPHome changes defaults frequently – determine the installed version with `esphome version` or `framework_versions`, check the configuration with `esphome_lint` (static, incl. pin check) and `esphome_validate` (real `esphome config`).

## Installation

- **Home Assistant:** as the app/add-on "ESPHome Device Builder" (Settings → Apps).
- **Docker:**
  ```bash
  docker run --rm --net=host -v "${PWD}":/config -it ghcr.io/esphome/esphome
  ```
  Web UI at `http://localhost:6052`.
- **Python/pip** (from ESPHome 2026.7: **Python ≥ 3.12**):
  ```bash
  pip install esphome                                  # CLI only
  pip install "esphome-device-builder[esphome]"        # with web UI
  esphome-device-builder config                        # start the UI (config folder)
  ```
  Alternatively isolated with `pipx install esphome` or `uv tool install esphome`, or one-off with `uvx esphome config device.yaml` (not mentioned in the official docs; `uvx` tested with ESPHome 2026.9.0).
- **Desktop apps** (Windows/macOS/Linux) with their own Python environment.
- **From 2026.7:** the built-in dashboard (`esphome dashboard`) is removed → separate package `esphome-device-builder`. Docker/HA users are not affected.

## CLI

| Command | Purpose |
|---|---|
| `esphome wizard device.yaml` | Create a new configuration interactively |
| `esphome config device.yaml` | Validate, print the resolved config (`--show-secrets` only locally) |
| `esphome compile device.yaml` | Build only |
| `esphome upload device.yaml --device /dev/cu.usbserial-0001` | Flash the last build (serial or OTA) – get confirmation |
| `esphome run device.yaml` | Validate, build, flash, logs |
| `esphome run device.yaml --device OTA --no-logs` | OTA without log view |
| `esphome logs device.yaml --device 192.168.1.50` | Logs via API or serial |
| `esphome clean device.yaml` / `esphome clean-all` | Delete build files (mandatory after a framework/toolchain change) |
| `esphome -s name value compile device.yaml` | Override a substitution via CLI |

`--device` accepts a serial port, IP/hostname or `OTA`.

## Basic structure

```yaml
substitutions:
  name: basement-sensor
  friendly_name: Basement Sensor

esphome:
  name: ${name}
  friendly_name: ${friendly_name}

esp32:
  variant: esp32c6          # or board: esp32-c6-devkitc-1
  flash_size: 4MB
  framework:
    type: esp-idf           # default for ESP32 from 2026.1
  # toolchain: esp-idf      # default from 2026.7; platformio = legacy behavior (deprecated)

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  ap:                       # fallback hotspot
    password: !secret fallback_ap_password

captive_portal:

api:
  encryption:
    key: !secret api_key    # 32 bytes, base64; `esphome wizard` generates one

ota:
  - platform: esphome
    encryption:             # from 2026.9: without key → uses the api encryption key

logger:
  level: DEBUG
```

ESP8266:

```yaml
esp8266:
  board: d1_mini
  restore_from_flash: false   # mind flash wear
```

`secrets.yaml` sits next to the device files and is not checked in.

### Securing OTA

- **From ESPHome 2026.9:** `encryption:` under `ota: - platform: esphome` encrypts OTA with the same Noise protocol as the native API.
  - Without `key`, the `api:` encryption key is used.
  - Without an `api:` block, set your own key:
    ```yaml
    ota:
      - platform: esphome
        encryption:
          key: !secret ota_key
    ```
  - Cannot be combined with `password`. ESPHome recommends `encryption` over `password` (validation warns; according to the warning, `password` costs about 3.5 KB of flash).
  - Devices with older firmware do not understand this yet: when switching, first install firmware ≥ 2026.9, then switch to `encryption` (verify the exact transition path via OTA; serially flashed devices can carry `encryption:` from the start).
- **Variant for ESPHome < 2026.9:**
  ```yaml
  ota:
    - platform: esphome
      password: !secret ota_password
  ```
- Since 2026.1: API password authentication and OTA MD5 authentication removed – only `api: encryption` or OTA password remain, and from 2026.9 OTA encryption.
- Default OTA ports: ESP32 3232, ESP8266 8266.

## Framework and toolchain – changes in 2026

| Version | Change | Consequence |
|---|---|---|
| 2026.1 | **ESP-IDF is the default framework for ESP32** | Configs without `framework:` build with IDF; Arduino only with `framework: type: arduino` |
| 2026.1 | `custom_components` folder deprecated | switch to `external_components` |
| 2026.2 | Unused ESP-IDF components are excluded from the build (shorter build time) | If your own/external code needs an IDF component: `esp32: framework: advanced: include_builtin_idf_components: [esp_http_client, …]` |
| 2026.2 | Default certificate bundle reduced to the CMN variant | check for TLS errors with exotic CAs |
| 2026.7 | **Native ESP-IDF toolchain is the default** (instead of PlatformIO) | Legacy behavior with `esp32: toolchain: platformio` (deprecated, removal in 2027.2 according to the docs) |
| 2026.7 | `packages: !include file.yaml` invalid | List syntax: `packages: [!include file.yaml]` |
| 2026.7 | Python ≥ 3.12, dashboard → `esphome-device-builder` | update pip installations |
| 2026.9 | OTA encryption | see above |

Always check the current status and further breaking changes in the changelog of the installed version (https://esphome.io/changelog/). 2026.9 includes, among others, breaking changes in `modbus_controller` (`custom_command` → `custom_pdu`).

### Arduino-only components and replacements

| Arduino-only | Replacement under ESP-IDF |
|---|---|
| `neopixelbus`, `fastled_clockless` | `esp32_rmt_led_strip` |
| `fastled_spi` | `spi_led_strip` |
| `bme680_bsec` | `bme68x_bsec2` |
| `heatpumpir`, `midea`, WLED effect | no replacement → keep `framework: type: arduino` |

Arduino under ESPHome runs as a component on ESP-IDF: longer build times, more memory. Migration steps: `esphome clean`, `framework: type: esp-idf`, work through messages about incompatible components, rebuild, test on hardware.

## Structuring

**Substitutions** – `${name}`; can be overridden via CLI with `-s`.

**Packages** (from 2026.7 list syntax for `!include`):
```yaml
packages:
  - !include common/base.yaml
  - !include
    file: common/relay.yaml
    vars:
      relay_pin: GPIO4
  - github://org/esphome-configs/common/wifi.yaml@v1.2.0   # pin the ref
```
Merging: dicts key by key, component lists by `id`, later values win. Adjust with `!extend <id>`, remove with `!remove`.

**!include** for individual blocks: `sensor: !include sensors.yaml`.

**External components:**
```yaml
external_components:
  - source: github://org/esphome-components@v0.3.1
    components: [my_sensor]
    refresh: never           # with a tag reference
  - source:
      type: local
      path: my_components     # components/<name>/__init__.py
```

## Lambdas (C++)

```yaml
sensor:
  - platform: adc
    pin: GPIO2
    id: vbat
    attenuation: 12db
    update_interval: 30s
    filters:
      - lambda: return x * 2.0;          # 1:1 voltage divider

binary_sensor:
  - platform: template
    name: "Battery low"
    lambda: |-
      if (isnan(id(vbat).state)) return {};
      return id(vbat).state < 3.3;
```
- Access other components via `id(...)`; state via `.state`.
- Logging: `ESP_LOGD("tag", "Value: %.2f", x);`
- Lambdas run in the main loop: nothing blocking (no `delay()` beyond a few ms), otherwise watchdog/API disconnects. For waits, use the `delay:` action in automations.
- Shared state via `globals:` instead of static variables.

## Debugging

- `logger: level: VERBOSE` (or `VERY_VERBOSE`) temporarily; quiet individual components with `logs: { component: WARN }`.
- Serial logs disabled/redirected: `logger: baud_rate: 0` frees the UART – then logs only via API.
- `debug:` component:
  ```yaml
  debug:
    update_interval: 30s
  text_sensor:
    - platform: debug
      reset_reason:
        name: "Reset reason"
  sensor:
    - platform: debug
      free:
        name: "Heap free"
      block:
        name: "Heap largest block"
      loop_time:
        name: "Loop time"
  ```
- Analyze crash backtraces from `esphome logs` with `serial_log_analyze` and the ELF from `.esphome/build/<name>/` (verify the path per toolchain).
- "Component took a long time for an operation" → blocking code in a lambda/component.

## Pin check

- Run `esphome_lint` before hardware changes: detects strapping pins, flash/PSRAM pins, ADC2 with Wi-Fi active, pins assigned twice. Then `esphome_validate`.
- Intentional multiple use of a pin: `allow_other_uses: true` on the pin schema (verify, per component).
- Do not blanket-ignore strapping pin warnings – clarify the circuitry at boot (`pin_check`).

## Sources

- https://esphome.io/install/
- https://esphome.io/install/getting-started/
- https://esphome.io/guides/cli/
- https://esphome.io/blog/2026/07/15/esphome-2026-7/
- https://esphome.io/guides/esp32_arduino_to_idf/
- https://esphome.io/changelog/2026.1.0/
- https://esphome.io/changelog/2026.2.0/
- https://esphome.io/changelog/2026.9.0/
- https://esphome.io/components/esp32/
- https://esphome.io/components/ota/esphome/
- https://esphome.io/components/packages/
- https://esphome.io/components/external_components/
- https://esphome.io/components/debug/
