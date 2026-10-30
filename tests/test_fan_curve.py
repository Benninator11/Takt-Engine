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
    render_firmware_fan_config,
    FAN_CONFIG_BEGIN_MARKER,
    FAN_CONFIG_END_MARKER,
)


class FanCurveTests(unittest.TestCase):
    def test_default_profile_has_four_firmware_stages(self):
        self.assertEqual(len(validate_fan_curve(DEFAULT_FAN_CURVE)["points"]), 4)

    def test_only_four_native_firmware_stages_are_accepted(self):
        safe_four = [
            {"temperature_c": 50, "speed_percent": 29},
            {"temperature_c": 60, "speed_percent": 49},
            {"temperature_c": 67.5, "speed_percent": 69},
            {"temperature_c": 75, "speed_percent": 95},
        ]
        self.assertEqual(len(validate_fan_curve(safe_four)["points"]), 4)
        with self.assertRaisesRegex(ValueError, "genau vier"):
            validate_fan_curve(DEFAULT_FAN_CURVE[:3])
        with self.assertRaisesRegex(ValueError, "genau vier"):
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
            self.assertEqual(len(load_persistent_fan_curve(path)["points"]), 4)


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

    def test_firmware_curve_writes_four_native_stages_and_preserves_user_config(self):
        original = "# user config\ndtparam=audio=on\n"
        rendered = render_firmware_fan_config(original, DEFAULT_FAN_CURVE, 5.0)
        self.assertIn("# user config", rendered)
        self.assertIn("dtparam=audio=on", rendered)
        self.assertIn("[all]", rendered)
        self.assertIn("dtparam=fan_temp0=50000", rendered)
        self.assertIn("dtparam=fan_temp0_hyst=5000", rendered)
        self.assertIn("dtparam=fan_temp0_speed=74", rendered)
        self.assertIn("dtparam=fan_temp1=60000", rendered)
        self.assertIn("dtparam=fan_temp1_speed=125", rendered)
        self.assertIn("dtparam=fan_temp2=67500", rendered)
        self.assertIn("dtparam=fan_temp3=75000", rendered)
        self.assertIn("dtparam=fan_temp3_speed=255", rendered)
        self.assertIn(FAN_CONFIG_BEGIN_MARKER, rendered)
        self.assertIn(FAN_CONFIG_END_MARKER, rendered)

    def test_firmware_curve_replaces_only_its_managed_block(self):
        original = (
            "# keep me\n" + FAN_CONFIG_BEGIN_MARKER + "\n[pi5]\n"
            "dtparam=fan_temp0=40000\n" + FAN_CONFIG_END_MARKER + "\n"
            "dtparam=audio=on\\n"
        )
        rendered = render_firmware_fan_config(original, DEFAULT_FAN_CURVE, 5.0)
        self.assertEqual(rendered.count(FAN_CONFIG_BEGIN_MARKER), 1)
        self.assertEqual(rendered.count(FAN_CONFIG_END_MARKER), 1)
        self.assertNotIn("dtparam=fan_temp0=40000", rendered)
        self.assertIn("# keep me", rendered)
        self.assertIn("dtparam=audio=on", rendered)

    def test_firmware_curve_refuses_a_damaged_managed_block(self):
        with self.assertRaisesRegex(ValueError, "beschädigt"):
            render_firmware_fan_config(FAN_CONFIG_BEGIN_MARKER + "\n", DEFAULT_FAN_CURVE, 5.0)

    def test_live_fan_bar_adjusts_selected_firmware_stage(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        source = gui.read_text()
        fan_ui = source[source.index("def _build_fan_curve_page"):source.index("def _set_fan_curve_rows")]
        self.assertIn('self.fan_live_scale = Gtk.Scale.new_with_range', fan_ui)
        self.assertIn('self.fan_live_scale.connect("value-changed", self._on_fan_stage_speed_changed)', fan_ui)
        self.assertIn('self.fan_stage_combo.connect("changed", self._on_fan_stage_selected)', fan_ui)
        self.assertNotIn("Live-Leistung übernehmen", fan_ui)
        self.assertNotIn("Gtk.ProgressBar()", fan_ui)

    def test_installer_disables_old_competing_fan_daemon(self):
        installer = Path(__file__).resolve().parents[1] / "scripts" / "install-deps.sh"
        content = installer.read_text()
        self.assertIn('systemctl disable --now takt-engine-fan.service', content)
        self.assertNotIn('install -m 0644 "$PROJECT_DIR/scripts/takt-engine-fan.service"', content)

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
