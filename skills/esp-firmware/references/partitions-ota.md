# Partition tables, NVS, file systems, OTA

Always run changes to partition CSVs through `partition_validate` (overlaps, alignment, flash size, OTA slot sizes, otadata).

## Partition table

- Location: `CONFIG_PARTITION_TABLE_OFFSET`, default **0x8000**. The table is 0xC00 bytes (max. 95 entries) plus MD5 and occupies one 4 KB sector. The first partition therefore starts at ≥ offset + 0x1000.
- If the bootloader grows (secure boot, flash encryption, debug log level, `-Og`), the offset must move up (e.g. 0x10000). Then reflash **bootloader, partition table and app together**. The offset is baked into the bootloader.
- **Alignment:** app partitions on **0x10000 (64 KB)**, data partitions on 0x1000 (4 KB). With an empty offset field, `gen_esp32part.py` computes aligned offsets automatically.
- Built-in layouts (`CONFIG_PARTITION_TABLE_TYPE`): "Single factory app, no OTA" (nvs 0x6000, phy_init, factory 1M) and "Factory app, two OTA definitions" (nvs 0x4000, otadata 0x2000, phy_init, factory + ota_0 + ota_1 at 1M each). Plus variants with an `nvs_keys` partition for NVS encryption.
- Custom CSV (`CONFIG_PARTITION_TABLE_CUSTOM`, `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME`):

```csv
# Name,   Type, SubType,  Offset,  Size,  Flags
nvs,      data, nvs,      0x9000,  0x4000,
otadata,  data, ota,      0xd000,  0x2000,
phy_init, data, phy,      0xf000,  0x1000,
ota_0,    app,  ota_0,    0x10000, 0x1E0000,
ota_1,    app,  ota_1,    ,        0x1E0000,
storage,  data, littlefs, ,        0x20000,
coredump, data, coredump, ,        64K,
```

  (Example for exactly 4 MB with table offset 0x8000: ota_1 at 0x1F0000, storage at 0x3D0000, coredump ends at 0x400000. Check with `partition_validate`. Templates for 4/8/16 MB: `templates/partitions/`.)
- Rules: both OTA slots **the same size** and larger than the largest expected app plus headroom. `otadata` is exactly 0x2000 (two sectors for power-fail safety). Without a factory partition, `ota_0` boots when otadata is empty.
- Set flash size in `CONFIG_ESPTOOLPY_FLASHSIZE` to match the module. A table larger than the real flash fails at boot.
- Inspect: `idf.py partition-table`. Read/write partitions: `parttool.py`. Current OTA state: `idf.py read-otadata`.

## NVS

- Key/value store with wear levelling. **Key and namespace names ≤ 15 characters**, max. 254 namespaces per partition.
- **Minimum size 0x3000 (3 pages)**, at least one page must stay free. A read-only NVS partition (flag `readonly`) can be 0x1000.
- Standard init pattern (note: erasing = **data loss** of Wi-Fi credentials, calibration and all app keys):

```c
esp_err_t err = nvs_flash_init();
if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_LOGW(TAG, "NVS unusable (%s), erasing", esp_err_to_name(err));
    ESP_ERROR_CHECK(nvs_flash_erase());
    err = nvs_flash_init();
}
ESP_ERROR_CHECK(err);
```

  For devices with factory data (serial number, calibration), put that data in its **own read-only NVS partition** so the automatic erase or recovery on unstable power does not hit it.
- Usage: `nvs_open("app", NVS_READWRITE, &h)` → `nvs_set_*`/`nvs_get_*` → `nvs_commit(h)` → `nvs_close(h)`. `ESP_ERR_NVS_NOT_FOUND` is a normal case (default value), not an error.
- Strings/blobs: query the length first (`nvs_get_str(h, key, NULL, &len)`). Don't store large or frequently changing data in NVS (file system instead).
- Fill level: `nvs_get_stats()`. Generate factory images: `nvs_partition_gen.py` (CSV → bin, optionally encrypted).
- **NVS encryption** (`CONFIG_NVS_ENCRYPTION`): two schemes, see `security.md`. **From IDF 6.0, HMAC is the default** on chips with an HMAC peripheral and flash encryption enabled. If you used the flash-encryption scheme before, set `CONFIG_NVS_SEC_KEY_PROTECT_USING_FLASH_ENC=y` explicitly.
- Arduino: `Preferences` (NVS wrapper).

## File systems

| | LittleFS | FATFS | SPIFFS |
|---|---|---|---|
| Source | managed component `joltwallet/littlefs` | in IDF (optionally with wear levelling) | in IDF |
| Directories | yes | yes | no |
| Power-fail safety | integrated | no | partial (`esp_spiffs_check`) |
| Status | recommended for general use (per docs) | good for SD cards / PC compatibility | **no longer developed or maintained** (per docs), slows down above roughly 70% full |

- Mount via VFS (`esp_vfs_littlefs_register`, `esp_vfs_fat_spiflash_mount_rw_wl`, `esp_vfs_spiffs_register`), then POSIX/stdio APIs.
- IDF 6.0: FATFS uses dynamic buffers by default; `esp_vfs_console` renamed to `esp_stdio`; deprecated functions such as `esp_vfs_fat_sdmmc_unmount` removed.
- Build images: `littlefs_create_partition_image` (component), `fatfs_create_spiflash_image`, `spiffs_create_partition_image` in `CMakeLists.txt`.

## OTA flow

1. Determine the next slot: `esp_ota_get_next_update_partition(NULL)`.
2. `esp_ota_begin(part, OTA_SIZE_UNKNOWN, &h)` (erases the slot; with known size only the needed range; `OTA_WITH_SEQUENTIAL_WRITES` erases progressively).
3. Write chunks: `esp_ota_write(h, buf, len)`.
4. `esp_ota_end(h)` validates the image (magic, chip, SHA-256, signature with secure boot). Error → `ESP_ERR_OTA_VALIDATE_FAILED`.
5. `esp_ota_set_boot_partition(part)` → `esp_restart()`.

Simpler over HTTPS:

```c
esp_http_client_config_t http = {
    .url = url,
    .crt_bundle_attach = esp_crt_bundle_attach,
    .timeout_ms = 10000,
    .keep_alive_enable = true,
};
esp_https_ota_config_t ota = { .http_config = &http };
esp_err_t err = esp_https_ota(&ota);          /* since IDF 5.0: pointer to esp_https_ota_config_t */
if (err == ESP_OK) {
    esp_restart();
}
ESP_LOGE(TAG, "OTA failed: %s", esp_err_to_name(err));
```

- Advanced API for progress, version check and resume: `esp_https_ota_begin` → `esp_https_ota_get_img_desc` (compare the version *before* downloading) → loop `esp_https_ota_perform` while `ESP_ERR_HTTPS_OTA_IN_PROGRESS` → `esp_https_ota_is_complete_data_received` → `esp_https_ota_finish` (or `esp_https_ota_abort`).
- `bulk_flash_erase = true` erases the whole slot at once, which can trigger the TWDT (extend the timeout).
- IDF 6.0: partial download only with `CONFIG_ESP_HTTPS_OTA_ENABLE_PARTIAL_DOWNLOAD`.
- `esp_ota_begin` refuses the running partition (`ESP_ERR_OTA_PARTITION_CONFLICT`) and, with rollback enabled, a running app that has not been confirmed yet (`ESP_ERR_OTA_ROLLBACK_INVALID_STATE`).
- Updating bootloader/partition table via OTA is possible in newer IDF versions (partition types bootloader/partition_table). **Risky:** a power failure at that moment bricks the device. Only with a deliberate plan.

## Rollback

- `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`: a new image starts as `ESP_OTA_IMG_PENDING_VERIFY`. If it reboots without confirmation → `ESP_OTA_IMG_ABORTED` and the bootloader returns to the previous slot.

```c
const esp_partition_t *run = esp_ota_get_running_partition();
esp_ota_img_states_t st;
if (esp_ota_get_state_partition(run, &st) == ESP_OK && st == ESP_OTA_IMG_PENDING_VERIFY) {
    if (self_test_ok()) {                       /* e.g. network + backend reachable */
        ESP_ERROR_CHECK(esp_ota_mark_app_valid_cancel_rollback());
    } else {
        esp_ota_mark_app_invalid_rollback_and_reboot();
    }
}
```

- Define the self-test sensibly: confirm only after connectivity **and** the capability to perform the next OTA are proven, but don't make it depend on transient server problems.

## Anti-rollback (secure_version)

- `CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK` + `CONFIG_BOOTLOADER_APP_SECURE_VERSION`: the bootloader refuses apps whose `secure_version` is below the value in eFuse.
- **Irreversible:** eFuse bits are burned when the version increases. The number of possible increments is limited by the eFuse field size (`CONFIG_BOOTLOADER_APP_SEC_VER_SIZE_EFUSE_FIELD`). Only raise it for security fixes.
- No `factory`/`test` partitions allowed. ESP32: only with eFuse coding scheme `NONE`.

## App description

- `esp_app_desc_t` in every image: version, project name, IDF version, compile time, `secure_version`, ELF SHA-256.
- Read: `esp_app_get_description()` (`esp_app_desc.h`; **IDF 6.0:** deprecated variants in `esp_ota_ops.h` removed). For another partition: `esp_ota_get_partition_description()`.
- Version source: `PROJECT_VER` in `CMakeLists.txt`, otherwise `version.txt`, otherwise `git describe`. Set it deterministically for release builds.

## Delta OTA

- Espressif offers the managed component `espressif/esp_delta_ota` (patch-based). Weigh it against complexity: patches must match the exact source image, and rollback/version management gets harder.

## Failure patterns

| Symptom | Likely cause |
|---|---|
| `ESP_ERR_OTA_VALIDATE_FAILED` | wrong chip/target, truncated download, missing/wrong signature (secure boot), image requires a newer chip revision than the device has |
| `esp_ota_begin` → `ESP_ERR_NOT_FOUND`/`NULL` partition | no OTA slots or otadata in the table |
| Image does not fit | slot too small (`idf.py size` vs. slot size), see `memory.md` |
| After OTA, the old version keeps starting | rollback active and app not confirmed, or `esp_ota_set_boot_partition` missing |
| Boot loop after changing the table | bootloader/table/app not flashed together, changed `CONFIG_PARTITION_TABLE_OFFSET` |
| "No bootable app partitions" / invalid header at app offset | app not flashed, wrong offset, flash encryption state vs. plaintext image |
| NVS init error after update | NVS partition resized/moved (then `nvs_flash_erase` with data loss) |
| Flash size warning at boot | `CONFIG_ESPTOOLPY_FLASHSIZE` does not match the module |

For log analysis use `serial_log_analyze`, for error codes `esp_err_lookup`.

## Sources

- Partition tables: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/partition-tables.html
- NVS: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/storage/nvs_flash.html
- NVS encryption: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/storage/nvs_encryption.html
- File system considerations: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/file-system-considerations.html
- LittleFS component: https://components.espressif.com/components/joltwallet/littlefs
- OTA: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/ota.html
- ESP HTTPS OTA: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/esp_https_ota.html
- App image format / esp_app_desc: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/app_image_format.html
- Bootloader: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/bootloader.html
- Delta OTA: https://components.espressif.com/components/espressif/esp_delta_ota
- Migration 6.0 storage/system/security: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/storage.html, https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/system.html, https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/security.html
