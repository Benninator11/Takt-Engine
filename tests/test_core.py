import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from takt_engine.core.config import (
    BEGIN_MARKER, END_MARKER, create_backup, parse_config_values,
    render_managed_config, restore_backup,
)
from takt_engine.core.detector import detect_model, detect_hardware
from takt_engine.core.limits import (LIMITS as LIMITS_FOR_TEST, PI5_CONSERVATIVE_THRESHOLDS,
                                                   ValidationError, clock_gradient_color, clock_warning_zone, experimental_clock_warnings, validate_values)
from takt_engine.core.presets import load_presets
from takt_engine.core.runtime import (
    RuntimeStatus, calculate_cpu_usage, parse_clock_mhz, parse_cpu_counters,
    parse_temperature, parse_throttled, safety_state,
)
from takt_engine.core.extras import (
    build_benchmark_comparison, build_config_diff, build_diagnostic_report,
    delete_custom_profile, format_diagnostic_report, load_benchmark_history,
    load_custom_profiles, save_benchmark_result, save_custom_profile,
    current_boot_id, export_custom_profile, import_custom_profile, load_pending_apply,
    load_tuning_history, record_tuning_change, save_pending_apply, verify_pending_apply,
    update_pending_verification, format_tuning_history,
)
from types import SimpleNamespace
from unittest.mock import patch
from takt_engine.bench.runner import run_benchmark
from takt_engine.core.system import (SystemActionError, build_reboot_command, request_system_reboot)
from takt_engine.core.diagnostics import (
    build_compatibility_report, build_tuning_recommendation, inspect_config_text, run_self_test,
)


class SystemRebootTests(unittest.TestCase):
    def test_root_reboot_command_does_not_use_pkexec(self):
        self.assertEqual(
            build_reboot_command(is_root=True, systemctl_path="/usr/bin/systemctl"),
            ["/usr/bin/systemctl", "reboot"],
        )

    def test_desktop_user_reboot_command_uses_pkexec(self):
        self.assertEqual(
            build_reboot_command(is_root=False, systemctl_path="/usr/bin/systemctl", pkexec_path="/usr/bin/pkexec"),
            ["/usr/bin/pkexec", "/usr/bin/systemctl", "reboot"],
        )

    def test_non_root_restart_requests_only_systemctl_reboot(self):
        calls = []
        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "", "")
        paths = {"systemctl": "/usr/bin/systemctl", "pkexec": "/usr/bin/pkexec"}
        result = request_system_reboot(runner=fake_run, which=paths.get, geteuid=lambda: 1000)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls[0][0], ["/usr/bin/pkexec", "/usr/bin/systemctl", "reboot"])
        self.assertEqual(calls[0][1]["timeout"], 20)

    def test_root_restart_does_not_require_pkexec(self):
        calls = []
        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")
        result = request_system_reboot(
            runner=fake_run,
            which=lambda name: "/usr/bin/systemctl" if name == "systemctl" else None,
            geteuid=lambda: 0,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, [["/usr/bin/systemctl", "reboot"]])

    def test_restart_refuses_when_systemctl_is_missing(self):
        with patch("takt_engine.core.system.Path.is_file", return_value=False):
            with self.assertRaisesRegex(SystemActionError, "systemctl wurde nicht gefunden"):
                request_system_reboot(which=lambda _name: None, geteuid=lambda: 1000)

    def test_restart_refuses_when_pkexec_is_missing_for_desktop_user(self):
        with self.assertRaisesRegex(SystemActionError, "pkexec wurde nicht gefunden"):
            request_system_reboot(
                which=lambda name: "/usr/bin/systemctl" if name == "systemctl" else None,
                geteuid=lambda: 1000,
            )

    def test_restart_reports_nonzero_system_result(self):
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "authorization denied")
        with self.assertRaisesRegex(SystemActionError, "authorization denied"):
            request_system_reboot(
                runner=fake_run,
                which=lambda name: {"systemctl": "/usr/bin/systemctl", "pkexec": "/usr/bin/pkexec"}.get(name),
                geteuid=lambda: 1000,
            )

    def test_gui_has_confirmed_restart_button_and_benchmark_guard(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        content = gui.read_text()
        for token in ('self.restart_button = Gtk.Button(label="↻ Neustart…")',
                      "def restart_system_dialog(self, _button=None):",
                      "if self.benchmark_running:",
                      "request_system_reboot(timeout=20)",
                      "Jetzt neu starten",
                      "nicht angewendet"):
            with self.subTest(token=token):
                self.assertIn(token, content)


class DetectModelTests(unittest.TestCase):
    def test_detect_pi5(self):
        result = detect_model("Raspberry Pi 5 Model B Rev 1.0")
        self.assertEqual(result, ("pi5", "Raspberry Pi 5", True))

    def test_detect_pi4_from_cpuinfo_fallback(self):
        result = detect_model("", "Hardware : BCM2711")
        self.assertEqual(result, ("pi4", "Raspberry Pi 4", True))

    def test_unknown_pi_is_detected_but_not_supported(self):
        result = detect_model("Raspberry Pi 3 Model B Plus Rev 1.3")
        self.assertEqual(result[0], None)
        self.assertTrue(result[2])

    def test_non_pi(self):
        self.assertEqual(detect_model("Generic x86 computer"), (None, "Generic x86 computer", False))

    def test_firmware_config_path_has_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model").write_text("Raspberry Pi 5 Model B")
            (root / "cpuinfo").write_text("")
            (root / "os-release").write_text('PRETTY_NAME="Test OS"\n')
            (root / "firmware").mkdir()
            (root / "firmware/config.txt").write_text("# firmware\n")
            (root / "boot").mkdir()
            (root / "boot/config.txt").write_text("# legacy\n")
            info = detect_hardware(root / "model", root / "cpuinfo", root / "os-release",
                                   root / "firmware/config.txt", root / "boot/config.txt")
            self.assertEqual(info.config_path, root / "firmware/config.txt")
            self.assertEqual(info.os_name, "Test OS")


class LimitsTests(unittest.TestCase):
    def test_valid_pi4_values(self):
        values = {"arm_freq": 1800, "v3d_freq": 500, "core_freq": 500, "over_voltage_delta": 0}
        self.assertEqual(validate_values("pi4", values), values)

    def test_rejects_too_high_cpu_clock(self):
        with self.assertRaises(ValidationError):
            validate_values("pi4", {"arm_freq": 5000, "v3d_freq": 500, "core_freq": 500, "over_voltage_delta": 0})

    def test_rejects_core_frequency_on_pi5(self):
        with self.assertRaises(ValidationError):
            validate_values("pi5", {"arm_freq": 2400, "v3d_freq": 960, "core_freq": 500, "over_voltage_delta": 0})

    def test_rejects_unlisted_keys(self):
        with self.assertRaises(ValidationError):
            validate_values("pi5", {"arm_freq": 2400, "v3d_freq": 960, "over_voltage_delta": 0, "force_turbo": 1})

    def test_rejects_pi5_voltage_over_app_limit(self):
        with self.assertRaises(ValidationError):
            validate_values("pi5", {"arm_freq": 2400, "v3d_freq": 960, "over_voltage_delta": 50001})

    def test_allows_small_negative_voltage_offset_for_undervolting(self):
        values = {"arm_freq": 2400, "v3d_freq": 960, "over_voltage_delta": -5000}
        self.assertEqual(validate_values("pi5", values), values)

    def test_rejects_undervolting_beyond_app_guardrail(self):
        with self.assertRaises(ValidationError):
            validate_values("pi5", {"arm_freq": 2400, "v3d_freq": 960, "over_voltage_delta": -25001})

    def test_pi5_extended_slider_ceiling_accepts_requested_values_but_rejects_above_ceiling(self):
        self.assertEqual(LIMITS_FOR_TEST["pi5"].arm_max, 3800)
        self.assertEqual(LIMITS_FOR_TEST["pi5"].v3d_max, 2000)
        values = {"arm_freq": 3800, "v3d_freq": 2000, "over_voltage_delta": 0}
        self.assertEqual(validate_values("pi5", values), values)
        self.assertEqual(
            experimental_clock_warnings("pi5", values),
            [("arm_freq", 3800, 2800), ("v3d_freq", 2000, 1000)],
        )
        with self.assertRaises(ValidationError):
            validate_values("pi5", {**values, "arm_freq": 3801})
        with self.assertRaises(ValidationError):
            validate_values("pi5", {**values, "v3d_freq": 2001})

    def test_pi5_values_at_conservative_threshold_do_not_need_experimental_warning(self):
        values = {"arm_freq": PI5_CONSERVATIVE_THRESHOLDS["arm_freq"],
                  "v3d_freq": PI5_CONSERVATIVE_THRESHOLDS["v3d_freq"],
                  "over_voltage_delta": 0}
        self.assertEqual(experimental_clock_warnings("pi5", values), [])

    def test_pi5_clock_warning_zones_have_safe_caution_and_extreme_bands(self):
        self.assertEqual(clock_warning_zone("pi5", "arm_freq", 2800), "safe")
        self.assertEqual(clock_warning_zone("pi5", "arm_freq", 3000), "caution")
        self.assertEqual(clock_warning_zone("pi5", "arm_freq", 3200), "extreme")
        self.assertEqual(clock_warning_zone("pi5", "v3d_freq", 1000), "safe")
        self.assertEqual(clock_warning_zone("pi5", "v3d_freq", 1400), "caution")
        self.assertEqual(clock_warning_zone("pi5", "v3d_freq", 1800), "extreme")

    def test_pi4_and_non_clock_controls_keep_neutral_zone(self):
        self.assertEqual(clock_warning_zone("pi4", "arm_freq", 1900), "default")
        self.assertEqual(clock_warning_zone("pi5", "over_voltage_delta", -5000), "default")
        self.assertEqual(clock_warning_zone("pi5", "v3d_freq", "invalid"), "default")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.pi4_values = {"arm_freq": 1800, "v3d_freq": 500, "core_freq": 500, "over_voltage_delta": 0}

    def test_render_preserves_user_config_and_adds_managed_block(self):
        original = "# my comment\ndtparam=audio=on\n\n[all]\nstart_x=1\n"
        rendered = render_managed_config(original, "pi4", self.pi4_values)
        self.assertIn("# my comment", rendered)
        self.assertIn("dtparam=audio=on", rendered)
        self.assertIn("[pi4]", rendered)
        self.assertIn("arm_freq=1800", rendered)
        self.assertIn(BEGIN_MARKER, rendered)
        self.assertIn(END_MARKER, rendered)

    def test_second_render_replaces_not_duplicates_managed_block(self):
        first = render_managed_config("# existing\n", "pi4", self.pi4_values)
        second = render_managed_config(first, "pi4", {**self.pi4_values, "arm_freq": 1900})
        self.assertEqual(second.count(BEGIN_MARKER), 1)
        self.assertEqual(second.count(END_MARKER), 1)
        self.assertIn("arm_freq=1900", second)
        self.assertNotIn("arm_freq=1800", second)

    def test_render_writes_negative_undervolting_offset(self):
        values = {"arm_freq": 2400, "v3d_freq": 960, "over_voltage_delta": -5000}
        rendered = render_managed_config("# existing\n", "pi5", values)
        self.assertIn("over_voltage_delta=-5000", rendered)

    def test_damaged_block_is_refused(self):
        with self.assertRaises(ValueError):
            render_managed_config(f"{BEGIN_MARKER}\narm_freq=1\n", "pi4", self.pi4_values)

    def test_backup_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.txt"
            config.write_text("original\n")
            backup = create_backup(config, root / "backups")
            config.write_text("changed\n")
            restore_backup(backup, config)
            self.assertEqual(config.read_text(), "original\n")
            self.assertTrue(backup.is_file())

    def test_managed_output_respects_config_line_limit(self):
        rendered = render_managed_config("# original\n", "pi4", self.pi4_values)
        self.assertTrue(all(len(line) <= 98 for line in rendered.splitlines()))

    def test_config_parser_uses_last_value_in_matching_sections(self):
        content = """arm_freq=2000
[all]
v3d_freq=900
[pi4]
arm_freq=1800
[pi5]
arm_freq = 2600 # manually changed
v3d_freq=990
[all]
over_voltage_delta=-5000
"""
        pi5 = parse_config_values(
            content, "pi5", {"arm_freq": 2400, "v3d_freq": 960, "over_voltage_delta": 0}
        )
        self.assertEqual(pi5, {"arm_freq": 2600, "v3d_freq": 990, "over_voltage_delta": -5000})
        pi4 = parse_config_values(
            content, "pi4", {"arm_freq": 1500, "v3d_freq": 500, "core_freq": 500, "over_voltage_delta": 0}
        )
        self.assertEqual(pi4, {"arm_freq": 1800, "v3d_freq": 900, "core_freq": 500, "over_voltage_delta": -5000})

    def test_config_parser_falls_back_to_model_defaults(self):
        values = parse_config_values(
            "# arm_freq=2800 is only a comment\n[pi4]\narm_freq=1900\n",
            "pi5",
            {"arm_freq": 2400, "v3d_freq": 960, "over_voltage_delta": 0},
        )
        self.assertEqual(values, {"arm_freq": 2400, "v3d_freq": 960, "over_voltage_delta": 0})

    def test_config_parser_keeps_out_of_app_range_value_visible_for_warning(self):
        values = parse_config_values(
            "[pi5]\narm_freq=3200\nv3d_freq=1500\n",
            "pi5",
            {"arm_freq": 2400, "v3d_freq": 960, "over_voltage_delta": 0},
        )
        self.assertEqual(values["arm_freq"], 3200)
        self.assertEqual(values["v3d_freq"], 1500)

    def test_config_parser_rejects_unknown_model(self):
        with self.assertRaises(ValueError):
            parse_config_values("[all]\narm_freq=2000\n", "pi3", {"arm_freq": 1200})

    def test_privileged_writer_refuses_unapproved_config_path(self):
        helper = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "privileged_writer.py"
        values = json.dumps(self.pi4_values)
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.txt"
            config.write_text("untouched\n")
            result = subprocess.run(
                [sys.executable, str(helper), "--config", str(config), "--model", "pi4", "--values", values],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Bootpfade", result.stderr)
            self.assertEqual(config.read_text(), "untouched\n")


class PresetTests(unittest.TestCase):
    def test_builtin_profiles_are_expandable_categorized_and_valid(self):
        presets = load_presets()
        self.assertGreater(len(presets), 10)
        self.assertTrue(any(preset.get("category") == "performance" for preset in presets))
        self.assertTrue(any(preset.get("category") == "undervolting" for preset in presets))
        self.assertEqual(len({preset["id"] for preset in presets}), len(presets))
        for preset in presets:
            with self.subTest(preset=preset["id"]):
                validate_values(preset["model"], preset["values"])

    def test_undervolting_presets_use_only_small_negative_offsets(self):
        presets = [preset for preset in load_presets() if preset.get("category") == "undervolting"]
        self.assertTrue(presets)
        for preset in presets:
            with self.subTest(preset=preset["id"]):
                offset = preset["values"]["over_voltage_delta"]
                self.assertIn(offset, (-5000, -10000))


class ThemeAndDesktopTests(unittest.TestCase):
    def test_claude_dark_orange_theme_is_installed_in_gui(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        content = gui.read_text()
        self.assertIn("#252422", content)
        self.assertIn("#d97745", content.lower())
        self.assertIn("def apply_claude_theme()", content)
        self.assertIn("apply_claude_theme()", content)

    def test_smooth_warning_gradient_is_used_and_extra_legend_is_removed(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        content = gui.read_text()
        for token in (
            "def _update_clock_zone", "def _animate_clock_gradient",
            "def _tick_clock_gradient", "def _render_clock_gradient_css",
            "clock-gradient-", "GLib.timeout_add(24, self._tick_clock_gradient, key)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, content)
        self.assertNotIn("zone_legend =", content)
        self.assertNotIn("zone-note", content)
        self.assertNotIn("● Grün/Blau: konservativer Bereich", content)

    def test_clock_gradient_interpolates_green_yellow_orange_red(self):
        self.assertEqual(clock_gradient_color("pi5", "arm_freq", 2400), "#65c58a")
        self.assertEqual(clock_gradient_color("pi5", "arm_freq", 2800), "#e2ca55")
        self.assertEqual(clock_gradient_color("pi5", "arm_freq", 3100), "#ed8b43")
        self.assertEqual(clock_gradient_color("pi5", "arm_freq", 3800), "#e3534c")
        green_yellow_mid = clock_gradient_color("pi5", "arm_freq", 2600)
        yellow_orange_mid = clock_gradient_color("pi5", "arm_freq", 2950)
        orange_red_mid = clock_gradient_color("pi5", "arm_freq", 3450)
        self.assertNotEqual(green_yellow_mid, "#65c58a")
        self.assertNotEqual(green_yellow_mid, "#e2ca55")
        self.assertNotEqual(yellow_orange_mid, "#e2ca55")
        self.assertNotEqual(yellow_orange_mid, "#ed8b43")
        self.assertNotEqual(orange_red_mid, "#ed8b43")
        self.assertNotEqual(orange_red_mid, "#e3534c")
        self.assertEqual(clock_gradient_color("pi5", "v3d_freq", 1000), "#e2ca55")
        self.assertEqual(clock_gradient_color("pi5", "v3d_freq", 1500), "#ed8b43")

    def test_clock_gradient_clamps_out_of_range_config_values(self):
        self.assertEqual(clock_gradient_color("pi5", "arm_freq", 1000), "#65c58a")
        self.assertEqual(clock_gradient_color("pi5", "arm_freq", 9999), "#e3534c")
        self.assertEqual(clock_gradient_color("pi4", "arm_freq", 1800), "#f3a06c")
        self.assertEqual(clock_gradient_color("pi5", "over_voltage_delta", 0), "#f3a06c")

    def test_custom_svg_icon_exists_and_is_svg(self):
        icon = Path(__file__).resolve().parents[1] / "data" / "takt-engine.svg"
        content = icon.read_text()
        self.assertIn("<svg", content)
        self.assertIn("#d97745", content.lower())

    def test_pi5_extreme_requested_targets_fit_new_app_ceiling(self):
        self.assertEqual(LIMITS_FOR_TEST["pi5"].arm_max, 3800)
        self.assertEqual(LIMITS_FOR_TEST["pi5"].v3d_max, 2000)
        values = {"arm_freq": 3800, "v3d_freq": 2000, "over_voltage_delta": 0}
        self.assertEqual(validate_values("pi5", values), values)
        self.assertEqual(len(experimental_clock_warnings("pi5", values)), 2)
        with self.assertRaises(ValidationError):
            validate_values("pi5", {**values, "arm_freq": 3801})
        with self.assertRaises(ValidationError):
            validate_values("pi5", {**values, "v3d_freq": 2001})

    def test_gui_asks_for_extra_confirmation_for_experimental_clocks(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        content = gui.read_text()
        self.assertIn("def _confirm_experimental_clock_values", content)
        self.assertIn("Mögliche Folgen sind Instabilität", content)
        self.assertIn("if experimental and not self._confirm_experimental_clock_values(experimental)", content)

    def test_gui_reloads_config_settings_and_preserves_unsaved_slider_edits(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        content = gui.read_text()
        self.assertIn("self._sync_sliders_from_config(force=True)", content)
        self.assertIn("GLib.timeout_add_seconds(3, self.refresh_status)", content)
        self.assertIn("def reload_config_sliders(self, _button=None):", content)
        self.assertIn("if self._sliders_dirty and not force:", content)

    def test_installer_creates_app_menu_and_per_user_desktop_shortcut(self):
        installer = Path(__file__).resolve().parents[1] / "scripts" / "install-deps.sh"
        content = installer.read_text()
        self.assertIn("/usr/share/applications/takt-engine.desktop", content)
        self.assertIn("Takt-Engine.desktop", content)
        self.assertIn("xdg-user-dir DESKTOP", content)
        self.assertIn("chmod 0755 /usr/local/bin/takt-engine", content)
        self.assertIn("Icon=/opt/takt-engine/share/takt-engine.svg", content)


    def test_apply_action_has_one_second_orange_pulse(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        content = gui.read_text()
        self.assertIn("GLib.timeout_add(100, self._tick_apply_animation)", content)
        self.assertIn("phases = (0, 1, 2, 3, 2, 1, 0, 1, 2, 0)", content)
        self.assertIn("button.apply-pulse-3", content)
        self.assertIn("self._continue_apply_settings()", content)

    def test_benninator_is_small_semitransparent_white_in_header(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        content = gui.read_text()
        self.assertIn("Benninator", content)
        self.assertIn('foreground="#ffffff" foreground_alpha="36000" size="small"', content)
        self.assertIn("header_row.pack_end(self.nickname_label", content)


class RuntimeParseTests(unittest.TestCase):
    def test_temperature(self):
        self.assertEqual(parse_temperature("temp=52.6'C"), 52.6)
        self.assertIsNone(parse_temperature("not a temperature"))

    def test_clock(self):
        self.assertEqual(parse_clock_mhz("frequency(48)=2400000000"), 2400)
        self.assertIsNone(parse_clock_mhz(""))

    def test_throttled_active_and_historical(self):
        self.assertEqual(parse_throttled("throttled=0x50005"), ("0x50005", True, True, True))
        self.assertEqual(parse_throttled("throttled=0x0"), ("0x0", False, False, False))
        self.assertEqual(parse_throttled("unknown"), (None, False, False, False))


class InstallerTests(unittest.TestCase):
    def test_installer_uses_split_polkit_packages_and_installs_helper_policy(self):
        root = Path(__file__).resolve().parents[1]
        installer = root / "scripts" / "install-deps.sh"
        content = installer.read_text()
        install_lines = [line for line in content.splitlines() if line.strip().startswith("apt-get install")]
        self.assertEqual(len(install_lines), 1)
        self.assertIn("pkexec", install_lines[0])
        self.assertIn("polkitd", install_lines[0])
        self.assertNotIn("policykit-1", install_lines[0])
        self.assertIn('install -m 0644 "$PROJECT_DIR/polkit/org.benninator.takt-engine.policy"', content)
        self.assertIn('chmod 0755 "$INSTALL_DIR/src/takt_engine/privileged_writer.py"', content)

        policy = root / "polkit" / "org.benninator.takt-engine.policy"
        self.assertIn("/opt/takt-engine/src/takt_engine/privileged_writer.py", policy.read_text())

    def test_root_backup_reader_checks_open_handle_owner_type_size_and_nul_bytes(self):
        helper = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "privileged_writer.py"
        spec = importlib.util.spec_from_file_location("takt_engine_helper_backup_test", helper)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / "config.txt.test.bak"
            expected = chr(10).join(("[all]", "arm_freq=2400", ""))
            backup.write_text(expected, encoding="utf-8")
            self.assertEqual(module._read_restore_backup(backup, os.getuid()), expected)
            with self.assertRaisesRegex(ValueError, "gehört nicht"):
                module._read_restore_backup(backup, os.getuid() + 1)

            backup.write_bytes(b"[all]" + bytes((0,)) + b"tail")
            with self.assertRaisesRegex(ValueError, "NUL"):
                module._read_restore_backup(backup, os.getuid())

            backup.write_bytes(b"x" * (module.MAX_RESTORE_BACKUP_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "256 KiB"):
                module._read_restore_backup(backup, os.getuid())

            with self.assertRaisesRegex(ValueError, "reguläre Datei"):
                module._read_restore_backup(root, os.getuid())


class AdvancedFeatureTests(unittest.TestCase):
    def setUp(self):
        self.pi5_values = {"arm_freq": 2400, "v3d_freq": 960, "over_voltage_delta": 0}

    def test_custom_profiles_save_load_duplicate_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            saved = save_custom_profile("  Everyday   profile ", "pi5", self.pi5_values, path)
            self.assertEqual(saved["name"], "Everyday profile")
            loaded = load_custom_profiles(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["values"], self.pi5_values)
            with self.assertRaises(ValueError):
                save_custom_profile("EVERYDAY PROFILE", "pi5", self.pi5_values, path)
            self.assertTrue(delete_custom_profile(saved["id"], path))
            self.assertEqual(load_custom_profiles(path), [])
            self.assertFalse(delete_custom_profile(saved["id"], path))

    def test_custom_profiles_reject_invalid_names_values_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            with self.assertRaises(ValueError):
                save_custom_profile("   ", "pi5", self.pi5_values, path)
            with self.assertRaises(ValueError):
                save_custom_profile("profile", "pi5", {**self.pi5_values, "arm_freq": 3900}, path)
            with self.assertRaises(ValueError):
                save_custom_profile("a" * 41, "pi5", self.pi5_values, path)

    def test_corrupt_custom_profile_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            path.write_text("{ broken", encoding="utf-8")
            self.assertEqual(load_custom_profiles(path), [])

    def test_benchmark_history_persists_and_compares_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            status = RuntimeStatus(temperature_c=60.0, arm_clock_mhz=2400,
                                   throttled_hex="0x0", active_throttling=False,
                                   undervoltage=False, historical_flags=False,
                                   v3d_clock_mhz=960, cpu_usage_percent=40.0)
            result = SimpleNamespace(passed=True, duration_seconds=60,
                                     peak_temperature_c=65.0, final_status=status,
                                     return_code=0, summary="Bestanden")
            first = save_benchmark_result(result, "pi5", path)
            result2 = SimpleNamespace(passed=False, duration_seconds=60,
                                      peak_temperature_c=72.0,
                                      final_status=RuntimeStatus(72.0, 2300, "0x0", False, False, False,
                                                                 v3d_clock_mhz=900, cpu_usage_percent=95.0),
                                      return_code=1, summary="Temperatur erhöht")
            second = save_benchmark_result(result2, "pi5", path)
            history = load_benchmark_history(path)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["timestamp"], first["timestamp"])
            self.assertEqual(history[1]["timestamp"], second["timestamp"])
            comparison = build_benchmark_comparison(history, "pi5")
            self.assertIn("NICHT BESTANDEN", comparison)
            self.assertIn("+7.0 °C", comparison)
            self.assertIn("-100 MHz", comparison)

    def test_benchmark_history_is_capped_at_fifty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            status = RuntimeStatus(50.0, 2400, "0x0", False, False, False)
            for _ in range(55):
                result = SimpleNamespace(passed=True, duration_seconds=10,
                                         peak_temperature_c=50.0, final_status=status,
                                         return_code=0, summary="OK")
                save_benchmark_result(result, "pi5", path)
            self.assertEqual(len(load_benchmark_history(path)), 50)

    def test_config_diff_shows_real_changes_and_preserves_other_lines(self):
        old = "# keep me\n[all]\nstart_x=1\n"
        new = old + "# BEGIN TAKT ENGINE MANAGED BLOCK\n[pi5]\narm_freq=2400\n# END TAKT ENGINE MANAGED BLOCK\n"
        diff = build_config_diff(old, new)
        self.assertTrue(any(line.startswith("+") and "arm_freq=2400" in line for line in diff))
        self.assertFalse(any(line.startswith("-") and "start_x=1" in line for line in diff))

    def test_diagnostic_report_is_structured_and_excludes_full_config(self):
        hardware = SimpleNamespace(model_id="pi5", model_name="Raspberry Pi 5",
                                   is_raspberry_pi=True, os_name="Raspberry Pi OS",
                                   config_path=Path("/boot/firmware/config.txt"))
        status = RuntimeStatus(temperature_c=55.0, arm_clock_mhz=2400,
                               throttled_hex="0x0", active_throttling=False,
                               undervoltage=False, historical_flags=False,
                               v3d_clock_mhz=960, cpu_usage_percent=20.5)
        report = build_diagnostic_report(hardware, status, self.pi5_values, [])
        rendered = format_diagnostic_report(report)
        self.assertEqual(report["runtime"]["cpu_usage_percent"], 20.5)
        self.assertIn("arm_freq = 2400", rendered)
        self.assertIn("keine komplette config.txt", rendered)
        self.assertNotIn("wifi_password", rendered)
        self.assertNotIn("start_x=1", rendered)

    def test_cpu_usage_parser_and_calculator(self):
        previous = parse_cpu_counters("cpu 100 0 50 800 50 0 0 0 0 0\n")
        current = parse_cpu_counters("cpu 150 0 80 870 50 0 0 0 0 0\n")
        self.assertEqual(previous, (1000, 850))
        self.assertEqual(current, (1150, 920))
        self.assertAlmostEqual(calculate_cpu_usage(previous, current), 53.3, places=1)
        self.assertIsNone(calculate_cpu_usage(None, current))
        self.assertIsNone(parse_cpu_counters("garbled"))

    def test_clock_parser_accepts_v3d_frequency_id(self):
        self.assertEqual(parse_clock_mhz("frequency(46)=960000000"), 960)
        self.assertEqual(parse_clock_mhz("clock=1000000000"), 1000)

    def test_benchmark_comparison_warns_when_test_settings_differ(self):
        history = [
            {"model": "pi5", "passed": True, "timestamp": "first", "duration_seconds": 60,
             "requested_duration_seconds": 60, "threads": 2, "peak_temperature_c": 60.0},
            {"model": "pi5", "passed": True, "timestamp": "second", "duration_seconds": 30,
             "requested_duration_seconds": 30, "threads": 4, "peak_temperature_c": 58.0},
        ]
        text = build_benchmark_comparison(history, "pi5")
        self.assertIn("nur eingeschränkt vergleichbar", text)
        self.assertNotIn("Temperaturvergleich bei gleicher", text)

    def test_benchmark_rejects_invalid_duration_and_thread_count_before_starting(self):
        with self.assertRaises(ValueError):
            run_benchmark(9, 1)
        with self.assertRaises(ValueError):
            run_benchmark(10, 0)

    def test_benchmark_reports_missing_stress_ng(self):
        with patch("takt_engine.bench.runner.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "stress-ng ist nicht installiert"):
                run_benchmark(10, 1)

    def test_benchmark_terminates_at_80_degrees(self):
        class FakeProcess:
            def __init__(self):
                self.returncode = None
                self.terminated = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -15

            def communicate(self, timeout=None):
                return "", None

            def kill(self):
                self.returncode = -9

            def wait(self):
                return self.returncode

        process = FakeProcess()
        statuses = iter([
            RuntimeStatus(temperature_c=74.0, arm_clock_mhz=2400,
                          throttled_hex="0x0", active_throttling=False,
                          undervoltage=False, historical_flags=False),
            RuntimeStatus(temperature_c=80.0, arm_clock_mhz=2200,
                          throttled_hex="0x0", active_throttling=False,
                          undervoltage=False, historical_flags=False),
            RuntimeStatus(temperature_c=80.0, arm_clock_mhz=2200,
                          throttled_hex="0x0", active_throttling=False,
                          undervoltage=False, historical_flags=False),
        ])
        with patch("takt_engine.bench.runner.shutil.which", return_value="/usr/bin/stress-ng"):
            with patch("takt_engine.bench.runner.time.monotonic", return_value=0.0):
                result = run_benchmark(
                    10, 1, status_reader=lambda: next(statuses),
                    process_factory=lambda *_args, **_kwargs: process,
                )
        self.assertTrue(process.terminated)
        self.assertFalse(result.passed)
        self.assertIn("Sicherheitstopp bei 80 °C", result.summary)

    def test_safety_monitor_classifies_temperature_and_flags(self):
        normal = RuntimeStatus(temperature_c=55.0, arm_clock_mhz=2400,
                               throttled_hex="0x0", active_throttling=False,
                               undervoltage=False, historical_flags=False)
        self.assertEqual(safety_state(normal)[0], "ok")
        warm = RuntimeStatus(temperature_c=76.0, arm_clock_mhz=2400,
                             throttled_hex="0x0", active_throttling=False,
                             undervoltage=False, historical_flags=False)
        self.assertEqual(safety_state(warm)[0], "caution")
        hot = RuntimeStatus(temperature_c=80.0, arm_clock_mhz=2400,
                            throttled_hex="0x0", active_throttling=False,
                            undervoltage=False, historical_flags=False)
        self.assertEqual(safety_state(hot)[0], "critical")
        undervolted = RuntimeStatus(temperature_c=55.0, arm_clock_mhz=2400,
                                    throttled_hex="0x1", active_throttling=False,
                                    undervoltage=True, historical_flags=False)
        self.assertEqual(safety_state(undervolted)[0], "critical")

    def test_gui_integrates_all_seven_feature_areas_and_animations(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        content = gui.read_text()
        for expected in (
            "def _build_monitor_page", "def _draw_monitor_chart", "v3d_clock_mhz",
            "def _refresh_benchmark_history", "save_benchmark_result",
            "def _show_config_preview", "def save_custom_profile_dialog",
            "def _update_safety_banner", "running-pulse-", "def export_diagnostic_report",
            "def _tick_live_badge", "def _on_tab_switched",
        ):
            with self.subTest(feature=expected):
                self.assertIn(expected, content)


class NewRoadmapFeatureTests(unittest.TestCase):
    def test_config_inspector_detects_duplicate_out_of_range_and_include(self):
        config = """[all]
arm_freq=2400
include=extra.txt
[pi5]
arm_freq=3000
arm_freq=3100
v3d_freq=1500
"""
        findings = inspect_config_text(config, "pi5")
        messages = "\n".join(item["message"] for item in findings)
        self.assertIn("Include-Datei", messages)
        self.assertIn("bereits in Zeile", messages)
        self.assertIn("experimentellen Pi-5-Bereich", messages)
        self.assertIn("aktiv vorgesehen", messages)
        self.assertTrue(any(item["level"] == "WARNUNG" for item in findings))

    def test_config_inspector_warns_when_pi5_values_enter_experimental_zone(self):
        findings = inspect_config_text("[pi5]\narm_freq=3000\nv3d_freq=1200\n", "pi5")
        messages = "\n".join(item["message"] for item in findings)
        self.assertIn("arm_freq=3000 liegt im experimentellen Pi-5-Bereich", messages)
        self.assertIn("v3d_freq=1200 liegt im experimentellen Pi-5-Bereich", messages)

    def test_tuning_assistant_does_not_recommend_experimental_pi5_zone(self):
        status = RuntimeStatus(temperature_c=50.0, arm_clock_mhz=2400, throttled_hex="0x0",
                              active_throttling=False, undervoltage=False, historical_flags=False)
        current = {"arm_freq": 2750, "v3d_freq": 990, "over_voltage_delta": 0}
        result = build_tuning_recommendation("pi5", current, status, "Mehr Leistung")
        self.assertLessEqual(result["values"]["arm_freq"], 2800)
        self.assertLessEqual(result["values"]["v3d_freq"], 1000)

    def test_config_inspector_reports_bad_integer_and_section_syntax(self):
        findings = inspect_config_text("[pi5\narm_freq=fast\n", "pi5")
        self.assertTrue(any(item["level"] == "FEHLER" and "Abschnittsfilter" in item["message"] for item in findings))

    def test_config_inspector_does_not_report_normal_config_as_error(self):
        findings = inspect_config_text("[all]\nhdmi_enable_4kp60=0\n[pi5]\narm_freq=2600\nv3d_freq=980\nover_voltage_delta=0\n", "pi5")
        self.assertFalse(any(item["level"] == "FEHLER" for item in findings))

    def test_tuning_assistant_clamps_existing_experimental_values(self):
        status = RuntimeStatus(temperature_c=50.0, arm_clock_mhz=2400, throttled_hex="0x0",
                              active_throttling=False, undervoltage=False, historical_flags=False)
        current = {"arm_freq": 3600, "v3d_freq": 1800, "over_voltage_delta": 0}
        result = build_tuning_recommendation("pi5", current, status, "Mehr Leistung")
        self.assertEqual(result["values"]["arm_freq"], 2800)
        self.assertEqual(result["values"]["v3d_freq"], 1000)

    def test_tuning_assistant_stops_when_system_is_hot(self):
        hot = RuntimeStatus(temperature_c=81.0, arm_clock_mhz=2400, throttled_hex="0x0",
                            active_throttling=False, undervoltage=False, historical_flags=False)
        result = build_tuning_recommendation("pi5", LIMITS_FOR_TEST["pi5"].defaults, hot, "Mehr Leistung")
        self.assertIsNone(result["values"])
        self.assertIn("Keine Taktsteigerung", result["message"])

    def test_tuning_assistant_suggests_only_valid_small_step_when_cool(self):
        cool = RuntimeStatus(temperature_c=51.0, arm_clock_mhz=2400, throttled_hex="0x0",
                             active_throttling=False, undervoltage=False, historical_flags=False)
        result = build_tuning_recommendation("pi5", {"arm_freq": 2500, "v3d_freq": 960, "over_voltage_delta": 0}, cool, "Mehr Leistung")
        self.assertEqual(result["values"]["arm_freq"], 2550)
        validate_values("pi5", result["values"])

    def test_tuning_history_records_only_managed_values_and_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            record = record_tuning_change("pi5", {"arm_freq": 2400, "other": "secret"},
                                          {"arm_freq": 2500, "v3d_freq": 980}, 53.2, "/tmp/config.txt.abc.bak", path)
            history = load_tuning_history(path)
            self.assertEqual(len(history), 1)
            self.assertNotIn("other", history[0]["old_values"])
            self.assertEqual(history[0]["backup"], "config.txt.abc.bak")
            formatted = format_tuning_history(history)
            self.assertIn("arm_freq: 2400 → 2500", formatted)
            self.assertIsNotNone(record)

    def test_tuning_history_is_capped_at_two_hundred(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            for index in range(205):
                record_tuning_change("pi5", {"arm_freq": 2400}, {"arm_freq": 2400 + 1 + index}, path=path)
            self.assertEqual(len(load_tuning_history(path)), 200)

    def test_profile_export_import_roundtrip_and_model_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profiles_path = root / "profiles.json"
            profile = save_custom_profile("Portable Test", "pi5", LIMITS_FOR_TEST["pi5"].defaults, profiles_path)
            exported = export_custom_profile(profile, root / "portable.json")
            imported = import_custom_profile(exported, "pi5", root / "imported.json")
            self.assertEqual(imported["name"], "Portable Test")
            self.assertEqual(load_custom_profiles(root / "imported.json")[0]["values"], LIMITS_FOR_TEST["pi5"].defaults)
            with self.assertRaises(ValueError):
                import_custom_profile(exported, "pi4", root / "wrong-model.json")

    def test_profile_import_rejects_unknown_schema_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "bad.json"
            source.write_text(json.dumps({"format": "takt-engine-profile", "schema_version": 1,
                                          "profile": {"name": "bad", "model": "pi5", "values": {"arm_freq": 3900}}}))
            with self.assertRaises(ValueError):
                import_custom_profile(source, "pi5", root / "profiles.json")

    def test_pending_apply_and_reboot_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reboot.json"
            values = dict(LIMITS_FOR_TEST["pi5"].defaults)
            state = save_pending_apply("pi5", values, trial_rollback=True, path=path, boot_id="before")
            same_boot = verify_pending_apply(state, "before", values)
            self.assertEqual(same_boot["status"], "reboot_pending")
            after_boot = verify_pending_apply(state, "after", values)
            self.assertEqual(after_boot["status"], "confirmed")
            update_pending_verification(after_boot, path)
            loaded = load_pending_apply(path)
            self.assertEqual(loaded["verification"], "confirmed")
            self.assertTrue(loaded["trial_rollback"])

    def test_reboot_verification_distinguishes_unknown_from_mismatch(self):
        state = {"boot_id": "before", "values": {"arm_freq": 2600}}
        self.assertEqual(verify_pending_apply(state, "after", {})["status"], "partial")
        self.assertEqual(verify_pending_apply(state, "after", {"arm_freq": 2400})["status"], "mismatch")
        self.assertEqual(verify_pending_apply(state, "before", {}, {"arm_freq": 2400})["status"], "config_mismatch")

    def test_postboot_rollback_helper_restores_only_after_different_boot(self):
        import importlib.util
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollback_dir = root / "rollback"
            rollback_dir.mkdir()
            config_path = root / "config.txt"
            config_path.write_text("trial settings\n")
            backup_path = rollback_dir / "config.txt.before-trial.bak"
            backup_path.write_text("known good settings\n")
            pending_path = rollback_dir / "pending.json"
            pending_path.write_text(json.dumps({"config_path": str(config_path), "armed_boot_id": "old-boot", "confirmed": False}))
            script = Path(__file__).resolve().parents[1] / "scripts" / "rollback-check.py"
            spec = importlib.util.spec_from_file_location("rollback_check_test", script)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            module.STATE_DIR = rollback_dir
            module.PENDING = pending_path
            module.BACKUP = backup_path
            module.ALLOWED_PATHS = {config_path}
            module.boot_id = lambda: "new-boot"
            self.assertEqual(module.main(), 0)
            self.assertEqual(config_path.read_text(), "known good settings\n")
            self.assertFalse(pending_path.exists())
            self.assertFalse(backup_path.exists())

    def test_postboot_rollback_helper_does_not_restore_in_same_boot(self):
        import importlib.util
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollback_dir = root / "rollback"
            rollback_dir.mkdir()
            config_path = root / "config.txt"
            config_path.write_text("trial settings\n")
            backup_path = rollback_dir / "config.txt.before-trial.bak"
            backup_path.write_text("known good settings\n")
            pending_path = rollback_dir / "pending.json"
            pending_path.write_text(json.dumps({"config_path": str(config_path), "armed_boot_id": "same-boot", "confirmed": False}))
            script = Path(__file__).resolve().parents[1] / "scripts" / "rollback-check.py"
            spec = importlib.util.spec_from_file_location("rollback_check_same_boot_test", script)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            module.STATE_DIR = rollback_dir
            module.PENDING = pending_path
            module.BACKUP = backup_path
            module.ALLOWED_PATHS = {config_path}
            module.boot_id = lambda: "same-boot"
            self.assertEqual(module.main(), 0)
            self.assertEqual(config_path.read_text(), "trial settings\n")
            self.assertTrue(pending_path.exists())

    def test_compatibility_and_self_test_are_read_only_reports(self):
        hardware = SimpleNamespace(model_id="pi5", model_name="Raspberry Pi 5", is_raspberry_pi=True,
                                   os_name="Test OS", config_path=None)
        compatibility = build_compatibility_report(hardware)
        self.assertIn("kernel", compatibility)
        self.assertIn("firmware", compatibility)
        checks = run_self_test(hardware)
        self.assertTrue(any(item["name"] == "Python" for item in checks))
        self.assertTrue(any(item["name"] == "Boot-config lesbar" for item in checks))

    def test_rollback_timer_is_opt_in_and_limited_to_allowed_boot_config(self):
        root = Path(__file__).resolve().parents[1]
        writer = (root / "src/takt_engine/privileged_writer.py").read_text()
        checker = (root / "scripts/rollback-check.py").read_text()
        timer = (root / "scripts/takt-engine-rollback.timer").read_text()
        self.assertIn("--arm-rollback", writer)
        self.assertIn("--confirm-rollback", writer)
        self.assertIn("/boot/firmware/config.txt", checker)
        self.assertIn("armed_boot_id", checker)
        self.assertIn("OnBootSec=120s", timer)

    def test_gui_integrates_all_new_roadmap_areas(self):
        gui = Path(__file__).resolve().parents[1] / "src" / "takt_engine" / "gui" / "main.py"
        content = gui.read_text()
        for token in ("def _build_tools_page", "def run_config_inspector", "def run_system_self_test",
                      "def run_compatibility_check", "def run_tuning_assistant", "def confirm_trial_boot",
                      "def export_profile_dialog", "def import_profile_dialog", "fan_rpm",
                      "record_tuning_change", "verify_pending_apply"):
            with self.subTest(token=token):
                self.assertIn(token, content)



if __name__ == "__main__":
    unittest.main()
