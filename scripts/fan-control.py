#!/usr/bin/env python3
"""Persistent Raspberry Pi 5 fan-curve daemon with a temporary safe override."""
from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/takt-engine/src")

from takt_engine.core.fan_curve import (  # noqa: E402
    DEFAULT_FAN_CURVE,
    DEFAULT_HYSTERESIS_C,
    FAN_CURVE_CONFIG_PATH,
    find_hwmon_fan,
    load_persistent_fan_curve,
    read_fan_override,
    read_soc_temperature,
    validate_fan_curve,
    curve_speed_for_temperature,
)

POLL_INTERVAL = 1.0
_STOP = False


def _stop_requested(_signum, _frame):
    global _STOP
    _STOP = True


def _write_pwm(device: Path, speed_percent: int) -> None:
    """Set pwm-fan hardware output; never use the driver's hard-off mode."""
    enable_path = device / "pwm1_enable"
    pwm_path = device / "pwm1"
    try:
        mode = int(enable_path.read_text(encoding="ascii").strip())
        if mode == 0:
            # Mode 1 permits PWM output while retaining the regulator for 0%.
            enable_path.write_text("1", encoding="ascii")
        value = max(0, min(255, int(round(speed_percent * 255 / 100))))
        pwm_path.write_text(str(value), encoding="ascii")
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Die Lüfter-PWM konnte nicht gesetzt werden: {exc}") from exc


def _load_curve():
    try:
        return load_persistent_fan_curve()
    except (OSError, ValueError, TypeError) as exc:
        logging.error("Gespeicherte Lüfterkurve ungültig; Standardkurve wird verwendet: %s", exc)
        return validate_fan_curve(DEFAULT_FAN_CURVE, DEFAULT_HYSTERESIS_C)


def run() -> int:
    global _STOP

    signal.signal(signal.SIGTERM, _stop_requested)
    signal.signal(signal.SIGINT, _stop_requested)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s takt-engine-fan: %(message)s",
    )

    device = None
    active_index = None
    last_signature = None
    last_output = None

    logging.info("Lüftersteuerung gestartet; Profil wird dauerhaft aus %s gelesen.", FAN_CURVE_CONFIG_PATH)
    try:
        while not _STOP:
            if device is None:
                device = find_hwmon_fan()
                if device is None:
                    logging.warning("Kein kompatibles pwm-fan-Gerät gefunden; Suche wird fortgesetzt.")
                    time.sleep(5)
                    continue
                logging.info("Lüftergerät erkannt: %s", device)
                active_index = None

            curve = _load_curve()
            signature = (
                tuple((point["temperature_c"], point["speed_percent"]) for point in curve["points"]),
                curve["hysteresis_c"],
            )
            if signature != last_signature:
                active_index = None
                last_signature = signature
                logging.info("Lüfterkurve mit %d Stufen geladen.", len(curve["points"]))

            temperature = read_soc_temperature()
            if temperature is None:
                # Sensor read failures must never result in a stopped fan.
                target_speed = 100
                active_index = len(curve["points"]) - 1
                reason = "Temperatursensor nicht lesbar – Sicherheitsdrehzahl 100 %"
            else:
                target_speed, active_index = curve_speed_for_temperature(
                    temperature,
                    curve["points"],
                    curve["hysteresis_c"],
                    active_index,
                )
                override = read_fan_override()
                if override is not None:
                    # A manual override may increase cooling but never undercut
                    # the currently required automatic curve speed.
                    target_speed = max(target_speed, override)
                if temperature >= 80.0:
                    target_speed = 100
                    reason = "Temperatur-Sicherheitsstufe"
                else:
                    reason = f"SoC {temperature:.1f} °C"

            try:
                _write_pwm(device, target_speed)
            except RuntimeError:
                # Re-scan hwmon in case the device was removed/re-probed.
                logging.exception("Lüftersteuerung fehlgeschlagen; setze auf Sicherheitszustand.")
                try:
                    _write_pwm(device, 100)
                except RuntimeError:
                    pass
                device = None
            else:
                if last_output != target_speed:
                    logging.info("Lüfterleistung %d %% (%s).", target_speed, reason)
                    last_output = target_speed

            time.sleep(POLL_INTERVAL)
    finally:
        if device is not None:
            try:
                _write_pwm(device, 100)
                logging.warning("Dienst wird beendet; Lüfter auf 100 %% gesetzt.")
            except RuntimeError:
                logging.exception("Sicherheitsdrehzahl beim Beenden konnte nicht gesetzt werden.")

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
