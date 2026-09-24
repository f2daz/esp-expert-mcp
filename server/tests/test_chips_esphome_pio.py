import pytest
import yaml

from esp_expert_mcp import chips, esphome, platformio


def levels(res, gpio):
    return {i["level"] for p in res["pins"] if p["gpio"] == gpio for i in p["issues"]}


def test_all_chips_load():
    data = chips.load()
    for c in ("esp32", "esp32s2", "esp32s3", "esp32c2", "esp32c3", "esp32c5", "esp32c6", "esp32h2", "esp32p4", "esp8266"):
        assert data[c]["sources"], c


def test_esp32_pin_rules():
    r = chips.check_pins("esp32", [
        {"gpio": 34, "usage": "output", "label": "LED"},
        {"gpio": 6, "usage": "input"},
        {"gpio": "GPIO4", "usage": "adc"},
        {"gpio": 12, "usage": "output"},
        {"gpio": 16, "usage": "output"},
        {"gpio": 25, "usage": "output"},
        {"gpio": 25, "usage": "input"},
    ], uses_wifi=True, psram="quad")
    assert "error" in levels(r, 34)          # input-only
    assert "error" in levels(r, 6)           # flash
    assert "error" in levels(r, 4)           # ADC2 + Wi-Fi
    assert "warning" in levels(r, 12)        # strapping
    assert "error" in levels(r, 16)          # PSRAM on WROVER
    assert r["status"] == "error"


def test_s3_octal_and_esp8266_labels():
    r = chips.check_pins("esp32-s3", [{"gpio": 35, "usage": "output"}], psram="octal")
    assert "error" in levels(r, 35)
    r = chips.check_pins("esp32s3", [{"gpio": 35, "usage": "output"}], psram="none")
    assert levels(r, 35) == set()
    r = chips.check_pins("esp8266", [{"gpio": "D8", "usage": "output"}, {"gpio": "A0", "usage": "adc"}])
    assert "warning" in levels(r, 15)
    assert r["pins"][1]["gpio"] == 17


ESPHOME_YAML = """
esphome:
  name: test
esp32:
  board: esp32-c3-devkitm-1
wifi:
  ssid: MeinNetz
  password: !secret wifi_password
api:
ota:
  - platform: esphome
light:
  - platform: fastled_clockless
    pin: GPIO9
sensor:
  - platform: adc
    pin: GPIO5
i2c:
  sda: 12
  scl: GPIO8
binary_sensor:
  - platform: gpio
    pin:
      pcf8574: hub
      number: 3
"""


def test_esphome_lint(tmp_path):
    f = tmp_path / "dev.yaml"
    f.write_text(ESPHOME_YAML)
    r = esphome.lint(str(f))
    assert r["variant"] == "esp32c3"
    msgs = " ".join(x["message"] for x in r["findings"])
    assert "wifi.ssid" in msgs and "wifi.password" not in msgs
    assert "encryption" in msgs and "OTA ohne Absicherung" in msgs and "fastled_clockless" in msgs
    assert r["pins_found"] == 4  # Expander-Pin ignoriert
    pc = r["pin_check"]
    assert "error" in levels(pc, 12)   # Flash-Pin
    assert "warning" in levels(pc, 9)  # Strapping


def test_yaml_loader_rejects_python_tags(tmp_path):
    f = tmp_path / "evil.yaml"
    f.write_text("esphome:\n  name: !!python/object/apply:os.system ['echo pwned']\n")
    r = esphome.lint(str(f))
    assert r["valid_yaml"] is False


def test_platformio(tmp_path):
    (tmp_path / "parts.csv").write_text("nvs,data,nvs,0x9000,0x5000\n")
    ini = tmp_path / "platformio.ini"
    ini.write_text("""
[platformio]
default_envs = s3

[env]
monitor_speed = 115200

[env:s3]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino
board_build.partitions = parts.csv
lib_deps =
    bblanchon/ArduinoJson@^7.0.0
    knolleary/PubSubClient

[env:d1]
platform = espressif8266@4.2.1
board = d1_mini
framework = arduino
monitor_filters = esp8266_exception_decoder
""")
    r = platformio.analyze(str(ini))
    s3, d1 = r["environments"]
    assert s3["chip"] == "esp32s3" and s3["partitions_path"].endswith("parts.csv")
    assert s3["monitor_speed"] == "115200"
    m = " ".join(f["message"] for f in s3["findings"])
    assert "nicht reproduzierbar" in m and "PubSubClient" in m and "pioarduino" in m
    assert d1["chip"] == "esp8266" and "gepinnt" in d1["platform_source"]
    assert not [f for f in d1["findings"] if f["level"] == "warning"]
