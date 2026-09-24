# Security: Secure Boot, flash encryption, eFuses, production

> **Irreversible.** Almost every security step burns **eFuses**. eFuse bits can only go from 0 to 1, never back. A mistake can make the device unflashable or unusable for good. **Burn nothing without explicit user approval**. That covers `espefuse burn-*`, `idf.py efuse-burn*`, first boot with a security-enabled bootloader, and `esp_flash_encryption_set_release_mode()`. Test on sacrificial devices first.

Markers below: **[IRREVERSIBLE]** = permanent after execution/first boot.

## Overview and order

1. Decide on the threat model: protection against firmware readout (flash encryption), against foreign firmware (Secure Boot), against local manipulation (disable JTAG/UART download).
2. Develop with **flash encryption in development mode** and signed images on test devices.
3. Production: Secure Boot v2 + flash encryption **release** + NVS encryption + restricted debug interfaces. Espressif recommends the host-based workflow (keys generated on the host, per-device flash encryption key), see "Security Features Enablement Workflows".

## Secure Boot v2

- Verifies the second-stage bootloader and every app (also at OTA) against a public-key digest in eFuse. The ROM bootloader is immutable and verifies the bootloader.
- Schemes: RSA-3072 (RSA-PSS), ECDSA-256/-384 depending on chip. **ESP32 only from chip revision v3.0** (`CONFIG_ESP32_REV_MIN` ≥ v3.0), older ESP32 only Secure Boot v1.
- Generate the key (for production preferably with OpenSSL/HSM and good entropy):

```sh
espsecure generate-signing-key --version 2 --scheme rsa3072 secure_boot_signing_key.pem
```

- Kconfig: `CONFIG_SECURE_BOOT`, `CONFIG_SECURE_BOOT_V2_ENABLED`. With `CONFIG_SECURE_BOOT_BUILD_SIGNED_BINARIES` the build signs locally. Otherwise sign externally (remote/HSM signing, `espsecure sign-data`).
- The bootloader is usually **not** flashed with `idf.py flash`: `idf.py bootloader` prints the command, and you run it manually. **[IRREVERSIBLE]** On the first boot the bootloader burns the key digest and enables Secure Boot.
- After that, every bootloader and app must be signed with a matching key. **Losing the key = no more updates.** Keep the key off the build server, back it up, restrict access.
- Chips with multiple digest slots allow additional keys and **key revocation** **[IRREVERSIBLE]**. ESP32 v3.0 has only one signature block/key.
- After activation, further eFuse keys can no longer be read-protected. Burn every key that needs read protection (flash encryption, HMAC) **before** Secure Boot.
- IDF 6.0: NISTP192 for Secure Boot ECDSA deprecated (NISTP256/384 recommended). `esp_secure_boot_verify_signature_block()` removed.
- Signed apps without hardware Secure Boot (`CONFIG_SECURE_SIGNED_APPS_NO_SECURE_BOOT`) only check OTA images. Weaker protection, availability per chip: verify.

## Flash encryption

- AES-XTS (chip-dependent), key in eFuse, transparent decryption via the flash cache. Encrypts app, bootloader, partition table and partitions flagged `encrypted`. **NVS is not covered by this**, it needs NVS encryption.
- Kconfig: `CONFIG_SECURE_FLASH_ENC_ENABLED`, mode via `CONFIG_SECURE_FLASH_ENCRYPTION_MODE` (Development/Release).
- **Development mode:** the bootloader encrypts plaintext images flashed via UART. Reflashing: `idf.py encrypted-flash` / `encrypted-app-flash`. This indirectly allows reading out the plaintext, so **not for production**. Encryption can be disabled again only to a limited extent via `SPI_BOOT_CRYPT_CNT`/`FLASH_CRYPT_CNT` (e.g. S3: **once per chip**; limit per chip in the docs) **[IRREVERSIBLE per step]**.
- **Release mode** **[IRREVERSIBLE]**: `SPI_BOOT_CRYPT_CNT` gets write-protected, and download mode can no longer write plaintext. Updates only via OTA or pre-encrypted images with a known key.
  - Important: selecting *Release* in menuconfig does **not** burn the eFuses on a device already running in development mode. For the transition, the app must call `esp_flash_encryption_set_release_mode()` once (check first with `esp_flash_encryption_cfg_verify_release_mode()`).
- Use a separate key per device (don't reuse keys across devices).
- Failure pattern: plaintext image on an encrypted device → garbled output, "invalid header" at the bootloader/app offset.
- IDF 6.0: `esp_flash_encryption_enabled()` deprecated → `esp_efuse_is_flash_encryption_enabled()`.

## NVS encryption

| Scheme | Key storage | Prerequisite |
|---|---|---|
| **HMAC-based** | NVS key is derived from an HMAC key in eFuse, no `nvs_keys` partition | chip with HMAC peripheral (not ESP32); flash encryption not required |
| **Flash-encryption-based** | keys in an `nvs_keys` partition (4 KB, flagged `encrypted`) | flash encryption enabled |

- Kconfig: `CONFIG_NVS_ENCRYPTION`, scheme via `CONFIG_NVS_SEC_KEY_PROTECTION_SCHEME`. **IDF 6.0:** on chips with HMAC and flash encryption enabled, HMAC is now the default. If you used the old scheme, set `CONFIG_NVS_SEC_KEY_PROTECT_USING_FLASH_ENC=y`.
- **[IRREVERSIBLE]** Burning the HMAC key (eFuse key block with HMAC purpose).
- The `nvs_keys` partition must be fully erased before the first start (otherwise `ESP_ERR_NVS_CORRUPT_KEY_PART`).
- Pre-encrypted factory NVS images: `nvs_partition_gen.py encrypt … --keygen [--key_protect_hmac --kp_hmac_keygen]`.

## eFuses

- Read: `espefuse --port PORT summary` (esptool v5: `--port` is **required** for all espefuse commands; IDF 6.0: eFuse commands in `idf.py` need a port).
- Anything that writes (`burn-efuse`, `burn-key`, `burn-key-digest`, `write-protect-efuse`, `read-protect-efuse`, `idf.py efuse-burn`) **[IRREVERSIBLE]**, only after explicit approval with the exact command shown.
- Virtual eFuses for tests: `CONFIG_EFUSE_VIRTUAL` (keep in flash with `CONFIG_EFUSE_VIRTUAL_KEEP_IN_FLASH`). Useful for simulating security workflows without burning.
- Anti-rollback (`secure_version`) consumes eFuse bits, see `partitions-ota.md` **[IRREVERSIBLE]**.

## Debug interfaces

- **JTAG:** hardware JTAG is disabled automatically when Secure Boot/flash encryption are activated (per docs). Chips with HMAC can soft-disable JTAG and re-enable it via HMAC. Explicit eFuses such as `DIS_PAD_JTAG`, `DIS_USB_JTAG` **[IRREVERSIBLE]**.
- **UART ROM download mode** (`CONFIG_SECURE_UART_ROM_DL_MODE`):
  - *Permanently disable ROM Download Mode* (recommended when not needed) **[IRREVERSIBLE]**, afterwards serial flashing is no longer possible at all. ESP32 only from v3.0.
  - *Permanently switch to Secure Download Mode* (default for newer chips in release mode) **[IRREVERSIBLE]**: only basic commands (SPI config, baud rate, flash write, `get-security-info`). esptool then only works with `--no-stub`, no readout, no `erase-flash` (only `erase-region`), and flash size must be passed via `--flash-size`.
  - Burn it as the **last** step. Afterwards no more eFuses can be burned via espefuse.
- Also check USB-Serial-JTAG/USB-OTG console and download on production devices.

## Signed OTA

- With Secure Boot v2, `esp_ota_end`/`esp_https_ota` verify the signature automatically. Unsigned images are rejected (`ESP_ERR_OTA_VALIDATE_FAILED`).
- Transport: HTTPS with server verification (bundle or pinned CA). Signature and transport are separate layers.
- Combine with rollback and anti-rollback.

## Secrets handling

- No Wi-Fi passwords, API keys, broker credentials or private keys in source code, repo or `sdkconfig.defaults`.
- Per-device secrets: factory NVS partition (generated and encrypted), provisioning (`network_provisioning`), or for TLS client keys a dedicated secure-cert partition (e.g. `espressif/esp_secure_cert_mgr`, DS peripheral depending on chip: verify).
- Signing and flash encryption keys: HSM or at least an isolated, backed-up environment. Never in CI logs.
- Firmware images without Secure Boot/flash encryption can be read out and modified. Treat anything in the image as public.

## Production checklist

- [ ] Target revision and security features confirmed per chip (`chip_info`, datasheet), workflow tested on sacrificial devices
- [ ] Signing key securely generated, backed up, access restricted; decided whether multiple digests/revocation are used
- [ ] Secure Boot v2 enabled, bootloader signed, partition table offset large enough for the bigger bootloader
- [ ] Flash encryption **release**, per-device key, encrypted partitions flagged
- [ ] NVS encryption (HMAC or nvs_keys), factory data in its own read-only partition
- [ ] UART download mode: disabled or secure download mode; JTAG disabled
- [ ] Rollback enabled, self-test defined; anti-rollback plan (bit budget)
- [ ] OTA only via HTTPS with server verification, signed images
- [ ] Log level reduced for production, no secrets in logs
- [ ] Order of eFuse burns documented, every **[IRREVERSIBLE]** step approved

## Sources

- Security overview: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/security/security.html
- Secure Boot v2: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/security/secure-boot-v2.html
- Flash encryption (ESP32 / S3): https://docs.espressif.com/projects/esp-idf/en/latest/esp32/security/flash-encryption.html, https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/security/flash-encryption.html
- Security features enablement workflows: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/security/security-features-enablement-workflows.html
- NVS encryption: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/storage/nvs_encryption.html
- eFuse manager: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/system/efuse.html
- espefuse: https://docs.espressif.com/projects/esptool/en/latest/esp32/espefuse/index.html
- esptool v5 migration (espefuse/espsecure): https://docs.espressif.com/projects/esptool/en/latest/esp32/migration-guide.html
- esptool known limitations (secure download mode): https://docs.espressif.com/projects/esptool/en/latest/esp32/troubleshooting.html
- Migration 6.0 security: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-6.x/6.0/security.html
