"""Persistent, validated Raspberry Pi 5 fan-curve profiles and hwmon access."""
from __future__ import annotations

import math
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

DEFAULT_FAN_CURVE = (
    {"temperature_c": 50.0, "speed_percent": 29},
    {"temperature_c": 60.0, "speed_percent": 49},
    {"temperature_c": 67.5, "speed_percent": 69},
    {"temperature_c": 75.0, "speed_percent": 100},
)
DEFAULT_HYSTERESIS_C = 5.0
MIN_FAN_SPEED_PERCENT = 29


def _finite_number(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} muss eine Zahl sein.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} muss eine Zahl sein.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} muss endlich sein.")
    return number


def validate_fan_curve(
    points: Sequence[Mapping[str, object]],
    hysteresis_c: object = DEFAULT_HYSTERESIS_C,
) -> dict:
    """Validate the four fan stages supported by Raspberry Pi 5 firmware."""
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)) or len(points) != 4:
        raise ValueError("Die Raspberry-Pi-5-Firmware unterstützt genau vier Lüfterstufen.")

    normalized = []
    previous_temp = None
    previous_speed = MIN_FAN_SPEED_PERCENT
    for index, point in enumerate(points):
        if not isinstance(point, Mapping):
            raise ValueError(f"Lüfterstufe {index + 1} ist ungültig.")
        temperature = _finite_number(point.get("temperature_c"), f"Temperatur Stufe {index + 1}")
        speed_raw = _finite_number(point.get("speed_percent"), f"Lüfterleistung Stufe {index + 1}")
        speed = int(round(speed_raw))

        if abs(temperature * 2 - round(temperature * 2)) > 1e-6:
            raise ValueError("Temperaturen müssen in 0,5-°C-Schritten eingestellt werden.")
        if temperature < 40.0 or temperature > 75.0:
            raise ValueError("Temperaturstufen müssen zwischen 40 °C und 75 °C liegen.")
        if index == 0 and temperature > 50.0:
            raise ValueError("Der Lüfter muss spätestens bei 50 °C anlaufen.")
        if previous_temp is not None and temperature - previous_temp < 0.5:
            raise ValueError("Zwischen zwei Temperaturstufen müssen mindestens 0,5 °C liegen.")
        if speed_raw != speed or speed < MIN_FAN_SPEED_PERCENT or speed > 100:
            raise ValueError(
                f"Lüfterstufe {index + 1} muss zwischen {MIN_FAN_SPEED_PERCENT} % und 100 % liegen."
            )
        if index == 0 and speed < MIN_FAN_SPEED_PERCENT:
            raise ValueError(f"Die erste Lüfterstufe muss mindestens {MIN_FAN_SPEED_PERCENT} % erreichen.")
        if speed < previous_speed:
            raise ValueError("Die Lüfterleistung darf mit steigender Temperatur nicht sinken.")

        normalized.append({
            "temperature_c": round(temperature, 1),
            "speed_percent": speed,
        })
        previous_temp = temperature
        previous_speed = speed

    if normalized[-1]["temperature_c"] > 75.0 or normalized[-1]["speed_percent"] < 95:
        raise ValueError("Die letzte Stufe muss spätestens bei 75 °C mindestens 95 % erreichen.")

    # Do not let custom profiles cool less than the official Pi 5 curve
    # at its four firmware reference temperatures.
    safety_floors = ((50.0, 29), (60.0, 49), (67.5, 69), (75.0, 95))
    for threshold, minimum_speed in safety_floors:
        active = [
            point["speed_percent"] for point in normalized
            if point["temperature_c"] <= threshold
        ]
        actual_speed = active[-1] if active else 0
        if actual_speed < minimum_speed:
            raise ValueError(
                f"Bei {threshold:g} °C muss die Kurve mindestens {minimum_speed} % erreichen."
            )

    hysteresis = _finite_number(hysteresis_c, "Hysterese")
    if hysteresis < 1.0 or hysteresis > 10.0:
        raise ValueError("Die Hysterese muss zwischen 1 °C und 10 °C liegen.")
    if abs(hysteresis * 2 - round(hysteresis * 2)) > 1e-6:
        raise ValueError("Die Hysterese muss in 0,5-°C-Schritten eingestellt werden.")

    return {"points": normalized, "hysteresis_c": round(hysteresis, 1)}


FAN_CONFIG_BEGIN_MARKER = "# BEGIN TAKT ENGINE PI5 FAN CURVE"
FAN_CONFIG_END_MARKER = "# END TAKT ENGINE PI5 FAN CURVE"


def render_firmware_fan_config(
    original: str,
    points: Sequence[Mapping[str, object]],
    hysteresis_c: object = DEFAULT_HYSTERESIS_C,
) -> str:
    """Write the native four-stage Raspberry Pi 5 fan curve to config.txt.

    The firmware/thermal driver owns the fan. Takt Engine must not race it by
    repeatedly writing pwm1 from a separate daemon.
    """
    normalized = validate_fan_curve(points, hysteresis_c)
    begin_count = original.count(FAN_CONFIG_BEGIN_MARKER)
    end_count = original.count(FAN_CONFIG_END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError(
            "Der Takt-Engine-Lüfterblock ist beschädigt oder doppelt vorhanden. "
            "Bitte config.txt vor dem Ändern manuell prüfen."
        )

    cleaned = original
    if begin_count == 1:
        pattern = re.compile(
            re.escape(FAN_CONFIG_BEGIN_MARKER)
            + r".*?"
            + re.escape(FAN_CONFIG_END_MARKER)
            + r"\s*",
            re.DOTALL,
        )
        cleaned = pattern.sub("", original, count=1)

    hysteresis_milli = int(round(normalized["hysteresis_c"] * 1000))
    lines = [
        "",
        FAN_CONFIG_BEGIN_MARKER,
        "[pi5]",
        "# Native Raspberry Pi 5 firmware fan curve (four hardware stages).",
    ]
    for index, point in enumerate(normalized["points"]):
        temperature_milli = int(round(point["temperature_c"] * 1000))
        pwm_value = max(0, min(255, int(round(point["speed_percent"] * 255 / 100))))
        lines.extend((
            f"dtparam=fan_temp{index}={temperature_milli}",
            f"dtparam=fan_temp{index}_hyst={hysteresis_milli}",
            f"dtparam=fan_temp{index}_speed={pwm_value}",
        ))
    lines.append(FAN_CONFIG_END_MARKER)
    result = cleaned.rstrip() + "\n" + "\n".join(lines) + "\n"
    if any(len(line) > 98 for line in result.splitlines()):
        raise ValueError("Eine config.txt-Zeile überschreitet das Firmware-Limit von 98 Zeichen.")
    return result


def parse_fan_curve_config(config_text: str) -> dict:
    """Read a legacy four-point firmware profile for migration."""
    defaults = (
        (50000, 5000, 75),
        (60000, 5000, 125),
        (67500, 5000, 175),
        (75000, 5000, 250),
    )
    values = [list(item) for item in defaults]
    section_applies = True
    setting_pattern = re.compile(r"^fan_temp([0-3])(?:_(hyst|speed))?\s*=\s*(\d+)\s*$", re.IGNORECASE)

    for raw_line in config_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and "]" in line:
            section = line[1:line.find("]")].strip().lower()
            section_applies = section in {"all", "pi5"}
            continue
        if not section_applies:
            continue
        match = re.match(r"^dtparam\s*=\s*(.+)$", line, re.IGNORECASE)
        if not match:
            continue
        # Raspberry Pi config.txt accepts multiple comma-separated parameters
        # on one dtparam line; parse both that form and one parameter per line.
        for raw_setting in match.group(1).split(","):
            setting = setting_pattern.fullmatch(raw_setting.strip())
            if not setting:
                continue
            index, suffix, raw_value = setting.groups()
            column = {"": 0, "hyst": 1, "speed": 2}[suffix.lower() if suffix else ""]
            values[int(index)][column] = int(raw_value)

    points = []
    for temperature, _hysteresis, pwm in values:
        points.append({
            "temperature_c": round(temperature / 1000.0, 1),
            "speed_percent": max(MIN_FAN_SPEED_PERCENT, int(round(max(0, min(255, pwm)) * 100 / 255))),
        })
    # The legacy firmware only stores four points. It may contain default
    # speeds that round to the same percentage, so preserve the raw curve.
    for index in range(1, len(points)):
        points[index]["speed_percent"] = max(points[index]["speed_percent"], points[index - 1]["speed_percent"])
    points[-1]["speed_percent"] = max(95, points[-1]["speed_percent"])
    hysteresis = round(values[0][1] / 1000.0, 1)
    if not 1.0 <= hysteresis <= 10.0:
        hysteresis = DEFAULT_HYSTERESIS_C
    return {"points": points, "hysteresis_c": hysteresis}


def curve_speed_for_temperature(
    temperature_c: float,
    points: Sequence[Mapping[str, object]],
    hysteresis_c: float = DEFAULT_HYSTERESIS_C,
    active_index: int | None = None,
) -> tuple[int, int]:
    """Return a PWM percentage and hysteresis-aware active stage index."""
    temperature = _finite_number(temperature_c, "Temperatur")
    normalized = validate_fan_curve(points, hysteresis_c)["points"]
    wanted = -1
    for index, point in enumerate(normalized):
        if temperature >= point["temperature_c"]:
            wanted = index
        else:
            break

    if active_index is None:
        active_index = wanted
    elif wanted > active_index:
        active_index = wanted
    else:
        while active_index >= 0 and temperature <= normalized[active_index]["temperature_c"] - float(hysteresis_c):
            active_index -= 1

    if temperature >= 80.0:
        return 100, len(normalized) - 1
    if active_index < 0:
        return 0, -1
    return int(normalized[active_index]["speed_percent"]), active_index


def find_hwmon_fan(root: Path = Path("/sys/class/hwmon")) -> Path | None:
    """Find the Linux pwm-fan hwmon device used by the Pi 5 active fan."""
    try:
        candidates = sorted(Path(root).glob("hwmon*"))
    except OSError:
        return None
    for candidate in candidates:
        try:
            name = (candidate / "name").read_text(encoding="ascii").strip().lower()
        except OSError:
            continue
        if name in {"pwmfan", "pwm-fan"} and (candidate / "pwm1").exists() and (candidate / "pwm1_enable").exists():
            return candidate
    return None


def read_hwmon_fan_state(root: Path = Path("/sys/class/hwmon")) -> dict | None:
    device = find_hwmon_fan(root)
    if device is None:
        return None
    try:
        pwm_raw = int((device / "pwm1").read_text(encoding="ascii").strip())
        enable = int((device / "pwm1_enable").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    try:
        rpm = int((device / "fan1_input").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        rpm = None
    pwm_raw = max(0, min(255, pwm_raw))
    return {
        "pwm_raw": pwm_raw,
        "speed_percent": int(round(pwm_raw * 100 / 255)),
        "enable": enable,
        "rpm": rpm,
        "device": str(device),
    }


def read_soc_temperature(thermal_root: Path = Path("/sys/class/thermal")) -> float | None:
    """Read the SoC temperature, preferring the CPU thermal zone."""
    zones = sorted(Path(thermal_root).glob("thermal_zone*"))
    preferred = []
    fallback = []
    for zone in zones:
        try:
            kind = (zone / "type").read_text(encoding="ascii", errors="ignore").strip().lower()
            raw = int((zone / "temp").read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            continue
        if raw < 10000 or raw > 150000:
            continue
        if "cpu" in kind or "soc" in kind or "bcm2712" in kind:
            preferred.append(raw / 1000.0)
        else:
            fallback.append(raw / 1000.0)
    if preferred:
        return max(preferred)
    if fallback:
        return max(fallback)

    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"temp=([0-9]+(?:\.[0-9]+)?)'C", result.stdout)
    return float(match.group(1)) if result.returncode == 0 and match else None
