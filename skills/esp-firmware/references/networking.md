# Networking: Wi-Fi, provisioning, SNTP, HTTP, MQTT, TLS, BLE, ESP-NOW

## Wi-Fi STA: init sequence

Order: NVS → netif → default event loop → STA netif → `esp_wifi_init` → register handlers → mode/config → `esp_wifi_start` → connect on `WIFI_EVENT_STA_START`.

```c
static EventGroupHandle_t s_net;
#define NET_GOT_IP BIT0

esp_err_t wifi_sta_start(const char *ssid, const char *pass)
{
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif");
    esp_err_t err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) return err;   /* may already exist */
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t icfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&icfg), TAG, "init");   /* 6.0: second call → ESP_ERR_INVALID_STATE */
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                        on_wifi, NULL, NULL), TAG, "wifi evt");
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                        on_wifi, NULL, NULL), TAG, "ip evt");

    wifi_config_t wc = { 0 };
    strlcpy((char *)wc.sta.ssid, ssid, sizeof(wc.sta.ssid));
    strlcpy((char *)wc.sta.password, pass, sizeof(wc.sta.password));
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &wc), TAG, "cfg");
    return esp_wifi_start();
}
```

NVS must be initialised beforehand (`nvs_flash_init`, see `partitions-ota.md`). Wi-Fi stores calibration and config there.

## Reconnect with backoff

The Wi-Fi driver **does not reconnect on its own**. On `WIFI_EVENT_STA_DISCONNECTED`, schedule a new `esp_wifi_connect()`, but **don't `vTaskDelay` in the event handler** (that blocks the event loop). Use a one-shot `esp_timer` instead:

```c
static esp_timer_handle_t s_retry_tmr;   /* esp_timer_create(... cb = retry_cb ...) */
static uint32_t s_backoff_ms = 500;

static void retry_cb(void *arg) { esp_wifi_connect(); }

static void on_wifi(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *d = data;
        xEventGroupClearBits(s_net, NET_GOT_IP);
        ESP_LOGW(TAG, "disconnected, reason=%d, retry in %" PRIu32 " ms", d->reason, s_backoff_ms);
        esp_timer_start_once(s_retry_tmr, (uint64_t)s_backoff_ms * 1000);
        s_backoff_ms = MIN(s_backoff_ms * 2, 60000);          /* cap, plus jitter if needed */
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_backoff_ms = 500;
        xEventGroupSetBits(s_net, NET_GOT_IP);
    }
}
```

- Log the `reason` codes (`wifi_err_reason_t`): distinguish auth failure (wrong password → no endless fast loop) from AP not found or beacon timeout.
- Application tasks wait on `NET_GOT_IP` with a timeout and tolerate losing it.
- Arduino 3.x: `WiFi.onEvent()`/`Network.onEvent()`, `WiFi.setAutoReconnect(true)`. That is a software flag in the Arduino layer that reconnects for certain reason codes.

## Provisioning

- **From ESP-IDF 6.0, `wifi_provisioning` is no longer part of IDF.** Replacement: managed component `espressif/network_provisioning` (adds Thread). API prefix `wifi_prov_*` → `network_prov_*`, e.g. `wifi_prov_mgr_is_provisioned` → `network_prov_mgr_is_wifi_provisioned`.

```yaml
# main/idf_component.yml
dependencies:
  espressif/network_provisioning: "^1.1.0"   # check the current version in the registry
```

- Transport: BLE or SoftAP. Use security scheme 1 or 2 (proof of possession or SRP6a), never "no security" in production.
- Alternatives: BluFi (6.0: protocol version raised, client apps must be updated), Improv (ESPHome ecosystem), SmartConfig (legacy).

## SNTP

```c
esp_sntp_config_t cfg = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
ESP_RETURN_ON_ERROR(esp_netif_sntp_init(&cfg), TAG, "sntp");
if (esp_netif_sntp_sync_wait(pdMS_TO_TICKS(10000)) != ESP_OK) {
    ESP_LOGW(TAG, "time not synced yet");   /* TLS certificate checks need valid time */
}
setenv("TZ", "CET-1CEST,M3.5.0,M10.5.0/3", 1); tzset();
```

- Multiple servers: `ESP_NETIF_SNTP_DEFAULT_CONFIG_MULTIPLE(n, ESP_SNTP_SERVER_LIST(...))` plus `CONFIG_LWIP_SNTP_MAX_SERVERS`. NTP from DHCP: `server_from_dhcp = true`, `start = false`, then call `esp_netif_sntp_start()` after connecting.
- `esp_netif_sntp_init()` may only be called once (before that, `esp_netif_sntp_deinit()`).

## HTTP client/server, OTA

- **Client:** `esp_http_client_init` → `esp_http_client_perform` (or `open`/`read` for streams) → `esp_http_client_cleanup`. Always check the status code and `content_length`. For HTTPS set `.crt_bundle_attach = esp_crt_bundle_attach`.
- **Server:** `httpd_start(&h, &(httpd_config_t)HTTPD_DEFAULT_CONFIG())`, `httpd_register_uri_handler`. Handlers run in the httpd task, so keep them short and respect its stack size (`stack_size`). HTTPS server: `esp_https_server`. IDF 6.0.1: WebSocket handlers are no longer called during the handshake.
- **OTA over HTTPS:** `esp_https_ota`, see `partitions-ota.md`.

## MQTT (esp-mqtt)

- **From IDF 6.0, a managed component:** `idf.py add-dependency espressif/mqtt`. Header `mqtt_client.h` and API unchanged.

```c
const esp_mqtt_client_config_t cfg = {
    .broker.address.uri = "mqtts://broker.example.com:8883",
    .broker.verification.crt_bundle_attach = esp_crt_bundle_attach,
    .credentials.username = user,            /* from NVS, not in code */
    .credentials.authentication.password = pass,
    .session.last_will = { .topic = "dev/abc/status", .msg = "offline",
                           .qos = 1, .retain = true },
    .session.keepalive = 30,
};
esp_mqtt_client_handle_t c = esp_mqtt_client_init(&cfg);
if (c == NULL) return ESP_FAIL;
ESP_RETURN_ON_ERROR(esp_mqtt_client_register_event(c, ESP_EVENT_ANY_ID, on_mqtt, NULL), TAG, "evt");
ESP_RETURN_ON_ERROR(esp_mqtt_client_start(c), TAG, "start");
```

- Config structs are nested since IDF 5.0 (`broker.*`, `credentials.*`, `session.*`, `network.*`). There is no `user_context`; pass context via the last argument of `register_event`.
- On `MQTT_EVENT_CONNECTED`: (re)subscribe and publish "online" retained. With a persistent session (`disable_clean_session`), the broker keeps subscriptions; otherwise they are lost on reconnect.
- **QoS:** 0 = fire-and-forget, 1 = at-least-once (duplicates possible, handle idempotently), 2 = exactly-once (more overhead). `esp_mqtt_client_publish` returns the msg_id or `-1` on error. `esp_mqtt_client_enqueue` buffers without blocking.
- `MQTT_EVENT_DATA` can arrive **fragmented** for large payloads (`current_data_offset`, `total_data_len`).
- `MQTT_EVENT_ERROR`: `error_handle->error_type` (`MQTT_ERROR_TYPE_TCP_TRANSPORT` with esp-tls/errno details, `..._CONNECTION_REFUSED` with return code).
- The client reconnects by itself (`network.reconnect_timeout_ms`). Don't additionally call `esp_mqtt_client_reconnect` in a loop.

## TLS and certificates

- **Certificate bundle:** `esp_crt_bundle_attach` (Mozilla-based, configurable via `CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_*`). Simpler than pinned root CAs, but costs flash.
- Pinning your own CA/server certificate: `.cert_pem`, embedded via `EMBED_TXTFILES` in the component's `CMakeLists.txt`. Plan for the certificate's lifetime.
- **Time:** certificate validation needs a correct system time (SNTP before the first TLS connection).
- **IDF 6.0 / Mbed TLS 4:** PSA Crypto is the primary interface, many legacy crypto APIs are gone, wolfSSL support in ESP-TLS is removed, TLS 1.2 key exchange without forward secrecy and curves < 250 bits (secp192r1/224r1) are removed. Check old servers/brokers.
- mTLS: client certificate/key ideally not in the firmware image but in a protected partition (e.g. `esp_secure_cert_mgr` with DS peripheral, availability per chip: verify).

## BLE: NimBLE vs. Bluedroid

| | NimBLE | Bluedroid |
|---|---|---|
| Protocols | BLE only | BLE + Bluetooth Classic (Classic only on ESP32) |
| Resources | less heap and flash (per docs) | larger |
| Kconfig | `CONFIG_BT_NIMBLE_ENABLED` | `CONFIG_BT_BLUEDROID_ENABLED` (default) |

- For pure BLE applications, prefer NimBLE. Quantify memory needs with `idf.py size-components` rather than guessing.
- On ESP32 with BLE only: `CONFIG_BTDM_CTRL_MODE_BLE_ONLY`. Free unused controller memory with `esp_bt_controller_mem_release(ESP_BT_MODE_CLASSIC_BT)`.
- Enable bonding persistence (`CONFIG_BT_NIMBLE_NVS_PERSIST`) and LE Secure Connections (`CONFIG_BT_NIMBLE_SM_SC`) for real pairing.
- Arduino core 3.x: the `BLE` library uses Bluedroid on ESP32 and NimBLE on all other SoCs (`BLEDevice::getBLEStackString()`). Security properties differ per stack. Per the library README, Bluedroid is to be replaced by NimBLE in core 4.0.0. Alternative: NimBLE-Arduino (h2zero).

## Wi-Fi/BLE coexistence

- Single radio, time-multiplexed: throughput and latency of both drop. Wi-Fi modem sleep must stay enabled when BT/BLE is active (`esp_wifi_set_ps(WIFI_PS_NONE)` is not allowed in that case, verify).
- Keep BLE scan windows/intervals moderate. Expect heavy RAM needs (Wi-Fi + BLE + TLS at the same time); plan for PSRAM (`CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP`) or NimBLE.
- Details and supported scenarios: coexistence guide (see sources).

## ESP-NOW

- Connectionless, vendor-specific action frames. Payload v1.0 up to 250 bytes (`ESP_NOW_MAX_DATA_LEN`), v2.0 up to 1470 bytes (`ESP_NOW_MAX_DATA_LEN_V2`). v1.0 devices only receive v2.0 packets ≤ 250 bytes.
- **Channel:** all peers on the same channel. With STA connected, the channel of the AP applies (peer `channel = 0` = current channel).
- Peers: max 20. The number of encrypted peers depends on the chip (`CONFIG_ESP_WIFI_ESPNOW_MAX_ENCRYPT_NUM`).
- The send callback runs in the high-priority Wi-Fi task: only a queue post there. No application-level ACK guarantee. Implement sequence numbers and ACKs yourself.
- IDF 6.0: `esp_wifi_config_espnow_rate` → `esp_now_set_peer_rate_config`.

## Thread, Zigbee, Matter (overview only)

- 802.15.4 radio: **ESP32-H2** (802.15.4 + BLE, no Wi-Fi), **ESP32-C6** and **ESP32-C5** (Wi-Fi 6 + BLE + 802.15.4). Confirm per chip with `chip_info`.
- Thread: OpenThread is part of ESP-IDF. A border router typically needs a Wi-Fi SoC plus an 802.15.4 RCP (e.g. S3 + H2).
- Zigbee: `esp-zigbee-sdk`. Matter: `esp-matter` SDK (on top of IDF, own version dependency). Both are out of scope here; follow their own docs.

## Sources

- Wi-Fi driver: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/wifi-driver/index.html
- Migration 6.0 Wi-Fi / protocols / provisioning: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/wifi.html, https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/protocols.html, https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/provisioning.html
- network_provisioning: https://components.espressif.com/components/espressif/network_provisioning
- Provisioning (overview): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/provisioning/index.html
- System time/SNTP: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/system_time.html
- HTTP client/server: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/protocols/esp_http_client.html, https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/protocols/esp_http_server.html
- MQTT component: https://components.espressif.com/components/espressif/mqtt
- Certificate bundle: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/protocols/esp_crt_bundle.html
- Migration 6.0 security (Mbed TLS 4): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/security.html
- BLE overview: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/ble/overview.html
- Coexistence: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/coexist.html
- ESP-NOW: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/network/esp_now.html
- OpenThread: https://docs.espressif.com/projects/esp-idf/en/latest/esp32c6/api-guides/openthread.html
- ESP Zigbee SDK: https://docs.espressif.com/projects/esp-zigbee-sdk/en/latest/
- ESP-Matter: https://docs.espressif.com/projects/esp-matter/en/latest/
- Arduino network API: https://docs.espressif.com/projects/arduino-esp32/en/latest/api/network.html
