"""Persistent, validated Raspberry Pi 5 fan-curve profiles and hwmon access."""
from __future__ import annotations

import json
import math
import re
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import os

FAN_CURVE_CONFIG_PATH = Path("/etc/takt-engine/fan-curve.json")
FAN_OVERRIDE_PATH = Path("/run/takt-engine/fan-override.json")
FAN_BACKUP_DIR = Path("/var/lib/takt-engine/fan-backups")
FAN_CURVE_FORMAT = "takt-engine-fan-curve"
FAN_CURVE_SCHEMA_VERSION = 1

DEFAULT_FAN_CURVE = (
    {"temperature_c": 50.0, "speed_percent": 29},
    {"temperature_c": 52.5, "speed_percent": 34},
    {"temperature_c": 55.0, "speed_percent": 39},
    {"temperature_c": 57.5, "speed_percent": 44},
    {"temperature_c": 60.0, "speed_percent": 49},
    {"temperature_c": 62.5, "speed_percent": 56},
    {"temperature_c": 65.0, "speed_percent": 63},
    {"temperature_c": 67.5, "speed_percent": 70},
    {"temperature_c": 71.0, "speed_percent": 84},
    {"temperature_c": 75.0, "speed_percent": 100},
)
DEFAULT_HYSTERESIS_C = 5.0
MIN_FAN_SPEED_PERCENT = 29
MIN_FAN_OVERRIDE_SECONDS = 5
MAX_FAN_OVERRIDE_SECONDS = 300


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
    """Validate a four-to-ten-stage curve with conservative thermal guardrails."""
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)) or not 4 <= len(points) <= 10:
        raise ValueError("Eine Lüfterkurve muss zwischen 4 und 10 Temperaturstufen enthalten.")

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


def _atomic_json_write(path: Path, payload: dict, mode: int = 0o644) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_persistent_fan_curve(path: Path = FAN_CURVE_CONFIG_PATH) -> dict:
    """Load the persistent profile, falling back to a safe default if not saved yet."""
    path = Path(path)
    if not path.is_file():
        return validate_fan_curve(DEFAULT_FAN_CURVE, DEFAULT_HYSTERESIS_C)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Gespeicherte Lüfterkurve konnte nicht gelesen werden: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != FAN_CURVE_FORMAT:
        raise ValueError("Die gespeicherte Lüfterkurve besitzt ein unbekanntes Format.")
    if payload.get("schema_version") != FAN_CURVE_SCHEMA_VERSION:
        raise ValueError("Die gespeicherte Lüfterkurve hat eine nicht unterstützte Schema-Version.")
    return validate_fan_curve(payload.get("points"), payload.get("hysteresis_c", DEFAULT_HYSTERESIS_C))


def save_persistent_fan_curve(
    points: Sequence[Mapping[str, object]],
    hysteresis_c: object = DEFAULT_HYSTERESIS_C,
    path: Path = FAN_CURVE_CONFIG_PATH,
    backup_dir: Path = FAN_BACKUP_DIR,
) -> Path | None:
    """Back up the previous settings and write a validated persistent profile."""
    normalized = validate_fan_curve(points, hysteresis_c)
    path = Path(path)
    backup_path = None
    if path.is_file():
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = backup_dir / f"fan-curve.{stamp}.json"
        shutil.copy2(path, backup_path)

    payload = {
        "format": FAN_CURVE_FORMAT,
        "schema_version": FAN_CURVE_SCHEMA_VERSION,
        "points": normalized["points"],
        "hysteresis_c": normalized["hysteresis_c"],
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _atomic_json_write(path, payload, 0o644)
    return backup_path


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
        setting = setting_pattern.fullmatch(match.group(1).strip())
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


def create_fan_override(
    speed_percent: int,
    duration_seconds: int = 60,
    path: Path = FAN_OVERRIDE_PATH,
) -> None:
    if isinstance(speed_percent, bool) or not 29 <= int(speed_percent) <= 100:
        raise ValueError("Die manuelle Lüfterleistung muss zwischen 29 % und 100 % liegen.")
    if isinstance(duration_seconds, bool) or not MIN_FAN_OVERRIDE_SECONDS <= int(duration_seconds) <= MAX_FAN_OVERRIDE_SECONDS:
        raise ValueError("Die manuelle Steuerung darf nur 5 bis 300 Sekunden dauern.")
    payload = {
        "speed_percent": int(speed_percent),
        "expires_at": time.time() + int(duration_seconds),
    }
    _atomic_json_write(Path(path), payload, 0o600)


def clear_fan_override(path: Path = FAN_OVERRIDE_PATH) -> None:
    Path(path).unlink(missing_ok=True)


def read_fan_override(path: Path = FAN_OVERRIDE_PATH, now: float | None = None) -> int | None:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        speed = int(payload["speed_percent"])
        expires_at = float(payload["expires_at"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        path.unlink(missing_ok=True)
        return None
    current = time.time() if now is None else now
    if not math.isfinite(expires_at) or expires_at <= current:
        path.unlink(missing_ok=True)
        return None
    if not MIN_FAN_SPEED_PERCENT <= speed <= 100:
        path.unlink(missing_ok=True)
        return None
    return speed
