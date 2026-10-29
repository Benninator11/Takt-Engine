"""Read-only runtime telemetry through vcgencmd, procfs and Linux sysfs."""
from dataclasses import dataclass
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RuntimeStatus:
    temperature_c: Optional[float]
    arm_clock_mhz: Optional[int]
    throttled_hex: Optional[str]
    active_throttling: bool
    undervoltage: bool
    historical_flags: bool
    note: str = ""
    v3d_clock_mhz: Optional[int] = None
    cpu_usage_percent: Optional[float] = None
    fan_rpm: Optional[int] = None
    cooling_states: Optional[str] = None


def parse_temperature(output: str) -> Optional[float]:
    match = re.search(r"temp=([0-9]+(?:\.[0-9]+)?)'C", output)
    return float(match.group(1)) if match else None


def parse_clock_mhz(output: str) -> Optional[int]:
    match = re.search(r"(?:frequency(?:\(\d+\))?|clock)\s*=\s*(\d+)", output, re.IGNORECASE)
    if not match:
        return None
    return round(int(match.group(1)) / 1_000_000)


def parse_throttled(output: str) -> tuple[Optional[str], bool, bool, bool]:
    match = re.search(r"0x([0-9a-fA-F]+)", output)
    if not match:
        return None, False, False, False
    value = int(match.group(1), 16)
    active_mask = value & 0xF
    undervoltage = bool(active_mask & 0x1)
    active_throttling = bool(active_mask & 0xE)
    historical = bool(value & 0xF0000)
    return f"0x{value:x}", active_throttling, undervoltage, historical


def parse_cpu_counters(proc_stat_text: str) -> Optional[tuple[int, int]]:
    """Return aggregate CPU (total, idle+io_wait) counters from /proc/stat."""
    try:
        first = next(line for line in proc_stat_text.splitlines() if line.startswith("cpu "))
        parts = [int(part) for part in first.split()[1:]]
    except (StopIteration, ValueError, IndexError):
        return None
    if len(parts) < 4:
        return None
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    # guest/guest_nice are already counted in user/nice on Linux.
    total = sum(parts[:8])
    return total, idle


def calculate_cpu_usage(previous: tuple[int, int] | None, current: tuple[int, int] | None) -> Optional[float]:
    if previous is None or current is None:
        return None
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]
    if total_delta <= 0 or idle_delta < 0:
        return None
    return round(max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta)), 1)


def safety_state(status: RuntimeStatus) -> tuple[str, str]:
    """Classify live health; this is diagnostic guidance, not a certification."""
    if status.temperature_c is not None and status.temperature_c >= 80.0:
        return "critical", "SICHERHEITSWARNUNG: 80 °C oder mehr erkannt – Last reduzieren und Kühlung prüfen."
    if status.undervoltage or status.active_throttling:
        parts = []
        if status.undervoltage:
            parts.append("Unterspannung")
        if status.active_throttling:
            parts.append("Drosselung")
        return "critical", "AKTIVE WARNUNG: " + " und ".join(parts) + " erkannt. Netzteil, Kühlung und Last prüfen."
    if status.temperature_c is not None and status.temperature_c >= 75.0:
        return "caution", f"Temperatur erhöht ({status.temperature_c:.1f} °C). Last und Kühlung im Blick behalten."
    if status.historical_flags:
        return "caution", "Frühere Unterspannung/Drosselung wurde seit dem letzten Neustart registriert."
    if status.temperature_c is None and status.arm_clock_mhz is None and status.throttled_hex is None:
        return "unknown", "Live-Telemetrie nicht verfügbar; Systemzustand kann nicht zuverlässig geprüft werden."
    return "ok", "Systemstatus unauffällig – keine aktuellen Warnflags erkannt."


def _run_vcgencmd(*args: str, timeout: float = 2.0) -> str:
    if not shutil.which("vcgencmd"):
        return ""
    try:
        result = subprocess.run(["vcgencmd", *args], capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


_cpu_lock = threading.Lock()
_previous_cpu_counters: tuple[int, int] | None = None


def _read_cpu_usage() -> Optional[float]:
    global _previous_cpu_counters
    try:
        content = Path("/proc/stat").read_text(encoding="ascii", errors="ignore")
    except OSError:
        return None
    current = parse_cpu_counters(content)
    with _cpu_lock:
        usage = calculate_cpu_usage(_previous_cpu_counters, current)
        _previous_cpu_counters = current
    return usage


def read_firmware_config() -> dict[str, int]:
    """Read integer settings exposed by vcgencmd; unavailable keys remain absent."""
    output = _run_vcgencmd("get_config", "int")
    values: dict[str, int] = {}
    for line in output.splitlines():
        match = re.match(r"\s*([A-Za-z0-9_]+)\s*=\s*(-?\d+)\s*$", line)
        if match:
            try:
                values[match.group(1)] = int(match.group(2))
            except ValueError:
                continue
    return values


def read_cooling_telemetry() -> tuple[Optional[int], Optional[str]]:
    """Read fan RPM/cooling states where Linux drivers expose them."""
    fan_values: list[int] = []
    for path in Path("/sys/class/hwmon").glob("hwmon*/fan*_input"):
        try:
            value = int(path.read_text(encoding="ascii").strip())
            if value >= 0:
                fan_values.append(value)
        except (OSError, ValueError):
            continue
    # Raspberry Pi 5 fan drivers can expose the tachometer through hwmon, while
    # other cooling modules may expose only a cooling-device state.
    cooling: list[str] = []
    for path in Path("/sys/class/thermal").glob("cooling_device*/cur_state"):
        try:
            state = path.read_text(encoding="ascii").strip()
            type_path = path.parent / "type"
            kind = type_path.read_text(encoding="ascii").strip() if type_path.exists() else path.parent.name
            if state.isdigit():
                cooling.append(f"{kind}: {state}")
        except OSError:
            continue
    return (max(fan_values) if fan_values else None, "; ".join(cooling) if cooling else None)


def read_status() -> RuntimeStatus:
    temp_output = _run_vcgencmd("measure_temp")
    clock_output = _run_vcgencmd("measure_clock", "arm")
    v3d_output = _run_vcgencmd("measure_clock", "v3d")
    throttle_output = _run_vcgencmd("get_throttled")
    temperature = parse_temperature(temp_output)
    clock = parse_clock_mhz(clock_output)
    v3d_clock = parse_clock_mhz(v3d_output)
    throttle_hex, throttling, undervoltage, historical = parse_throttled(throttle_output)

    if clock is None:
        try:
            raw = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq").read_text().strip()
            clock = round(int(raw) / 1000)
        except (OSError, ValueError):
            pass
    cpu_usage = _read_cpu_usage()
    fan_rpm, cooling_states = read_cooling_telemetry()
    note = ""
    if temperature is None and clock is None and throttle_hex is None:
        note = "Keine Telemetrie verfügbar (vcgencmd fehlt oder wird nicht unterstützt)."
    return RuntimeStatus(temperature, clock, throttle_hex, throttling, undervoltage, historical, note,
                         v3d_clock_mhz=v3d_clock, cpu_usage_percent=cpu_usage,
                         fan_rpm=fan_rpm, cooling_states=cooling_states)
