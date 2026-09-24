from esp_expert_mcp import partitions

OTA_4MB = """# Name, Type, SubType, Offset, Size, Flags
nvs,      data, nvs,     0x9000,  0x5000,
otadata,  data, ota,     0xe000,  0x2000,
app0,     app,  ota_0,   0x10000, 0x1E0000,
app1,     app,  ota_1,   0x1F0000,0x1E0000,
spiffs,   data, spiffs,  0x3D0000,0x20000,
coredump, data, coredump,0x3F0000,0x10000,
"""


def test_valid_ota_layout():
    r = partitions.validate(OTA_4MB, "4MB", "esp32")
    assert r["valid"], r["errors"]
    assert len(r["partitions"]) == 6


def test_misaligned_app_and_overflow():
    csv = "nvs,data,nvs,0x9000,0x6000\nfactory,app,factory,0xF000,3M\n"
    r = partitions.validate(csv, "2MB")
    assert not r["valid"]
    assert any("ausgerichtet" in e for e in r["errors"])
    assert any("größer als Flash" in e for e in r["errors"])


def test_auto_offsets_and_missing_otadata():
    csv = "nvs,data,nvs,,24K\nota_0,app,ota_0,,1M\nota_1,app,ota_1,,1M\n"
    r = partitions.validate(csv, "4MB")
    offs = [p["offset"] for p in r["partitions"]]
    assert offs == ["0x9000", "0x10000", "0x110000"]
    assert any("otadata" in e for e in r["errors"])


def test_otadata_size_and_overlap():
    csv = "nvs,data,nvs,0x9000,0x6000\notadata,data,ota,0xd000,0x1000\nx,app,factory,0x10000,1M\ny,data,fat,0x100000,64K\n"
    r = partitions.validate(csv)
    assert any("0x2000" in e for e in r["errors"])
    assert any("Überlappung" in e for e in r["errors"])
