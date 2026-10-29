"""Model-specific limits for the Takt Engine application.

These are conservative application guardrails, not guarantees that a particular
board, power supply or cooling setup will be stable at every permitted value.
"""
from dataclasses import dataclass
from typing import Dict, Mapping, Any


@dataclass(frozen=True)
class ModelLimits:
    model_id: str
    display_name: str
    arm_default: int
    arm_min: int
    arm_max: int
    v3d_default: int
    v3d_min: int
    v3d_max: int
    core_default: int | None
    core_min: int | None
    core_max: int | None
    voltage_delta_min: int
    voltage_delta_max: int
    defaults: Dict[str, int]


# The upper values below are UI/application entry ceilings, not guarantees that
# the firmware, board revision, cooling or power supply can run them reliably.
# Keep conservative tuning-assistant recommendations separate from these ceilings.
PI5_CONSERVATIVE_THRESHOLDS = {"arm_freq": 2800, "v3d_freq": 1000}
# Visual-only transition points for the warning-zone UI. They do not represent
# hardware certification or a guarantee that a fan can make these values safe.
PI5_CAUTION_CEILINGS = {"arm_freq": 3100, "v3d_freq": 1500}


def clock_warning_zone(model_id: str, key: str, value: Any) -> str:
    """Classify Pi 5 CPU/V3D slider values for visual warning colors.

    ``safe`` means only the conservative recommendation band, not a stability
    guarantee. Pi 4 and unrelated controls use the neutral ``default`` style.
    """
    if model_id != "pi5" or key not in PI5_CONSERVATIVE_THRESHOLDS:
        return "default"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "default"
    if number <= PI5_CONSERVATIVE_THRESHOLDS[key]:
        return "safe"
    if number <= PI5_CAUTION_CEILINGS[key]:
        return "caution"
    return "extreme"



PI5_CLOCK_COLOR_STOPS = {
    "arm_freq": (
        (2400, "#65c58a"),  # green at the slider's lower bound
        (2800, "#e2ca55"),  # yellow at the conservative threshold
        (3100, "#ed8b43"),  # orange at the elevated-risk threshold
        (3800, "#e3534c"),  # red at the experimental UI ceiling
    ),
    "v3d_freq": (
        (960, "#65c58a"),
        (1000, "#e2ca55"),
        (1500, "#ed8b43"),
        (2000, "#e3534c"),
    ),
}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    cleaned = value.lstrip("#")
    return tuple(int(cleaned[index:index + 2], 16) for index in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(round(channel)))):02x}" for channel in rgb)


def clock_gradient_color(model_id: str, key: str, value: Any) -> str:
    """Return a smooth green -> yellow -> orange -> red color for a Pi 5 clock.

    Colors are interpolated continuously across the slider range. They are a
    visual risk hint only, not a hardware stability or safety guarantee.
    Unsupported controls use the normal Claude-orange accent.
    """
    if model_id != "pi5" or key not in PI5_CLOCK_COLOR_STOPS:
        return "#f3a06c"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "#f3a06c"

    stops = PI5_CLOCK_COLOR_STOPS[key]
    if number <= stops[0][0]:
        return stops[0][1]
    if number >= stops[-1][0]:
        return stops[-1][1]

    for (left_value, left_hex), (right_value, right_hex) in zip(stops, stops[1:]):
        if number <= right_value:
            amount = (number - left_value) / (right_value - left_value)
            left_rgb = _hex_to_rgb(left_hex)
            right_rgb = _hex_to_rgb(right_hex)
            blended = tuple(
                left_channel + (right_channel - left_channel) * amount
                for left_channel, right_channel in zip(left_rgb, right_rgb)
            )
            return _rgb_to_hex(blended)
    return stops[-1][1]

def experimental_clock_warnings(model_id: str, values: Mapping[str, Any]) -> list[tuple[str, int, int]]:
    """Return Pi 5 clock settings above conservative app recommendations.

    These values remain selectable, but the GUI must show an extra warning before
    writing them to config.txt. The thresholds are recommendations, not firmware
    maximums and not a promise that values below them are stable.
    """
    if model_id != "pi5":
        return []
    warnings: list[tuple[str, int, int]] = []
    for key, threshold in PI5_CONSERVATIVE_THRESHOLDS.items():
        raw = values.get(key)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > threshold:
            warnings.append((key, value, threshold))
    return warnings


LIMITS: Dict[str, ModelLimits] = {
    "pi4": ModelLimits(
        model_id="pi4", display_name="Raspberry Pi 4", arm_default=1500,
        arm_min=1500, arm_max=2000, v3d_default=500, v3d_min=500,
        v3d_max=600, core_default=500, core_min=500, core_max=600,
        voltage_delta_min=-25000, voltage_delta_max=25000,
        defaults={"arm_freq": 1500, "v3d_freq": 500, "core_freq": 500,
                         "over_voltage_delta": 0},
    ),
    "pi5": ModelLimits(
        model_id="pi5", display_name="Raspberry Pi 5", arm_default=2400,
        # User-requested experimental UI ceilings. These are not vendor-certified
        # stable operating points; the GUI asks for a separate confirmation above
        # the conservative thresholds defined above.
        arm_min=2400, arm_max=3800, v3d_default=960, v3d_min=960,
        v3d_max=2000, core_default=None, core_min=None, core_max=None,
        voltage_delta_min=-25000, voltage_delta_max=50000,
        defaults={"arm_freq": 2400, "v3d_freq": 960, "over_voltage_delta": 0},
    ),
}

ALLOWED_KEYS = {"arm_freq", "v3d_freq", "core_freq", "over_voltage_delta"}


class ValidationError(ValueError):
    """Raised when a requested configuration is outside the app's guardrails."""


def get_limits(model_id: str) -> ModelLimits:
    try:
        return LIMITS[model_id]
    except KeyError as exc:
        raise ValidationError(f"Nicht unterstütztes Modell: {model_id!r}") from exc


def validate_values(model_id: str, values: Mapping[str, Any]) -> Dict[str, int]:
    """Validate all key/value pairs and return a normalized integer dictionary."""
    limits = get_limits(model_id)
    if not values:
        raise ValidationError("Es wurden keine Einstellungen angegeben.")

    normalized: Dict[str, int] = {}
    for key, raw_value in values.items():
        if key not in ALLOWED_KEYS:
            raise ValidationError(f"Nicht erlaubte Einstellung: {key}")
        if isinstance(raw_value, bool):
            raise ValidationError(f"Ungültiger Wert für {key}: {raw_value!r}")
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Ungültiger Zahlenwert für {key}: {raw_value!r}") from exc
        if str(value) != str(raw_value).strip() and not isinstance(raw_value, int):
            raise ValidationError(f"Es sind nur ganze Zahlen erlaubt: {key}")

        if key == "arm_freq":
            low, high = limits.arm_min, limits.arm_max
        elif key == "v3d_freq":
            low, high = limits.v3d_min, limits.v3d_max
        elif key == "core_freq":
            if limits.core_min is None or limits.core_max is None:
                raise ValidationError("core_freq wird für den Raspberry Pi 5 nicht angeboten.")
            low, high = limits.core_min, limits.core_max
        else:
            low, high = limits.voltage_delta_min, limits.voltage_delta_max

        if not low <= value <= high:
            raise ValidationError(f"{key}={value} liegt außerhalb des erlaubten App-Bereichs ({low}–{high}).")
        normalized[key] = value

    if "arm_freq" not in normalized or "v3d_freq" not in normalized or "over_voltage_delta" not in normalized:
        raise ValidationError("CPU-Takt, V3D-Takt und Spannungs-Offset müssen angegeben sein.")
    if model_id == "pi4" and "core_freq" not in normalized:
        raise ValidationError("Für den Pi 4 muss core_freq angegeben sein.")
    return normalized
