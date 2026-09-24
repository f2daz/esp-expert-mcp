from esp_expert_mcp import panic

ESP32_LOG = """rst:0xc (SW_CPU_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)
Guru Meditation Error: Core  1 panic'ed (LoadProhibited). Exception was unhandled.
Core  1 register dump:
PC      : 0x400d1f2a  PS      : 0x00060630  A0      : 0x800d2b1c  A1      : 0x3ffb1f50
EXCCAUSE: 0x0000001c  EXCVADDR: 0x00000008  LBEG    : 0x4000c2e0
Backtrace: 0x400d1f27:0x3ffb1f50 0x400d2b19:0x3ffb1f70 0x40089a2e:0x3ffb1f90
"""

ESP8266_LOG = """
--------------- CUT HERE FOR EXCEPTION DECODER ---------------
Exception (29):
epc1=0x40201234 epc2=0x00000000 epc3=0x00000000 excvaddr=0x00000000 depc=0x00000000
>>>stack>>>
ctx: cont
sp: 3ffffdc0 end: 3fffffc0 offset: 0190
3fffff50:  40201234 3ffee5b8 3ffee5b8 40202f3d
<<<stack<<<
 ets Jan  8 2013,rst cause:2, boot mode:(3,6)
"""

RISCV_LOG = """Guru Meditation Error: Core  0 panic'ed (Load access fault). Exception was unhandled.
MEPC    : 0x42008a1c  RA      : 0x42008a10  SP      : 0x3fc9e1a0
MCAUSE  : 0x00000005  MTVAL   : 0x00000000
"""


def test_esp32_loadprohibited():
    r = panic.analyze(ESP32_LOG)
    assert r["reset"][0]["name"] == "SW_CPU_RESET"
    p = [f for f in r["findings"] if f["category"] == "panic"][0]
    assert p["reason"] == "LoadProhibited" and "NULL" in p["hint"]
    assert r["backtrace_addresses"] == ["0x400d1f27", "0x400d2b19", "0x40089a2e"]
    assert any("NULL" in str(d) for d in r["derived"])


def test_esp8266_exception():
    r = panic.analyze(ESP8266_LOG)
    assert any(f.get("name") == "StoreProhibited" for f in r["findings"])
    assert r["backtrace_addresses"] == ["0x40201234", "0x40202f3d"]
    assert any(x.get("platform") == "esp8266" for x in r["reset"])


def test_riscv():
    r = panic.analyze(RISCV_LOG)
    assert r["backtrace_addresses"][0] == "0x42008a1c"
    assert any(d.get("MCAUSE") == 5 for d in r["derived"])


def test_stack_overflow_and_brownout():
    r = panic.analyze("***ERROR*** A stack overflow in task sensor_task has been detected.\nBrownout detector was triggered\n")
    cats = {f["category"] for f in r["findings"]}
    assert {"stack_overflow", "brownout"} <= cats
