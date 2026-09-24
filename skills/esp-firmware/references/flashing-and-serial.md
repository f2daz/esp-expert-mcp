# Flashing, esptool, boot modes, serial connection

> **Safety rules:** flashing and erasing change the device. Get confirmation before `flash`/`write-flash`/`erase-flash`/`erase-region`, unless the user has explicitly asked for it. `erase-flash` also deletes **NVS** (Wi-Fi credentials, calibration, keys). `espefuse` write commands and security activation are **irreversible**, only after explicit approval (see `security.md`). Reading (`chip-id`, `read-mac`, `flash-id`, `espefuse summary`) is harmless but resets the chip.

## esptool v5: names and commands

- Programs are now called **`esptool`, `espefuse`, `espsecure`** (without `.py`). The `.py` wrappers are deprecated.
- **Commands and options use hyphens:** `write_flash` → `write-flash`, `chip_id` → `chip-id`, `erase_flash` → `erase-flash`, `read_mac` → `read-mac`, `flash_id` → `flash-id`; `--flash_mode` → `--flash-mode`, `--flash_size` → `--flash-size`.
- `write-flash --verify` removed (verification is automatic). `merge-bin --fill-flash-size` → `--pad-to-size`. `make_image` (ESP8266) removed.
- espefuse: `--port` is required for **every** command; `execute-scripts` removed.
- Get the current esptool version with `framework_versions`, don't assume it.

```sh
esptool --port /dev/cu.usbmodem101 chip-id                     # read-only, resets the chip
esptool --port PORT --baud 460800 write-flash 0x10000 build/app.bin
esptool --port PORT erase-region 0x9000 0x6000                  # erases only NVS: confirm first!
idf.py -p PORT flash monitor                                    # IDF workflow (flash args from the build)
```

- `--before`: `default-reset` (DTR/RTS), `no-reset`, `no-reset-no-sync`. `--after`: `hard-reset` (default), `no-reset`, `no-reset-stub`, `watchdog-reset` (see below).
- `--no-stub`: talk to the ROM loader only (required in secure download mode, some features missing).
- Troubleshooting: `esptool --trace …` logs the whole serial exchange.

## Boot modes per chip (download mode)

| Chip | Download mode | Also required |
|---|---|---|
| ESP32 | GPIO0 = low at reset | GPIO2 floating or low |
| ESP32-S2 / S3 | GPIO0 = low | GPIO46 floating or low |
| ESP32-C2 / C3 / C6 / H2 | GPIO9 = low | GPIO8 = high (GPIO8 = 0 and GPIO9 = 0 is an invalid combination) |
| ESP32-C5 | GPIO28 = low | GPIO27 = high |
| ESP32-P4 | GPIO35 = low | GPIO36 = high |
| ESP8266 | GPIO0 = low | GPIO2 = high, GPIO15 = low |

- Source: esptool docs "Boot Mode Selection" per target. For other/new chips or module-specific wiring, check with `chip_info` and `pin_check`.
- Manual: hold BOOT (download pin to GND), press and release RESET/EN, release BOOT.
- The internal pull-up on the boot pin is weak (C3: 45 kΩ per docs). A boot button/circuit needs a strong pull-down, e.g. 10 kΩ to GND as in the docs. External pull-ups on the same pin must not override it.
- Normal boot with ROM log `boot:0x…` shows the strapping value. "waiting for download" means download mode is active.

## Auto-reset circuit (DTR/RTS)

- esptool toggles **DTR → GPIO0 (C3 etc.: GPIO9)** and **RTS → EN (CHIP_PU)** via the USB-UART bridge (CP210x, CH340, FTDI). Both lines are active low.
- Espressif boards use two transistors so that "DTR and RTS asserted together" does **not** cause a reset (serial terminals that set both would otherwise hold the chip in reset). With this circuit, **1–10 µF from EN to GND** is required for a reliable reset.
- Serial terminals with RTS/CTS hardware flow control enabled hold the chip in reset. Disable flow control.
- Linux: an open port asserts RTS by default. Reset loops can be avoided with `stty -F /dev/ttyUSB0 -hupcl`.
- No auto-reset available (bare modules, some adapters): use the manual boot mode and `--before no-reset`.

## Native USB

| Interface | Chips | Behaviour |
|---|---|---|
| **USB-Serial-JTAG** (fixed function: CDC-ACM + JTAG) | C3, S3, C5, C6, H2, P4 (check per chip) | esptool resets into download mode via USB itself, no DTR/RTS circuit needed. Port stays stable as long as the app doesn't take over the USB pins |
| **USB-OTG** (ROM CDC, TinyUSB in the app) | S2, S3 | ROM download mode and app CDC are different USB devices → **the port name can change after reset/flashing**. Check the port list again |

- USB-Serial-JTAG disappears in **deep sleep** (PHY off) and does not respond in light sleep. The host may need a re-plug. For automatic light sleep: `CONFIG_USJ_NO_AUTO_LS_ON_CONNECTION` (per chip).
- If the app reconfigures the USB pins (D−/D+, e.g. C3 GPIO18/19) as GPIO or crashes early in a loop, auto-download no longer works → manual boot mode.
- `--after watchdog-reset`: works for leaving download mode over USB-OTG. **Disabled on ESP32-C6** (system freeze possible), **not available** on ESP8266, ESP32, ESP32-H2. Not in secure download mode.
- Arduino: "USB CDC On Boot" and "USB Mode" (Hardware CDC and JTAG vs. USB-OTG/TinyUSB) determine which port `Serial` uses.
- macOS: native USB appears as `/dev/cu.usbmodem*`, bridges as `/dev/cu.usbserial-*`, `/dev/cu.SLAB_USBtoUART` or `/dev/cu.wchusbserial*` (driver-dependent). **Use `/dev/cu.*`, not `/dev/tty.*`.**
- Find the port with `serial_ports`. Close the monitor/other programs (e.g. serial monitor in the IDE, ModemManager on Linux) before flashing.

## Error patterns

| Message | Cause / action |
|---|---|
| `Failed to connect to ESP32…: Timed out waiting for packet header` / "No serial data received." | chip is not entering the bootloader: wrong port, port busy, no auto-reset, strapping pins held by external circuitry, power supply. Try manual boot mode, lower baud rate (`-b 115200`, for testing even `9600`) |
| `Wrong boot mode detected (0xXX)! The chip needs to be in download mode.` | communication works, but auto-reset does not switch to download mode → check the DTR/RTS circuit or boot manually |
| `Download mode successfully detected, but getting no sync reply: The serial TX path seems to be down.` | host → ESP TX line broken (wiring, level shifter) |
| `Invalid head of packet (0xXX): Possible serial noise or corruption.` | bad USB cable, breadboard shorting flash pins, **brownout during flashing**, baud rate too high. Try `--baud 115200`, `--trace`, `--chip esp32…` |
| `A serial exception error occurred: … Device not configured` | pySerial/driver: port gone (USB re-enumeration, native USB after reset), missing permissions or driver |
| `Failed to write to target RAM (result was 0107: Operation timed out)` | unstable USB-serial driver/adapter/hub. Change adapter/cable, avoid hubs, raise timeouts via the esptool config file |
| `MD5 of file does not match data in flash` | write failed or verification failed: power supply, faulty/protected flash, wrong flash mode/size, flash encryption active (plaintext vs. ciphertext). Lower the baud rate, check `flash-id` |
| Flashing succeeds, app doesn't start | wrong flash mode (`-fm dio` for dio-only flash), bootloader missing/at wrong offset, flash pins (ESP32 GPIO6–11) wired externally, wrong partition table offset |
| Aborts or resets during flashing | brownout: USB port/hub too weak, missing capacitance. FTDI 3.3 V outputs are not enough to power an ESP (per docs) |

## Baud rates

- ROM log/console: typically 115200 (ESP8266 ROM: 74880).
- Flashing: 460800 or 921600 is common. With long/cheap cables, hubs or bridges, fall back to 115200. Very high rates depend on the bridge (check the CP210x/CH34x variant).
- Secure download mode: on ESP32-C5 and C2 the baud rate cannot be changed with `--baud`.

## Drivers and permissions

- **CP210x** (Silicon Labs), **CH340/CH343/CH9102** (WCH), **FTDI**: current macOS and Linux versions usually ship drivers. On Windows or old macOS versions install the vendor driver (verify for your OS version). Some CH34x variants need the current vendor driver.
- **Linux:** add the user to `dialout` (Debian/Ubuntu) or `uucp` (Arch), then log in again. Disable/stop ModemManager if it grabs the port.
- Native USB (CDC-ACM) usually needs no driver (Windows ≥ 8, Linux, macOS).

## Web flasher as an alternative

- **ESP Web Tools** (esphome.github.io/esp-web-tools) and esptool-js-based pages use Web Serial (Chromium-based browsers). Useful for end users without a toolchain. Needs a manifest with the correct offsets per chip.
- The same safety rules apply (erase option deletes NVS).

## Flash offsets (orientation)

- Bootloader offset depends on the chip (ESP32 and S2: 0x1000; many newer chips: 0x0; C5/P4 differ). **Use the build output** (`build/flash_args`, `idf.py flash` output) instead of memorising values.
- Merged images: `esptool merge-bin -o merged.bin …`, preferably `--format hex` so that gaps are not flashed as 0xFF (faster, doesn't erase areas in between).

## Sources

- esptool docs: https://docs.espressif.com/projects/esptool/en/latest/
- esptool v5 migration: https://docs.espressif.com/projects/esptool/en/latest/esp32/migration-guide.html
- Advanced options (--before/--after): https://docs.espressif.com/projects/esptool/en/latest/esp32/esptool/advanced-options.html
- Boot mode selection (select target at the top): https://docs.espressif.com/projects/esptool/en/latest/esp32/advanced-topics/boot-mode-selection.html, C3: https://docs.espressif.com/projects/esptool/en/latest/esp32c3/advanced-topics/boot-mode-selection.html, C5: https://docs.espressif.com/projects/esptool/en/latest/esp32c5/advanced-topics/boot-mode-selection.html, P4: https://docs.espressif.com/projects/esptool/en/latest/esp32p4/advanced-topics/boot-mode-selection.html
- Troubleshooting and known limitations: https://docs.espressif.com/projects/esptool/en/latest/esp32/troubleshooting.html
- USB-Serial-JTAG console (C3): https://docs.espressif.com/projects/esp-idf/en/latest/esp32c3/api-guides/usb-serial-jtag-console.html
- USB-OTG console (S3): https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/usb-otg-console.html
- Establish serial connection (drivers, ports): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/get-started/establish-serial-connection.html
- ESP Web Tools: https://esphome.github.io/esp-web-tools/
