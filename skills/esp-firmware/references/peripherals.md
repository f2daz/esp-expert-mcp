# Peripherals: GPIO, I2C, SPI, UART, ADC, LEDC, RMT, TWAI, touch, I2S

Before any wiring: run `pin_check` for the planned pin map (strapping pins, flash/PSRAM pins, input-only, USB, JTAG). Get chip facts from `chip_info`.

## General API notes (ESP-IDF 5.x/6.x)

- From **IDF 5.3** the old `driver` component is split into `esp_driver_*` components (`esp_driver_gpio`, `esp_driver_i2c`, `esp_driver_spi`, `esp_driver_uart` …). In `CMakeLists.txt`, list the specific components in `REQUIRES`/`PRIV_REQUIRES`.
- **Removed in IDF 6.0** (legacy drivers): `driver/adc.h` (and `esp_adc_cal`), `driver/i2s.h`, `driver/rmt.h`, `driver/timer.h` (→ `driver/gptimer.h`), `driver/pcnt.h` (→ `driver/pulse_cnt.h`), `driver/mcpwm.h`, `driver/dac.h`, `driver/sigmadelta.h` (→ `driver/sdm.h`).
- **EOL in 6.0, still present:** legacy I2C `driver/i2c.h` (removal planned for v7.0) and the legacy TWAI driver (deprecation warning, suppressible via `CONFIG_TWAI_SUPPRESS_DEPRECATE_WARN`).
- Other 6.0 changes: `gpio_iomux_in()/gpio_iomux_out()` removed; LEDC `ledc_timer_set()` removed and `LEDC_SLOW_CLK_RTC8M` → `LEDC_SLOW_CLK_RC_FAST`; UART macro `UART_FIFO_LEN` removed (use `UART_HW_FIFO_LEN(port)`); `CONFIG_SPI_MASTER_IN_IRAM` now depends on `CONFIG_FREERTOS_IN_IRAM`.
- New drivers are **handle-based** (`*_new_*` → handle → `*_del_*`). Always release resources on error paths.

## GPIO

```c
gpio_config_t io = {
    .pin_bit_mask = BIT64(GPIO_NUM_4),
    .mode = GPIO_MODE_INPUT,
    .pull_up_en = GPIO_PULLUP_ENABLE,
    .pull_down_en = GPIO_PULLDOWN_DISABLE,
    .intr_type = GPIO_INTR_NEGEDGE,
};
ESP_ERROR_CHECK(gpio_config(&io));
```

- Open drain: `GPIO_MODE_OUTPUT_OD` / `GPIO_MODE_INPUT_OUTPUT_OD` (e.g. bit-banged wired-OR lines). Internal pull-ups are weak and no replacement for bus pull-ups.
- ESP32: GPIO34–39 are **input only** and have no internal pull-up/pull-down.
- **Strapping pins** (e.g. ESP32 GPIO0/2/5/12/15, S2/S3 GPIO0/45/46, C3/C6 GPIO8/9, see datasheet) must not be driven to the wrong level at reset by external circuitry. Check with `pin_check`.
- Pins used by flash/PSRAM (e.g. ESP32 GPIO6–11, and GPIO16/17 with PSRAM on ESP32; octal flash/PSRAM on S3) are off-limits.
- ISRs: `gpio_install_isr_service()` + `gpio_isr_handler_add()`, rules in `rtos.md`.
- Arduino: `pinMode`, `digitalWrite`, `attachInterrupt` (ISR with `IRAM_ATTR`).

## I2C (new master API `driver/i2c_master.h`, IDF ≥ 5.2)

```c
i2c_master_bus_config_t bus_cfg = {
    .i2c_port = I2C_NUM_0,
    .sda_io_num = GPIO_NUM_8,
    .scl_io_num = GPIO_NUM_9,
    .clk_source = I2C_CLK_SRC_DEFAULT,
    .glitch_ignore_cnt = 7,
    .flags.enable_internal_pullup = false,   /* external pull-ups fitted */
};
i2c_master_bus_handle_t bus;
ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus_cfg, &bus), TAG, "bus");

i2c_device_config_t dev_cfg = {
    .dev_addr_length = I2C_ADDR_BIT_LEN_7,
    .device_address = 0x44,
    .scl_speed_hz = 100000,
};
i2c_master_dev_handle_t dev;
ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(bus, &dev_cfg, &dev), TAG, "dev");

uint8_t reg = 0x00, buf[2];
esp_err_t err = i2c_master_transmit_receive(dev, &reg, 1, buf, sizeof(buf), 50 /* ms */);
```

- **Timeouts:** the last argument is `xfer_timeout_ms`; `-1` waits forever, so avoid it in production.
- **Error codes:** `ESP_ERR_TIMEOUT` usually means missing/weak pull-ups, a stuck bus or no clock stretching support. From **IDF 6.0**, a NACK returns `ESP_ERR_INVALID_RESPONSE` (previously `ESP_ERR_INVALID_STATE`); check error handling when migrating.
- **Probe:** `i2c_master_probe(bus, addr, timeout_ms)`. Needs pull-ups.
- **Bus recovery:** `i2c_master_bus_reset(bus)`. If a slave holds SDA low (reset during a transfer), additional manual clocking of SCL may be needed, or power-cycling the slave. On failure, the driver resets its hardware FSM itself.
- **Pull-ups:** internal ones are not sufficient for higher frequencies (the docs recommend external ones). Size them for bus capacitance and speed.
- The legacy API (`i2c_param_config`, `i2c_driver_install`, `i2c_master_cmd_begin`) is EOL. **Do not mix legacy and new driver in one application.**
- Arduino: `Wire.begin(sda, scl)`, `Wire.setClock()`, `Wire.setTimeOut()`.

## SPI master

```c
spi_bus_config_t bus = {
    .mosi_io_num = GPIO_NUM_11, .miso_io_num = GPIO_NUM_13, .sclk_io_num = GPIO_NUM_12,
    .quadwp_io_num = -1, .quadhd_io_num = -1,
    .max_transfer_sz = 4096,
};
ESP_RETURN_ON_ERROR(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO), TAG, "bus");

spi_device_interface_config_t devcfg = {
    .clock_speed_hz = 10 * 1000 * 1000,
    .mode = 0,
    .spics_io_num = GPIO_NUM_10,
    .queue_size = 4,
};
spi_device_handle_t dev;
ESP_RETURN_ON_ERROR(spi_bus_add_device(SPI2_HOST, &devcfg, &dev), TAG, "dev");

spi_transaction_t t = { .length = 8 * len /* bits! */, .tx_buffer = tx, .rx_buffer = rx };
ESP_RETURN_ON_ERROR(spi_device_polling_transmit(dev, &t), TAG, "xfer");
```

- `length` is in **bits**. For ≤ 32 bits, `SPI_TRANS_USE_TXDATA/RXDATA` avoids a separate buffer.
- SPI1 is reserved for flash/PSRAM. Applications use `SPI2_HOST` (and `SPI3_HOST` if available).
- **DMA:** `SPI_DMA_CH_AUTO`. Allocate buffers with `heap_caps_malloc(n, MALLOC_CAP_DMA)` (see `memory.md`). Buffers on the stack are discouraged.
- Transfer modes: `spi_device_polling_transmit` (short, low latency), `spi_device_transmit` (interrupt), `spi_device_queue_trans` + `spi_device_get_trans_result` (pipelined; the buffer must stay alive until the result arrives).
- Keeping a bus for a sequence: `spi_device_acquire_bus()`/`spi_device_release_bus()`.
- CS: driver-controlled via `spics_io_num`; for special protocols set `-1` and drive it via GPIO yourself.

## UART

```c
const uart_port_t port = UART_NUM_1;
uart_config_t cfg = {
    .baud_rate = 115200, .data_bits = UART_DATA_8_BITS, .parity = UART_PARITY_DISABLE,
    .stop_bits = UART_STOP_BITS_1, .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
    .source_clk = UART_SCLK_DEFAULT,
};
QueueHandle_t evq;
ESP_RETURN_ON_ERROR(uart_driver_install(port, 2048, 0, 16, &evq, 0), TAG, "install");
ESP_RETURN_ON_ERROR(uart_param_config(port, &cfg), TAG, "cfg");
ESP_RETURN_ON_ERROR(uart_set_pin(port, GPIO_NUM_17, GPIO_NUM_18,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE), TAG, "pins");
```

- `rx_buffer_size` must be > `UART_HW_FIFO_LEN(port)`; `tx_buffer_size` is 0 (blocking send) or > FIFO length.
- **Events** (queue): `UART_DATA`, `UART_FIFO_OVF`, `UART_BUFFER_FULL` (on these two: `uart_flush_input` + `xQueueReset`), `UART_BREAK`, `UART_FRAME_ERR`, `UART_PARITY_ERR`, `UART_PATTERN_DET`.
- Read with a timeout: `uart_read_bytes(port, buf, len, pdMS_TO_TICKS(20))`.
- **RS485 half duplex:** `uart_set_mode(port, UART_MODE_RS485_HALF_DUPLEX)`; the transceiver DE/RE is driven via the RTS pin (`uart_set_pin(..., rts, UART_PIN_NO_CHANGE)`). Plan for bus termination/biasing in hardware.
- UART0 is usually the console/log. Don't reuse it for protocols without first redirecting the console (`CONFIG_ESP_CONSOLE_*`).
- Arduino: `HardwareSerial::begin(baud, cfg, rx, tx)`, RS485 via `setMode()` + RTS via `setPins()`.

## ADC (oneshot + calibration)

```c
adc_oneshot_unit_handle_t adc;
adc_oneshot_unit_init_cfg_t ucfg = { .unit_id = ADC_UNIT_1 };
ESP_RETURN_ON_ERROR(adc_oneshot_new_unit(&ucfg, &adc), TAG, "unit");
adc_oneshot_chan_cfg_t ccfg = { .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT };
ESP_RETURN_ON_ERROR(adc_oneshot_config_channel(adc, ADC_CHANNEL_3, &ccfg), TAG, "chan");

adc_cali_handle_t cali = NULL;
#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
adc_cali_curve_fitting_config_t cc = { .unit_id = ADC_UNIT_1, .chan = ADC_CHANNEL_3,
                                       .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT };
esp_err_t cerr = adc_cali_create_scheme_curve_fitting(&cc, &cali);
#elif ADC_CALI_SCHEME_LINE_FITTING_SUPPORTED
adc_cali_line_fitting_config_t lc = { .unit_id = ADC_UNIT_1,
                                      .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT };
esp_err_t cerr = adc_cali_create_scheme_line_fitting(&lc, &cali);
#endif
int raw, mv;
ESP_RETURN_ON_ERROR(adc_oneshot_read(adc, ADC_CHANNEL_3, &raw), TAG, "read");
if (cali && adc_cali_raw_to_voltage(cali, raw, &mv) == ESP_OK) { /* mV */ }
```

- Headers: `esp_adc/adc_oneshot.h`, `esp_adc/adc_cali.h`, `esp_adc/adc_cali_scheme.h`. ESP32 uses line fitting, newer chips mostly curve fitting (query with `adc_cali_check_scheme()`). Calibration may fail if the eFuse data is missing, so handle that error.
- `ADC_ATTEN_DB_12` replaces the old `ADC_ATTEN_DB_11` (same value). The **measurable voltage range per attenuation** differs by chip. Take it from the datasheet ("ADC characteristics"), not from memory.
- `adc_oneshot_read` is thread-safe but **not ISR-safe**. For continuous sampling use `adc_continuous`.
- **ADC2 and Wi-Fi:** ADC2 is shared with Wi-Fi. On ESP32 `adc_oneshot_read` then returns `ESP_ERR_TIMEOUT` (result invalid). Put measurement channels on ADC1. Check other targets against datasheet/errata.
- Accuracy: ESP ADCs are nonlinear and noisy. Average multiple samples, calibrate, and use an external reference or ADC for precise measurements.
- Arduino: `analogReadMilliVolts(pin)` (calibrated), `analogSetPinAttenuation`.

## LEDC (PWM)

```c
ledc_timer_config_t tcfg = {
    .speed_mode = LEDC_LOW_SPEED_MODE, .duty_resolution = LEDC_TIMER_13_BIT,
    .timer_num = LEDC_TIMER_0, .freq_hz = 5000, .clk_cfg = LEDC_AUTO_CLK,
};
ESP_RETURN_ON_ERROR(ledc_timer_config(&tcfg), TAG, "timer");
ledc_channel_config_t ccfg = {
    .gpio_num = GPIO_NUM_5, .speed_mode = LEDC_LOW_SPEED_MODE, .channel = LEDC_CHANNEL_0,
    .timer_sel = LEDC_TIMER_0, .duty = 0, .hpoint = 0,
};
ESP_RETURN_ON_ERROR(ledc_channel_config(&ccfg), TAG, "chan");
ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 4096));
ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0));
```

- Frequency × resolution is bounded by the clock. Too high a combination → error at `ledc_timer_config`. `ledc_find_suitable_duty_resolution()` helps.
- `LEDC_HIGH_SPEED_MODE` exists only on ESP32.
- `ledc_set_duty`/`ledc_update_duty` are **not thread-safe** per channel. Thread-safe: `ledc_set_duty_and_update` (after `ledc_fade_func_install`).
- Arduino 3.x: `ledcAttach(pin, freq, res)`, `ledcWrite(pin, duty)`; `ledcSetup`/`ledcAttachPin` were removed.

## RMT (new API) and LED strips

- TX: `rmt_new_tx_channel()` → encoder (`rmt_new_bytes_encoder`, `rmt_new_copy_encoder` or your own) → `rmt_enable()` → `rmt_transmit()` → `rmt_tx_wait_all_done()`.
- RX: `rmt_new_rx_channel()`, `rmt_rx_register_event_callbacks()` (`on_recv_done`, ISR context), `rmt_receive()`.
- Legacy `driver/rmt.h` has been removed since IDF 6.0.
- **WS2812 & co.:** use the managed component `espressif/led_strip` (`idf.py add-dependency espressif/led_strip`) instead of writing your own:

```c
led_strip_config_t sc = { .strip_gpio_num = GPIO_NUM_48, .max_leds = 1,
                          .led_model = LED_MODEL_WS2812,
                          .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB };
led_strip_rmt_config_t rc = { .clk_src = RMT_CLK_SRC_DEFAULT, .resolution_hz = 10 * 1000 * 1000 };
led_strip_handle_t strip;
ESP_RETURN_ON_ERROR(led_strip_new_rmt_device(&sc, &rc, &strip), TAG, "strip");
ESP_ERROR_CHECK(led_strip_set_pixel(strip, 0, 0, 16, 0));
ESP_ERROR_CHECK(led_strip_refresh(strip));
```

  Field names differ between component major versions; check the installed version (`idf_component.yml`). Alternative backend: `led_strip_new_spi_device()`.
- Level: WS2812 at 5 V often needs a level shifter from 3.3 V.

## TWAI (CAN)

- **An external CAN transceiver is required** (e.g. 3.3 V-capable parts); the ESP only provides TX/RX logic levels. Termination is part of the bus design.
- **New node API** (documented in IDF 5.5): `esp_twai.h` + `esp_twai_onchip.h`, `twai_onchip_node_config_t` (`io_cfg.tx/rx`, `bit_timing.bitrate`, `tx_queue_depth`), `twai_new_node_onchip()`, `twai_node_enable()`, `twai_node_transmit()`, callbacks via `twai_event_callbacks_t` (`on_rx_done`, `on_tx_done`, `on_error`, `on_state_change`). In the RX callback: `twai_node_receive_from_isr()`.
- **Bus-off:** from TEC ≥ 256 the node goes offline. `twai_node_transmit` then returns `ESP_ERR_INVALID_STATE`. Recovery **from task context** with `twai_node_recover()`. The controller only rejoins after 129 × 11 recessive bits; `on_state_change` reports `TWAI_ERROR_BUS_OFF` → `TWAI_ERROR_ACTIVE`. Recover rate-limited, not in a tight loop.
- Legacy API (`driver/twai.h`, `twai_driver_install`, alerts like `TWAI_ALERT_BUS_OFF`, `twai_initiate_recovery`) is deprecated in 6.0.

## Touch

- New driver from **IDF 5.5**: `driver/touch_sens.h` (component `esp_driver_touch_sens`), e.g. `touch_sensor_new_controller()`. The legacy `driver/touch_sensor.h` warns (`CONFIG_TOUCH_SUPPRESS_DEPRECATE_WARN`).
- Hardware generations: V1 ESP32, V2 S2/S3, V3 P4 and newer. No touch on C3/C6 etc. (`chip_info`).
- Waterproofing, denoise and thresholds depend heavily on the board. Calibrate on the target hardware.

## I2S (brief)

- Headers `driver/i2s_std.h`, `i2s_pdm.h`, `i2s_tdm.h`: `i2s_new_channel()` → `i2s_channel_init_std_mode()` → `i2s_channel_enable()` → `i2s_channel_read/write()`. Legacy `driver/i2s.h` has been removed since 6.0 (including the ESP32 built-in ADC/DAC mode via I2S).

## Sources

- Migration 5.5 → 6.0, peripherals: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/peripherals.html
- Migration 5.3 (driver split): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-5.x/5.3/peripherals.html
- GPIO: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/gpio.html
- I2C: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/i2c.html
- SPI master: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/spi_master.html
- UART: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/uart.html
- ADC oneshot: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/adc/adc_oneshot.html
- ADC calibration: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/adc/adc_calibration.html
- LEDC: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/ledc.html
- RMT: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/rmt.html
- led_strip: https://espressif.github.io/idf-extra-components/latest/led_strip/index.html, https://components.espressif.com/components/espressif/led_strip
- TWAI: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/twai.html
- Touch: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/cap_touch_sens.html
- I2S: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/i2s.html
- Arduino LEDC 3.x: https://docs.espressif.com/projects/arduino-esp32/en/latest/api/ledc.html
