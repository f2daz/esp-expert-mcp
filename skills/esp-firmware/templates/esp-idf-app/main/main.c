/*
 * Startpunkt für eine ESP-IDF-Anwendung: NVS-Init mit Recovery, eine Worker-Task
 * mit Queue, OTA-Bestätigung nach erfolgreichem Start.
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
        ESP_LOGW(TAG, "NVS neu formatieren (%s)", esp_err_to_name(err));
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
            ESP_LOGD(TAG, "idle, stack frei: %u B", (unsigned)uxTaskGetStackHighWaterMark(NULL));
        }
    }
}

static void confirm_running_image(void)
{
    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    if (esp_ota_get_state_partition(running, &state) == ESP_OK && state == ESP_OTA_IMG_PENDING_VERIFY) {
        // Erst bestätigen, wenn die Anwendung wirklich funktioniert (z. B. nach erfolgreichem Netzwerkstart).
        ESP_LOGI(TAG, "Neue Firmware bestätigt");
        esp_ota_mark_app_valid_cancel_rollback();
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "Reset-Grund: %d", (int)esp_reset_reason());
    ESP_ERROR_CHECK(init_nvs());

    s_event_queue = xQueueCreate(8, sizeof(app_event_t));
    if (s_event_queue == NULL) {
        ESP_LOGE(TAG, "Queue konnte nicht angelegt werden");
        return;
    }
    // Stackgröße in Bytes (ESP-IDF), Priorität über Idle
    if (xTaskCreate(worker_task, "worker", 4096, NULL, 5, NULL) != pdPASS) {
        ESP_LOGE(TAG, "worker_task nicht gestartet");
        return;
    }

    confirm_running_image();
}
