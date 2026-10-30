import unittest
import tempfile
from pathlib import Path

from takt_engine.core.fan_curve import (
    DEFAULT_FAN_CURVE,
    validate_fan_curve,
    save_persistent_fan_curve,
    load_persistent_fan_curve,
    curve_speed_for_temperature,
)


class FanCurveTests(unittest.TestCase):
    def test_default_profile_has_ten_stages(self):
        self.assertEqual(len(validate_fan_curve(DEFAULT_FAN_CURVE)["points"]), 10)

    def test_accepts_four_to_ten_stages(self):
        self.assertEqual(len(validate_fan_curve(DEFAULT_FAN_CURVE[:4])["points"]), 4)
        with self.assertRaises(ValueError):
            validate_fan_curve(DEFAULT_FAN_CURVE[:3])
        with self.assertRaises(ValueError):
            validate_fan_curve(DEFAULT_FAN_CURVE + (dict(DEFAULT_FAN_CURVE[-1]),))

    def test_rejects_late_start_and_falling_speed(self):
        points = [dict(p) for p in DEFAULT_FAN_CURVE[:4]]
        points[0]["temperature_c"] = 56
        with self.assertRaises(ValueError):
            validate_fan_curve(points)
        points = [dict(p) for p in DEFAULT_FAN_CURVE[:3]]
        points[1]["speed_percent"] = 70
        points[2]["speed_percent"] = 65
        with self.assertRaises(ValueError):
            validate_fan_curve(points)

    def test_profile_is_persistent_and_backup_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "curve.json"
            backups = root / "backups"
            save_persistent_fan_curve(DEFAULT_FAN_CURVE[:4], 5, path, backups)
            backup = save_persistent_fan_curve(DEFAULT_FAN_CURVE, 4, path, backups)
            self.assertTrue(backup.is_file())
            self.assertEqual(len(load_persistent_fan_curve(path)["points"]), 10)

    def test_hysteresis_and_critical_temperature(self):
        points = [
            {"temperature_c": 50, "speed_percent": 30},
            {"temperature_c": 60, "speed_percent": 60},
            {"temperature_c": 67.5, "speed_percent": 75},
            {"temperature_c": 75, "speed_percent": 100},
        ]
        speed, index = curve_speed_for_temperature(61, points, 5)
        self.assertEqual((speed, index), (60, 1))
        speed, index = curve_speed_for_temperature(58, points, 5, index)
        self.assertEqual((speed, index), (60, 1))
        self.assertEqual(curve_speed_for_temperature(81, points, 5)[0], 100)


if __name__ == "__main__":
    unittest.main()
