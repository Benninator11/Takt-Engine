"""Validated Raspberry Pi 5 firmware fan-curve configuration."""
from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence


FAN_CURVE_BEGIN_MARKER = "# BEGIN TAKT ENGINE FAN CURVE - managed by Takt Engine"
FAN_CURVE_END_MARKER = "# END TAKT ENGINE FAN CURVE"

# Raspberry Pi's documented Raspberry Pi 5 fan defaults. Speeds are shown as
# rounded percentages in the GUI; firmware stores the PWM value from 0 to 255.
DEFAULT_FAN_CURVE = (
    {"temperature_c": 50.0, "speed_percent": 29},
    {"temperature_c": 60.0, "speed_percent": 49},
    {"temperature_c": 67.5, "speed_percent": 69},
    {"temperature_c": 75.0, "speed_percent": 98},
)
DEFAULT_HYSTERESIS_C = 5.0
MIN_FAN_SPEED_PERCENT = (29, 49, 69, 95)


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
    """Validate four conservative, rising Raspberry Pi 5 fan-curve steps."""
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)) or len(points) != 4:
        raise ValueError("Eine Lüfterkurve muss genau vier Temperaturstufen enthalten.")

    normalized = []
    previous_temp = None
    previous_speed = 0
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
        if index == 0 and temperature > 55.0:
            raise ValueError("Der Lüfter muss spätestens bei 55 °C anlaufen.")
        if previous_temp is not None and temperature - previous_temp < 2.5:
            raise ValueError("Zwischen zwei Temperaturstufen müssen mindestens 2,5 °C liegen.")
        if speed_raw != speed or speed < MIN_FAN_SPEED_PERCENT[index] or speed > 100:
            raise ValueError(
                f"Lüfterstufe {index + 1} muss mindestens {MIN_FAN_SPEED_PERCENT[index]} % "
                "und höchstens 100 % erreichen."
            )
        if speed <= previous_speed:
            raise ValueError("Die Lüfterleistung darf mit steigender Temperatur nicht sinken.")

        normalized.append({
            "temperature_c": round(temperature, 1),
            "speed_percent": speed,
        })
        previous_temp = temperature
        previous_speed = speed

    if normalized[-1]["speed_percent"] < 95:
        raise ValueError("Die letzte Stufe muss mindestens 95 % Lüfterleistung erreichen.")

    hysteresis = _finite_number(hysteresis_c, "Hysterese")
    if hysteresis < 1.0 or hysteresis > 10.0:
        raise ValueError("Die Hysterese muss zwischen 1 °C und 10 °C liegen.")
    if abs(hysteresis * 2 - round(hysteresis * 2)) > 1e-6:
        raise ValueError("Die Hysterese muss in 0,5-°C-Schritten eingestellt werden.")

    return {
        "points": normalized,
        "hysteresis_c": round(hysteresis, 1),
    }


def _applicable_fan_settings(config_text: str) -> dict[str, int]:
    defaults: dict[str, int] = {}
    for index, point in enumerate(DEFAULT_FAN_CURVE):
        defaults[f"fan_temp{index}"] = int(round(point["temperature_c"] * 1000))
        defaults[f"fan_temp{index}_hyst"] = int(DEFAULT_HYSTERESIS_C * 1000)
        defaults[f"fan_temp{index}_speed"] = (75, 125, 175, 250)[index]

    values = dict(defaults)
    section_applies = True
    setting_pattern = re.compile(
        r"^fan_temp([0-3])(?:_(hyst|speed))?\s*=\s*(\d+)\s*$",
        re.IGNORECASE,
    )

    for raw_line in config_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and "]" in line:
            section_name = line[1:line.find("]")].strip().lower()
            section_applies = section_name in {"all", "pi5"}
            continue
        if not section_applies:
            continue
        match = re.match(r"^dtparam\s*=\s*(.+)$", line, re.IGNORECASE)
        if not match:
            continue
        setting = setting_pattern.fullmatch(match.group(1).strip())
        if setting:
            index, suffix, raw_value = setting.groups()
            key = f"fan_temp{index}" + (f"_{suffix.lower()}" if suffix else "")
            values[key] = int(raw_value)

    return values


def parse_fan_curve_config(config_text: str) -> dict:
    """Read the last applicable firmware fan settings, or documented defaults."""
    values = _applicable_fan_settings(config_text)
    points = []
    for index in range(4):
        temperature = values[f"fan_temp{index}"] / 1000.0
        pwm = max(0, min(255, values[f"fan_temp{index}_speed"]))
        percentage = int(round(pwm * 100 / 255))
        points.append({
            "temperature_c": round(temperature, 1),
            "speed_percent": percentage,
        })
    hysteresis_values = [values[f"fan_temp{index}_hyst"] for index in range(4)]
    hysteresis = round((hysteresis_values[-1] if hysteresis_values else 5000) / 1000.0, 1)
    return {"points": points, "hysteresis_c": hysteresis}


def render_fan_curve_config(
    original: str,
    points: Sequence[Mapping[str, object]],
    hysteresis_c: object = DEFAULT_HYSTERESIS_C,
) -> str:
    """Replace only Takt Engine's fan-curve block; preserve all other config lines."""
    curve = validate_fan_curve(points, hysteresis_c)

    begin_count = original.count(FAN_CURVE_BEGIN_MARKER)
    end_count = original.count(FAN_CURVE_END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError(
            "Der Takt-Engine-Lüfterblock ist beschädigt oder doppelt vorhanden. "
            "Bitte config.txt zuerst manuell prüfen."
        )

    cleaned = original
    if begin_count == 1:
        pattern = re.compile(
            re.escape(FAN_CURVE_BEGIN_MARKER)
            + r".*?"
            + re.escape(FAN_CURVE_END_MARKER)
            + r"\s*",
            re.DOTALL,
        )
        cleaned = pattern.sub("", original, count=1)

    lines = ["", FAN_CURVE_BEGIN_MARKER, "[pi5]"]
    hysteresis_millic = int(round(curve["hysteresis_c"] * 1000))
    for index, point in enumerate(curve["points"]):
        temperature_millic = int(round(point["temperature_c"] * 1000))
        pwm = int(round(point["speed_percent"] * 255 / 100))
        lines.extend((
            f"dtparam=fan_temp{index}={temperature_millic}",
            f"dtparam=fan_temp{index}_hyst={hysteresis_millic}",
            f"dtparam=fan_temp{index}_speed={pwm}",
        ))
    lines.append(FAN_CURVE_END_MARKER)

    result = cleaned.rstrip() + "\n" + "\n".join(lines) + "\n"
    if any(len(line) > 98 for line in result.splitlines()):
        raise ValueError("Eine config.txt-Zeile überschreitet das Firmware-Limit von 98 Zeichen.")
    return result
