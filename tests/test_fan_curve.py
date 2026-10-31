import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    _gtk_init = Gtk.init_check(None)
    GTK_AVAILABLE = _gtk_init[0] if isinstance(_gtk_init, tuple) else bool(_gtk_init)
except (ImportError, ValueError, RuntimeError):
    Gtk = None
    GTK_AVAILABLE = False

from takt_engine.core.fan_curve import (
    DEFAULT_FAN_CURVE,
    validate_fan_curve,
    curve_speed_for_temperature,
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
        points = [dict(p) for p in DEFAULT_FAN_CURVE]
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

    def test_firmware_curve_writes_four_native_stages_and_preserves_user_config(self):
        original = "# user config\ndtparam=audio=on\n"
        rendered = render_firmware_fan_config(original, DEFAULT_FAN_CURVE, 5.0)
        self.assertIn("# user config", rendered)
        self.assertIn("dtparam=audio=on", rendered)
        self.assertIn("[pi5]", rendered)
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
            "dtparam=audio=on\n"
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

    @unittest.skipUnless(GTK_AVAILABLE, "GTK3/PyGObject oder ein X-Display ist nicht verfügbar")
    def test_live_fan_bar_adjusts_selected_firmware_stage(self):
        from takt_engine.gui.main import TaktEngineWindow

        combo = Gtk.ComboBoxText()
        combo.append_text("Stufe 1 · ab 50,0 °C")
        combo.set_active(0)
        speed = Gtk.SpinButton.new_with_range(29, 100, 1)
        speed.set_value(49)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 29, 100, 1)
        scale.set_value(49)
        target_label = Gtk.Label(label="Zielwert Stufe 1: 49 %")
        redraws = []
        status_text = []
        refreshes = []

        state = SimpleNamespace(
            _fan_slider_syncing=False,
            fan_stage_combo=combo,
            fan_curve_row_widgets=[{"speed": speed}],
            fan_live_target_label=target_label,
            fan_curve_chart=SimpleNamespace(queue_draw=lambda: redraws.append(True)),
            fan_curve_status_label=SimpleNamespace(set_text=lambda value: status_text.append(value)),
            _current_fan_curve_values=lambda: {
                "points": [{"temperature_c": 50, "speed_percent": speed.get_value_as_int()}]
            },
            _refresh_fan_stage_control=lambda: refreshes.append(True),
        )
        speed.connect(
            "value-changed",
            lambda widget: TaktEngineWindow._on_fan_curve_changed(state, widget),
        )
        scale.connect(
            "value-changed",
            lambda widget: TaktEngineWindow._on_fan_stage_speed_changed(state, widget),
        )

        scale.set_value(73)

        self.assertEqual(speed.get_value_as_int(), 73)
        self.assertEqual(target_label.get_text(), "Zielwert Stufe 1: 73 %")
        self.assertEqual(refreshes, [], "Der Stage-Refresh darf den Slider beim Ziehen nicht zurücksetzen.")
        self.assertTrue(redraws, "Der SpinButton muss den Diagramm-Refresh ausgelöst haben.")
        self.assertEqual(status_text[-1], "4 Firmware-Stufen · Änderungen noch nicht gespeichert.")

    @unittest.skipUnless(GTK_AVAILABLE, "GTK3/PyGObject oder ein X-Display ist nicht verfügbar")
    def test_language_switch_translates_widgets_and_preserves_combo_values(self):
        from takt_engine.gui.main import TaktEngineWindow
        from takt_engine.gui.i18n import translate_text

        window = Gtk.Window()
        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label(label="Übertakten")
        combo = Gtk.ComboBoxText()
        combo.append_text("Ausgewogen")
        combo.set_active(0)
        layout.pack_start(title, False, False, 0)
        layout.pack_start(combo, False, False, 0)
        window.add(layout)
        window.show_all()

        state = SimpleNamespace(language="en")
        state._translate_combo_cell = lambda _combo, renderer, model, iterator: renderer.set_property(
            "text", translate_text(model.get_value(iterator, 0), state.language)
        )
        state._translate_widget_tree = lambda widget, visited: TaktEngineWindow._translate_widget_tree(
            state, widget, visited
        )

        TaktEngineWindow._translate_widget_tree(state, window, set())
        self.assertEqual(title.get_text(), "Overclocking")
        model = combo.get_model()
        iterator = model.get_iter_first()
        self.assertEqual(model.get_value(iterator, 0), "Ausgewogen")
        renderer = combo.get_cells()[0]
        TaktEngineWindow._translate_combo_cell(state, combo, renderer, model, iterator)
        self.assertEqual(renderer.get_property("text"), "Balanced")

        state.language = "de"
        TaktEngineWindow._translate_widget_tree(state, window, set())
        self.assertEqual(title.get_text(), "Übertakten")
        self.assertEqual(model.get_value(iterator, 0), "Ausgewogen")
        window.destroy()

    def test_live_fan_page_connects_controls_and_keeps_separate_labels(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        source = gui.read_text()
        fan_ui = source[source.index("def _build_fan_curve_page"):source.index("def _set_fan_curve_rows")]
        self.assertIn('self.fan_live_scale = Gtk.Scale.new_with_range', fan_ui)
        self.assertIn('self.fan_live_scale.connect("value-changed", self._on_fan_stage_speed_changed)', fan_ui)
        self.assertIn('self.fan_stage_combo.connect("changed", self._on_fan_stage_selected)', fan_ui)
        self.assertIn("self.fan_live_target_label", fan_ui)
        self.assertIn("self.fan_live_actual_label", fan_ui)
        self.assertNotIn("Live-Leistung übernehmen", fan_ui)
        self.assertNotIn("Gtk.ProgressBar()", fan_ui)

    def test_installer_disables_old_competing_fan_daemon(self):
        installer = Path(__file__).resolve().parents[1] / "scripts" / "install-deps.sh"
        content = installer.read_text()
        self.assertIn("systemctl disable --now takt-engine-fan.service", content)
        self.assertIn("WARNUNG: Alter Lüfterdienst", content)
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
