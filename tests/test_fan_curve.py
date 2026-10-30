import unittest
from takt_engine.core.fan_curve import DEFAULT_FAN_CURVE, validate_fan_curve

class FanCurveTests(unittest.TestCase):
    def test_default_curve_has_ten_stages(self):
        self.assertEqual(len(validate_fan_curve(DEFAULT_FAN_CURVE)["points"]), 10)

    def test_accepts_two_stages(self):
        self.assertEqual(len(validate_fan_curve(DEFAULT_FAN_CURVE[:2])["points"]), 2)

if __name__ == "__main__":
    unittest.main()
