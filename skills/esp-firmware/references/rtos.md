# FreeRTOS in ESP-IDF: tasks, synchronisation, ISRs, watchdogs

## Know ESP-IDF FreeRTOS

- Default is **IDF FreeRTOS**: based on Vanilla FreeRTOS (v10.5.1 per the docs), modified for **dual-core SMP**. The alternative is Amazon SMP FreeRTOS (`CONFIG_FREERTOS_SMP`); the docs describe it as experimental and only available on ESP32.
- **Stack sizes are in bytes**, not in words as in Vanilla FreeRTOS. This applies to `xTaskCreate*` and `uxTaskGetStackHighWaterMark`. Convert code examples from non-ESP sources.
- **Cores per target:** ESP32, ESP32-S3 and ESP32-P4 are dual-core. S2, C2, C3, C5, C6 and H2 are single-core, and `CONFIG_FREERTOS_UNICORE` is always set on them. Single-core ESP32 variants also exist, so if in doubt, call `chip_info`.
- `CONFIG_FREERTOS_UNICORE` on a dual-core target → only core 0 runs.
- `vTaskSuspendAll()` suspends the scheduler **only on the calling core**. The other core keeps running, so it does not protect shared data.
- **ESP-IDF 6.0:** FreeRTOS functions are placed in **flash** by default instead of IRAM (`CONFIG_FREERTOS_IN_IRAM` restores the old behaviour). Removed: `xTaskGetAffinity()` (→ `xTaskGetCoreID()`), `vTaskDelayUntil()` (→ `xTaskDelayUntil()`) and `xQueueGenericReceive()`.

## Creating tasks

```c
static void sensor_task(void *arg);

TaskHandle_t h = NULL;
BaseType_t ok = xTaskCreatePinnedToCore(sensor_task, "sensor",
                                        4096,          /* bytes! */
                                        NULL, 5, &h,
                                        tskNO_AFFINITY); /* or 0 / 1 */
if (ok != pdPASS) {
    ESP_LOGE(TAG, "sensor task: no memory");
    return ESP_ERR_NO_MEM;
}
```

- **Core pinning:** Wi-Fi/BT tasks run on a fixed core depending on configuration (see Kconfig `CONFIG_ESP_WIFI_TASK_*`, `CONFIG_BT_*_PINNED_TO_CORE`). Put time-critical application tasks on the other core, or use `tskNO_AFFINITY`. On single-core targets the core argument is ignored; for portable code pass `tskNO_AFFINITY` or `0`.
- **Priorities:** idle = 0. System tasks (esp_timer, Wi-Fi, lwIP, event loop) have fixed, partly high priorities; the current table is in the docs under "Performance → Speed → Built-in Task Priorities". Don't put application tasks above the network tasks across the board, or the network stack will starve.
- **Stack size:** start generously, then measure and shrink to "high-water mark + margin". `printf`/`ESP_LOG*` with floats, TLS and JSON are stack-hungry.

```c
UBaseType_t free_min = uxTaskGetStackHighWaterMark(NULL); /* bytes */
ESP_LOGD(TAG, "stack min free: %u", (unsigned)free_min);
```

- `app_main` runs in the main task (`CONFIG_ESP_MAIN_TASK_STACK_SIZE`). The main task may return; your own tasks must not return, they end with `vTaskDelete(NULL)`.
- **Arduino:** `setup()`/`loop()` run in their own task (on ESP32 on `ARDUINO_RUNNING_CORE`, usually core 1). `delay()` maps to `vTaskDelay`. The FreeRTOS API is available directly.

## Choosing a communication primitive

| Need | Primitive |
|---|---|
| Data from A to B (copied) | Queue (`xQueueSend`/`xQueueReceive`) |
| "Event happened", single receiver | Task notification (`xTaskNotifyGive`/`ulTaskNotifyTake`), the lightest option |
| Several state bits, several waiters | Event group (`xEventGroupWaitBits`) |
| Mutual exclusion between tasks | Mutex (`xSemaphoreCreateMutex`) with priority inheritance |
| Signal from ISR to task | Binary semaphore, or better a task notification |
| Byte streams, variable length | Stream/message buffer or ESP-IDF `ringbuf` |
| Very short protection, also ISR ↔ task, multi-core | Spinlock/critical section |

**Mutex vs. binary semaphore:** a mutex has an owner and priority inheritance. Only the task holding it may release it, and it is not allowed in an ISR. A binary semaphore has no owner. It is for signalling, not for protecting resources (risk of priority inversion). For nested calls use `xSemaphoreCreateRecursiveMutex`.

```c
if (xSemaphoreTake(s_bus_mtx, pdMS_TO_TICKS(100)) != pdTRUE) {
    ESP_LOGW(TAG, "bus busy");
    return ESP_ERR_TIMEOUT;
}
esp_err_t err = do_transfer();
xSemaphoreGive(s_bus_mtx);
return err;
```

Always wait with a timeout. Use `portMAX_DELAY` only where waiting forever is correct for the use case (e.g. a consumer loop).

## Critical sections and spinlocks

In ESP-IDF, critical sections take a **spinlock** (`portMUX_TYPE`), even on single-core targets (for API compatibility):

```c
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static uint32_t s_count;

void IRAM_ATTR on_edge_isr(void *arg) {
    portENTER_CRITICAL_ISR(&s_mux);
    s_count++;
    portEXIT_CRITICAL_ISR(&s_mux);
}

uint32_t count_get_and_clear(void) {
    portENTER_CRITICAL(&s_mux);   /* taskENTER_CRITICAL(&s_mux) is equivalent */
    uint32_t c = s_count;
    s_count = 0;
    portEXIT_CRITICAL(&s_mux);
    return c;
}
```

- Masks interrupts (up to a certain priority level) on the current core and keeps the other core out by spinning. Keep it to **a few instructions**: no logging, no `malloc`, no blocking or FreeRTOS wait APIs. Otherwise expect an interrupt WDT reset or a deadlock.
- `volatile` does not make anything atomic. For simple counters/flags use `<stdatomic.h>` or a critical section. For 64-bit values, always.

## ISR rules

- Use only `…FromISR` APIs, never block, no `ESP_LOGx`/`printf` (emergency option: `ESP_DRAM_LOGE` with tag and format string in DRAM).
- Evaluate `pxHigherPriorityTaskWoken` and call `portYIELD_FROM_ISR()` at the end.
- **IRAM:** register ISRs that must run during flash write/erase operations (NVS, OTA, SPIFFS) with `ESP_INTR_FLAG_IRAM`. The ISR and every function and constant it touches must then be in IRAM/DRAM (`IRAM_ATTR`, `DRAM_ATTR`). From IDF 6.0, FreeRTOS lives in flash by default. Whether the `FromISR` APIs you use are IRAM-safe may require `CONFIG_FREERTOS_IN_IRAM` (verify).
- Without `ESP_INTR_FLAG_IRAM`, the ISR is deferred during flash operations, and `IRAM_ATTR` only buys latency.

```c
static TaskHandle_t s_worker;

static void IRAM_ATTR button_isr(void *arg) {
    BaseType_t woken = pdFALSE;
    vTaskNotifyGiveFromISR(s_worker, &woken);
    portYIELD_FROM_ISR(woken);
}

static void worker_task(void *arg) {
    for (;;) {
        if (ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(5000)) == 0) {
            continue;                      /* timeout: heartbeat, feed WDT */
        }
        handle_button();                   /* logging/blocking is fine here */
    }
}

/* init: worker first, then the ISR */
xTaskCreate(worker_task, "worker", 3072, NULL, 6, &s_worker);
ESP_ERROR_CHECK(gpio_install_isr_service(0));   /* once per application */
ESP_ERROR_CHECK(gpio_isr_handler_add(GPIO_NUM_4, button_isr, NULL));
```

`gpio_install_isr_service` returns `ESP_ERR_INVALID_STATE` if the service is already installed (e.g. by a component). Tolerate that case instead of aborting.

## Timers: esp_timer vs. FreeRTOS timers

| | `esp_timer` | FreeRTOS software timer |
|---|---|---|
| Resolution | µs (64-bit) | tick (`CONFIG_FREERTOS_HZ`) |
| Callback context | esp_timer task (high priority, serialised) or ISR (`ESP_TIMER_ISR`, if enabled) | timer service task |
| Light sleep | can trigger a wakeup or be skipped (`skip_unhandled_events`) | tick-based |

For both: keep callbacks short, never block, hand work to a task via notification/queue. A blocking callback delays all other timers.

## Watchdogs

- **Task WDT (TWDT):** detects tasks that don't yield for too long. By default it watches the idle tasks (`CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPUx`). Subscribe your own tasks with `esp_task_wdt_add(NULL)` and feed them with `esp_task_wdt_reset()`. From IDF 5.0 it is configured via `esp_task_wdt_config_t` (`timeout_ms`, `idle_core_mask`, `trigger_panic`) and `esp_task_wdt_init()`/`esp_task_wdt_reconfigure()`. For code sections without their own task: `esp_task_wdt_add_user()`.
- **Interrupt WDT (IWDT):** fires when interrupts stay masked for too long (long critical section, stuck ISR). Log: "Interrupt wdt timeout on CPUx".
- **RTC/LP WDT:** watches boot and panic handling.
- A TWDT reset is not "fixed" by longer timeouts but by restructuring: busy loops with `vTaskDelay`, splitting long computations, timeouts on blocking calls. Exception: known long flash erases (e.g. `bulk_flash_erase` during OTA), where extending the timeout via `esp_task_wdt_reconfigure` is appropriate.

## Typical deadlocks and races

- **Lock order:** task A takes M1→M2, task B takes M2→M1. Avoid it with a fixed global order, or with an owner task instead of shared mutexes.
- **Blocking in an event handler** (`esp_event`): the handler runs in the event loop task. Waiting there for an event the same loop is supposed to deliver blocks forever. Handlers only set bits or notifications.
- **Blocking in timer callbacks** (esp_timer or FreeRTOS): blocks all timers.
- **Mutex in an ISR**, or `xSemaphoreGive` on a mutex from another task: undefined behaviour or assert.
- **Pointer to stack data sent via queue** and the function returns: the receiver reads garbage. Fix: copy by value (queue item size) or hand over ownership of a heap buffer with a clear free rule.
- **Task deleted while holding a mutex** or owning driver handles: resources stay locked. Stop tasks cleanly with a stop flag plus a notification.
- **Priority inversion** with a binary semaphore used as a lock: use a mutex.
- **Read-modify-write** on shared structures without protection, especially on dual-core (true parallelism).

## Proven patterns

**Producer/consumer with a queue:**

```c
typedef struct { int64_t ts_us; float value; } sample_t;
static QueueHandle_t s_q;

s_q = xQueueCreate(16, sizeof(sample_t));
if (s_q == NULL) { return ESP_ERR_NO_MEM; }

/* producer */
sample_t s = { .ts_us = esp_timer_get_time(), .value = v };
if (xQueueSend(s_q, &s, 0) != pdTRUE) { s_dropped++; }   /* never block in the sampling path */

/* consumer */
sample_t r;
while (xQueueReceive(s_q, &r, portMAX_DELAY) == pdTRUE) { publish(&r); }
```

**One owner task per bus/resource:** one task owns the I2C/SPI/UART driver exclusively. Other tasks send requests via queue (with a reply queue or notification). This avoids tangles of mutexes, serialises access and keeps bus recovery in one place. The new IDF drivers (`i2c_master`, SPI master) are thread-safe themselves, but an owner task still pays off when a sequence of transactions must be atomic.

**State machine + event group** for connectivity (Wi-Fi connected, got IP, MQTT connected): handlers set bits, application tasks wait on them with a timeout.

## Sources

- IDF FreeRTOS (SMP, stack in bytes, critical sections): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/freertos_idf.html
- FreeRTOS additions (ring buffer etc.): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/freertos_additions.html
- Watchdogs: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/wdts.html
- esp_timer: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/esp_timer.html
- Built-in task priorities: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/performance/speed.html
- IRAM-safe interrupts: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/spi_flash/spi_flash_concurrency.html
- Migration 5.5 → 6.0, system: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/system.html
