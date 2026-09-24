from esp_expert_mcp import sdkconfig

SDK = '''CONFIG_IDF_TARGET="esp32s3"
CONFIG_ESPTOOLPY_FLASHSIZE="8MB"
CONFIG_SECURE_FLASH_ENC_ENABLED=y
CONFIG_SECURE_FLASH_ENCRYPTION_MODE_DEVELOPMENT=y
# CONFIG_ESP_TASK_WDT_EN is not set
CONFIG_FREERTOS_HZ=100
CONFIG_ESP_MAIN_TASK_STACK_SIZE=3072
CONFIG_PARTITION_TABLE_CUSTOM=y
CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions.csv"
'''


def test_analyze(tmp_path):
    (tmp_path / "sdkconfig").write_text(SDK)
    (tmp_path / "sdkconfig.defaults").write_text("CONFIG_FREERTOS_HZ=1000\n")
    (tmp_path / "partitions.csv").write_text("nvs,data,nvs,0x9000,0x5000\n")
    r = sdkconfig.analyze(str(tmp_path / "sdkconfig"))
    assert r["summary"]["target"] == "esp32s3" and r["summary"]["flash_size"] == "8MB"
    msgs = " ".join(f["message"] for f in r["findings"])
    for s in ("DEVELOPMENT", "Task-Watchdog", "100 Hz", "3072"):
        assert s in msgs
    assert r["partition_csv_path"].endswith("partitions.csv")
    assert r["defaults_drift"][0]["key"] == "CONFIG_FREERTOS_HZ"
    g = sdkconfig.get(str(tmp_path / "sdkconfig"), ["FREERTOS_HZ", "SECURE"])
    assert g["CONFIG_FREERTOS_HZ"] == "100" and len(g["CONFIG_SECURE"]) == 2
