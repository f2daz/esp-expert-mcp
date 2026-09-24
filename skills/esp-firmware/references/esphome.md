# ESPHome

YAML-basierte Firmware für ESP32/ESP8266 (u. a.), eng mit Home Assistant verzahnt. ESPHome ändert Defaults häufig – installierte Version mit `esphome version` bzw. `framework_versions` klären, Konfiguration mit `esphome_lint` (statisch, inkl. Pinprüfung) und `esphome_validate` (echtes `esphome config`) prüfen.

## Installation

- **Home Assistant:** als App/Add-on „ESPHome Device Builder“ (Einstellungen → Apps).
- **Docker:**
  ```bash
  docker run --rm --net=host -v "${PWD}":/config -it ghcr.io/esphome/esphome
  ```
  Web-Oberfläche unter `http://localhost:6052`.
- **Python/pip** (ab ESPHome 2026.7: **Python ≥ 3.12**):
  ```bash
  pip install esphome                                  # nur CLI
  pip install "esphome-device-builder[esphome]"        # mit Web-Oberfläche
  esphome-device-builder config                        # Oberfläche starten (Konfig-Ordner)
  ```
  Alternativ isoliert mit `pipx install esphome` oder `uv tool install esphome` (nicht in der offiziellen Doku genannt, prüfen).
- **Desktop-Apps** (Windows/macOS/Linux) mit eigener Python-Umgebung.
- **Ab 2026.7:** das eingebaute Dashboard (`esphome dashboard`) ist entfernt → separates Paket `esphome-device-builder`. Docker/HA-Nutzer sind nicht betroffen.

## CLI

| Befehl | Zweck |
|---|---|
| `esphome wizard geraet.yaml` | Neue Konfiguration interaktiv anlegen |
| `esphome config geraet.yaml` | Validieren, aufgelöste Konfig ausgeben (`--show-secrets` nur lokal) |
| `esphome compile geraet.yaml` | Nur bauen |
| `esphome upload geraet.yaml --device /dev/cu.usbserial-0001` | Letzten Build flashen (seriell oder OTA) – bestätigen lassen |
| `esphome run geraet.yaml` | Validieren, bauen, flashen, Logs |
| `esphome run geraet.yaml --device OTA --no-logs` | OTA ohne Logansicht |
| `esphome logs geraet.yaml --device 192.168.1.50` | Logs per API bzw. seriell |
| `esphome clean geraet.yaml` / `esphome clean-all` | Build-Dateien löschen (nach Framework-/Toolchain-Wechsel Pflicht) |
| `esphome -s name wert compile geraet.yaml` | Substitution per CLI überschreiben |

`--device` akzeptiert seriellen Port, IP/Hostname oder `OTA`.

## Grundstruktur

```yaml
substitutions:
  name: sensor-keller
  friendly_name: Sensor Keller

esphome:
  name: ${name}
  friendly_name: ${friendly_name}

esp32:
  variant: esp32c6          # oder board: esp32-c6-devkitc-1
  flash_size: 4MB
  framework:
    type: esp-idf           # ab 2026.1 Standard für ESP32
  # toolchain: esp-idf      # ab 2026.7 Standard; platformio = Altverhalten (deprecated)

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  ap:                       # Fallback-Hotspot
    password: !secret fallback_ap_password

captive_portal:

api:
  encryption:
    key: !secret api_key    # 32 Byte, base64; `esphome wizard` erzeugt einen

ota:
  - platform: esphome
    encryption:             # ab 2026.9: ohne key → nutzt api-encryption-key

logger:
  level: DEBUG
```

ESP8266:

```yaml
esp8266:
  board: d1_mini
  restore_from_flash: false   # Flash-Verschleiß beachten
```

`secrets.yaml` liegt neben den Gerätedateien und wird nicht eingecheckt.

### OTA-Absicherung

- **Ab ESPHome 2026.9:** `encryption:` unter `ota: - platform: esphome` verschlüsselt OTA mit demselben Noise-Protokoll wie die native API.
  - Ohne `key` wird der `api:`-Encryption-Key verwendet.
  - Ohne `api:`-Block eigenen Schlüssel setzen:
    ```yaml
    ota:
      - platform: esphome
        encryption:
          key: !secret ota_key
    ```
  - Nicht mit `password` kombinierbar. ESPHome empfiehlt `encryption` statt `password` (Validierung warnt; `password` kostet laut Warnung ca. 3,5 KB Flash).
  - Geräte mit älterer Firmware verstehen das noch nicht: beim Umstieg zuerst eine Firmware ≥ 2026.9 aufspielen, dann auf `encryption` wechseln (genauen Übergangsweg per OTA prüfen; seriell geflashte Geräte können `encryption:` von Anfang an tragen).
- **Variante für ESPHome < 2026.9:**
  ```yaml
  ota:
    - platform: esphome
      password: !secret ota_password
  ```
- Seit 2026.1: API-Passwort-Authentifizierung und OTA-MD5-Authentifizierung entfernt – nur noch `api: encryption` bzw. OTA-Passwort, ab 2026.9 OTA-Encryption.
- OTA-Standardports: ESP32 3232, ESP8266 8266.

## Framework und Toolchain – Änderungen 2026

| Version | Änderung | Folge |
|---|---|---|
| 2026.1 | **ESP-IDF ist Standard-Framework für ESP32** | Konfigs ohne `framework:` bauen mit IDF; Arduino nur mit `framework: type: arduino` |
| 2026.1 | `custom_components`-Ordner deprecated | auf `external_components` umstellen |
| 2026.2 | Ungenutzte ESP-IDF-Komponenten werden vom Build ausgeschlossen (kürzere Buildzeit) | Braucht eigener/externer Code eine IDF-Komponente: `esp32: framework: advanced: include_builtin_idf_components: [esp_http_client, …]` |
| 2026.2 | Standard-Zertifikatsbundle auf CMN-Variante verkleinert | bei TLS-Fehlern zu exotischen CAs prüfen |
| 2026.7 | **Native ESP-IDF-Toolchain ist Standard** (statt PlatformIO) | Altverhalten mit `esp32: toolchain: platformio` (deprecated, Entfernung laut Doku 2027.2) |
| 2026.7 | `packages: !include datei.yaml` ungültig | Listen-Syntax: `packages: [!include datei.yaml]` |
| 2026.7 | Python ≥ 3.12, Dashboard → `esphome-device-builder` | pip-Installationen aktualisieren |
| 2026.9 | OTA-Encryption | siehe oben |

Aktuellen Stand und weitere Breaking Changes immer im Changelog der installierten Version prüfen (https://esphome.io/changelog/). 2026.9 enthält u. a. Breaking Changes bei `modbus_controller` (`custom_command` → `custom_pdu`).

### Arduino-only-Komponenten und Ersatz

| Arduino-only | Ersatz unter ESP-IDF |
|---|---|
| `neopixelbus`, `fastled_clockless` | `esp32_rmt_led_strip` |
| `fastled_spi` | `spi_led_strip` |
| `bme680_bsec` | `bme68x_bsec2` |
| `heatpumpir`, `midea`, WLED-Effekt | kein Ersatz → `framework: type: arduino` beibehalten |

Arduino unter ESPHome läuft als Komponente auf ESP-IDF: längere Buildzeiten, mehr Speicher. Migrationsschritte: `esphome clean`, `framework: type: esp-idf`, Meldungen zu inkompatiblen Komponenten abarbeiten, neu bauen, auf Hardware testen.

## Strukturierung

**Substitutions** – `${name}`; per CLI mit `-s` überschreibbar.

**Packages** (ab 2026.7 Listen-Syntax für `!include`):
```yaml
packages:
  - !include common/base.yaml
  - !include
    file: common/relay.yaml
    vars:
      relay_pin: GPIO4
  - github://org/esphome-configs/common/wifi.yaml@v1.2.0   # Ref pinnen
```
Zusammenführung: Dicts schlüsselweise, Komponentenlisten nach `id`, spätere Werte gewinnen. Anpassen mit `!extend <id>`, entfernen mit `!remove`.

**!include** für einzelne Blöcke: `sensor: !include sensors.yaml`.

**External Components:**
```yaml
external_components:
  - source: github://org/esphome-components@v0.3.1
    components: [my_sensor]
    refresh: never           # bei Tag-Referenz
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
      - lambda: return x * 2.0;          # Spannungsteiler 1:1

binary_sensor:
  - platform: template
    name: "Akku schwach"
    lambda: |-
      if (isnan(id(vbat).state)) return {};
      return id(vbat).state < 3.3;
```
- Zugriff auf andere Komponenten über `id(...)`; Zustand über `.state`.
- Logging: `ESP_LOGD("tag", "Wert: %.2f", x);`
- Lambdas laufen in der Hauptschleife: nichts Blockierendes (kein `delay()` über wenige ms), sonst Watchdog/API-Abbrüche. Für Wartezeiten `delay:`-Aktion in Automationen.
- Gemeinsamer Zustand über `globals:` statt statischer Variablen.

## Debugging

- `logger: level: VERBOSE` (bzw. `VERY_VERBOSE`) temporär; einzelne Komponenten dämpfen mit `logs: { component: WARN }`.
- Serielle Logs deaktiviert/umgeleitet: `logger: baud_rate: 0` gibt UART frei – dann nur Logs über API.
- `debug:`-Komponente:
  ```yaml
  debug:
    update_interval: 30s
  text_sensor:
    - platform: debug
      reset_reason:
        name: "Reset-Grund"
  sensor:
    - platform: debug
      free:
        name: "Heap frei"
      block:
        name: "Heap größter Block"
      loop_time:
        name: "Loop-Zeit"
  ```
- Crash-Backtraces aus `esphome logs` mit `serial_log_analyze` und der ELF aus `.esphome/build/<name>/` auswerten (Pfad je Toolchain prüfen).
- „Component took a long time for an operation“ → blockierender Code in Lambda/Komponente.

## Pinprüfung

- Vor Hardware-Änderungen `esphome_lint` laufen lassen: erkennt Strapping-Pins, Flash-/PSRAM-Pins, ADC2 bei aktivem Wi-Fi, doppelt belegte Pins. Danach `esphome_validate`.
- Bewusste Mehrfachnutzung eines Pins: `allow_other_uses: true` am Pin-Schema (prüfen, je Komponente).
- Strapping-Pin-Warnungen nicht pauschal ignorieren – Beschaltung beim Booten klären (`pin_check`).

## Quellen

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
