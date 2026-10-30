import unittest
import tempfile
import importlib.util
from pathlib import Path

from takt_engine.core.fan_curve import (
    DEFAULT_FAN_CURVE,
    validate_fan_curve,
    save_persistent_fan_curve,
    load_persistent_fan_curve,
    curve_speed_for_temperature,
    create_fan_override,
    read_fan_override,
    clear_fan_override,
)


class FanCurveTests(unittest.TestCase):
    def test_default_profile_has_ten_stages(self):
        self.assertEqual(len(validate_fan_curve(DEFAULT_FAN_CURVE)["points"]), 10)

    def test_accepts_four_to_ten_stages(self):
        safe_four = [
            {"temperature_c": 50, "speed_percent": 29},
            {"temperature_c": 60, "speed_percent": 49},
            {"temperature_c": 67.5, "speed_percent": 69},
            {"temperature_c": 75, "speed_percent": 95},
        ]
        self.assertEqual(len(validate_fan_curve(safe_four)["points"]), 4)
        with self.assertRaises(ValueError):
            validate_fan_curve(DEFAULT_FAN_CURVE[:3])
        with self.assertRaises(ValueError):
            validate_fan_curve(DEFAULT_FAN_CURVE + (dict(DEFAULT_FAN_CURVE[-1]),))

    def test_rejects_late_start_and_falling_speed(self):
        points = [dict(p) for p in DEFAULT_FAN_CURVE[:4]]
        points[0]["temperature_c"] = 56
        with self.assertRaises(ValueError):
            validate_fan_curve(points)
        points = [
            {"temperature_c": 50, "speed_percent": 29},
            {"temperature_c": 60, "speed_percent": 49},
            {"temperature_c": 67.5, "speed_percent": 69},
            {"temperature_c": 75, "speed_percent": 95},
        ]
        points[2]["speed_percent"] = 45
        with self.assertRaises(ValueError):
            validate_fan_curve(points)

    def test_profile_is_persistent_and_backup_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "curve.json"
            backups = root / "backups"
            safe_four = [
                {"temperature_c": 50, "speed_percent": 29},
                {"temperature_c": 60, "speed_percent": 49},
                {"temperature_c": 67.5, "speed_percent": 69},
                {"temperature_c": 75, "speed_percent": 95},
            ]
            save_persistent_fan_curve(safe_four, 5, path, backups)
            backup = save_persistent_fan_curve(DEFAULT_FAN_CURVE, 4, path, backups)
            self.assertTrue(backup.is_file())
            self.assertEqual(len(load_persistent_fan_curve(path)["points"]), 10)


    def test_live_override_expires(self):
        from pathlib import Path
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "override.json"
            create_fan_override(70, 30, path)
            expires = json.loads(path.read_text())["expires_at"]
            self.assertEqual(read_fan_override(path, now=expires - 1), 70)
            self.assertIsNone(read_fan_override(path, now=expires + 1))
            self.assertFalse(path.exists())
            create_fan_override(80, 30, path)
            clear_fan_override(path)
            self.assertFalse(path.exists())

    def test_fan_daemon_uses_enabled_pwm_fan_mode(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "fan-control.py"
        spec = importlib.util.spec_from_file_location("takt_engine_fan_control_test", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            device = Path(tmp)
            (device / "pwm1_enable").write_text("0")
            (device / "pwm1").write_text("0")
            module._write_pwm(device, 50)
            self.assertEqual((device / "pwm1_enable").read_text(), "2")
            self.assertEqual((device / "pwm1").read_text(), "128")

    def test_live_fan_bar_is_adjustable(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        source = gui.read_text()
        fan_ui = source[source.index("def _build_fan_curve_page"):source.index("def _set_fan_curve_rows")]
        self.assertIn('self.fan_live_scale = Gtk.Scale.new_with_range', fan_ui)
        self.assertIn('self.fan_live_scale.connect("value-changed"', fan_ui)
        self.assertNotIn("Gtk.ProgressBar()", fan_ui)

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
