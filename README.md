# esp-expert

Claude-Code-Plugin für die Firmwareentwicklung auf Espressif-Chips (ESP8266, ESP32, ESP32-S2/S3, C2/C3/C5/C6, H2, P4). Es besteht aus zwei Teilen:

- **Skill `esp-firmware`** mit der Arbeitsweise (erst Hardware klären, Konfiguration als Quelltext behandeln, erst nach erfolgreichem Build „fertig“ melden) und Fachreferenzen zu ESP-IDF, Arduino-Core, PlatformIO, ESPHome, ESP8266, FreeRTOS, Peripherie, Netzwerk, OTA, Speicher, Low-Power, Security, Debugging und Flashen, dazu Vorlagen.
- **MCP-Server `esp-expert`** (Python, MCP-SDK 2.x) mit deterministischen Prüfwerkzeugen. Wo sich Daten ändern, fragt er live ab und rät keine Werte.

## Werkzeuge

| Tool | Zweck |
|---|---|
| `chip_info` | SoC-Stammdaten: Kerne, RAM, Funk, USB, Strapping-, Flash- und Input-only-Pins, ADC, Touch, RTC-GPIO, Quellen |
| `pin_check` | Prüft eine geplante GPIO-Belegung (Flash/PSRAM, Strapping, Input-only, USB, UART0, ADC2 + Wi-Fi, Doppelbelegung) |
| `partition_validate` | Partitions-CSV: Ausrichtung, Überlappung, OTA-Layout, otadata/NVS, Flash-Größe, Reserve zum App-Binary |
| `serial_log_analyze` | Reset-Grund, Guru Meditation, EXCCAUSE/MCAUSE, Stack-Overflow, WDT, Brownout, ESP8266-Exceptions; Backtrace per addr2line |
| `esp_err_lookup` | esp_err_t → Name und Beschreibung (aus lokalem `$IDF_PATH` oder dem ESP-IDF-Repo) |
| `sdkconfig_analyze` / `sdkconfig_get` | Zusammenfassung, riskante Einstellungen, Abweichungen zu `sdkconfig.defaults` |
| `platformio_analyze` | `platformio.ini`: Environments, Plattform-Quelle und Pinning, Board → Chip, Partitionen, Artefakte |
| `esphome_lint` / `esphome_validate` | ESPHome-YAML statisch prüfen bzw. per `esphome config` validieren |
| `serial_ports` / `chip_probe` | Ports mit USB-Bridge-Erkennung; Chip, Flash und MAC per esptool (nur lesend) |
| `framework_versions` / `idf_target_support` | Aktuelle Releases (GitHub, semantisch sortiert), IDF-Versionen je Target |

Geräte beschreiben (flash, erase, eFuse) kann der Server bewusst nicht. Das läuft über `idf.py`, `pio`, `arduino-cli`, `esphome` oder `esptool` in der Shell, jeweils nach Rückfrage.

## Installation

Voraussetzung: [uv](https://docs.astral.sh/uv/). Python ≥ 3.11 installiert uv bei Bedarf selbst.

```bash
# in Claude Code
/plugin marketplace add /pfad/zu/esp-expert-mcp
/plugin install esp-expert@esp-expert
```

Nur zum Ausprobieren, ohne Installation:

```bash
claude --plugin-dir /pfad/zu/esp-expert-mcp
```

MCP-Server einzeln, etwa für Claude Desktop oder andere MCP-Clients:

```json
{
  "mcpServers": {
    "esp-expert": {
      "command": "uv",
      "args": ["run", "--quiet", "--directory", "/pfad/zu/esp-expert-mcp/server", "esp-expert-mcp"]
    }
  }
}
```

Optionale Umgebungsvariablen:
- `IDF_PATH`: Die Fehlercodes kommen dann aus der installierten ESP-IDF-Version.
- `GITHUB_TOKEN`: Hebt das GitHub-Rate-Limit für `framework_versions` an.

Optionale Werkzeuge auf dem Rechner:
- `esptool` für `chip_probe`
- `esphome` (oder uvx) für `esphome_validate`
- eine ESP-Toolchain (`*-addr2line`) zum Dekodieren von Backtraces

## Entwicklung

```bash
cd server
uv run --group dev pytest        # Tests
claude plugin validate ..        # Manifeste prüfen
```

Chip-Daten: `server/src/esp_expert_mcp/data/chips.json`. Sie stammen aus den ESP-IDF-Seiten „GPIO & RTC GPIO“ und den Datenblättern von Espressif, die Quellen stehen je Chip im Feld `sources`. Wo sich Datenblatt und IDF-Doku widersprechen (ESP32-C5 und ESP32-H2 bei den Strapping-Pins), sind beide Angaben in `notes` bzw. `strapping_pins` vermerkt. Für den ESP32-P4 gibt es bisher nur ein Pre-release-Datenblatt.

## Herkunft

Als Ideengeber dienten [adamlipecz/esp32-firmware-engineer-skill](https://github.com/adamlipecz/esp32-firmware-engineer-skill) (ESP-IDF, strenge Blocker-Regeln), [onigetoc/esp32-skill](https://github.com/onigetoc/esp32-skill) (Arduino-CLI-Workflow) und die [ESPHome-Doku](https://esphome.io/install/getting-started/). Beide Repos haben keine Lizenz. Deshalb wurden nur Struktur und Themen übernommen, alle Texte und der gesamte Code sind neu geschrieben.
