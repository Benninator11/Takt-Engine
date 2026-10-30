import unittest

from takt_engine.core.fan_curve import (
    DEFAULT_FAN_CURVE,
    DEFAULT_HYSTERESIS_C,
    FAN_CURVE_BEGIN_MARKER,
    FAN_CURVE_END_MARKER,
    parse_fan_curve_config,
    render_fan_curve_config,
    validate_fan_curve,
)


class FanCurveValidationTests(unittest.TestCase):
    def test_documented_defaults_are_valid(self):
        result = validate_fan_curve(DEFAULT_FAN_CURVE, DEFAULT_HYSTERESIS_C)
        self.assertEqual(result["points"], list(DEFAULT_FAN_CURVE))
        self.assertEqual(result["hysteresis_c"], 5.0)

    def test_requires_exactly_four_points(self):
        with self.assertRaisesRegex(ValueError, "genau vier"):
            validate_fan_curve(DEFAULT_FAN_CURVE[:3], 5)

    def test_rejects_first_temperature_above_fifty_five_degrees(self):
        points = [dict(point) for point in DEFAULT_FAN_CURVE]
        points[0]["temperature_c"] = 56
        with self.assertRaisesRegex(ValueError, "spätestens bei 55"):
            validate_fan_curve(points, 5)

    def test_rejects_temperature_steps_that_are_too_close(self):
        points = [dict(point) for point in DEFAULT_FAN_CURVE]
        points[1]["temperature_c"] = 52
        with self.assertRaisesRegex(ValueError, "mindestens 2,5"):
            validate_fan_curve(points, 5)

    def test_rejects_decreasing_fan_speed(self):
        points = [dict(point) for point in DEFAULT_FAN_CURVE]
        points[1]["speed_percent"] = 80
        points[2]["speed_percent"] = 69
        with self.assertRaisesRegex(ValueError, "nicht sinken"):
            validate_fan_curve(points, 5)

    def test_requires_high_final_fan_speed(self):
        points = [dict(point) for point in DEFAULT_FAN_CURVE]
        points[3]["speed_percent"] = 90
        with self.assertRaisesRegex(ValueError, "mindestens 95"):
            validate_fan_curve(points, 5)

    def test_rejects_invalid_hysteresis(self):
        with self.assertRaisesRegex(ValueError, "zwischen 1"):
            validate_fan_curve(DEFAULT_FAN_CURVE, 0)


class FanCurveConfigTests(unittest.TestCase):
    def test_empty_config_returns_documented_defaults(self):
        curve = parse_fan_curve_config("")
        self.assertEqual(curve["points"], list(DEFAULT_FAN_CURVE))
        self.assertEqual(curve["hysteresis_c"], DEFAULT_HYSTERESIS_C)

    def test_parser_uses_all_and_pi5_sections_but_ignores_pi4(self):
        config = """[all]
dtparam=fan_temp0=52000
[pi4]
dtparam=fan_temp1=58000
[pi5]
dtparam=fan_temp0=51000
dtparam=fan_temp0_hyst=4000
dtparam=fan_temp0_speed=90
"""
        curve = parse_fan_curve_config(config)
        self.assertEqual(curve["points"][0]["temperature_c"], 51.0)
        self.assertEqual(curve["points"][0]["speed_percent"], 35)
        self.assertEqual(curve["points"][1]["temperature_c"], 60.0)
        self.assertEqual(curve["hysteresis_c"], 4.0)

    def test_renderer_preserves_other_settings_and_writes_only_pi5_curve(self):
        original = "# keep this line\n[all]\nhdmi_enable_4kp60=0\n"
        rendered = render_fan_curve_config(original, DEFAULT_FAN_CURVE, 5)
        self.assertIn("# keep this line", rendered)
        self.assertIn("hdmi_enable_4kp60=0", rendered)
        self.assertIn("[pi5]", rendered)
        self.assertIn("dtparam=fan_temp0=50000", rendered)
        self.assertIn("dtparam=fan_temp3=75000", rendered)
        self.assertEqual(rendered.count(FAN_CURVE_BEGIN_MARKER), 1)
        self.assertEqual(rendered.count(FAN_CURVE_END_MARKER), 1)

    def test_renderer_is_idempotent_and_replaces_its_own_block(self):
        first = render_fan_curve_config("[all]\nstart_x=1\n", DEFAULT_FAN_CURVE, 5)
        changed = [dict(point) for point in DEFAULT_FAN_CURVE]
        changed[0]["temperature_c"] = 52
        second = render_fan_curve_config(first, changed, 4)
        self.assertEqual(second.count(FAN_CURVE_BEGIN_MARKER), 1)
        self.assertEqual(second.count(FAN_CURVE_END_MARKER), 1)
        self.assertIn("start_x=1", second)
        self.assertIn("dtparam=fan_temp0=52000", second)
        self.assertIn("dtparam=fan_temp0_hyst=4000", second)
        self.assertNotIn("dtparam=fan_temp0=50000", second)

    def test_renderer_refuses_damaged_markers(self):
        damaged = FAN_CURVE_BEGIN_MARKER + "\n[pi5]\n"
        with self.assertRaisesRegex(ValueError, "beschädigt"):
            render_fan_curve_config(damaged, DEFAULT_FAN_CURVE, 5)

    def test_gui_exposes_fan_curve_page_and_guarded_apply(self):
        gui = __import__("pathlib").Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        source = gui.read_text()
        for token in (
            'self._build_fan_curve_page()',
            'def _build_fan_curve_page(self):',
            'def apply_fan_curve_dialog(self, _button=None):',
            'apply_fan_curve(',
            'Bitte den Raspberry Pi neu starten.',
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
