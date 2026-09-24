/*
 * Starting point for an ESP-IDF application: NVS init with recovery, a worker task
 * with a queue, OTA confirmation after a successful start.
 */
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_err.h"
#include "esp_check.h"
#include <inttypes.h>
#include "esp_system.h"
#include "esp_ota_ops.h"
#include "nvs_flash.h"

static const char *TAG = "app";

typedef struct {
    uint32_t id;
    int32_t value;
} app_event_t;

static QueueHandle_t s_event_queue;

static esp_err_t init_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "Reformatting NVS (%s)", esp_err_to_name(err));
        ESP_RETURN_ON_ERROR(nvs_flash_erase(), TAG, "nvs_flash_erase");
        err = nvs_flash_init();
    }
    return err;
}

static void worker_task(void *arg)
{
    app_event_t ev;
    for (;;) {
        if (xQueueReceive(s_event_queue, &ev, pdMS_TO_TICKS(1000)) == pdTRUE) {
            ESP_LOGI(TAG, "event id=%" PRIu32 " value=%" PRId32, ev.id, ev.value);
        } else {
            ESP_LOGD(TAG, "idle, free stack: %u B", (unsigned)uxTaskGetStackHighWaterMark(NULL));
        }
    }
}

static void confirm_running_image(void)
{
    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    if (esp_ota_get_state_partition(running, &state) == ESP_OK && state == ESP_OTA_IMG_PENDING_VERIFY) {
        // Only confirm once the application really works (e.g. after the network came up).
        ESP_LOGI(TAG, "New firmware confirmed");
        esp_ota_mark_app_valid_cancel_rollback();
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "Reset reason: %d", (int)esp_reset_reason());
    ESP_ERROR_CHECK(init_nvs());

    s_event_queue = xQueueCreate(8, sizeof(app_event_t));
    if (s_event_queue == NULL) {
        ESP_LOGE(TAG, "Failed to create queue");
        return;
    }
    // Stack size in bytes (ESP-IDF), priority above idle
    if (xTaskCreate(worker_task, "worker", 4096, NULL, 5, NULL) != pdPASS) {
        ESP_LOGE(TAG, "Failed to start worker_task");
        return;
    }

    confirm_running_image();
}
