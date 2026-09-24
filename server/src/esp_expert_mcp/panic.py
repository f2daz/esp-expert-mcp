"""Serial log analysis: reset reasons, Guru Meditation, ESP8266 exceptions,
backtraces (optionally resolved via addr2line against the matching ELF)."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess

from . import errcodes

# Xtensa EXCCAUSE (ESP32/S2/S3 and ESP8266 "Exception (n)")
XTENSA_EXCCAUSE = {
    0: ("IllegalInstruction", "Invalid opcode – often a jump into data, a corrupted function pointer or stack corruption."),
    2: ("InstructionFetchError", "Instruction could not be fetched – PC points to invalid memory."),
    3: ("LoadStoreError", "Access with wrong width, e.g. 8/16-bit access to IRAM/flash constants (ESP8266: PROGMEM without pgm_read_*)."),
    4: ("Level1Interrupt", "Level-1 interrupt – normally not an error."),
    6: ("IntegerDivideByZero", "Division by zero."),
    9: ("LoadStoreAlignment", "Unaligned access (e.g. uint32_t* on an odd address, packed structs)."),
    20: ("InstFetchProhibited", "Jump to a non-executable address – usually a NULL or freed callback/function pointer."),
    28: ("LoadProhibited", "Read from an invalid address – EXCVADDR near 0 ⇒ NULL pointer dereference."),
    29: ("StoreProhibited", "Write to an invalid address – EXCVADDR near 0 ⇒ NULL pointer, otherwise buffer overflow/use-after-free."),
}

# RISC-V mcause (ESP32-C2/C3/C5/C6/H2/P4)
RISCV_MCAUSE = {
    0: ("Instruction address misaligned", "Jump target not aligned – corrupted function pointer."),
    1: ("Instruction access fault", "Jump to a non-executable address – NULL/invalid function pointer."),
    2: ("Illegal instruction", "Invalid opcode – stack corruption or jump into data; also a result of abort() in some IDF versions."),
    3: ("Breakpoint", "ebreak – often from abort()/assert or a debugger."),
    4: ("Load address misaligned", "Unaligned read."),
    5: ("Load access fault", "Read from an invalid address – MTVAL near 0 ⇒ NULL pointer."),
    6: ("Store address misaligned", "Unaligned write."),
    7: ("Store access fault", "Write to an invalid address – NULL pointer, buffer overflow, use-after-free."),
    8: ("Environment call from U-mode", "ecall from user mode."),
    11: ("Environment call from M-mode", "ecall from machine mode."),
}

# Reset reasons (names as printed by ROM/ESP-IDF)
RESET_REASONS = {
    "POWERON_RESET": "Power-on – normal cold start. If unexpected: is the supply dropping?",
    "POWERON": "Power-on.",
    "SW_RESET": "Software reset of the chip (esp_restart()).",
    "SW_CPU_RESET": "Software reset of the CPU – esp_restart() or restart after a panic.",
    "RTC_SW_CPU_RESET": "Software reset of the CPU – esp_restart() or restart after a panic.",
    "RTC_SW_SYS_RESET": "Software system reset (esp_restart()).",
    "DEEPSLEEP_RESET": "Wake-up from deep sleep – expected when deep sleep is used.",
    "OWDT_RESET": "Legacy watchdog.",
    "TG0WDT_SYS_RESET": "Timer group 0 watchdog (interrupt WDT) – ISR or critical section too long, interrupts blocked.",
    "TG1WDT_SYS_RESET": "Timer group 1 watchdog (interrupt/task WDT depending on config).",
    "TGWDT_CPU_RESET": "Timer group watchdog reset of the CPU.",
    "TG0WDT_CPU_RESET": "Timer group 0 watchdog reset of the CPU.",
    "TG1WDT_CPU_RESET": "Timer group 1 watchdog reset of the CPU.",
    "RTCWDT_SYS_RESET": "RTC watchdog – common during boot (bootloader hangs, flash problems) or after a brownout.",
    "RTCWDT_CPU_RESET": "RTC watchdog reset of the CPU.",
    "RTCWDT_RTC_RESET": "RTC watchdog resets the digital and RTC domains – common with an unstable supply.",
    "RTCWDT_BROWN_OUT_RESET": "Brownout – supply voltage dropped. Check power supply, cable, bulk capacitor, Wi-Fi TX peaks.",
    "BROWNOUT_RESET": "Brownout – supply voltage dropped.",
    "EXT_CPU_RESET": "External CPU reset (e.g. by the other CPU / APP_CPU).",
    "INTRUSION_RESET": "Intrusion-Reset.",
    "SDIO_RESET": "Reset via SDIO.",
    "USB_UART_CHIP_RESET": "Reset via USB-Serial/JTAG (e.g. by esptool/monitor).",
    "USB_JTAG_CHIP_RESET": "Reset via USB-JTAG.",
    "SUPER_WDT_RESET": "Super watchdog – severe hang.",
    "GLITCH_RTC_RESET": "Glitch detector (voltage/clock glitch).",
    "EFUSE_RESET": "eFuse CRC error.",
    "JTAG_RESET": "Reset via JTAG.",
    "CHIP_POWER_ON_RESET": "Power-on.",
    "CHIP_BROWN_OUT_RESET": "Brownout.",
    "CORE_SW_RESET": "Software reset of the CPU.",
    "CORE_DEEP_SLEEP": "Wake-up from deep sleep.",
    "CORE_MWDT0": "Watchdog (MWDT0).",
    "CORE_MWDT1": "Watchdog (MWDT1).",
    "CORE_RTC_WDT": "RTC watchdog.",
    "SYS_RTC_WDT": "RTC watchdog (system).",
    "SYS_BROWN_OUT": "Brownout.",
    "SYS_SUPER_WDT": "Super watchdog.",
    "CORE_USB_UART": "Reset via USB-Serial/JTAG.",
    "CORE_USB_JTAG": "Reset via USB-JTAG.",
}

# ESP8266 ROM: "rst cause:N"
ESP8266_RST_CAUSE = {
    1: "Power-on",
    2: "External reset (RST pin) or wake-up from deep sleep (GPIO16→RST)",
    4: "Hardware watchdog – code blocks without yield()/delay() or interrupts disabled for too long",
}
# ESP8266 SDK/Arduino rst_info.reason
ESP8266_RST_REASON = {
    0: "REASON_DEFAULT_RST – Power-on",
    1: "REASON_WDT_RST – hardware watchdog",
    2: "REASON_EXCEPTION_RST – exception (see exception number)",
    3: "REASON_SOFT_WDT_RST – software watchdog: loop()/callback blocks without yield()",
    4: "REASON_SOFT_RESTART – ESP.restart()/ESP.reset()",
    5: "REASON_DEEP_SLEEP_AWAKE – wake-up from deep sleep",
    6: "REASON_EXT_SYS_RST – external reset",
}

PATTERNS: list[tuple[str, str, str]] = [
    # (regex, category, hint)
    (r"Guru Meditation Error: Core\s+(\d) panic'ed \(([^)]+)\)", "panic", ""),
    (r"\*\*\*ERROR\*\*\* A stack overflow in task (\S+) has been detected", "stack_overflow",
     "Task stack too small: increase the stack size (xTaskCreate), make large local buffers static/heap, measure uxTaskGetStackHighWaterMark()."),
    (r"Stack canary watchpoint triggered \((\S+)\)", "stack_overflow",
     "Stack canary of the named task triggered – increase the stack, check recursion/large local arrays."),
    (r"Stack protection fault|Stack pointer.*out of bounds", "stack_overflow", "Stack overflow."),
    (r"abort\(\) was called at PC (0x[0-9a-fA-F]+) on core (\d)", "abort",
     "abort() – decode the backtrace; often triggered by assert/ESP_ERROR_CHECK/new without memory."),
    (r"assert failed: (.+)", "assert", "Assertion failed – check the condition and the caller in the backtrace."),
    (r"ESP_ERROR_CHECK failed: esp_err_t (0x[0-9a-fA-F]+)(?: \((\w+)\))?", "esp_error_check", ""),
    (r"CORRUPT HEAP|heap_caps_free.*corrupt|Bad head at", "heap_corruption",
     "Heap corruption: buffer overflow, double free, use-after-free. Use CONFIG_HEAP_POISONING_COMPREHENSIVE and heap_caps_check_integrity_all()."),
    (r"Task watchdog got triggered", "task_wdt",
     "Task WDT: a task is hogging the CPU (busy loop without vTaskDelay, deadlock, long flash operation). The affected task is listed in the following lines."),
    (r"Interrupt wdt timeout on CPU(\d)", "int_wdt",
     "Interrupt WDT: ISR too long or interrupts disabled for too long in a critical section (portENTER_CRITICAL, spinlock deadlock)."),
    (r"Brownout detector was triggered", "brownout",
     "Brownout: supply is dropping. Check USB cable/power supply, LDO, bulk capacitor (≥100 µF near 3V3), Wi-Fi TX peaks – do not simply disable the detector."),
    (r"Cache disabled but cached memory region accessed", "cache_disabled",
     "Code/data in flash was accessed while the flash cache was disabled (ISR without IRAM_ATTR, flash write). Place the ISR and the functions it calls in IRAM."),
    (r"Double exception", "double_exception", "Double exception – usually a stack overflow in the exception handler or massive stack corruption."),
    (r"invalid header: 0x[0-9a-fA-F]+", "boot_invalid_header",
     "Bootloader finds no valid image: wrong flash mode/offset, empty flash or wrong strapping pins (e.g. GPIO12 on ESP32)."),
    (r"flash read err|ets_main\.c", "boot_flash",
     "Boot error while reading flash: check flash mode (QIO/DIO), flash frequency, strapping pin GPIO12 (VDD_SDIO)."),
    (r"E \(\d+\) (\w+): (.+)", "esp_log_error", ""),
    (r"Soft WDT reset", "esp8266_soft_wdt", "ESP8266 soft WDT: loop()/callback blocks > ~3 s without yield()/delay()."),
    (r"wdt reset", "esp8266_hw_wdt", "ESP8266 hardware WDT: very long blocking or interrupts disabled."),
    (r"Panic (\S+):(\d+) (.+)", "esp8266_panic", "ESP8266 core panic (file:line) – often an assert or heap problem."),
    (r"MEMORY ALLOCATION FAILED|heap_caps_malloc.*failed|Out of memory|OOM", "oom",
     "Memory exhausted: log esp_get_free_heap_size()/heap_caps_get_largest_free_block(), check fragmentation, use PSRAM."),
]



def _explain_reset(log: str) -> list[dict]:
    out = []
    for m in re.finditer(r"rst:(0x[0-9a-fA-F]+) \(([A-Z0-9_]+)\)(?:,boot:(0x[0-9a-fA-F]+) \(([^)]*)\))?", log):
        code, name, boot, bootname = m.groups()
        entry = {"raw": m.group(0), "code": code, "name": name,
                 "meaning": RESET_REASONS.get(name, "Unknown reset name – look it up in ESP-IDF esp_rom/…/rtc.h.")}
        if bootname:
            entry["boot_mode"] = bootname
            if "DOWNLOAD" in bootname:
                entry["boot_hint"] = ("Chip boots into download mode: the boot strapping pin was LOW at reset "
                                      "(ESP32/S2/S3: GPIO0, C2/C3/C6/H2: GPIO9 – other targets: chip_info).")
        out.append(entry)
    for m in re.finditer(r"rst cause:(\d+), boot mode:\((\d),(\d)\)", log):
        cause, mode, _ = m.groups()
        out.append({
            "raw": m.group(0), "platform": "esp8266",
            "meaning": ESP8266_RST_CAUSE.get(int(cause), "unknown"),
            "boot_mode": {"1": "UART download (GPIO0=LOW)", "3": "flash boot (normal)"}.get(mode, f"mode {mode}"),
        })
    for m in re.finditer(r"Fatal exception:(\d+) flag:(\d)", log):
        flag = int(m.group(2))
        out.append({"raw": m.group(0), "platform": "esp8266",
                    "meaning": ESP8266_RST_REASON.get(flag, f"rst_info.reason {flag}")})
    return out


def _registers(log: str) -> dict:
    regs = {}
    for name in ("PC", "PS", "EXCCAUSE", "EXCVADDR", "MEPC", "MCAUSE", "MTVAL", "RA", "SP", "epc1", "excvaddr", "depc"):
        m = re.search(rf"\b{name}\s*[:=]\s*(0x[0-9a-fA-F]+)", log)
        if m:
            regs[name] = m.group(1)
    return regs


def _find_addr2line(arch: str | None) -> list[str]:
    names = {
        "xtensa": ["xtensa-esp-elf-addr2line", "xtensa-esp32-elf-addr2line", "xtensa-esp32s3-elf-addr2line", "xtensa-esp32s2-elf-addr2line"],
        "riscv": ["riscv32-esp-elf-addr2line"],
        "lx106": ["xtensa-lx106-elf-addr2line"],
    }
    candidates = names.get(arch or "", []) or sum(names.values(), [])
    found = []
    for n in candidates:
        p = shutil.which(n)
        if p:
            found.append(p)
    if not found:
        roots = [os.path.expanduser("~/.espressif/tools"), os.path.expanduser("~/.platformio/packages"),
                 os.path.expanduser("~/Library/Arduino15/packages"), os.path.expanduser("~/.arduino15/packages")]
        for root in roots:
            for n in candidates:
                found += glob.glob(f"{root}/**/bin/{n}", recursive=True)
    return found


def _elf_arch(elf: str) -> str | None:
    """e_machine from the ELF header: 94 = Xtensa, 243 = RISC-V."""
    try:
        with open(elf, "rb") as fh:
            head = fh.read(20)
    except OSError:
        return None
    if head[:4] != b"\x7fELF":
        return None
    machine = int.from_bytes(head[18:20], "little")
    return {94: "xtensa", 243: "riscv"}.get(machine)


def decode_addresses(addresses: list[str], elf: str, arch: str | None = None) -> dict:
    if not os.path.isfile(elf):
        return {"error": f"ELF not found: {elf}"}
    # ESP8266 (lx106) also has e_machine Xtensa – keep an explicit arch
    arch = arch if arch == "lx106" else (_elf_arch(elf) or arch)
    tools = _find_addr2line(arch)
    if not tools:
        return {"error": "No addr2line found (xtensa-esp-elf / riscv32-esp-elf / xtensa-lx106-elf). "
                         "Activate the ESP-IDF environment or provide the toolchain path."}
    tool = tools[0]
    try:
        res = subprocess.run([tool, "-pfiaC", "-e", elf, *addresses], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": str(e)}
    frames = [l.strip() for l in res.stdout.splitlines() if l.strip()]
    return {"tool": tool, "frames": frames, "stderr": res.stderr.strip() or None}


def analyze(log: str, elf: str | None = None, arch: str | None = None) -> dict:
    findings = []
    log_errors = 0
    for rx, cat, hint in PATTERNS:
        for m in re.finditer(rx, log):
            if cat == "esp_log_error":
                log_errors += 1
                if log_errors > 20:
                    continue
            f = {"category": cat, "match": m.group(0).strip()}
            if cat == "panic":
                f["core"] = int(m.group(1))
                f["reason"] = m.group(2)
                f["hint"] = _panic_hint(m.group(2))
            elif cat == "esp_error_check":
                f["code"] = m.group(1)
                f["name"] = m.group(2) or errcodes.lookup(m.group(1)).get("name")
                f["hint"] = "ESP_ERROR_CHECK aborts on error. Handle the return value instead of aborting; determine the cause from the error code."
            elif cat == "esp_log_error":
                f["tag"], f["message"] = m.group(1), m.group(2)[:200]
            elif hint:
                f["hint"] = hint
            findings.append(f)

    m8266 = re.search(r"Exception \((\d+)\):", log)
    if m8266:
        n = int(m8266.group(1))
        name, hint = XTENSA_EXCCAUSE.get(n, (f"EXCCAUSE {n}", "see Xtensa ISA"))
        findings.append({"category": "esp8266_exception", "exccause": n, "name": name, "hint": hint})

    regs = _registers(log)
    derived = []
    if "EXCCAUSE" in regs:
        c = int(regs["EXCCAUSE"], 16)
        derived.append({"EXCCAUSE": c, "meaning": XTENSA_EXCCAUSE.get(c, ("?", ""))})
    if "MCAUSE" in regs:
        c = int(regs["MCAUSE"], 16) & 0x7FFFFFFF
        derived.append({"MCAUSE": c, "meaning": RISCV_MCAUSE.get(c, ("?", ""))})
    for key in ("EXCVADDR", "MTVAL", "excvaddr"):
        if key in regs:
            v = int(regs[key], 16)
            if v < 0x1000:
                derived.append({key: regs[key], "meaning": "Address near 0 ⇒ NULL pointer (possibly with a field offset into a struct)."})

    backtrace = []
    bt = re.search(r"Backtrace:\s*((?:0x[0-9a-fA-F]+:0x[0-9a-fA-F]+\s*)+)", log)
    if bt:
        backtrace = [pair.split(":")[0] for pair in bt.group(1).split()]
        if "CORRUPTED" in log[bt.end():bt.end() + 40]:
            derived.append({"backtrace": "|<-CORRUPTED – stack corrupted, backtrace incomplete."})
    if not backtrace:
        stack = re.search(r">>>stack>>>(.*?)<<<stack<<<", log, re.S)
        if stack:  # ESP8266: code addresses from the stack dump
            # IRAM 0x401xxxxx, flash (irom0) 0x402xxxxx; stack dump without 0x prefix, first column = stack address
            words = re.findall(r"(?<![0-9a-fA-F:])(40[12][0-9a-fA-F]{5})(?![0-9a-fA-F:])", stack.group(1))
            backtrace = list(dict.fromkeys(f"0x{w.lower()}" for w in words))
            arch = arch or "lx106"
    if not backtrace and "MEPC" in regs:
        backtrace = [regs["MEPC"]] + ([regs["RA"]] if "RA" in regs else [])
        arch = arch or "riscv"
    if "epc1" in regs and regs["epc1"] not in backtrace:
        backtrace.insert(0, regs["epc1"])

    result = {
        "reset": _explain_reset(log),
        "findings": findings,
        "registers": regs,
        "derived": derived,
        "backtrace_addresses": backtrace,
    }
    if elf and backtrace:
        result["decoded"] = decode_addresses(backtrace, elf, arch)
    elif backtrace:
        result["decoded"] = ("No ELF given. With 'elf' (e.g. build/<project>.elf, .pio/build/<env>/firmware.elf, "
                             "ESPHome: .esphome/build/<name>/.pioenvs/<name>/firmware.elf) the addresses are resolved.")
    if not findings and not result["reset"]:
        result["note"] = "No known error patterns found. Pass the complete log starting at reset."
    return result


def _panic_hint(reason: str) -> str:
    for _, (name, hint) in {**XTENSA_EXCCAUSE, **{100 + k: v for k, v in RISCV_MCAUSE.items()}}.items():
        if name.lower() in reason.lower():
            return hint
    if "Unhandled debug exception" in reason:
        return "Usually a stack canary/watchpoint – stack overflow of the task named in the following lines."
    if "Interrupt wdt" in reason:
        return "Interrupt watchdog – ISR/critical section too long."
    if "Cache" in reason:
        return "Flash cache was disabled – place ISR/functions in IRAM."
    return "Decode the backtrace against the matching ELF."
