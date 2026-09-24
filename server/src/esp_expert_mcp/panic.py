"""Analyse von Serial-Logs: Reset-Gründe, Guru-Meditation, ESP8266-Exceptions,
Backtraces (optional per addr2line gegen die passende ELF aufgelöst)."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess

from . import errcodes

# Xtensa EXCCAUSE (ESP32/S2/S3 und ESP8266 "Exception (n)")
XTENSA_EXCCAUSE = {
    0: ("IllegalInstruction", "Ungültiger Opcode – oft Sprung in Datenbereich, zerstörter Funktionszeiger oder Stack-Korruption."),
    2: ("InstructionFetchError", "Befehl konnte nicht geladen werden – PC zeigt auf ungültigen Speicher."),
    3: ("LoadStoreError", "Zugriff mit falscher Breite, z. B. 8/16-Bit-Zugriff auf IRAM/Flash-Konstanten (ESP8266: PROGMEM ohne pgm_read_*)."),
    4: ("Level1Interrupt", "Interrupt-Level-1 – normalerweise kein Fehler."),
    6: ("IntegerDivideByZero", "Division durch Null."),
    9: ("LoadStoreAlignment", "Unausgerichteter Zugriff (z. B. uint32_t* auf ungerade Adresse, gepackte Structs)."),
    20: ("InstFetchProhibited", "Sprung an nicht ausführbare Adresse – meist NULL- oder gelöschter Callback/Funktionszeiger."),
    28: ("LoadProhibited", "Lesezugriff auf ungültige Adresse – EXCVADDR nahe 0 ⇒ NULL-Pointer-Dereferenzierung."),
    29: ("StoreProhibited", "Schreibzugriff auf ungültige Adresse – EXCVADDR nahe 0 ⇒ NULL-Pointer, sonst Pufferüberlauf/Use-after-free."),
}

# RISC-V mcause (ESP32-C2/C3/C5/C6/H2/P4)
RISCV_MCAUSE = {
    0: ("Instruction address misaligned", "Sprungziel nicht ausgerichtet – zerstörter Funktionszeiger."),
    1: ("Instruction access fault", "Sprung an nicht ausführbare Adresse – NULL-/ungültiger Funktionszeiger."),
    2: ("Illegal instruction", "Ungültiger Opcode – Stack-Korruption oder Sprung in Daten; auch Folge von abort() in manchen IDF-Versionen."),
    3: ("Breakpoint", "ebreak – oft durch abort()/assert oder Debugger."),
    4: ("Load address misaligned", "Unausgerichteter Lesezugriff."),
    5: ("Load access fault", "Lesezugriff auf ungültige Adresse – MTVAL nahe 0 ⇒ NULL-Pointer."),
    6: ("Store address misaligned", "Unausgerichteter Schreibzugriff."),
    7: ("Store access fault", "Schreibzugriff auf ungültige Adresse – NULL-Pointer, Pufferüberlauf, Use-after-free."),
    8: ("Environment call from U-mode", "ecall aus User-Mode."),
    11: ("Environment call from M-mode", "ecall aus Machine-Mode."),
}

# Reset-Gründe (Namen wie sie ROM/ESP-IDF ausgeben)
RESET_REASONS = {
    "POWERON_RESET": "Einschalten/Power-on – normaler Kaltstart. Tritt er unerwartet auf: Versorgung einbrechend?",
    "POWERON": "Einschalten/Power-on.",
    "SW_RESET": "Software-Reset des Chips (esp_restart()).",
    "SW_CPU_RESET": "Software-Reset der CPU – esp_restart() oder Neustart nach Panic.",
    "RTC_SW_CPU_RESET": "Software-Reset der CPU – esp_restart() oder Neustart nach Panic.",
    "RTC_SW_SYS_RESET": "Software-System-Reset (esp_restart()).",
    "DEEPSLEEP_RESET": "Aufwachen aus Deep-Sleep – erwartet, wenn Deep-Sleep genutzt wird.",
    "OWDT_RESET": "Legacy-Watchdog.",
    "TG0WDT_SYS_RESET": "Timer-Group-0-Watchdog (Interrupt-WDT) – ISR oder Critical Section zu lang, Interrupts blockiert.",
    "TG1WDT_SYS_RESET": "Timer-Group-1-Watchdog (Interrupt-/Task-WDT je nach Konfig).",
    "TGWDT_CPU_RESET": "Timer-Group-Watchdog-Reset der CPU.",
    "TG0WDT_CPU_RESET": "Timer-Group-0-Watchdog-Reset der CPU.",
    "TG1WDT_CPU_RESET": "Timer-Group-1-Watchdog-Reset der CPU.",
    "RTCWDT_SYS_RESET": "RTC-Watchdog – häufig beim Booten (Bootloader hängt, Flash-Probleme) oder nach Brownout.",
    "RTCWDT_CPU_RESET": "RTC-Watchdog-Reset der CPU.",
    "RTCWDT_RTC_RESET": "RTC-Watchdog setzt Digital- und RTC-Domäne zurück – häufig bei instabiler Versorgung.",
    "RTCWDT_BROWN_OUT_RESET": "Brownout – Versorgungsspannung eingebrochen. Netzteil, Kabel, Stützkondensator, Wi-Fi-TX-Spitzen prüfen.",
    "BROWNOUT_RESET": "Brownout – Versorgungsspannung eingebrochen.",
    "EXT_CPU_RESET": "Externer CPU-Reset (z. B. durch die andere CPU / APP_CPU).",
    "INTRUSION_RESET": "Intrusion-Reset.",
    "SDIO_RESET": "Reset über SDIO.",
    "USB_UART_CHIP_RESET": "Reset über USB-Serial/JTAG (z. B. durch esptool/Monitor).",
    "USB_JTAG_CHIP_RESET": "Reset über USB-JTAG.",
    "SUPER_WDT_RESET": "Super-Watchdog – schwerer Hänger.",
    "GLITCH_RTC_RESET": "Glitch-Detektor (Spannungs-/Taktglitch).",
    "EFUSE_RESET": "eFuse-CRC-Fehler.",
    "JTAG_RESET": "Reset über JTAG.",
    "CHIP_POWER_ON_RESET": "Einschalten/Power-on.",
    "CHIP_BROWN_OUT_RESET": "Brownout.",
    "CORE_SW_RESET": "Software-Reset der CPU.",
    "CORE_DEEP_SLEEP": "Aufwachen aus Deep-Sleep.",
    "CORE_MWDT0": "Watchdog (MWDT0).",
    "CORE_MWDT1": "Watchdog (MWDT1).",
    "CORE_RTC_WDT": "RTC-Watchdog.",
    "SYS_RTC_WDT": "RTC-Watchdog (System).",
    "SYS_BROWN_OUT": "Brownout.",
    "SYS_SUPER_WDT": "Super-Watchdog.",
    "CORE_USB_UART": "Reset über USB-Serial/JTAG.",
    "CORE_USB_JTAG": "Reset über USB-JTAG.",
}

# ESP8266 ROM: "rst cause:N"
ESP8266_RST_CAUSE = {
    1: "Power-on",
    2: "Externer Reset (RST-Pin) oder Aufwachen aus Deep-Sleep (GPIO16→RST)",
    4: "Hardware-Watchdog – Code blockiert ohne yield()/delay() oder Interrupts zu lange gesperrt",
}
# ESP8266 SDK/Arduino rst_info.reason
ESP8266_RST_REASON = {
    0: "REASON_DEFAULT_RST – Power-on",
    1: "REASON_WDT_RST – Hardware-Watchdog",
    2: "REASON_EXCEPTION_RST – Exception (siehe Exception-Nummer)",
    3: "REASON_SOFT_WDT_RST – Software-Watchdog: loop()/Callback blockiert ohne yield()",
    4: "REASON_SOFT_RESTART – ESP.restart()/ESP.reset()",
    5: "REASON_DEEP_SLEEP_AWAKE – Aufwachen aus Deep-Sleep",
    6: "REASON_EXT_SYS_RST – externer Reset",
}

PATTERNS: list[tuple[str, str, str]] = [
    # (regex, Kategorie, Hinweis)
    (r"Guru Meditation Error: Core\s+(\d) panic'ed \(([^)]+)\)", "panic", ""),
    (r"\*\*\*ERROR\*\*\* A stack overflow in task (\S+) has been detected", "stack_overflow",
     "Stack der Task zu klein: Stackgröße erhöhen (xTaskCreate), große lokale Puffer static/heap machen, uxTaskGetStackHighWaterMark() messen."),
    (r"Stack canary watchpoint triggered \((\S+)\)", "stack_overflow",
     "Stack-Canary der genannten Task ausgelöst – Stack erhöhen, Rekursion/große lokale Arrays prüfen."),
    (r"Stack protection fault|Stack pointer.*out of bounds", "stack_overflow", "Stack-Überlauf."),
    (r"abort\(\) was called at PC (0x[0-9a-fA-F]+) on core (\d)", "abort",
     "abort() – Backtrace dekodieren; oft ausgelöst von assert/ESP_ERROR_CHECK/new ohne Speicher."),
    (r"assert failed: (.+)", "assert", "Assertion fehlgeschlagen – Bedingung und Aufrufer im Backtrace prüfen."),
    (r"ESP_ERROR_CHECK failed: esp_err_t (0x[0-9a-fA-F]+)(?: \((\w+)\))?", "esp_error_check", ""),
    (r"CORRUPT HEAP|heap_caps_free.*corrupt|Bad head at", "heap_corruption",
     "Heap-Korruption: Pufferüberlauf, doppeltes free, Use-after-free. CONFIG_HEAP_POISONING_COMPREHENSIVE und heap_caps_check_integrity_all() nutzen."),
    (r"Task watchdog got triggered", "task_wdt",
     "Task-WDT: eine Task blockiert die CPU (Busy-Loop ohne vTaskDelay, Deadlock, lange Flash-Operation). Betroffene Task steht in den Folgezeilen."),
    (r"Interrupt wdt timeout on CPU(\d)", "int_wdt",
     "Interrupt-WDT: ISR zu lang oder Interrupts in Critical Section zu lange gesperrt (portENTER_CRITICAL, Spinlock-Deadlock)."),
    (r"Brownout detector was triggered", "brownout",
     "Brownout: Versorgung bricht ein. USB-Kabel/Netzteil, LDO, Stützkondensator (≥100 µF nahe 3V3), Wi-Fi-TX-Spitzen prüfen – Detektor nicht einfach abschalten."),
    (r"Cache disabled but cached memory region accessed", "cache_disabled",
     "Code/Daten im Flash wurden benutzt, während der Flash-Cache aus war (ISR ohne IRAM_ATTR, Flash-Schreibvorgang). ISR und aufgerufene Funktionen in IRAM legen."),
    (r"Double exception", "double_exception", "Double Exception – meist Stack-Überlauf in Exception-Handler oder massive Stack-Korruption."),
    (r"invalid header: 0x[0-9a-fA-F]+", "boot_invalid_header",
     "Bootloader findet kein gültiges Image: falscher Flash-Modus/-Offset, Flash leer oder Strapping-Pins falsch (z. B. GPIO12 bei ESP32)."),
    (r"flash read err|ets_main\.c", "boot_flash",
     "Boot-Fehler beim Flash-Lesen: Flash-Modus (QIO/DIO), Flash-Frequenz, Strapping-Pin GPIO12 (VDD_SDIO) prüfen."),
    (r"E \(\d+\) (\w+): (.+)", "esp_log_error", ""),
    (r"Soft WDT reset", "esp8266_soft_wdt", "ESP8266 Soft-WDT: loop()/Callback blockiert > ~3 s ohne yield()/delay()."),
    (r"wdt reset", "esp8266_hw_wdt", "ESP8266 Hardware-WDT: sehr lange Blockade oder Interrupts gesperrt."),
    (r"Panic (\S+):(\d+) (.+)", "esp8266_panic", "ESP8266-Core-Panic (Datei:Zeile) – häufig assert oder Heap-Problem."),
    (r"MEMORY ALLOCATION FAILED|heap_caps_malloc.*failed|Out of memory|OOM", "oom",
     "Speicher erschöpft: esp_get_free_heap_size()/heap_caps_get_largest_free_block() loggen, Fragmentierung prüfen, PSRAM nutzen."),
]



def _explain_reset(log: str) -> list[dict]:
    out = []
    for m in re.finditer(r"rst:(0x[0-9a-fA-F]+) \(([A-Z0-9_]+)\)(?:,boot:(0x[0-9a-fA-F]+) \(([^)]*)\))?", log):
        code, name, boot, bootname = m.groups()
        entry = {"raw": m.group(0), "code": code, "name": name,
                 "meaning": RESET_REASONS.get(name, "Unbekannter Reset-Name – in ESP-IDF esp_rom/…/rtc.h nachsehen.")}
        if bootname:
            entry["boot_mode"] = bootname
            if "DOWNLOAD" in bootname:
                entry["boot_hint"] = ("Chip startet im Download-Modus: Boot-Strapping-Pin war beim Reset LOW "
                                      "(ESP32/S2/S3: GPIO0, C2/C3/C6/H2: GPIO9 – andere Targets: chip_info).")
        out.append(entry)
    for m in re.finditer(r"rst cause:(\d+), boot mode:\((\d),(\d)\)", log):
        cause, mode, _ = m.groups()
        out.append({
            "raw": m.group(0), "platform": "esp8266",
            "meaning": ESP8266_RST_CAUSE.get(int(cause), "unbekannt"),
            "boot_mode": {"1": "UART-Download (GPIO0=LOW)", "3": "Flash-Boot (normal)"}.get(mode, f"Modus {mode}"),
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
    """e_machine aus dem ELF-Header: 94 = Xtensa, 243 = RISC-V."""
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
        return {"error": f"ELF nicht gefunden: {elf}"}
    # ESP8266 (lx106) hat ebenfalls e_machine Xtensa – explizite Angabe behalten
    arch = arch if arch == "lx106" else (_elf_arch(elf) or arch)
    tools = _find_addr2line(arch)
    if not tools:
        return {"error": "Kein addr2line gefunden (xtensa-esp-elf / riscv32-esp-elf / xtensa-lx106-elf). "
                         "ESP-IDF-Umgebung aktivieren oder Pfad der Toolchain angeben."}
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
                f["hint"] = "ESP_ERROR_CHECK bricht bei Fehler ab. Rückgabewert behandeln statt abzubrechen, Ursache über Fehlercode klären."
            elif cat == "esp_log_error":
                f["tag"], f["message"] = m.group(1), m.group(2)[:200]
            elif hint:
                f["hint"] = hint
            findings.append(f)

    m8266 = re.search(r"Exception \((\d+)\):", log)
    if m8266:
        n = int(m8266.group(1))
        name, hint = XTENSA_EXCCAUSE.get(n, (f"EXCCAUSE {n}", "siehe Xtensa ISA"))
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
                derived.append({key: regs[key], "meaning": "Adresse nahe 0 ⇒ NULL-Pointer (ggf. mit Feld-Offset in einem Struct)."})

    backtrace = []
    bt = re.search(r"Backtrace:\s*((?:0x[0-9a-fA-F]+:0x[0-9a-fA-F]+\s*)+)", log)
    if bt:
        backtrace = [pair.split(":")[0] for pair in bt.group(1).split()]
        if "CORRUPTED" in log[bt.end():bt.end() + 40]:
            derived.append({"backtrace": "|<-CORRUPTED – Stack beschädigt, Backtrace unvollständig."})
    if not backtrace:
        stack = re.search(r">>>stack>>>(.*?)<<<stack<<<", log, re.S)
        if stack:  # ESP8266: Code-Adressen aus dem Stack-Dump
            # IRAM 0x401xxxxx, Flash (irom0) 0x402xxxxx; Stack-Dump ohne 0x-Präfix, erste Spalte = Stackadresse
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
        result["decoded"] = ("Keine ELF angegeben. Mit 'elf' (z. B. build/<projekt>.elf, .pio/build/<env>/firmware.elf, "
                             "ESPHome: .esphome/build/<name>/.pioenvs/<name>/firmware.elf) werden die Adressen aufgelöst.")
    if not findings and not result["reset"]:
        result["note"] = "Keine bekannten Fehlermuster gefunden. Vollständigen Log ab Reset übergeben."
    return result


def _panic_hint(reason: str) -> str:
    for _, (name, hint) in {**XTENSA_EXCCAUSE, **{100 + k: v for k, v in RISCV_MCAUSE.items()}}.items():
        if name.lower() in reason.lower():
            return hint
    if "Unhandled debug exception" in reason:
        return "Meist Stack-Canary/Watchpoint – Stack-Überlauf der in den Folgezeilen genannten Task."
    if "Interrupt wdt" in reason:
        return "Interrupt-Watchdog – ISR/Critical Section zu lang."
    if "Cache" in reason:
        return "Flash-Cache war deaktiviert – ISR/Funktionen in IRAM legen."
    return "Backtrace gegen die passende ELF dekodieren."
