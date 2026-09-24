# Low power: sleep modes, wakeup, power management

**Never quote current figures from memory.** Typical values per mode come from the datasheet of the specific chip (section "Current Consumption" / "Power Consumption"). Links under sources. Board values are often far above chip values.

## Modes

| Mode | What keeps running | Typical use |
|---|---|---|
| **Active** | CPU, radio, peripherals | normal operation |
| **Modem sleep** | CPU active, radio switched off between DTIM beacons (Wi-Fi power save) | connected, rarely sending |
| **Light sleep** | CPU clock-gated, RAM and state retained; resumes after the sleep call | short pauses, keep Wi-Fi/BLE connection (automatic light sleep) |
| **Deep sleep** | only RTC/LP domain (RTC timer, RTC/LP memory, optional ULP/LP core) | long pauses; wakeup = **reboot** through the bootloader |
| **Hibernation** | deep sleep with RTC memory/peripherals also powered down (ESP32 terminology) | minimal draw; only timer/RTC-IO wakeup, no RTC data retention |

- Light sleep with manual `esp_light_sleep_start()` or deep sleep: **stop Wi-Fi/BT first** (`esp_wifi_stop()`, `esp_bluedroid_disable()`/`nimble_port_stop()`). The connection is lost.
- To keep a connection alive: Wi-Fi/BT modem sleep **plus automatic light sleep** via power management (below).

## Wakeup sources

| Source | API | Note |
|---|---|---|
| Timer | `esp_sleep_enable_timer_wakeup(us)` | all chips |
| EXT0 (one RTC GPIO, level) | `esp_sleep_enable_ext0_wakeup(gpio, level)` | ESP32, S2, S3 only (needs RTC_PERIPH powered) |
| EXT1 (multiple RTC/LP GPIOs) | `esp_sleep_enable_ext1_wakeup_io(mask, mode)` | ESP32: `ESP_EXT1_WAKEUP_ANY_HIGH`/`ALL_LOW`; S2/S3/C6: additionally `ANY_LOW`. C6: only GPIOs with RTC/LP function (GPIO0–7). Not on C3 (use GPIO wakeup) |
| GPIO (deep sleep, chips without EXT0) | ≤ IDF 5.x: `esp_deep_sleep_enable_gpio_wakeup()`; **IDF 6.0:** `esp_sleep_enable_gpio_wakeup_on_hp_periph_powerdown()` | e.g. C3/C6, only certain GPIOs (see chip docs) |
| GPIO (light sleep) | `gpio_wakeup_enable()` + `esp_sleep_enable_gpio_wakeup()` | any IO |
| UART (light sleep) | `esp_sleep_enable_uart_wakeup()` | first bytes are lost |
| Touch | `esp_sleep_enable_touchpad_wakeup()` | chips with touch |
| ULP / LP core | `esp_sleep_enable_ulp_wakeup()` | ESP32: ULP-FSM; S2/S3: ULP-FSM/-RISC-V; C5/C6/P4: LP core (per chip: `chip_info`) |

- Evaluate the wakeup cause: **IDF 6.0** `esp_sleep_get_wakeup_causes()` (bitmap of all sources), previously `esp_sleep_get_wakeup_cause()` (one source).
- With EXT1, `esp_sleep_get_ext1_wakeup_status()` returns the triggering pins.

```c
RTC_DATA_ATTR static uint32_t s_boot_count;     /* survives deep sleep, not power loss */

void app_main(void)
{
    s_boot_count++;
    if (esp_reset_reason() == ESP_RST_DEEPSLEEP) {
        ESP_LOGI(TAG, "wake #%" PRIu32, s_boot_count);
    }
    do_measurement_and_send();

    ESP_ERROR_CHECK(esp_sleep_enable_timer_wakeup(15ULL * 60 * 1000 * 1000));
    /* button with pull-down, active high; the pin must be RTC/LP-capable on this chip */
    ESP_ERROR_CHECK(esp_sleep_enable_ext1_wakeup_io(BIT64(GPIO_NUM_2), ESP_EXT1_WAKEUP_ANY_HIGH));
    esp_deep_sleep_start();          /* does not return */
}
```

(Check the EXT1 modes and wakeup-capable pins in the API reference of the specific chip.)

## Power management (DFS + automatic light sleep)

```c
/* sdkconfig: CONFIG_PM_ENABLE=y, CONFIG_FREERTOS_USE_TICKLESS_IDLE=y */
esp_pm_config_t pm = {
    .max_freq_mhz = 160,
    .min_freq_mhz = 40,          /* typically XTAL frequency, chip-dependent */
    .light_sleep_enable = true,
};
ESP_ERROR_CHECK(esp_pm_configure(&pm));
```

- Automatic light sleep needs `CONFIG_FREERTOS_USE_TICKLESS_IDLE`. The system sleeps whenever no task is ready and no lock is held.
- **PM locks:** `esp_pm_lock_create(ESP_PM_CPU_FREQ_MAX | ESP_PM_APB_FREQ_MAX | ESP_PM_NO_LIGHT_SLEEP, 0, "name", &h)`, `esp_pm_lock_acquire/release` (recursive). Drivers take locks themselves (SPI master, I2C, I2S, SDMMC during transactions; Wi-Fi, BT, TWAI, GPTimer, … while active).
- Diagnostics: `esp_pm_dump_locks(stdout)`, `CONFIG_PM_PROFILING`. A forgotten lock (e.g. installed UART driver, active GPTimer) prevents light sleep entirely.
- Peripherals that should keep running in light sleep: check their clock source (e.g. `allow_pd` / sleep retention on newer chips, I2C `allow_pd`).
- **Wi-Fi power save:** `esp_wifi_set_ps(WIFI_PS_MIN_MODEM)` (wake every DTIM) or `WIFI_PS_MAX_MODEM` (wake per `listen_interval` in `wifi_sta_config_t`). `WIFI_PS_NONE` = no power save. Latency grows with longer sleep intervals, and the AP's DTIM setting plays a part.
- Arduino: `WiFi.setSleep(true/false)`, `esp_sleep_*` and `esp_pm_*` are directly callable. Arduino core builds may be compiled without `CONFIG_PM_ENABLE` (verify).

## Pins during sleep

- **Holding digital GPIOs:** `gpio_hold_en(gpio)`. On **ESP32/S2/C3/S3/C2**, a digital GPIO is not held through deep sleep by `gpio_hold_en` alone; additionally call `gpio_deep_sleep_hold_en()`. Release with `gpio_hold_dis()` after wakeup (configure the level beforehand, otherwise glitch).
- USB pads cannot be held low after deep sleep. P4 before rev 3.0 cannot hold IO states after deep-sleep wakeup.
- **RTC GPIOs:** `rtc_gpio_hold_en()`. After light sleep with RTC_PERIPH powered down, the wakeup IOs are held and need `rtc_gpio_hold_dis()`.
- **Isolate:** `rtc_gpio_isolate(gpio)` separates a pin (incl. internal pulls), e.g. ESP32 GPIO12 on modules with an external pull-up. `esp_sleep_config_gpio_isolate()` for all pins in the sleep state.
- Internal pull-ups/pull-downs don't work when RTC_PERIPH is powered down. Keep it on with `esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_ON)` or use external resistors.
- Flash: leave it powered normally. `CONFIG_ESP_SLEEP_SET_FLASH_DPD` (deep power-down) only per docs guidance. Switching flash off entirely is discouraged.

## Typical causes of high sleep current

1. **Board, not chip:** LDO with high quiescent current, always-on USB-UART bridge (CP210x/CH340), power/status LEDs, voltage dividers for battery measurement, sensors without power switching.
2. **Floating pins** or pins driven against external pull-ups/pull-downs (current through resistors). Put every pin in a defined state or isolate it.
3. **Pull-ups on buses** (I2C) still powered while slaves are switched off. Backfeeding through IO protection diodes.
4. **External peripherals** not in shutdown (radio modules, displays, PSRAM/SD).
5. **Wakeup source constantly active** (EXT1 level already present) → apparent "no sleep". Check the wakeup cause.
6. **PM lock held** (automatic light sleep never engages).
7. Debug interfaces: USB-Serial-JTAG/USB-OTG connected and active keeps parts awake; measure without USB.
8. Deep-sleep wake stub or ULP running more often than intended.

## Measurement methodology

- Measure **without a USB connection** from a lab supply or battery. Current meter in the supply line; for dynamic profiles a power analyser/SMU or a shunt + oscilloscope (sleep µA and TX peaks differ by orders of magnitude, so watch range switching and burden voltage of the meter).
- First the bare module (or cut board jumpers), then the full board. The difference shows the board share.
- Measure phases separately: boot, connect, send, sleep. For duty-cycle devices, energy per cycle is the metric, not a single current value.
- Log the wakeup cause, awake time (`esp_timer_get_time()` at start/before sleep) and reset reason for every cycle.
- Espressif describes measurement setups for modules in the guide "Current Consumption Measurement of Modules".

## Sources

- Sleep modes (per chip, select target): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/sleep_modes.html, C6: https://docs.espressif.com/projects/esp-idf/en/latest/esp32c6/api-reference/system/sleep_modes.html
- Power management: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/power_management.html
- Low-power mode guide: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/low-power-mode/index.html
- GPIO (hold): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/gpio.html
- ULP: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/ulp.html
- Deep-sleep wake stub: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/deep-sleep-stub.html
- Current measurement: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/current-consumption-measurement-modules.html
- Migration 6.0 system (wakeup APIs): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/system.html
- Datasheets (current consumption): ESP32 https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf, ESP32-S3 https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf, ESP32-C3 https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf, ESP32-C6 https://www.espressif.com/sites/default/files/documentation/esp32-c6_datasheet_en.pdf
