"""GTK3 desktop interface for Takt Engine."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from datetime import datetime

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib
except (ImportError, ValueError) as exc:  # pragma: no cover - depends on target OS
    raise SystemExit(
        "GTK3/PyGObject fehlt. Unter Raspberry Pi OS bitte scripts/install-deps.sh ausführen.\n"
        f"Details: {exc}"
    )

from takt_engine import __version__
from takt_engine.gui.i18n import load_ui_language, save_ui_language, translate_text
from takt_engine.bench.runner import run_benchmark
from takt_engine.core.apply import (
    apply_fan_curve,
    apply_settings, confirm_boot_rollback, restore_config_backup,
)
from takt_engine.core.config import parse_config_values, read_config, render_managed_config
from takt_engine.core.detector import detect_hardware
from takt_engine.core.fan_curve import (
    DEFAULT_FAN_CURVE, DEFAULT_HYSTERESIS_C,
    MIN_FAN_SPEED_PERCENT, parse_fan_curve_config, read_hwmon_fan_state,
    validate_fan_curve,
)
from takt_engine.core.limits import (LIMITS, ValidationError, clock_gradient_color, clock_warning_zone,
                                            experimental_clock_warnings, validate_values)
from takt_engine.core.presets import load_presets
from takt_engine.core.runtime import read_firmware_config, read_status, safety_state
from takt_engine.core.system import request_system_reboot, SystemActionError
from takt_engine.core.diagnostics import (
    build_compatibility_report, build_tuning_recommendation, inspect_config_text, rollback_timer_ready, run_self_test,
)
from takt_engine.core.extras import (
    build_benchmark_comparison,
    build_config_diff,
    build_diagnostic_report,
    current_boot_id,
    export_custom_profile,
    format_tuning_history,
    import_custom_profile,
    load_pending_apply,
    load_tuning_history,
    record_tuning_change,
    save_pending_apply,
    update_pending_verification,
    update_reboot_state_fields,
    verify_pending_apply,
    delete_custom_profile as delete_stored_custom_profile,
    format_diagnostic_report,
    load_benchmark_history,
    load_custom_profiles,
    save_benchmark_result,
    save_custom_profile as store_custom_profile,
)


APP_NAME = "Takt Engine"


CLAUDE_DARK_CSS = b"""
* { color: #f0ece7; }
window, dialog { background-color: #252422; color: #f0ece7; }
notebook { background-color: #252422; }
notebook > header { background-color: #1f1e1c; border: 0; }
notebook > header > tabs > tab {
  background-color: #2b2927; color: #c5bdb5;
  padding: 9px 14px; border: 1px solid #3c3935;
}
notebook > header > tabs > tab:checked {
  background-color: #37312c; color: #f2a16d;
  border-bottom: 2px solid #d97745;
}
button {
  background-image: none; background-color: #393633; color: #f3eee8;
  border: 1px solid #514a44; border-radius: 8px; padding: 6px 12px;
}
button:hover { background-color: #4a423b; }
button:disabled { color: #8f8983; background-color: #2d2b29; }
button.suggested-action {
  background-image: none; background-color: #d97745; color: #211813;
  border: 1px solid #ed9765; font-weight: bold;
}
button.suggested-action:hover { background-color: #e88755; }
label { color: #f0ece7; }
.dim-label { color: #b9b0a7; }
label.caution { color: #f2a16d; font-weight: bold; }
label.safety-ok { color: #a8d5a2; font-weight: bold; padding: 5px 8px; background-color: #2c342b; border-radius: 6px; }
label.safety-caution { color: #f2bd79; font-weight: bold; padding: 5px 8px; background-color: #3d3326; border-radius: 6px; }
label.safety-critical { color: #ff9a82; font-weight: bold; padding: 5px 8px; background-color: #442b28; border-radius: 6px; }
label.safety-unknown { color: #c3bbb3; padding: 5px 8px; background-color: #302d2a; border-radius: 6px; }
label.live-pulse-0 { color: #d97745; }
label.live-pulse-1 { color: #f2a16d; }
label.live-pulse-2 { color: #ffe0c7; }
button.running-pulse-0 { border-color: #d97745; }
button.running-pulse-1 { border-color: #f2a16d; box-shadow: 0 0 8px #d97745; }
scale trough { background-color: #46413b; border-radius: 6px; min-height: 6px; }
scale highlight { background-color: #df8150; border-radius: 6px; }
scale slider {
  background-image: none; background-color: #f3a06c;
  border: 1px solid #d97745; min-width: 16px; min-height: 16px; border-radius: 9px;
}
textview, textview text { background-color: #201f1d; color: #eae5de; }
scrolledwindow { background-color: #252422; }
list, row { background-color: #2a2826; color: #f0ece7; }
progressbar trough { background-color: #423d38; border-radius: 6px; }
progressbar progress { background-color: #d97745; border-radius: 6px; }
spinbutton, entry, combobox {
  background-color: #302d2a; color: #f0ece7;
  border: 1px solid #534b44; border-radius: 6px;
}
tooltip { background-color: #191817; color: #f4ece6; border: 1px solid #d97745; }
/* Short orange pulse while Takt Engine prepares an apply operation. */
button.apply-pulse-0 { background-image: none; background-color: #d97745; color: #211813; border-color: #f1b48d; box-shadow: 0 0 4px #d97745; }
button.apply-pulse-1 { background-image: none; background-color: #e98753; color: #211813; border-color: #f5c09c; box-shadow: 0 0 8px #e98753; }
button.apply-pulse-2 { background-image: none; background-color: #f3a06c; color: #211813; border-color: #ffdbbd; box-shadow: 0 0 14px #f3a06c; }
button.apply-pulse-3 { background-image: none; background-color: #ffe0c7; color: #211813; border-color: #fff0e4; box-shadow: 0 0 18px #f3a06c; }
label.brand-pulse-0 { color: #f2a16d; }
label.brand-pulse-1 { color: #f5b286; }
label.brand-pulse-2 { color: #ffd0ad; }
label.brand-pulse-3 { color: #fff0e4; }
"""


def apply_claude_theme():
    """Apply the app's charcoal-and-warm-orange theme without changing system GTK settings."""
    provider = Gtk.CssProvider()
    provider.load_from_data(CLAUDE_DARK_CSS)
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def _format_temperature(value):
    return f"{value:.1f} °C" if value is not None else "Nicht verfügbar"


def _format_clock(value):
    return f"{value} MHz" if value is not None else "Nicht verfügbar"


class TaktEngineWindow(Gtk.Window):
    def __init__(self):
        language = load_ui_language()
        super().__init__(
            title=translate_text("Takt Engine – Raspberry Pi Taktverwaltung", language)
        )
        self.language = language
        self.set_default_size(1080, 760)
        self.set_border_width(14)
        self.connect("delete-event", self.on_close)
        self.hardware = detect_hardware()
        self.model_id = self.hardware.model_id
        self.limits = LIMITS.get(self.model_id)
        self.presets = load_presets()
        self.benchmark_stop = threading.Event()
        self.benchmark_running = False
        self.scales = {}
        self.value_labels = {}
        self.scale_bounds = {}
        self.scale_units = {}
        self.limit_labels = {}
        self._clock_gradient_colors = {}
        self._clock_gradient_targets = {}
        self._clock_gradient_animation_sources = {}
        self._clock_gradient_provider = Gtk.CssProvider()
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen, self._clock_gradient_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10,
            )
        self._loading_values = False
        self._sliders_dirty = False
        self._external_config_pending = False
        self._last_config_text = None
        self._config_values = None
        self._apply_animation_running = False
        self._apply_animation_stage = 0
        self._apply_animation_source_id = None
        self._apply_button_original_label = "Änderungen anwenden…"
        self.monitor_history = []
        self._monitor_history_limit = 60
        self._live_pulse_stage = 0
        self._tab_animation_stage = 0
        self._tab_animation_source_id = None
        self._bench_animation_stage = 0
        self._bench_animation_source_id = None

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(outer)
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_row.set_valign(Gtk.Align.START)
        outer.pack_start(header_row, False, False, 0)
        heading = Gtk.Label()
        heading.set_markup('<span size="xx-large" weight="bold">Takt Engine</span>')
        heading.set_xalign(0)
        heading.set_halign(Gtk.Align.START)
        heading_row_expand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        heading_row_expand.pack_start(heading, True, True, 0)
        header_row.pack_start(heading_row_expand, True, True, 0)
        self.heading_label = heading
        self.live_badge = Gtk.Label(label="● LIVE")
        self.live_badge.set_halign(Gtk.Align.END)
        self.live_badge.set_valign(Gtk.Align.START)
        self.live_badge.get_style_context().add_class("live-pulse-0")
        header_row.pack_end(self.live_badge, False, False, 0)
        self.nickname_label = Gtk.Label()
        self.nickname_label.set_markup('<span foreground="#ffffff" foreground_alpha="36000" size="small">Benninator</span>')
        self.nickname_label.set_halign(Gtk.Align.END)
        self.nickname_label.set_valign(Gtk.Align.START)
        self.nickname_label.set_xalign(1)
        header_row.pack_end(self.nickname_label, False, False, 0)
        self.language_button = Gtk.Button(label="EN" if self.language == "de" else "DE")
        self.language_button.set_tooltip_text(
            "Auf Englisch umschalten" if self.language == "de" else "Switch to German"
        )
        self.language_button.connect("clicked", self._toggle_language)
        header_row.pack_end(self.language_button, False, False, 0)
        self.restart_button = Gtk.Button(label="↻ Neustart…")
        self.restart_button.set_tooltip_text("Den Raspberry Pi nach Bestätigung vollständig neu starten")
        self.restart_button.get_style_context().add_class("suggested-action")
        self.restart_button.connect("clicked", self.restart_system_dialog)
        header_row.pack_end(self.restart_button, False, False, 0)
        subtitle = Gtk.Label(label="Taktprofile, Status und Stabilität für Raspberry Pi 4 / 5")
        subtitle.set_xalign(0)
        outer.pack_start(subtitle, False, False, 0)

        self.notice = Gtk.Label()
        self.notice.set_xalign(0)
        self.notice.set_line_wrap(True)
        self.notice.get_style_context().add_class("dim-label")
        outer.pack_start(self.notice, False, False, 0)
        self.safety_banner = Gtk.Label(label="Systemstatus wird geprüft …")
        self.safety_banner.set_xalign(0)
        self.safety_banner.set_line_wrap(True)
        self.safety_banner.get_style_context().add_class("safety-unknown")
        outer.pack_start(self.safety_banner, False, False, 0)

        self.notebook = Gtk.Notebook()
        outer.pack_start(self.notebook, True, True, 0)
        self._build_overclock_page()
        self._build_presets_page()
        self._build_monitor_page()
        self._build_fan_curve_page()
        self._build_benchmark_page()
        self._build_status_page()
        self._build_tools_page()
        self.notebook.connect("switch-page", self._on_tab_switched)
        self._update_capability_notice()
        self._sync_sliders_from_config(force=True)
        self._refresh_benchmark_history()
        self.refresh_status()
        self._refresh_verification_status()
        self._refresh_tuning_history()
        self._refresh_language_widgets()
        GLib.idle_add(self._maybe_prompt_trial_confirmation)
        GLib.timeout_add_seconds(1, self._language_refresh_tick)
        GLib.timeout_add_seconds(3, self.refresh_status)
        GLib.timeout_add(650, self._tick_live_badge)

    def _toggle_language(self, _button=None):
        """Switch the complete UI language without rebuilding or changing app state."""
        self.language = "en" if self.language == "de" else "de"
        try:
            save_ui_language(self.language)
        except OSError as exc:
            # Keep the language change active for this session even if the setting
            # cannot be saved (for example, a read-only home directory).
            print(f"Takt Engine: Spracheinstellung konnte nicht gespeichert werden: {exc}", file=sys.stderr)

        self.language_button.set_label("EN" if self.language == "de" else "DE")
        self.language_button.set_tooltip_text(
            "Auf Englisch umschalten" if self.language == "de" else "Switch to German"
        )
        self._refresh_language_widgets()
        return False

    def _language_refresh_tick(self):
        # Several pages show live values and asynchronous results. Translating the
        # widget tree periodically also catches text that was refreshed later.
        self._refresh_language_widgets()
        return True

    def _translate_combo_cell(self, _combo, renderer, model, iterator):
        value = model.get_value(iterator, 0)
        if isinstance(value, str):
            renderer.set_property("text", translate_text(value, self.language))

    def _refresh_language_widgets(self):
        """Translate current labels, tabs, tooltips and read-only output widgets."""
        try:
            windows = Gtk.Window.list_toplevels()
        except Exception:
            windows = [self]
        for window in windows:
            self._translate_widget_tree(window, set())

        self.set_title(
            translate_text("Takt Engine – Raspberry Pi Taktverwaltung", self.language)
        )
        if hasattr(self, "language_button"):
            self.language_button.set_label("EN" if self.language == "de" else "DE")
            self.language_button.set_tooltip_text(
                "Auf Englisch umschalten" if self.language == "de" else "Switch to German"
            )

    def _translate_widget_tree(self, widget, visited):
        if widget is None or id(widget) in visited:
            return
        visited.add(id(widget))

        if isinstance(widget, Gtk.Label):
            current = widget.get_label()
            if current:
                translated = translate_text(current, self.language)
                if widget.get_use_markup():
                    widget.set_markup(translated)
                else:
                    widget.set_text(translated)

        if isinstance(widget, Gtk.Button):
            current = widget.get_label()
            if current:
                widget.set_label(translate_text(current, self.language))

        if isinstance(widget, Gtk.Window):
            current = widget.get_title()
            if current:
                widget.set_title(translate_text(current, self.language))

        if isinstance(widget, Gtk.Entry):
            placeholder = widget.get_placeholder_text()
            if placeholder:
                widget.set_placeholder_text(translate_text(placeholder, self.language))

        if isinstance(widget, Gtk.ProgressBar):
            progress_text = widget.get_text()
            if progress_text:
                widget.set_text(translate_text(progress_text, self.language))

        if isinstance(widget, Gtk.TextView) and widget.get_name() == "takt-translatable":
            buffer = widget.get_buffer()
            start = buffer.get_start_iter()
            end = buffer.get_end_iter()
            current = buffer.get_text(start, end, True)
            if current:
                translated = translate_text(current, self.language)
                if translated != current:
                    buffer.set_text(translated)

        if isinstance(widget, Gtk.ComboBox):
            # Keep the original German model values so callbacks and saved
            # settings remain language-independent. Only the displayed cell
            # text is translated.
            for cell in widget.get_cells():
                if isinstance(cell, Gtk.CellRendererText):
                    widget.set_cell_data_func(cell, self._translate_combo_cell)
            widget.queue_draw()

        try:
            tooltip = widget.get_tooltip_text()
        except (AttributeError, TypeError):
            tooltip = None
        if tooltip:
            widget.set_tooltip_text(translate_text(tooltip, self.language))

        if isinstance(widget, Gtk.Notebook):
            for index in range(widget.get_n_pages()):
                page = widget.get_nth_page(index)
                self._translate_widget_tree(widget.get_tab_label(page), visited)

        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                self._translate_widget_tree(child, visited)

    def _make_page(self, title):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_border_width(12)
        self.notebook.append_page(page, Gtk.Label(label=title))
        return page

    def restart_system_dialog(self, _button=None):
        """Ask for explicit confirmation before rebooting the entire Raspberry Pi."""
        if self.benchmark_running:
            self.show_error("Bitte stoppe zuerst den laufenden Benchmark und warte, bis er beendet ist.")
            return

        details = (
            "Takt Engine fordert einen vollständigen Neustart des Raspberry Pi an. "
            "Offene Programme können beendet werden."
        )
        if self._sliders_dirty:
            details += (
                "\n\nAchtung: Deine aktuellen Regleränderungen wurden noch nicht angewendet. "
                "Sie werden durch den Neustart nicht in config.txt geschrieben."
            )
        pending = load_pending_apply()
        if pending and pending.get("trial_rollback") and pending.get("verification") == "reboot_pending":
            details += (
                "\n\nEin sicheres Testprofil wartet auf Prüfung. Bestätige es nach dem Neustart "
                "innerhalb von 120 Sekunden, sonst wird die vorherige Konfiguration zurückgespielt."
            )

        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="Raspberry Pi jetzt neu starten?",
        )
        dialog.format_secondary_text(details)
        dialog.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        reboot_response = Gtk.ResponseType.ACCEPT
        restart_choice = dialog.add_button("Jetzt neu starten", reboot_response)
        restart_choice.get_style_context().add_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response == reboot_response:
            self._begin_system_reboot()

    def _begin_system_reboot(self):
        self.restart_button.set_sensitive(False)
        self.restart_button.set_label("Neustart wird angefordert…")
        self.notice.set_text("Systemneustart wird angefordert. Bitte warte auf die Systemautorisierung.")
        threading.Thread(target=self._system_reboot_worker, daemon=True).start()

    def _system_reboot_worker(self):
        try:
            request_system_reboot(timeout=20)
        except (SystemActionError, OSError, subprocess.SubprocessError) as exc:
            GLib.idle_add(self._system_reboot_failed, str(exc))
            return
        GLib.idle_add(self._system_reboot_accepted)

    def _system_reboot_accepted(self):
        self.notice.set_text("Der Systemneustart wurde angenommen. Takt Engine wird beim Herunterfahren beendet.")
        self.restart_button.set_label("Neustart angefordert")
        return False

    def _system_reboot_failed(self, message):
        self.restart_button.set_sensitive(True)
        self.restart_button.set_label("↻ Neustart…")
        self.notice.set_text("Systemneustart fehlgeschlagen.")
        self.show_error("Der Raspberry Pi konnte nicht neu gestartet werden.\n\n" + message)
        return False

    def _build_overclock_page(self):
        page = self._make_page("Übertakten")
        warning = Gtk.Label(label=(
            "Achtung: Übertakten kann Abstürze, Datenverlust oder Bootprobleme verursachen. "
            "Die Profile sind keine Stabilitätsgarantie. Änderungen benötigen einen Neustart."
        ))
        warning.set_xalign(0)
        warning.set_line_wrap(True)
        page.pack_start(warning, False, False, 0)
        if self.model_id == "pi5":
            limit_note = Gtk.Label(label=(
                "Erweiterte App-Einstellbereiche: CPU bis 3.800 MHz und V3D bis 2.000 MHz. "
                "Das sind experimentelle Eingabegrenzen, keine offiziell zugesicherten stabilen Taktraten. "
                "Die dokumentierten Pi-5-Standardwerte liegen bei 2.400 MHz CPU und 960 MHz V3D. "
                "Oberhalb von 2.800/1.000 MHz erscheint vor dem Anwenden eine zusätzliche Warnung. "
                "Sehr hohe Werte können ignoriert werden, Abstürze verursachen oder den Start verhindern."
            ))
            limit_note.set_xalign(0)
            limit_note.set_line_wrap(True)
            limit_note.get_style_context().add_class("caution")
            page.pack_start(limit_note, False, False, 0)
        self._add_slider(page, "CPU-Takt (arm_freq)", "arm_freq", self.limits.arm_min if self.limits else 1500,
                         self.limits.arm_max if self.limits else 2000, self.limits.arm_default if self.limits else 1800, 50, "MHz")
        self._add_slider(page, "3D-Grafiktakt / V3D (v3d_freq)", "v3d_freq", self.limits.v3d_min if self.limits else 500,
                         self.limits.v3d_max if self.limits else 600, self.limits.v3d_default if self.limits else 500, 10, "MHz")
        if self.limits and self.limits.core_min is not None:
            self._add_slider(page, "Core-Takt (core_freq)", "core_freq", self.limits.core_min,
                             self.limits.core_max, self.limits.core_default, 10, "MHz")
        else:
            note = Gtk.Label(label="Core-Takt: separater core_freq-Regler wird für den Pi 5 nicht angeboten; V3D wird separat geregelt.")
            note.set_xalign(0)
            note.set_line_wrap(True)
            page.pack_start(note, False, False, 0)
        self._add_slider(page, "SoC-Spannungs-Offset / Undervolting (over_voltage_delta)", "over_voltage_delta",
                         self.limits.voltage_delta_min if self.limits else -25000,
                         self.limits.voltage_delta_max if self.limits else 25000, 0, 5000, "µV")
        voltage_note = Gtk.Label(label=(
            "Negative Werte senken den vom DVFS berechneten SoC-Spannungswert; das ist kein separater CPU-only-Regler. "
            "Zum Ausprobieren nur kleine Schritte von -5000 µV verwenden. Bei Rechenfehlern, Abstürzen oder Bootproblemen "
            "auf 0 µV zurückstellen. Positive Werte erhöhen Wärme und Energiebedarf. Die Spannungsregelung bleibt modellabhängig."
        ))
        voltage_note.set_xalign(0)
        voltage_note.set_line_wrap(True)
        page.pack_start(voltage_note, False, False, 0)

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        page.pack_start(button_row, False, False, 4)
        defaults_button = Gtk.Button(label="Modell-Standardwerte laden")
        defaults_button.connect("clicked", self.load_defaults)
        button_row.pack_start(defaults_button, False, False, 0)
        reload_button = Gtk.Button(label="config.txt neu einlesen")
        reload_button.connect("clicked", self.reload_config_sliders)
        button_row.pack_start(reload_button, False, False, 0)
        self.apply_button = Gtk.Button(label="Änderungen anwenden…")
        self.apply_button.get_style_context().add_class("suggested-action")
        self.apply_button.connect("clicked", self.apply_current_settings)
        button_row.pack_end(self.apply_button, False, False, 0)
        self.slider_sync_status = Gtk.Label()
        self.slider_sync_status.set_xalign(0)
        self.slider_sync_status.set_line_wrap(True)
        self.slider_sync_status.get_style_context().add_class("dim-label")
        page.pack_start(self.slider_sync_status, False, False, 0)

    def _add_slider(self, page, title, key, lower, upper, default, step, unit):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        page.pack_start(row, False, False, 2)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.pack_start(top, False, False, 0)
        label = Gtk.Label(label=title)
        label.set_xalign(0)
        top.pack_start(label, True, True, 0)
        value_label = Gtk.Label(label=f"{default} {unit}")
        top.pack_end(value_label, False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, float(lower), float(upper), float(step))
        scale.set_digits(0)
        scale.set_draw_value(False)
        scale.set_value(float(default))
        scale.connect("value-changed", self.on_scale_changed, key, unit, value_label)
        row.pack_start(scale, False, False, 0)
        bounds = Gtk.Label(label=f"App-Grenzen: {lower}–{upper} {unit}")
        bounds.set_xalign(0)
        bounds.get_style_context().add_class("dim-label")
        row.pack_start(bounds, False, False, 0)
        self.scales[key] = scale
        self.value_labels[key] = value_label
        self.scale_bounds[key] = (float(lower), float(upper), float(step))
        self.scale_units[key] = unit
        self.limit_labels[key] = bounds
        self._update_clock_zone(key, int(default))

    def _update_clock_zone(self, key, value):
        """Update the warning tooltip and smoothly blend the Pi 5 clock colors."""
        zone = clock_warning_zone(self.model_id, key, value)
        scale = self.scales.get(key)
        value_label = self.value_labels.get(key)
        if self.model_id == "pi5" and key in ("arm_freq", "v3d_freq"):
            class_name = self._clock_gradient_class(key)
            for widget in (scale, value_label):
                if widget is None:
                    continue
                context = widget.get_style_context()
                for old_class in ("clock-zone-safe", "clock-zone-caution", "clock-zone-extreme", "clock-zone-default"):
                    context.remove_class(old_class)
                context.add_class(class_name)
            self._animate_clock_gradient(key, clock_gradient_color(self.model_id, key, value))
        else:
            for widget in (scale, value_label):
                if widget is None:
                    continue
                context = widget.get_style_context()
                for old_class in ("clock-zone-safe", "clock-zone-caution", "clock-zone-extreme"):
                    context.remove_class(old_class)
                context.add_class("clock-zone-default")
        if value_label is not None:
            descriptions = {
                "safe": "Konservativer Empfehlungsbereich; keine Stabilitätsgarantie.",
                "caution": "Erhöhtes Risiko; geeignete Kühlung dringend empfohlen.",
                "extreme": "Extrembereich; Instabilität oder Bootprobleme möglich.",
                "default": "",
            }
            value_label.set_tooltip_text(descriptions[zone] or None)

    @staticmethod
    def _clock_gradient_class(key):
        return "clock-gradient-" + key.replace("_", "-")

    @staticmethod
    def _rgb_from_hex(color):
        value = color.lstrip("#")
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))

    @staticmethod
    def _hex_from_rgb(rgb):
        return "#" + "".join(f"{max(0, min(255, int(round(channel)))):02x}" for channel in rgb)

    def _animate_clock_gradient(self, key, target_hex):
        """Animate toward the current value color; repeated drag events update the target."""
        target = self._rgb_from_hex(target_hex)
        self._clock_gradient_targets[key] = target
        if key not in self._clock_gradient_colors:
            self._clock_gradient_colors[key] = target
            self._render_clock_gradient_css()
            return
        if key not in self._clock_gradient_animation_sources:
            self._clock_gradient_animation_sources[key] = GLib.timeout_add(24, self._tick_clock_gradient, key)

    def _tick_clock_gradient(self, key):
        current = self._clock_gradient_colors.get(key)
        target = self._clock_gradient_targets.get(key)
        if current is None or target is None:
            self._clock_gradient_animation_sources.pop(key, None)
            return False
        # Exponential easing keeps color movement smooth while the slider is dragged.
        next_color = tuple(old + (new - old) * 0.28 for old, new in zip(current, target))
        if max(abs(old - new) for old, new in zip(next_color, target)) < 1.25:
            next_color = target
        self._clock_gradient_colors[key] = next_color
        self._render_clock_gradient_css()
        if next_color == target:
            self._clock_gradient_animation_sources.pop(key, None)
            return False
        return True

    def _render_clock_gradient_css(self):
        """Refresh the small GTK CSS sheet used for the animated slider colors."""
        rules = []
        for key, rgb in self._clock_gradient_colors.items():
            color = self._hex_from_rgb(rgb)
            class_name = self._clock_gradient_class(key)
            rules.extend((
                f"scale.{class_name} highlight {{ background-color: {color}; border-radius: 6px; }}",
                f"scale.{class_name} slider {{ background-image: none; background-color: {color}; border: 1px solid {color}; min-width: 16px; min-height: 16px; border-radius: 9px; }}",
                f"label.{class_name} {{ color: {color}; font-weight: bold; }}",
            ))
        css = "\n".join(rules)
        try:
            self._clock_gradient_provider.load_from_data(css.encode("utf-8"))
        except Exception:
            # Keep the previous valid stylesheet if the GTK provider rejects a frame.
            return

    def on_scale_changed(self, scale, key, unit, value_label):
        value = int(round(scale.get_value()))
        self._update_clock_zone(key, value)
        if key == "over_voltage_delta":
            value_label.set_text(f"{value} µV ({value / 1_000_000:+.3f} V)")
        else:
            value_label.set_text(f"{value} {unit}")
        if not self._loading_values:
            self._sliders_dirty = not self._sliders_match_config()
            self._update_sync_status()

    def _build_presets_page(self):
        page = self._make_page("Voreinstellungen")
        note = Gtk.Label(label="Wähle ein Profil aus Standard, Leistung oder Undervolting. Es übernimmt zunächst nur Werte in die Regler; config.txt wird erst nach „Änderungen anwenden“ und deiner Bestätigung geändert.")
        note.set_xalign(0)
        note.set_line_wrap(True)
        page.pack_start(note, False, False, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        page.pack_start(scroller, True, True, 0)
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.add(listbox)
        matches = [preset for preset in self.presets if preset.get("model") == self.model_id]
        if not self.limits:
            matches = self.presets
        category_titles = {
            "standard": "Standard & Alltag",
            "performance": "Mehr Leistung",
            "undervolting": "Undervolting",
        }
        for category in ("standard", "performance", "undervolting"):
            grouped_profiles = [
                preset for preset in matches
                if preset.get("category", "performance") == category
            ]
            if not grouped_profiles:
                continue

            section_row = Gtk.ListBoxRow()
            section_row.set_selectable(False)
            section_row.set_activatable(False)
            section_label = Gtk.Label()
            section_label.set_markup(
                f"<span size='large' weight='bold'>{GLib.markup_escape_text(category_titles[category])}</span>"
            )
            section_label.set_xalign(0)
            section_label.set_margin_start(10)
            section_label.set_margin_top(10)
            section_label.set_margin_bottom(4)
            section_row.add(section_label)
            listbox.add(section_row)

            if category == "undervolting":
                info_row = Gtk.ListBoxRow()
                info_row.set_selectable(False)
                info_row.set_activatable(False)
                info_label = Gtk.Label(label=(
                    "Negative Spannungs-Offsets sind experimentell. Auch kleine Schritte können "
                    "Rechenfehler oder Abstürze verursachen. Profile einzeln testen und bei Problemen "
                    "auf 0 µV zurückstellen."
                ))
                info_label.set_xalign(0)
                info_label.set_line_wrap(True)
                info_label.set_margin_start(10)
                info_label.set_margin_end(10)
                info_label.set_margin_bottom(6)
                info_label.get_style_context().add_class("caution")
                info_row.add(info_label)
                listbox.add(info_row)

            for preset in grouped_profiles:
                row = Gtk.ListBoxRow()
                content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
                content.set_border_width(10)
                row.add(content)
                title = Gtk.Label()
                title.set_markup(f"<b>{GLib.markup_escape_text(preset['name'])}</b>")
                title.set_xalign(0)
                content.pack_start(title, False, False, 0)
                desc = Gtk.Label(label=preset["description"])
                desc.set_xalign(0)
                desc.set_line_wrap(True)
                content.pack_start(desc, False, False, 0)
                warning = Gtk.Label(label="Hinweis: " + preset["warning"])
                warning.set_xalign(0)
                warning.set_line_wrap(True)
                warning.get_style_context().add_class("dim-label")
                content.pack_start(warning, False, False, 0)
                select_button = Gtk.Button(label="Profil in Regler laden")
                select_button.set_halign(Gtk.Align.START)
                select_button.connect("clicked", self.load_preset, preset)
                content.pack_start(select_button, False, False, 0)
                listbox.add(row)
        if not matches:
            empty = Gtk.Label(label="Kein passendes Profil gefunden. Bitte unterstützten Raspberry Pi 4 oder Pi 5 verwenden.")
            empty.set_line_wrap(True)
            page.pack_start(empty, False, False, 0)

        custom_title = Gtk.Label()
        custom_title.set_markup("<b>Eigene Profile</b>")
        custom_title.set_xalign(0)
        page.pack_start(custom_title, False, False, 0)
        custom_note = Gtk.Label(label="Eigene Profile werden nur lokal für deinen Benutzer gespeichert und verändern config.txt erst nach dem Anwenden.")
        custom_note.set_xalign(0)
        custom_note.set_line_wrap(True)
        custom_note.get_style_context().add_class("dim-label")
        page.pack_start(custom_note, False, False, 0)
        self.save_profile_button = Gtk.Button(label="Aktuelle Regler als Profil speichern…")
        self.save_profile_button.set_halign(Gtk.Align.START)
        self.save_profile_button.connect("clicked", self.save_custom_profile_dialog)
        self.save_profile_button.set_sensitive(bool(self.limits))
        page.pack_start(self.save_profile_button, False, False, 0)
        profile_io = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.export_profile_button = Gtk.Button(label="Profil exportieren…")
        self.export_profile_button.connect("clicked", self.export_profile_dialog)
        profile_io.pack_start(self.export_profile_button, False, False, 0)
        self.import_profile_button = Gtk.Button(label="Profil importieren…")
        self.import_profile_button.connect("clicked", self.import_profile_dialog)
        profile_io.pack_start(self.import_profile_button, False, False, 0)
        page.pack_start(profile_io, False, False, 0)
        custom_scroller = Gtk.ScrolledWindow()
        custom_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        custom_scroller.set_min_content_height(130)
        custom_scroller.set_max_content_height(180)
        page.pack_start(custom_scroller, False, True, 0)
        self.custom_profile_list = Gtk.ListBox()
        self.custom_profile_list.set_selection_mode(Gtk.SelectionMode.NONE)
        custom_scroller.add(self.custom_profile_list)
        self._refresh_custom_profiles()

    def _refresh_custom_profiles(self):
        if not hasattr(self, "custom_profile_list"):
            return
        for child in self.custom_profile_list.get_children():
            self.custom_profile_list.remove(child)
        profiles = load_custom_profiles()
        for profile in profiles:
            row = Gtk.ListBoxRow()
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            content.set_border_width(7)
            row.add(content)
            name_label = Gtk.Label()
            name_label.set_markup(
                f"<b>{GLib.markup_escape_text(profile['name'])}</b>  "
                f"<span foreground='#b9b0a7'>({profile['model'].upper()})</span>"
            )
            name_label.set_xalign(0)
            name_label.set_line_wrap(True)
            content.pack_start(name_label, True, True, 0)
            load_button = Gtk.Button(label="Laden")
            load_button.set_sensitive(profile["model"] == self.model_id and bool(self.limits))
            load_button.connect("clicked", self.load_saved_profile, profile)
            content.pack_start(load_button, False, False, 0)
            remove_button = Gtk.Button(label="Löschen")
            remove_button.connect("clicked", self.delete_saved_profile, profile)
            content.pack_start(remove_button, False, False, 0)
            self.custom_profile_list.add(row)
        if not profiles:
            empty_row = Gtk.ListBoxRow()
            label = Gtk.Label(label="Noch keine eigenen Profile gespeichert.")
            label.set_xalign(0)
            label.get_style_context().add_class("dim-label")
            label.set_margin_start(8)
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            empty_row.add(label)
            self.custom_profile_list.add(empty_row)
        self.custom_profile_list.show_all()

    def save_custom_profile_dialog(self, _button=None):
        if not self.limits:
            self.show_error("Eigene Taktprofile können nur für einen unterstützten Raspberry Pi 4 oder Pi 5 gespeichert werden.")
            return
        dialog = Gtk.Dialog(title="Eigenes Profil speichern", transient_for=self, flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        dialog.add_button("Profil speichern", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.set_resizable(False)
        content = dialog.get_content_area()
        content.set_spacing(8)
        content.set_border_width(14)
        label = Gtk.Label(label="Name für die aktuelle Reglerauswahl (max. 40 Zeichen):")
        label.set_xalign(0)
        content.pack_start(label, False, False, 0)
        entry = Gtk.Entry()
        entry.set_max_length(40)
        entry.set_placeholder_text("z. B. Alltag – kühl")
        content.pack_start(entry, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        profile_name = entry.get_text().strip()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        try:
            values = self._current_values()
            profile = store_custom_profile(profile_name, self.model_id, values)
        except (OSError, ValueError) as exc:
            self.show_error(str(exc))
            return
        self._refresh_custom_profiles()
        self._append_bench_log(f"Eigenes Profil gespeichert: {profile['name']}")
        self.show_info(f"Profil „{profile['name']}“ wurde lokal gespeichert. Es wurde noch nichts in config.txt geändert.")

    def load_saved_profile(self, _button, profile):
        try:
            if profile["model"] != self.model_id:
                raise ValidationError("Dieses Profil passt nicht zum erkannten Raspberry-Pi-Modell.")
            values = validate_values(profile["model"], profile["values"])
            self._load_values(values)
            self.notebook.set_current_page(0)
            self._append_bench_log(f"Eigenes Profil geladen: {profile['name']}")
        except (ValueError, KeyError) as exc:
            self.show_error(str(exc))

    def delete_saved_profile(self, _button, profile):
        dialog = Gtk.MessageDialog(
            transient_for=self, flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE,
            text=f"Eigenes Profil „{profile['name']}“ löschen?",
        )
        dialog.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        dialog.add_button("Löschen", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        try:
            if not delete_stored_custom_profile(profile["id"]):
                self.show_error("Das Profil wurde nicht gefunden; die Profilliste wurde möglicherweise in einer anderen Sitzung geändert.")
            self._refresh_custom_profiles()
        except OSError as exc:
            self.show_error(f"Profil konnte nicht gelöscht werden: {exc}")


    def export_profile_dialog(self, _button=None):
        profiles = load_custom_profiles()
        if not profiles:
            self.show_info("Es gibt noch keine eigenen Profile zum Exportieren.")
            return
        dialog = Gtk.Dialog(title="Profil exportieren", transient_for=self, flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        dialog.add_button("Weiter…", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(8)
        content.set_border_width(12)
        content.pack_start(Gtk.Label(label="Zu exportierendes Profil auswählen:"), False, False, 0)
        combo = Gtk.ComboBoxText()
        for profile in profiles:
            combo.append(profile["id"], f"{profile['name']} ({profile['model'].upper()})")
        combo.set_active_id(profiles[0]["id"])
        content.pack_start(combo, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        selected_id = combo.get_active_id()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not selected_id:
            return
        selected = next((item for item in profiles if item["id"] == selected_id), None)
        if selected is None:
            self.show_error("Profil wurde zwischenzeitlich entfernt. Bitte erneut versuchen.")
            return
        chooser = Gtk.FileChooserDialog(
            title="Profil als JSON speichern", parent=self, action=Gtk.FileChooserAction.SAVE,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK),
        )
        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_name(f"takt-engine-{selected['model']}-{selected['name'].lower().replace(' ', '-')}.json")
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Takt-Engine-Profil (*.json)")
        file_filter.add_pattern("*.json")
        chooser.add_filter(file_filter)
        response = chooser.run()
        filename = chooser.get_filename() if response == Gtk.ResponseType.OK else None
        chooser.destroy()
        if not filename:
            return
        try:
            target = Path(filename)
            if target.suffix.lower() != ".json":
                target = target.with_suffix(".json")
            export_custom_profile(selected, target)
            self.show_info(f"Profil exportiert:\n{target}\n\nBeim Import werden Modell und Grenzwerte erneut geprüft.")
        except (OSError, ValueError) as exc:
            self.show_error(f"Profil konnte nicht exportiert werden: {exc}")

    def import_profile_dialog(self, _button=None):
        if not self.model_id or not self.limits:
            self.show_error("Import ist nur für einen unterstützten Raspberry Pi 4 oder Pi 5 möglich.")
            return
        chooser = Gtk.FileChooserDialog(
            title="Takt-Engine-Profil importieren", parent=self, action=Gtk.FileChooserAction.OPEN,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK),
        )
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Takt-Engine-Profil (*.json)")
        file_filter.add_pattern("*.json")
        chooser.add_filter(file_filter)
        response = chooser.run()
        filename = chooser.get_filename() if response == Gtk.ResponseType.OK else None
        chooser.destroy()
        if not filename:
            return
        try:
            profile = import_custom_profile(Path(filename), self.model_id)
            self._refresh_custom_profiles()
            self.show_info(
                f"Profil „{profile['name']}“ wurde importiert.\n\n"
                "Es wurde noch nichts in config.txt geändert. Lade es zuerst in die Regler und prüfe die Vorschau."
            )
        except (OSError, ValueError) as exc:
            self.show_error(f"Profil wurde nicht importiert: {exc}")

    def _build_monitor_page(self):
        page = self._make_page("Live-Monitor")
        intro = Gtk.Label(label="Live-Telemetrie zeigt den tatsächlich gemessenen Zustand. Werte aus config.txt sind nur Sollwerte; DVFS und Last können den realen Takt verändern.")
        intro.set_xalign(0)
        intro.set_line_wrap(True)
        page.pack_start(intro, False, False, 0)
        self.monitor_summary = Gtk.Label(label="Sammle erste Messwerte …")
        self.monitor_summary.set_xalign(0)
        self.monitor_summary.set_line_wrap(True)
        self.monitor_summary.get_style_context().add_class("dim-label")
        page.pack_start(self.monitor_summary, False, False, 0)
        self.monitor_chart = Gtk.DrawingArea()
        self.monitor_chart.set_size_request(800, 410)
        self.monitor_chart.connect("draw", self._draw_monitor_chart)
        page.pack_start(self.monitor_chart, True, True, 0)
        self.monitor_legend = Gtk.Label(label="Orange: Temperatur · Hellblau: CPU-Takt · Grün: V3D-Takt · Violett: CPU-Last · Messpunkte alle ca. 3 Sekunden")
        self.monitor_legend.set_xalign(0)
        self.monitor_legend.get_style_context().add_class("dim-label")
        page.pack_start(self.monitor_legend, False, False, 0)

    def _build_fan_curve_page(self):
        page = self._make_page("Lüfterkurve")
        self.fan_curve_row_widgets = []
        self.fan_animation_angle = 0.0
        self.fan_current_percent = 0
        self.fan_current_rpm = None
        self.fan_last_temperature = None
        self._fan_save_animation_stage = 0
        self._fan_save_animation_source_id = None
        self._fan_slider_syncing = False

        if self.model_id != "pi5" or not self.hardware.config_path:
            note = Gtk.Label(label=(
                "Die native Lüfterkurve benötigt einen Raspberry Pi 5 mit einer vorhandenen "
                "config.txt. Die vier PWM-Stufen werden direkt von der Pi-Firmware verwaltet."
            ))
            note.set_xalign(0)
            note.set_line_wrap(True)
            page.pack_start(note, False, False, 0)
            return

        intro = Gtk.Label(label=(
            "Die Raspberry-Pi-5-Firmware unterstützt vier Temperaturstufen. "
            "Takt Engine schreibt diese Werte in config.txt; nach dem Neustart "
            "regelt die Firmware den Lüfter automatisch – auch wenn die App geschlossen ist."
        ))
        intro.set_xalign(0)
        intro.set_line_wrap(True)
        page.pack_start(intro, False, False, 0)

        self.fan_curve_runtime_label = Gtk.Label(label="Lüfter-Telemetrie wird gelesen …")
        self.fan_curve_runtime_label.set_xalign(0)
        self.fan_curve_runtime_label.set_line_wrap(True)
        self.fan_curve_runtime_label.get_style_context().add_class("dim-label")
        page.pack_start(self.fan_curve_runtime_label, False, False, 0)

        visual_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.fan_animation_area = Gtk.DrawingArea()
        self.fan_animation_area.set_size_request(72, 72)
        self.fan_animation_area.connect("draw", self._draw_fan_animation)
        visual_row.pack_start(self.fan_animation_area, False, False, 0)

        visual_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        visual_text.set_valign(Gtk.Align.CENTER)
        visual_text.pack_start(
            Gtk.Label(label="Lüfterleistung · Stufe auswählen und Balken ziehen"),
            False, False, 0,
        )
        self.fan_stage_combo = Gtk.ComboBoxText()
        self.fan_stage_combo.connect("changed", self._on_fan_stage_selected)
        visual_text.pack_start(self.fan_stage_combo, False, False, 0)

        self.fan_live_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, MIN_FAN_SPEED_PERCENT, 100, 1
        )
        self.fan_live_scale.set_digits(0)
        self.fan_live_scale.set_draw_value(True)
        self.fan_live_scale.set_value(29)
        self.fan_live_scale.set_hexpand(True)
        self.fan_live_scale.set_tooltip_text(
            "Stellt die PWM-Leistung der ausgewählten Temperaturstufe ein. "
            "Danach die Kurve speichern und den Raspberry Pi neu starten."
        )
        self.fan_live_scale.connect("value-changed", self._on_fan_stage_speed_changed)
        visual_text.pack_start(self.fan_live_scale, False, False, 0)

        self.fan_live_target_label = Gtk.Label(label="Zielwert Stufe 1: 29 %")
        self.fan_live_target_label.set_xalign(0)
        self.fan_live_target_label.get_style_context().add_class("dim-label")
        visual_text.pack_start(self.fan_live_target_label, False, False, 0)

        self.fan_live_actual_label = Gtk.Label(label="Istwert: PWM/RPM wird gelesen …")
        self.fan_live_actual_label.set_xalign(0)
        self.fan_live_actual_label.get_style_context().add_class("dim-label")
        visual_text.pack_start(self.fan_live_actual_label, False, False, 0)
        visual_row.pack_start(visual_text, True, True, 0)
        page.pack_start(visual_row, False, False, 4)

        chart = Gtk.DrawingArea()
        chart.set_size_request(600, 160)
        chart.connect("draw", self._draw_fan_curve_chart)
        self.fan_curve_chart = chart
        page.pack_start(chart, False, False, 4)

        safety_note = Gtk.Label(label=(
            "Schutzkurve: Start spätestens bei 50 °C, mindestens 49 % bei 60 °C, "
            "69 % bei 67,5 °C und volle Leistung bei 75 °C. Die Stufen müssen "
            "temperaturabhängig aufsteigend bleiben. Die Firmware behält ihre eigene "
            "thermische Steuerung und Hysterese."
        ))
        safety_note.set_xalign(0)
        safety_note.set_line_wrap(True)
        safety_note.get_style_context().add_class("caution")
        page.pack_start(safety_note, False, False, 0)

        self.fan_curve_grid = Gtk.Grid()
        self.fan_curve_grid.set_column_spacing(18)
        self.fan_curve_grid.set_row_spacing(5)
        self.fan_curve_grid.set_hexpand(False)
        row_scroll = Gtk.ScrolledWindow()
        row_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        row_scroll.set_min_content_height(175)
        row_scroll.set_max_content_height(240)
        row_scroll.add(self.fan_curve_grid)
        page.pack_start(row_scroll, True, True, 0)

        hysteresis_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hysteresis_label = Gtk.Label(label="Hysterese (°C):")
        hysteresis_label.set_xalign(0)
        hysteresis_row.pack_start(hysteresis_label, False, False, 0)
        self.fan_hysteresis_spin = Gtk.SpinButton.new_with_range(1.0, 10.0, 0.5)
        self.fan_hysteresis_spin.set_digits(1)
        self.fan_hysteresis_spin.set_value(DEFAULT_HYSTERESIS_C)
        self.fan_hysteresis_spin.connect("value-changed", self._on_fan_curve_changed)
        hysteresis_row.pack_start(self.fan_hysteresis_spin, False, False, 0)
        page.pack_start(hysteresis_row, False, False, 2)

        curve_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reset_button = Gtk.Button(label="Standardkurve laden")
        reset_button.connect("clicked", self.reset_fan_curve)
        curve_buttons.pack_start(reset_button, False, False, 0)
        read_button = Gtk.Button(label="Firmwarekurve aus config.txt laden")
        read_button.connect("clicked", self.load_fan_curve_from_config)
        curve_buttons.pack_start(read_button, False, False, 0)
        self.fan_curve_apply_button = Gtk.Button(label="Kurve speichern…")
        self.fan_curve_apply_button.get_style_context().add_class("suggested-action")
        self.fan_curve_apply_button.connect("clicked", self.apply_fan_curve_dialog)
        curve_buttons.pack_start(self.fan_curve_apply_button, False, False, 0)
        page.pack_start(curve_buttons, False, False, 3)

        self.fan_curve_status_label = Gtk.Label(label="Firmwarekurve wird geladen …")
        self.fan_curve_status_label.set_xalign(0)
        self.fan_curve_status_label.set_line_wrap(True)
        self.fan_curve_status_label.get_style_context().add_class("dim-label")
        page.pack_start(self.fan_curve_status_label, False, False, 0)

        self._set_fan_curve_rows(list(DEFAULT_FAN_CURVE), animate=False)
        self.load_fan_curve_from_config(announce=False)
        self._update_fan_hwmon_status()
        self._fan_animation_source_id = GLib.timeout_add(50, self._tick_fan_animation)

    def _set_fan_curve_rows(self, points, animate=True):
        for child in self.fan_curve_grid.get_children():
            self.fan_curve_grid.remove(child)
        self.fan_curve_row_widgets = []

        for column, heading in enumerate(("Stufe", "Temperatur (°C)", "Lüfterleistung (%)")):
            label = Gtk.Label(label=heading)
            label.set_xalign(0)
            label.set_markup(f"<b>{heading}</b>")
            self.fan_curve_grid.attach(label, column, 0, 1, 1)

        for index, point in enumerate(points):
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
            stage_label = Gtk.Label(label=f"Stufe {index + 1}")
            stage_label.set_xalign(0)
            stage_label.set_size_request(54, -1)
            temperature = Gtk.SpinButton.new_with_range(40.0, 75.0, 0.5)
            temperature.set_digits(1)
            temperature.set_value(point["temperature_c"])
            temperature.set_width_chars(6)
            speed = Gtk.SpinButton.new_with_range(MIN_FAN_SPEED_PERCENT, 100, 1)
            speed.set_digits(0)
            speed.set_value(point["speed_percent"])
            speed.set_width_chars(5)
            temperature.connect("value-changed", self._on_fan_curve_changed)
            speed.connect("value-changed", self._on_fan_curve_changed)
            row_box.pack_start(stage_label, False, False, 0)
            row_box.pack_start(temperature, False, False, 0)
            row_box.pack_start(speed, False, False, 0)

            reveal = Gtk.Revealer()
            reveal.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
            reveal.set_transition_duration(220 if animate else 0)
            reveal.add(row_box)
            self.fan_curve_grid.attach(reveal, 0, index + 1, 3, 1)
            self.fan_curve_row_widgets.append({
                "temperature": temperature,
                "speed": speed,
                "revealer": reveal,
            })
            reveal.show_all()
            reveal.set_reveal_child(True)

        self.fan_curve_grid.show_all()
        if hasattr(self, "fan_curve_chart"):
            self.fan_curve_chart.queue_draw()
        self._refresh_fan_stage_control()

    def _refresh_fan_stage_control(self):
        if not hasattr(self, "fan_stage_combo") or not self.fan_curve_row_widgets:
            return
        try:
            selected = self.fan_stage_combo.get_active()
        except Exception:
            selected = 0
        if selected < 0 or selected >= len(self.fan_curve_row_widgets):
            selected = 0

        self._fan_slider_syncing = True
        try:
            self.fan_stage_combo.remove_all()
            for index, row in enumerate(self.fan_curve_row_widgets):
                temperature = row["temperature"].get_value()
                self.fan_stage_combo.append_text(
                    f"Stufe {index + 1} · ab {temperature:.1f} °C"
                )
            self.fan_stage_combo.set_active(selected)
            speed = self.fan_curve_row_widgets[selected]["speed"].get_value_as_int()
            self.fan_live_scale.set_value(speed)
        finally:
            self._fan_slider_syncing = False
        self.fan_live_target_label.set_text(
            f"Zielwert Stufe {selected + 1}: "
            f"{self.fan_curve_row_widgets[selected]['speed'].get_value_as_int()} %"
        )

    def _on_fan_stage_selected(self, combo):
        if getattr(self, "_fan_slider_syncing", False):
            return
        index = combo.get_active()
        if 0 <= index < len(self.fan_curve_row_widgets):
            self._fan_slider_syncing = True
            try:
                self.fan_live_scale.set_value(
                    self.fan_curve_row_widgets[index]["speed"].get_value()
                )
            finally:
                self._fan_slider_syncing = False
            self.fan_live_target_label.set_text(
                f"Zielwert Stufe {index + 1}: "
                f"{self.fan_curve_row_widgets[index]['speed'].get_value_as_int()} %"
            )

    def _on_fan_stage_speed_changed(self, scale):
        if getattr(self, "_fan_slider_syncing", False):
            return
        index = self.fan_stage_combo.get_active()
        if not 0 <= index < len(self.fan_curve_row_widgets):
            return
        value = int(round(scale.get_value()))
        self._fan_slider_syncing = True
        try:
            self.fan_curve_row_widgets[index]["speed"].set_value(value)
        finally:
            self._fan_slider_syncing = False
        self.fan_live_target_label.set_text(f"Zielwert Stufe {index + 1}: {value} %")

    def _current_fan_curve_values(self):
        points = [
            {
                "temperature_c": row["temperature"].get_value(),
                "speed_percent": row["speed"].get_value_as_int(),
            }
            for row in self.fan_curve_row_widgets
        ]
        return validate_fan_curve(points, self.fan_hysteresis_spin.get_value())

    def reset_fan_curve(self, _button=None):
        self._set_fan_curve_rows(list(DEFAULT_FAN_CURVE), animate=True)
        self.fan_hysteresis_spin.set_value(DEFAULT_HYSTERESIS_C)
        self.fan_curve_status_label.set_text(
            "Vierstufige Standardkurve geladen. Speichere sie und starte den Pi neu, damit sie aktiv wird."
        )

    def load_fan_curve_from_config(self, _button=None, announce=True):
        try:
            config_text = ""
            if self.hardware.config_path and self.hardware.config_path.is_file():
                config_text = read_config(self.hardware.config_path)
            if "fan_temp" in config_text:
                curve = parse_fan_curve_config(config_text)
                label = "Firmware-Lüfterkurve aus config.txt geladen."
            else:
                curve = validate_fan_curve(DEFAULT_FAN_CURVE, DEFAULT_HYSTERESIS_C)
                label = "Keine eigene Firmwarekurve gefunden. Standardkurve geladen."
            self._set_fan_curve_rows(curve["points"], animate=True)
            self.fan_hysteresis_spin.set_value(curve["hysteresis_c"])
            self.fan_curve_status_label.set_text(label)
            if announce:
                self.show_info(label)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            if announce:
                self.show_error(f"Firmwarekurve konnte nicht gelesen werden: {exc}")
            else:
                self.fan_curve_status_label.set_text(f"Firmwarekurve konnte nicht gelesen werden: {exc}")

    def apply_fan_curve_dialog(self, _button=None):
        if self.model_id != "pi5" or not self.hardware.config_path:
            self.show_error("Die native Lüfterkurve ist nur auf einem erkannten Raspberry Pi 5 mit config.txt verfügbar.")
            return
        if self.benchmark_running:
            self.show_error("Bitte stoppe zuerst den laufenden Benchmark.")
            return
        try:
            curve = self._current_fan_curve_values()
        except ValueError as exc:
            self.show_error(str(exc))
            return

        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="Firmware-Lüfterkurve speichern?",
        )
        dialog.format_secondary_text(
            "Takt Engine erstellt zuerst eine Sicherung und schreibt die vier nativen "
            "fan_temp-Stufen in config.txt. Danach übernimmt die Raspberry-Pi-Firmware "
            "die Lüftersteuerung. Die Änderung wird erst nach einem Neustart aktiv. "
            "Der alte konkurrierende Takt-Engine-PWM-Dienst wird deaktiviert."
        )
        dialog.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        dialog.add_button("Speichern", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return

        self.fan_curve_apply_button.set_sensitive(False)
        self._start_fan_save_animation()
        try:
            backup, result = apply_fan_curve(
                self.hardware.config_path, curve["points"], curve["hysteresis_c"]
            )
            self.fan_curve_status_label.set_text(
                "Firmwarekurve in config.txt gespeichert · Neustart erforderlich."
            )
            self.show_info(
                (result.stdout or "Firmware-Lüfterkurve gespeichert.").strip()
                + f"\n\nSicherung: {backup}\n\nBitte den Raspberry Pi neu starten."
            )
            self._fan_status_pulse()
        except (OSError, RuntimeError, ValueError) as exc:
            self.show_error(str(exc))
        finally:
            self.fan_curve_apply_button.set_sensitive(True)
            self._stop_fan_save_animation()

    def _start_fan_save_animation(self):
        self._fan_save_animation_stage = 0
        if self._fan_save_animation_source_id is not None:
            GLib.source_remove(self._fan_save_animation_source_id)
        self._fan_save_animation_source_id = GLib.timeout_add(90, self._tick_fan_save_animation)

    def _tick_fan_save_animation(self):
        phases = (0, 1, 2, 1)
        context = self.fan_curve_apply_button.get_style_context()
        for name in ("apply-pulse-0", "apply-pulse-1", "apply-pulse-2", "apply-pulse-3"):
            context.remove_class(name)
        context.add_class(f"apply-pulse-{phases[self._fan_save_animation_stage % len(phases)]}")
        self._fan_save_animation_stage += 1
        return self._fan_save_animation_stage < 12

    def _stop_fan_save_animation(self):
        if self._fan_save_animation_source_id is not None:
            GLib.source_remove(self._fan_save_animation_source_id)
            self._fan_save_animation_source_id = None
        if hasattr(self, "fan_curve_apply_button"):
            context = self.fan_curve_apply_button.get_style_context()
            for name in ("apply-pulse-0", "apply-pulse-1", "apply-pulse-2", "apply-pulse-3"):
                context.remove_class(name)

    def _fan_status_pulse(self):
        if not hasattr(self, "fan_curve_status_label"):
            return
        context = self.fan_curve_status_label.get_style_context()
        context.add_class("safety-ok")
        GLib.timeout_add(900, lambda: (context.remove_class("safety-ok"), False)[1])

    def _on_fan_curve_changed(self, _widget=None):
        if hasattr(self, "fan_curve_chart"):
            self.fan_curve_chart.queue_draw()
        try:
            curve = self._current_fan_curve_values()
        except ValueError as exc:
            self.fan_curve_status_label.set_text(
                "Kurve noch nicht gültig – prüfe Reihenfolge, Temperaturen und Drehzahlen. "
                + str(exc)
            )
            return
        self.fan_curve_status_label.set_text(
            "4 Firmware-Stufen · Änderungen noch nicht gespeichert."
        )
        if not getattr(self, "_fan_slider_syncing", False):
            self._refresh_fan_stage_control()

    def _draw_fan_curve_chart(self, widget, cr):
        width = max(1, widget.get_allocated_width())
        height = max(1, widget.get_allocated_height())
        cr.set_source_rgb(0.125, 0.122, 0.114)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        left, right, top, bottom = 42, width - 18, 18, height - 30
        if right <= left or bottom <= top:
            return False
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        for percent in (0, 25, 50, 75, 100):
            y = bottom - (bottom - top) * percent / 100
            cr.set_source_rgb(0.36, 0.34, 0.31)
            cr.move_to(left, y)
            cr.line_to(right, y)
            cr.stroke()
            cr.set_source_rgb(0.72, 0.68, 0.63)
            cr.move_to(5, y + 4)
            cr.show_text(str(percent))
        for temp in (40, 50, 60, 70, 80):
            x = left + (right - left) * (temp - 40) / 40
            cr.set_source_rgb(0.36, 0.34, 0.31)
            cr.move_to(x, top)
            cr.line_to(x, bottom)
            cr.stroke()
            cr.set_source_rgb(0.72, 0.68, 0.63)
            cr.move_to(x - 8, height - 8)
            cr.show_text(str(temp))
        try:
            points = self._current_fan_curve_values()["points"]
        except (ValueError, AttributeError):
            return False
        cr.set_source_rgb(0.91, 0.49, 0.28)
        cr.set_line_width(2.5)
        for index, point in enumerate(points):
            x = left + (right - left) * (point["temperature_c"] - 40) / 40
            y = bottom - (bottom - top) * point["speed_percent"] / 100
            if index == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()
        for point in points:
            x = left + (right - left) * (point["temperature_c"] - 40) / 40
            y = bottom - (bottom - top) * point["speed_percent"] / 100
            cr.arc(x, y, 4.5, 0, 6.283185307)
            cr.set_source_rgb(0.98, 0.72, 0.51)
            cr.fill()
            cr.set_source_rgb(0.91, 0.49, 0.28)
        return False

    def _draw_fan_animation(self, widget, cr):
        width = max(1, widget.get_allocated_width())
        height = max(1, widget.get_allocated_height())
        cx, cy = width / 2, height / 2
        cr.save()
        cr.translate(cx, cy)
        cr.rotate(self.fan_animation_angle)
        cr.set_source_rgb(0.86, 0.43, 0.24)
        for _index in range(7):
            cr.move_to(0, -5)
            cr.curve_to(9, -13, 15, -23, 5, -28)
            cr.curve_to(-3, -32, -8, -20, -5, -8)
            cr.close_path()
            cr.fill()
            cr.rotate(0.897597901)
        cr.set_source_rgb(0.96, 0.72, 0.52)
        cr.arc(0, 0, 6, 0, 6.283185307)
        cr.fill()
        cr.restore()
        return False

    def _tick_fan_animation(self):
        if not self.get_visible():
            return True
        speed = max(0, min(100, self.fan_current_percent))
        if speed > 0:
            self.fan_animation_angle = (self.fan_animation_angle + 0.025 + speed * 0.0025) % 6.283185307
        if hasattr(self, "fan_animation_area"):
            self.fan_animation_area.queue_draw()
        return True

    def _update_fan_hwmon_status(self):
        if not hasattr(self, "fan_curve_runtime_label"):
            return
        state = read_hwmon_fan_state()
        temperature = (
            f"{self.fan_last_temperature:.1f} °C"
            if self.fan_last_temperature is not None else "nicht verfügbar"
        )
        # Telemetry is optional. The firmware curve can still be edited and
        # saved even when a kernel build does not expose the hwmon RPM files.
        self.fan_curve_apply_button.set_sensitive(
            bool(self.hardware.config_path and self.hardware.config_path.is_file())
        )
        self.fan_live_scale.set_sensitive(True)
        if state is None:
            self.fan_current_percent = 0
            self.fan_current_rpm = None
            self.fan_curve_runtime_label.set_text(
                f"SoC: {temperature} · Lüfter-PWM/RPM-Telemetrie nicht verfügbar. "
                "Die native Firmwarekurve kann trotzdem gespeichert werden."
            )
            self.fan_live_actual_label.set_text("Istwert: PWM/RPM nicht verfügbar")
            return

        self.fan_current_percent = state["speed_percent"]
        self.fan_current_rpm = state["rpm"]
        percent_text = f"{state['speed_percent']} %"
        rpm_text = f"{state['rpm']} RPM" if state["rpm"] is not None else "RPM nicht verfügbar"
        self.fan_curve_runtime_label.set_text(
            f"SoC: {temperature} · aktueller PWM-Wert: {percent_text} · Drehzahl: {rpm_text}"
        )
        self.fan_live_actual_label.set_text(
            f"Istwert: {percent_text} · {rpm_text}"
        )

    def _draw_monitor_chart(self, widget, cr):
        width = max(1, widget.get_allocated_width())
        height = max(1, widget.get_allocated_height())
        cr.set_source_rgb(0.125, 0.122, 0.114)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        left, right, top, bottom = 66, width - 16, 18, height - 20
        if right <= left + 30 or bottom <= top + 30:
            return False
        panels = [
            ("Temperatur °C", "temperature_c", 30.0, 90.0, (0.91, 0.48, 0.28)),
            ("CPU-Takt MHz", "arm_clock_mhz", 500.0, 3000.0, (0.64, 0.77, 0.94)),
            ("V3D-Takt MHz", "v3d_clock_mhz", 0.0, 1200.0, (0.63, 0.80, 0.62)),
            ("CPU-Last %", "cpu_usage_percent", 0.0, 100.0, (0.80, 0.67, 0.87)),
            ("Lüfter RPM", "fan_rpm", 0.0, 6000.0, (0.91, 0.75, 0.42)),
        ]
        panel_height = (bottom - top) / len(panels)
        points = self.monitor_history
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(11)
        for index, (label, key, minimum, maximum, color) in enumerate(panels):
            y0 = top + index * panel_height
            y1 = y0 + panel_height - 7
            cr.set_source_rgb(0.40, 0.38, 0.35)
            for gridline in range(3):
                y = y0 + 18 + (panel_height - 30) * gridline / 2
                cr.move_to(left, y)
                cr.line_to(right, y)
            cr.set_line_width(0.6)
            cr.stroke()
            cr.set_source_rgb(*color)
            cr.move_to(8, y0 + 14)
            cr.show_text(label)
            valid = [(i, record.get(key)) for i, record in enumerate(points) if isinstance(record.get(key), (int, float))]
            if len(valid) < 2:
                cr.set_source_rgb(0.70, 0.67, 0.63)
                cr.move_to(left + 8, y0 + panel_height / 2)
                cr.show_text("Messwerte werden gesammelt …")
                continue
            cr.set_source_rgb(*color)
            cr.set_line_width(2.0)
            for line_index, (sample_index, value) in enumerate(valid):
                x = left + (right - left) * sample_index / max(1, len(points) - 1)
                clamped = max(minimum, min(maximum, float(value)))
                y = y1 - 8 - (clamped - minimum) / (maximum - minimum) * max(1, panel_height - 34)
                if line_index == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.stroke()
            latest_value = valid[-1][1]
            latest_text = f"{float(latest_value):.1f}" if key == "temperature_c" else f"{int(latest_value)}"
            cr.set_source_rgb(*color)
            cr.move_to(right - 54, y0 + 14)
            cr.show_text(latest_text)
        return False

    def _tick_live_badge(self):
        if not self.get_visible():
            return True
        phases = (0, 1, 2, 1)
        context = self.live_badge.get_style_context()
        for class_name in context.list_classes():
            if class_name.startswith("live-pulse-"):
                context.remove_class(class_name)
        context.add_class(f"live-pulse-{phases[self._live_pulse_stage % len(phases)]}")
        self._live_pulse_stage += 1
        return True

    def _on_tab_switched(self, _notebook, _page, _page_num):
        if self._apply_animation_running:
            return
        if self._tab_animation_source_id is not None:
            GLib.source_remove(self._tab_animation_source_id)
            self._tab_animation_source_id = None
        self._tab_animation_stage = 0
        self._tab_animation_source_id = GLib.timeout_add(90, self._tick_tab_animation)

    def _tick_tab_animation(self):
        phases = (1, 2, 3, 1, 0)
        context = self.heading_label.get_style_context()
        for class_name in context.list_classes():
            if class_name.startswith("brand-pulse-"):
                context.remove_class(class_name)
        context.add_class(f"brand-pulse-{phases[self._tab_animation_stage]}")
        self._tab_animation_stage += 1
        if self._tab_animation_stage >= len(phases):
            context.remove_class(f"brand-pulse-{phases[-1]}")
            self._tab_animation_source_id = None
            return False
        return True

    def _build_benchmark_page(self):
        page = self._make_page("Benchmark")
        intro = Gtk.Label(label="CPU- und Speicherlast mit Live-Temperatur-/Throttling-Prüfung. Der Test erzeugt Last und kann das Gerät erwärmen; keine anderen wichtigen Aufgaben parallel ausführen.")
        intro.set_xalign(0)
        intro.set_line_wrap(True)
        page.pack_start(intro, False, False, 0)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        page.pack_start(controls, False, False, 0)
        controls.pack_start(Gtk.Label(label="Dauer (Sekunden):"), False, False, 0)
        self.duration_spin = Gtk.SpinButton.new_with_range(10, 600, 10)
        self.duration_spin.set_value(60)
        controls.pack_start(self.duration_spin, False, False, 0)
        controls.pack_start(Gtk.Label(label="CPU-Threads:"), False, False, 0)
        cpu_count = os.cpu_count() or 4
        self.threads_spin = Gtk.SpinButton.new_with_range(1, min(64, cpu_count * 2), 1)
        self.threads_spin.set_value(min(4, cpu_count))
        controls.pack_start(self.threads_spin, False, False, 0)
        self.bench_start = Gtk.Button(label="Benchmark starten")
        self.bench_start.connect("clicked", self.start_benchmark)
        controls.pack_start(self.bench_start, False, False, 0)
        self.bench_stop = Gtk.Button(label="Stoppen")
        self.bench_stop.set_sensitive(False)
        self.bench_stop.connect("clicked", self.stop_benchmark)
        controls.pack_start(self.bench_stop, False, False, 0)
        self.bench_progress = Gtk.ProgressBar()
        self.bench_progress.set_show_text(True)
        page.pack_start(self.bench_progress, False, False, 0)
        self.bench_status = Gtk.Label(label="Bereit. Für den Start wird stress-ng benötigt.")
        self.bench_status.set_xalign(0)
        self.bench_status.set_line_wrap(True)
        page.pack_start(self.bench_status, False, False, 0)
        self.bench_history_label = Gtk.Label(label="Noch keine gespeicherten Benchmarks.")
        self.bench_history_label.set_xalign(0)
        self.bench_history_label.set_line_wrap(True)
        self.bench_history_label.get_style_context().add_class("dim-label")
        page.pack_start(self.bench_history_label, False, False, 0)
        self.bench_log = Gtk.TextView()
        self.bench_log.set_name("takt-translatable")
        self.bench_log.set_editable(False)
        self.bench_log.set_cursor_visible(False)
        self.bench_log.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(160)
        scroll.add(self.bench_log)
        page.pack_start(scroll, True, True, 0)

    def _build_status_page(self):
        page = self._make_page("Status")
        self.status_view = Gtk.TextView()
        self.status_view.set_name("takt-translatable")
        self.status_view.set_editable(False)
        self.status_view.set_cursor_visible(False)
        self.status_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        page.pack_start(self.status_view, True, True, 0)
        button = Gtk.Button(label="Status aktualisieren")
        button.set_halign(Gtk.Align.START)
        button.connect("clicked", lambda _b: self.refresh_status())
        page.pack_start(button, False, False, 0)
        status_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        page.pack_start(status_buttons, False, False, 0)
        self.restore_button = Gtk.Button(label="Sicherung zurückspielen…")
        self.restore_button.set_halign(Gtk.Align.START)
        self.restore_button.connect("clicked", self.restore_backup_dialog)
        status_buttons.pack_start(self.restore_button, False, False, 0)
        self.export_report_button = Gtk.Button(label="Diagnosebericht exportieren…")
        self.export_report_button.set_halign(Gtk.Align.START)
        self.export_report_button.connect("clicked", self.export_diagnostic_report)
        status_buttons.pack_start(self.export_report_button, False, False, 0)


    def _build_tools_page(self):
        page = self._make_page("Werkzeuge")
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        page.pack_start(scroller, True, True, 0)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_border_width(4)
        scroller.add(body)

        intro = Gtk.Label(label=(
            "Diagnose- und Tuning-Werkzeuge. Analysen lesen nur; Änderungen an config.txt werden weiterhin "
            "ausschließlich über „Änderungen anwenden…“ und die Sicherheitsbestätigung geschrieben."
        ))
        intro.set_xalign(0)
        intro.set_line_wrap(True)
        body.pack_start(intro, False, False, 0)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, callback in (
            ("Config prüfen", self.run_config_inspector),
            ("Hardware/Firmware", self.run_compatibility_check),
            ("System-Selbsttest", self.run_system_self_test),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            action_row.pack_start(button, False, False, 0)
        body.pack_start(action_row, False, False, 0)
        self.tools_output = Gtk.TextView()
        self.tools_output.set_name("takt-translatable")
        self.tools_output.set_editable(False)
        self.tools_output.set_cursor_visible(False)
        self.tools_output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.tools_output.set_monospace(True)
        report_scroll = Gtk.ScrolledWindow()
        report_scroll.set_min_content_height(180)
        report_scroll.set_max_content_height(270)
        report_scroll.add(self.tools_output)
        body.pack_start(report_scroll, False, True, 0)

        heading = Gtk.Label()
        heading.set_markup("<b>Kühlung und Systemkompatibilität</b>")
        heading.set_xalign(0)
        body.pack_start(heading, False, False, 0)
        self.cooling_label = Gtk.Label(label="Kühlungsdaten werden gelesen …")
        self.cooling_label.set_xalign(0)
        self.cooling_label.set_line_wrap(True)
        body.pack_start(self.cooling_label, False, False, 0)
        self.compatibility_label = Gtk.Label(label="Nutze „Hardware/Firmware“ für Kernel-, Firmware- und Werkzeugversionen.")
        self.compatibility_label.set_xalign(0)
        self.compatibility_label.set_line_wrap(True)
        body.pack_start(self.compatibility_label, False, False, 0)

        heading = Gtk.Label()
        heading.set_markup("<b>Geführter Tuning-Assistent</b>")
        heading.set_xalign(0)
        body.pack_start(heading, False, False, 0)
        assistant_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.tuning_goal_combo = Gtk.ComboBoxText()
        for goal in ("Ausgewogen", "Kühl und leise", "Mehr Leistung"):
            self.tuning_goal_combo.append_text(goal)
        self.tuning_goal_combo.set_active(0)
        assistant_row.pack_start(self.tuning_goal_combo, False, False, 0)
        recommend = Gtk.Button(label="Vorschlag berechnen")
        recommend.connect("clicked", self.run_tuning_assistant)
        assistant_row.pack_start(recommend, False, False, 0)
        self.use_tuning_suggestion_button = Gtk.Button(label="Vorschlag in Regler laden")
        self.use_tuning_suggestion_button.set_sensitive(False)
        self.use_tuning_suggestion_button.connect("clicked", self.load_tuning_suggestion)
        assistant_row.pack_start(self.use_tuning_suggestion_button, False, False, 0)
        body.pack_start(assistant_row, False, False, 0)
        self.tuning_assistant_output = Gtk.Label(label="Der Assistent wendet keine Änderungen automatisch an.")
        self.tuning_assistant_output.set_xalign(0)
        self.tuning_assistant_output.set_line_wrap(True)
        body.pack_start(self.tuning_assistant_output, False, False, 0)
        self._last_tuning_suggestion = None

        heading = Gtk.Label()
        heading.set_markup("<b>Neustart-Verifikation und sichere Rückkehr</b>")
        heading.set_xalign(0)
        body.pack_start(heading, False, False, 0)
        self.reboot_verification_label = Gtk.Label(label="Noch keine anzuwendenden Werte protokolliert.")
        self.reboot_verification_label.set_xalign(0)
        self.reboot_verification_label.set_line_wrap(True)
        body.pack_start(self.reboot_verification_label, False, False, 0)
        verify_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        verify_button = Gtk.Button(label="Neustart-Verifikation aktualisieren")
        verify_button.connect("clicked", lambda _b: self._refresh_verification_status())
        verify_row.pack_start(verify_button, False, False, 0)
        self.confirm_trial_button = Gtk.Button(label="Teststart bestätigen")
        self.confirm_trial_button.connect("clicked", self.confirm_trial_boot)
        verify_row.pack_start(self.confirm_trial_button, False, False, 0)
        body.pack_start(verify_row, False, False, 0)
        self.rollback_trial_check = Gtk.CheckButton(label=(
            "Sicheres Testprofil: nach dem Neustart automatische Rückkehr, wenn ich nicht binnen 120 Sekunden bestätige"
        ))
        self.rollback_trial_check.set_active(False)
        self.rollback_trial_check.set_sensitive(rollback_timer_ready())
        self.rollback_trial_check.set_tooltip_text(
            "Nur verfügbar, wenn der systemd-Rollback-Timer installiert und aktiviert ist."
        )
        body.pack_start(self.rollback_trial_check, False, False, 0)
        rollback_note = Gtk.Label(label=(
            "Optional und standardmäßig aus. Funktioniert nur, wenn Linux und systemd starten: Der Timer wird 120 Sekunden "
            "nach dem Boot ausgelöst. Wenn der Rechner vor Linux hängen bleibt, kann dieser Mechanismus nicht helfen."
        ))
        rollback_note.set_xalign(0)
        rollback_note.set_line_wrap(True)
        rollback_note.get_style_context().add_class("dim-label")
        body.pack_start(rollback_note, False, False, 0)

        history_heading = Gtk.Label()
        history_heading.set_markup("<b>Tuning-Verlauf</b>")
        history_heading.set_xalign(0)
        body.pack_start(history_heading, False, False, 0)
        history_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        refresh_history = Gtk.Button(label="Verlauf aktualisieren")
        refresh_history.connect("clicked", lambda _b: self._refresh_tuning_history())
        history_buttons.pack_start(refresh_history, False, False, 0)
        body.pack_start(history_buttons, False, False, 0)
        self.tuning_history_view = Gtk.TextView()
        self.tuning_history_view.set_name("takt-translatable")
        self.tuning_history_view.set_editable(False)
        self.tuning_history_view.set_cursor_visible(False)
        self.tuning_history_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.tuning_history_view.set_monospace(True)
        history_scroll = Gtk.ScrolledWindow()
        history_scroll.set_min_content_height(150)
        history_scroll.set_max_content_height(250)
        history_scroll.add(self.tuning_history_view)
        body.pack_start(history_scroll, False, True, 0)

    @staticmethod
    def _set_text_view(view, text):
        view.get_buffer().set_text(str(text))

    def run_config_inspector(self, _button=None):
        if not self.hardware.config_path or not self.hardware.config_path.is_file():
            self._set_text_view(self.tools_output, "FEHLER: Keine lesbare config.txt am üblichen Boot-Pfad gefunden.")
            return
        try:
            raw = read_config(self.hardware.config_path)
            findings = inspect_config_text(raw, self.model_id)
            lines = [f"Config-Inspector · {self.hardware.config_path}", ""]
            for finding in findings:
                lines.append(f"[{finding['level']}] Zeile {finding['line']}: {finding['message']}")
            lines.extend(["", "Der Inspector prüft verwaltete Taktwerte und offensichtliche Konflikte; er ersetzt keine vollständige Firmware-Prüfung."])
            self._set_text_view(self.tools_output, "\n".join(lines))
        except (OSError, ValueError) as exc:
            self._set_text_view(self.tools_output, f"Config-Inspector fehlgeschlagen: {exc}")

    def run_compatibility_check(self, _button=None):
        try:
            report = build_compatibility_report(self.hardware)
            lines = ["Hardware-/Firmware-Kompatibilität", ""]
            lines.extend(f"{key}: {value}" for key, value in report.items())
            self._set_text_view(self.tools_output, "\n".join(lines))
            self.compatibility_label.set_text(
                f"{report['model']} · Revision {report['revision']} · Kernel {report['kernel']} · "
                f"Architektur {report['architecture']} · vcgencmd: {report['vcgencmd']}"
            )
        except Exception as exc:
            self._set_text_view(self.tools_output, f"Kompatibilitätsprüfung fehlgeschlagen: {exc}")

    def run_system_self_test(self, _button=None):
        try:
            results = run_self_test(self.hardware)
            passed = sum(1 for item in results if item["ok"])
            lines = [f"System-Selbsttest: {passed}/{len(results)} Checks erfüllt", ""]
            for item in results:
                lines.append(f"{'✓' if item['ok'] else '✗'} {item['name']}: {item['details']}")
            lines.extend(["", "Der Selbsttest verändert keine Konfiguration und erzeugt keine CPU-Last."])
            self._set_text_view(self.tools_output, "\n".join(lines))
        except Exception as exc:
            self._set_text_view(self.tools_output, f"System-Selbsttest fehlgeschlagen: {exc}")

    def run_tuning_assistant(self, _button=None):
        goal = self.tuning_goal_combo.get_active_text() or "Ausgewogen"
        status = read_status()
        current = self._config_values or (self.limits.defaults if self.limits else {})
        suggestion = build_tuning_recommendation(self.model_id, current, status, goal)
        self._last_tuning_suggestion = suggestion.get("values")
        self.use_tuning_suggestion_button.set_sensitive(bool(self._last_tuning_suggestion and self.limits))
        values = self._last_tuning_suggestion
        values_text = "\n" + "\n".join(f"{key} = {value}" for key, value in values.items()) if values else "\nKein Regler-Vorschlag – erst Systemzustand prüfen."
        self.tuning_assistant_output.set_text(f"{suggestion['title']}\n{suggestion['message']}{values_text}\n\nNicht automatisch angewendet.")

    def load_tuning_suggestion(self, _button=None):
        if not self._last_tuning_suggestion or not self.limits:
            self.show_info("Es gibt keinen gültigen Vorschlag zum Laden.")
            return
        try:
            values = validate_values(self.model_id, self._last_tuning_suggestion)
            self._load_values(values)
            self.notebook.set_current_page(0)
            self.show_info("Der Vorschlag wurde nur in die Regler geladen. config.txt wurde nicht geändert.")
        except (TypeError, ValueError) as exc:
            self.show_error(f"Vorschlag konnte nicht geladen werden: {exc}")

    def _refresh_tuning_history(self):
        if not hasattr(self, "tuning_history_view"):
            return
        try:
            history = load_tuning_history()
            self._set_text_view(self.tuning_history_view, format_tuning_history(history))
        except (OSError, ValueError, TypeError) as exc:
            self._set_text_view(self.tuning_history_view, f"Verlauf konnte nicht gelesen werden: {exc}")

    def _refresh_verification_status(self):
        if not hasattr(self, "reboot_verification_label"):
            return
        state = load_pending_apply()
        if state is None:
            self.reboot_verification_label.set_text("Noch keine über Takt Engine angewendeten Werte zum Verifizieren gespeichert.")
            self.confirm_trial_button.set_sensitive(False)
            return
        boot_now = current_boot_id()
        live_config_values = None
        if self.hardware.config_path and self.limits and self.model_id:
            try:
                live_config_values = parse_config_values(read_config(self.hardware.config_path), self.model_id, self.limits.defaults)
            except (OSError, ValueError, TypeError):
                live_config_values = None
        result = verify_pending_apply(state, boot_now, read_firmware_config(), live_config_values)
        if result["status"] != "reboot_pending":
            update_pending_verification(result)
        trial = bool(state.get("trial_rollback"))
        reboot_seen = state.get("boot_id") != boot_now
        extra = ""
        if trial and reboot_seen:
            extra = "\nSicheres Testprofil ist noch nicht bestätigt; die Rückkehrfunktion könnte nach 120 Sekunden ausgelöst werden."
        elif trial and not reboot_seen:
            extra = "\nRollback ist für den nächsten Neustart scharfgeschaltet."
        state_note = state.get("verification_note", "")
        if state_note and state.get("verification") not in {"reboot_pending", result.get("status")}:
            extra += "\nVorheriger Hinweis: " + str(state_note)
        self.reboot_verification_label.set_text(
            f"{result['message']}" + extra +
            (f"\nBestätigt: {', '.join(result['matched'])}" if result.get("matched") else "") +
            (f"\nAbweichungen: {', '.join(result['mismatched'])}" if result.get("mismatched") else "") +
            (f"\nNicht auslesbar: {', '.join(result['unknown'])}" if result.get("unknown") else "")
        )
        config_matches = (not trial) or (
            live_config_values is not None and all(live_config_values.get(key) == value for key, value in state.get("values", {}).items())
        )
        self.confirm_trial_button.set_sensitive(bool(trial and reboot_seen and config_matches))

    def _maybe_prompt_trial_confirmation(self):
        if getattr(self, "_trial_prompted", False):
            return False
        state = load_pending_apply()
        if not state or not state.get("trial_rollback") or state.get("boot_id") == current_boot_id():
            return False
        self._trial_prompted = True
        # Never confirm automatically. Also avoid confirming if someone changed or
        # the rollback service already restored config.txt in the meantime.
        try:
            current_values = parse_config_values(read_config(self.hardware.config_path), self.model_id, self.limits.defaults) if self.hardware.config_path and self.limits and self.model_id else {}
        except (OSError, ValueError, TypeError):
            current_values = {}
        expected = state.get("values", {})
        if not expected or any(current_values.get(key) != value for key, value in expected.items()):
            update_reboot_state_fields({"verification_note": "Die config.txt stimmt nicht mehr mit dem Testprofil überein. Bestätigung wurde nicht angeboten; manuelle Änderung oder Rückkehr prüfen."})
            self._refresh_verification_status()
            self.show_info("Die config.txt stimmt nicht mehr mit dem gespeicherten Testprofil überein. Takt Engine bestätigt den Test deshalb nicht automatisch. Prüfe die Regler und den Status.")
            return False
        dialog = Gtk.MessageDialog(
            transient_for=self, flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
            text="Neustart des Takt-Testprofils erkannt",
        )
        dialog.format_secondary_text(
            "Wenn der Raspberry Pi stabil läuft, bestätige den Teststart. Andernfalls nicht bestätigen: "
            "Der systemd-Timer kann die vorherige config.txt zurückspielen. Er funktioniert nur, wenn Linux startet; "
            "bei einem Fehler vor dem Linux-Start ist separate Wiederherstellung nötig."
        )
        dialog.add_button("Nicht jetzt", Gtk.ResponseType.CANCEL)
        dialog.add_button("System stabil – bestätigen", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.confirm_trial_boot()
        self._refresh_verification_status()
        return False

    def confirm_trial_boot(self, _button=None):
        state = load_pending_apply()
        if not state or not state.get("trial_rollback"):
            self.show_info("Kein unbestätigtes Testprofil gefunden.")
            return
        if state.get("boot_id") == current_boot_id():
            self.show_info("Der Neustart ist noch nicht erkannt. Bestätige den Teststart erst nach dem Neustart.")
            return
        try:
            result = confirm_boot_rollback()
            update_reboot_state_fields({
                "trial_rollback": False,
                "trial_confirmed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            })
            self._refresh_verification_status()
            self.show_info((result.stdout or "Teststart bestätigt.").strip() + "\n\nAutomatische Rückkehr wurde deaktiviert.")
        except (OSError, RuntimeError, ValueError) as exc:
            self.show_error(
                f"Teststart konnte nicht bestätigt werden: {exc}\n\n"
                "Möglicherweise wurde die automatische Rückkehr bereits ausgeführt. Prüfe config.txt und den Status."
            )
            self._refresh_verification_status()

    def _update_capability_notice(self):
        supported = self.model_id in LIMITS
        if not self.hardware.is_raspberry_pi:
            message = "Nicht auf einem Raspberry Pi erkannt: Die Oberfläche kann angesehen und getestet werden, das Anwenden ist gesperrt."
        elif not supported:
            message = f"Erkannt: {self.hardware.model_name}. Diese Version unterstützt nur Pi 4 und Pi 5; Anwenden ist gesperrt."
        elif self.hardware.config_path is None:
            message = "Kein config.txt an /boot/firmware/config.txt oder /boot/config.txt gefunden. Anwenden ist gesperrt."
        else:
            message = f"Erkannt: {self.hardware.model_name} · Konfiguration: {self.hardware.config_path} · Werte werden erst nach Neustart aktiv."
        self.notice.set_text(message)
        can_write = bool(supported and self.hardware.config_path and self.hardware.is_raspberry_pi)
        self.apply_button.set_sensitive(can_write)
        if hasattr(self, "restore_button"):
            self.restore_button.set_sensitive(can_write)

    def load_defaults(self, _button=None):
        if not self.limits:
            return
        self._load_values(self.limits.defaults)

    def load_preset(self, _button, preset):
        try:
            if self.model_id != preset["model"]:
                raise ValidationError("Dieses Profil passt nicht zum erkannten Modell.")
            values = validate_values(preset["model"], preset["values"])
            self._load_values(values)
            self.notebook.set_current_page(0)
            self._append_bench_log(f"Profil geladen: {preset['name']} — {preset['warning']}")
        except (ValueError, KeyError) as exc:
            self.show_error(str(exc))

    def _load_values(self, values, mark_dirty=True):
        self._loading_values = True
        try:
            for key, value in values.items():
                if key in self.scales:
                    self._set_scale_value(key, int(value))
        finally:
            self._loading_values = False
        if mark_dirty:
            self._sliders_dirty = not self._sliders_match_config()
            self._update_sync_status()

    def _set_scale_value(self, key, value):
        """Show even out-of-range manually configured values without permitting apply."""
        scale = self.scales[key]
        lower, upper, _step = self.scale_bounds[key]
        unit = self.scale_units[key]
        limit_label = self.limit_labels[key]
        if value < lower or value > upper:
            scale.set_range(min(lower, value), max(upper, value))
            limit_label.set_text(
                f"App-Grenzen: {int(lower)}–{int(upper)} {unit} · config.txt-Wert {value} "
                "liegt außerhalb und kann nicht angewendet werden."
            )
            context = limit_label.get_style_context()
            context.remove_class("dim-label")
            context.add_class("caution")
        else:
            scale.set_range(lower, upper)
            limit_label.set_text(f"App-Grenzen: {int(lower)}–{int(upper)} {unit}")
            context = limit_label.get_style_context()
            context.remove_class("caution")
            context.add_class("dim-label")
        scale.set_value(float(value))
        self._update_clock_zone(key, int(value))

    def _current_slider_values(self):
        return {key: int(round(scale.get_value())) for key, scale in self.scales.items()}

    def _sliders_match_config(self):
        if self._config_values is None:
            return False
        current = self._current_slider_values()
        return all(current.get(key) == value for key, value in self._config_values.items())

    def _update_sync_status(self):
        if not hasattr(self, "slider_sync_status"):
            return
        context = self.slider_sync_status.get_style_context()
        context.remove_class("caution")
        context.add_class("dim-label")
        if self._external_config_pending:
            self.slider_sync_status.set_text(
                "config.txt wurde extern geändert. Deine Regleränderungen bleiben erhalten. "
                "Nutze „config.txt neu einlesen“, um die neuen Werte zu übernehmen."
            )
            context.remove_class("dim-label")
            context.add_class("caution")
        elif self._sliders_dirty:
            self.slider_sync_status.set_text(
                "Nicht gespeicherte Regleränderungen. config.txt wird alle 3 Sekunden geprüft; "
                "deine Auswahl wird nicht automatisch überschrieben."
            )
            context.remove_class("dim-label")
            context.add_class("caution")
        else:
            self.slider_sync_status.set_text(
                "Regler synchron mit config.txt · automatische Prüfung alle 3 Sekunden. "
                "Live-Takt kann sich durch DVFS und Last unterscheiden."
            )

    def _sync_sliders_from_config(self, force=False):
        """Sync the GUI from config.txt; preserve unsaved slider edits by default."""
        if not self.limits or not self.hardware.config_path:
            return False
        try:
            config_text = read_config(self.hardware.config_path)
        except OSError as exc:
            if hasattr(self, "slider_sync_status"):
                self.slider_sync_status.set_text(f"config.txt kann nicht gelesen werden: {exc}")
            return False

        if not force and config_text == self._last_config_text:
            self._update_sync_status()
            return False

        try:
            values = parse_config_values(config_text, self.model_id, self.limits.defaults)
        except (ValueError, TypeError) as exc:
            if hasattr(self, "slider_sync_status"):
                self.slider_sync_status.set_text(f"config.txt-Werte konnten nicht gelesen werden: {exc}")
            return False

        self._last_config_text = config_text
        if self._sliders_dirty and not force:
            current_values = self._current_slider_values()
            if values == self._config_values:
                # A comment or unrelated option changed; do not announce a
                # slider conflict when our relevant settings stayed the same.
                self._external_config_pending = False
            elif values == current_values:
                # The external file now contains exactly the draft the user
                # has selected, so there is no conflicting unsaved change.
                self._config_values = values
                self._sliders_dirty = False
                self._external_config_pending = False
                self._load_values(values, mark_dirty=False)
            else:
                self._external_config_pending = True
            self._update_sync_status()
            return True

        self._config_values = values
        self._external_config_pending = False
        self._sliders_dirty = False
        self._load_values(values, mark_dirty=False)
        self._update_sync_status()
        return True

    def reload_config_sliders(self, _button=None):
        if self._sliders_dirty:
            dialog = Gtk.MessageDialog(
                transient_for=self, flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
                text="Reglerwerte wirklich neu einlesen?",
            )
            dialog.format_secondary_text(
                "Nicht gespeicherte Änderungen an den Reglern werden verworfen und durch die Werte aus config.txt ersetzt."
            )
            dialog.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
            dialog.add_button("config.txt einlesen", Gtk.ResponseType.OK)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.OK:
                return
        if not self._sync_sliders_from_config(force=True):
            self.show_error("Die Werte aus config.txt konnten nicht neu eingelesen werden.")

    def _current_values(self):
        values = self._current_slider_values()
        return validate_values(self.model_id or "", values)

    def apply_current_settings(self, _button=None):
        """Play a one-second orange pulse, then continue with normal confirmation."""
        if self._apply_animation_running:
            return
        self._apply_animation_running = True
        self._apply_animation_stage = 0
        self._apply_button_original_label = self.apply_button.get_label() or "Änderungen anwenden…"
        self.apply_button.set_label("✦ Taktprofil wird vorbereitet …")
        self.apply_button.set_sensitive(False)
        for scale in self.scales.values():
            scale.set_sensitive(False)
        self._apply_animation_source_id = GLib.timeout_add(100, self._tick_apply_animation)

    def _clear_apply_animation_styles(self):
        for widget, prefix in ((self.apply_button, "apply-pulse-"), (self.heading_label, "brand-pulse-")):
            context = widget.get_style_context()
            for class_name in context.list_classes():
                if class_name.startswith(prefix):
                    context.remove_class(class_name)

    def _tick_apply_animation(self):
        if not self._apply_animation_running:
            self._apply_animation_source_id = None
            return False

        # Ten 100 ms frames create a one-second warm-orange pulse, then fade back.
        phases = (0, 1, 2, 3, 2, 1, 0, 1, 2, 0)
        phase = phases[self._apply_animation_stage]
        self._clear_apply_animation_styles()
        self.apply_button.get_style_context().add_class(f"apply-pulse-{phase}")
        self.heading_label.get_style_context().add_class(f"brand-pulse-{phase}")
        self._apply_animation_stage += 1
        if self._apply_animation_stage < len(phases):
            return True

        self._apply_animation_source_id = None
        self._clear_apply_animation_styles()
        self.apply_button.set_label(self._apply_button_original_label)
        self._apply_animation_running = False
        self._continue_apply_settings()
        return False

    def _finish_apply_interaction(self):
        self._clear_apply_animation_styles()
        self._apply_animation_running = False
        self._apply_animation_source_id = None
        self.apply_button.set_label(self._apply_button_original_label or "Änderungen anwenden…")
        for scale in self.scales.values():
            scale.set_sensitive(True)
        can_write = bool(self.hardware.is_raspberry_pi and self.model_id in LIMITS and self.hardware.config_path)
        self.apply_button.set_sensitive(can_write)

    def _continue_apply_settings(self):
        if not (self.model_id in LIMITS and self.hardware.config_path and self.hardware.is_raspberry_pi):
            self.show_error("Anwenden ist nur auf einem unterstützten Pi 4/Pi 5 mit vorhandener config.txt möglich.")
            self._finish_apply_interaction()
            return
        try:
            values = self._current_values()
        except ValueError as exc:
            self.show_error(str(exc))
            self._finish_apply_interaction()
            return
        try:
            current_config = read_config(self.hardware.config_path)
            old_values = parse_config_values(current_config, self.model_id, self.limits.defaults)
            updated_config = render_managed_config(current_config, self.model_id, values)
        except (OSError, ValueError) as exc:
            self.show_error(f"Konfigurationsvorschau konnte nicht erstellt werden: {exc}")
            self._finish_apply_interaction()
            return
        if not self._show_config_preview(current_config, updated_config):
            self._finish_apply_interaction()
            return

        experimental = experimental_clock_warnings(self.model_id, values)
        if experimental and not self._confirm_experimental_clock_values(experimental):
            self._finish_apply_interaction()
            return

        value_lines = "\n".join(f"{key} = {value}" for key, value in values.items())
        dialog = Gtk.MessageDialog(
            transient_for=self, flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
            text="Übertaktungseinstellungen anwenden?",
        )
        dialog.format_secondary_text(
            "Vor dem Schreiben wird eine Sicherung erstellt. Die Änderungen benötigen einen Neustart. "
            "Instabilität oder Bootprobleme sind möglich.\n\n" +
            ("WARNUNG: Ein negativer Spannungs-Offset kann Rechenfehler, Abstürze oder Bootprobleme verursachen. "
             "Nur schrittweise testen; bei Problemen auf 0 µV zurückstellen.\n\n" if values.get("over_voltage_delta", 0) < 0 else "") +
            value_lines
        )
        dialog.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        dialog.add_button("Sichern und anwenden", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            self._finish_apply_interaction()
            return
        trial_rollback = bool(getattr(self, "rollback_trial_check", None) and self.rollback_trial_check.get_active())
        self.notice.set_text("Sicherung wird erstellt; die Berechtigungsabfrage kann erscheinen …")
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        try:
            backup, result = apply_settings(self.hardware.config_path, self.model_id, values, arm_rollback=trial_rollback)
            self.notice.set_text(f"Einstellungen geschrieben. Sicherung: {backup}. Bitte neu starten.")
            self._sync_sliders_from_config(force=True)
            try:
                record_tuning_change(self.model_id, old_values, values, read_status().temperature_c, str(backup))
                save_pending_apply(self.model_id, values, trial_rollback=trial_rollback)
                self._refresh_tuning_history()
                self._refresh_verification_status()
            except (OSError, ValueError, TypeError) as state_exc:
                self._append_bench_log(f"Warnung: lokale Änderungs-/Neustart-Historie konnte nicht gespeichert werden: {state_exc}")
            message = (result.stdout or "Konfiguration aktualisiert.").strip() + f"\n\nSicherung: {backup}\n\nNeustart erforderlich."
            if trial_rollback:
                message += ("\n\nSicheres Testprofil ist aktiv. Nach dem Neustart musst du den Teststart in Takt Engine bestätigen; "
                            "wenn du nicht bestätigst, versucht systemd nach 120 Sekunden die vorherige config.txt zurückzuspielen.")
            self.show_info(message)
        except (OSError, RuntimeError, ValueError) as exc:
            self.show_error(str(exc))
        finally:
            self._finish_apply_interaction()
            self.refresh_status()

    def _confirm_experimental_clock_values(self, experimental):
        """Require a separate, explicit acknowledgement for high Pi 5 clocks."""
        names = {"arm_freq": "CPU-Takt (arm_freq)", "v3d_freq": "3D-Grafiktakt (v3d_freq)"}
        lines = []
        for key, value, threshold in experimental:
            lines.append(f"• {names.get(key, key)}: {value} MHz (konservative Empfehlungsschwelle: {threshold} MHz)")
        details = (
            "Du hast Werte oberhalb der konservativen Pi-5-Empfehlung ausgewählt. "
            "Die Raspberry-Pi-Dokumentation nennt 2.400 MHz CPU und 960 MHz V3D als Standardwerte; "
            "sie garantiert nicht, dass die hier gewählten Extremwerte funktionieren.\n\n"
            + "\n".join(lines) + "\n\n"
            + "Mögliche Folgen sind Instabilität, Rechenfehler, Dateisystem-/Datenverlust oder ein System, das nicht startet. "
            "Vorherige config.txt-Backups und ein alternativer Wiederherstellungsweg sind wichtig. "
            "Der optionale automatische Rollback hilft nur, wenn Linux und systemd starten; er kann keinen Fehler vor Linux beheben.\n\n"
            + "Nur fortfahren, wenn du diese Risiken verstanden hast."
        )
        dialog = Gtk.MessageDialog(
            transient_for=self, flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
            text="Experimentelle Pi-5-Taktwerte bestätigen?",
        )
        dialog.format_secondary_text(details)
        dialog.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        continue_button = dialog.add_button("Risiko verstanden – weiter", Gtk.ResponseType.OK)
        continue_button.get_style_context().add_class("suggested-action")
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def _show_config_preview(self, original, updated):
        diff_lines = build_config_diff(original, updated)
        dialog = Gtk.Dialog(title="Änderungsvorschau – config.txt", transient_for=self, flags=Gtk.DialogFlags.MODAL)
        dialog.set_default_size(780, 520)
        dialog.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        continue_button = dialog.add_button("Weiter zur Sicherheitsbestätigung", Gtk.ResponseType.OK)
        continue_button.get_style_context().add_class("suggested-action")
        content = dialog.get_content_area()
        content.set_spacing(8)
        content.set_border_width(12)
        explanation = Gtk.Label(label=(
            "Prüfe die tatsächlichen Zeilenänderungen. Grün bedeutet neu/hinzugefügt, Orange bedeutet entfernt. "
            "Andere Zeilen sollten erhalten bleiben. Noch wurde nichts geschrieben."
        ))
        explanation.set_xalign(0)
        explanation.set_line_wrap(True)
        content.pack_start(explanation, False, False, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_monospace(True)
        buffer = view.get_buffer()
        removed_tag = buffer.create_tag("removed", foreground="#f2a16d")
        added_tag = buffer.create_tag("added", foreground="#a8d5a2")
        header_tag = buffer.create_tag("header", foreground="#9bbef5")
        if diff_lines:
            for line in diff_lines:
                tag = removed_tag if line.startswith("-") and not line.startswith("---") else None
                if line.startswith("+") and not line.startswith("+++"):
                    tag = added_tag
                elif line.startswith(("---", "+++", "@@")):
                    tag = header_tag
                buffer.insert_with_tags(buffer.get_end_iter(), line + "\n", tag) if tag else buffer.insert(buffer.get_end_iter(), line + "\n")
        else:
            buffer.set_text("Keine Änderungen notwendig: config.txt enthält bereits genau diese Werte.")
            continue_button.set_sensitive(False)
        scroller.add(view)
        content.pack_start(scroller, True, True, 0)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        return bool(diff_lines and response == Gtk.ResponseType.OK)

    def refresh_status(self):
        self._sync_sliders_from_config()
        status = read_status()
        self._update_safety_banner(status)
        self._record_monitor_sample(status)
        config_text = "Nicht verfügbar"
        if self.hardware.config_path and self.hardware.config_path.is_file():
            try:
                config_text = read_config(self.hardware.config_path)
                marker_start = "# BEGIN TAKT ENGINE MANAGED BLOCK"
                marker_end = "# END TAKT ENGINE MANAGED BLOCK"
                if marker_start in config_text and marker_end in config_text:
                    config_text = config_text.split(marker_start, 1)[1].split(marker_end, 1)[0].strip()
                    config_text = marker_start + "\n" + config_text + "\n" + marker_end
                else:
                    config_text = "Noch kein Takt-Engine-Block eingetragen.\n\n" + "\n".join(
                        line for line in config_text.splitlines() if line.strip() and not line.strip().startswith("#")
                    )[-1200:]
            except OSError as exc:
                config_text = f"Lesefehler: {exc}"
        throttle = status.throttled_hex or "Nicht verfügbar"
        active = "Ja" if (status.active_throttling or status.undervoltage) else "Nein / nicht erkannt"
        historical = "Ja" if status.historical_flags else "Nein / nicht erkannt"
        text = (
            f"Hardware\n"
            f"  Modell: {self.hardware.model_name}\n"
            f"  Raspberry Pi erkannt: {'Ja' if self.hardware.is_raspberry_pi else 'Nein'}\n"
            f"  Betriebssystem: {self.hardware.os_name}\n"
            f"  Boot-Konfiguration: {self.hardware.config_path or 'Nicht gefunden'}\n\n"
            f"Live-Telemetrie\n"
            f"  SoC-Temperatur: {_format_temperature(status.temperature_c)}\n"
            f"  CPU-Takt momentan: {_format_clock(status.arm_clock_mhz)}\n"
            f"  V3D-Takt momentan: {_format_clock(status.v3d_clock_mhz)}\n"
            f"  CPU-Auslastung: {f'{status.cpu_usage_percent:.1f} %' if status.cpu_usage_percent is not None else 'Nicht verfügbar'}\n"
            f"  Lüfterdrehzahl: {f'{status.fan_rpm} RPM' if status.fan_rpm is not None else 'Nicht verfügbar'}\n"
            f"  Kühlungsstatus: {status.cooling_states or 'Nicht verfügbar'}\n"
            f"  get_throttled: {throttle}\n"
            f"  Aktive Unterspannung/Drosselung: {active}\n"
            f"  Historische Flags: {historical}\n"
            f"  Hinweis: {status.note or 'Live-Werte sind Momentaufnahmen; Werte können unter Last variieren.'}\n\n"
            f"In config.txt gespeicherter Takt-Engine-Block\n{config_text}\n\n"
            "Hinweis: gespeicherte Werte sind vorgesehene Werte, nicht zwingend der aktuell anliegende Takt.\n"
        )
        self.status_view.get_buffer().set_text(text)
        desired = self._config_values or {}
        desired_cpu = desired.get("arm_freq")
        desired_v3d = desired.get("v3d_freq")
        cpu_desired_text = f"{desired_cpu} MHz" if desired_cpu is not None else "n. v."
        v3d_desired_text = f"{desired_v3d} MHz" if desired_v3d is not None else "n. v."
        cpu_load = f"{status.cpu_usage_percent:.1f} %" if status.cpu_usage_percent is not None else "n. v."
        if hasattr(self, "monitor_summary"):
            self.monitor_summary.set_text(
                f"Temperatur: {_format_temperature(status.temperature_c)}  ·  "
                f"CPU Ist: {_format_clock(status.arm_clock_mhz)} / Soll: {cpu_desired_text}  ·  "
                f"V3D Ist: {_format_clock(status.v3d_clock_mhz)} / Soll: {v3d_desired_text}  ·  "
                f"CPU-Auslastung: {cpu_load}  ·  "
                f"Lüfter: {status.fan_rpm if status.fan_rpm is not None else 'n. v.'} RPM  ·  "
                f"{self.safety_banner.get_text()}"
            )
            self.monitor_chart.queue_draw()
        if hasattr(self, "fan_curve_runtime_label"):
            fan_text = f"{status.fan_rpm} RPM" if status.fan_rpm is not None else "Drehzahl nicht verfügbar"
            self.fan_curve_runtime_label.set_text(
                f"SoC: {_format_temperature(status.temperature_c)} · Aktuelle Lüfterdrehzahl: {fan_text}"
            )
        self.fan_last_temperature = status.temperature_c
        self._update_fan_hwmon_status()
        if hasattr(self, "cooling_label"):
            fan_text = f"{status.fan_rpm} RPM" if status.fan_rpm is not None else "Lüfterdrehzahl nicht verfügbar"
            cooling_text = status.cooling_states or "keine Cooling-Device-Statuswerte verfügbar"
            self.cooling_label.set_text(
                f"SoC: {_format_temperature(status.temperature_c)} · Lüfter: {fan_text} · Kühlungssteuerung: {cooling_text}\n"
                f"Drosselung: {'aktiv' if status.active_throttling else 'nicht aktiv erkannt'} · "
                f"Unterspannung: {'aktiv' if status.undervoltage else 'nicht aktiv erkannt'}"
            )
        return True

    def _update_safety_banner(self, status):
        level, message = safety_state(status)
        context = self.safety_banner.get_style_context()
        for name in ("safety-ok", "safety-caution", "safety-critical", "safety-unknown"):
            context.remove_class(name)
        context.add_class({"ok": "safety-ok", "caution": "safety-caution",
                           "critical": "safety-critical", "unknown": "safety-unknown"}[level])
        self.safety_banner.set_text(message)

    def _record_monitor_sample(self, status):
        self.monitor_history.append({
            "temperature_c": status.temperature_c,
            "arm_clock_mhz": status.arm_clock_mhz,
            "v3d_clock_mhz": status.v3d_clock_mhz,
            "cpu_usage_percent": status.cpu_usage_percent,
            "fan_rpm": status.fan_rpm,
        })
        if len(self.monitor_history) > self._monitor_history_limit:
            del self.monitor_history[:-self._monitor_history_limit]

    def export_diagnostic_report(self, _button=None):
        status = read_status()
        config_values = self._config_values or (self.limits.defaults if self.limits else {})
        if self.hardware.config_path and self.limits:
            try:
                config_values = parse_config_values(
                    read_config(self.hardware.config_path), self.model_id, self.limits.defaults
                )
            except (OSError, ValueError, TypeError):
                pass
        history = load_benchmark_history()
        report = build_diagnostic_report(self.hardware, status, config_values, history, app_version=__version__)
        chooser = Gtk.FileChooserDialog(
            title="Diagnosebericht speichern", parent=self, action=Gtk.FileChooserAction.SAVE,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK),
        )
        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_name("takt-engine-diagnose.txt")
        text_filter = Gtk.FileFilter()
        text_filter.set_name("Textbericht (*.txt)")
        text_filter.add_pattern("*.txt")
        chooser.add_filter(text_filter)
        json_filter = Gtk.FileFilter()
        json_filter.set_name("JSON-Bericht (*.json)")
        json_filter.add_pattern("*.json")
        chooser.add_filter(json_filter)
        response = chooser.run()
        filename = chooser.get_filename() if response == Gtk.ResponseType.OK else None
        chooser.destroy()
        if not filename:
            return
        target = Path(filename)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.suffix.lower() == ".json":
                target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            else:
                if target.suffix.lower() != ".txt":
                    target = target.with_suffix(".txt")
                target.write_text(format_diagnostic_report(report), encoding="utf-8")
            self.show_info(f"Diagnosebericht gespeichert:\n{target}\n\nDer Bericht enthält nur relevante Taktwerte, Statusdaten und letzte Benchmarks – keine vollständige config.txt.")
        except OSError as exc:
            self.show_error(f"Diagnosebericht konnte nicht gespeichert werden: {exc}")

    def restore_backup_dialog(self, _button=None):
        if not (self.model_id in LIMITS and self.hardware.config_path and self.hardware.is_raspberry_pi):
            self.show_error("Wiederherstellen ist nur auf einem unterstützten Pi 4/Pi 5 möglich.")
            return
        backup_dir = Path.home() / ".config" / "takt-engine" / "backups"
        backups = sorted(backup_dir.glob("config.txt.*.bak"), reverse=True) if backup_dir.is_dir() else []
        if not backups:
            self.show_info(f"Keine Sicherungen gefunden.\n\nGesucht wurde in: {backup_dir}")
            return
        chooser = Gtk.FileChooserDialog(
            title="Takt-Engine-Sicherung auswählen", parent=self,
            action=Gtk.FileChooserAction.OPEN,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK),
        )
        chooser.set_current_folder(str(backup_dir))
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Takt-Engine-Sicherungen (*.bak)")
        file_filter.add_pattern("config.txt.*.bak")
        chooser.add_filter(file_filter)
        response = chooser.run()
        backup_path = Path(chooser.get_filename()) if response == Gtk.ResponseType.OK and chooser.get_filename() else None
        chooser.destroy()
        if backup_path is None:
            return
        confirm = Gtk.MessageDialog(
            transient_for=self, flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
            text="Konfiguration wirklich zurückspielen?",
        )
        confirm.format_secondary_text(
            f"Die aktuelle config.txt wird zuerst zusätzlich gesichert.\n\nAusgewählte Sicherung: {backup_path.name}\n\n"
            "Die Wiederherstellung benötigt eine Rechteabfrage und einen Neustart."
        )
        confirm.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        confirm.add_button("Sichern und wiederherstellen", Gtk.ResponseType.OK)
        response = confirm.run()
        confirm.destroy()
        if response != Gtk.ResponseType.OK:
            return
        self.restore_button.set_sensitive(False)
        try:
            safety_backup, result = restore_config_backup(self.hardware.config_path, self.model_id, backup_path)
            self._sync_sliders_from_config(force=True)
            self.show_info((result.stdout or "Sicherung wiederhergestellt.").strip() + f"\n\nVorherige Konfiguration gesichert unter: {safety_backup}\nBitte neu starten.")
        except (OSError, RuntimeError, ValueError) as exc:
            self.show_error(str(exc))
        finally:
            self.restore_button.set_sensitive(bool(self.hardware.is_raspberry_pi and self.model_id in LIMITS and self.hardware.config_path))
            self.refresh_status()

    def _refresh_benchmark_history(self):
        if not hasattr(self, "bench_history_label"):
            return
        try:
            history = load_benchmark_history()
            self.bench_history_label.set_text(build_benchmark_comparison(history, self.model_id or ""))
        except (OSError, ValueError, TypeError) as exc:
            self.bench_history_label.set_text(f"Benchmark-Historie konnte nicht gelesen werden: {exc}")

    def _tick_benchmark_animation(self):
        if not self.benchmark_running:
            self._bench_animation_source_id = None
            for name in ("running-pulse-0", "running-pulse-1"):
                self.bench_start.get_style_context().remove_class(name)
            return False
        context = self.bench_start.get_style_context()
        for name in ("running-pulse-0", "running-pulse-1"):
            context.remove_class(name)
        context.add_class(f"running-pulse-{self._bench_animation_stage % 2}")
        self._bench_animation_stage += 1
        return True

    def _stop_benchmark_animation(self):
        if self._bench_animation_source_id is not None:
            GLib.source_remove(self._bench_animation_source_id)
            self._bench_animation_source_id = None
        context = self.bench_start.get_style_context()
        context.remove_class("running-pulse-0")
        context.remove_class("running-pulse-1")

    def start_benchmark(self, _button=None):
        if self.benchmark_running:
            return
        duration = int(self.duration_spin.get_value_as_int())
        threads = int(self.threads_spin.get_value_as_int())
        self.benchmark_running = True
        self.benchmark_stop.clear()
        self.bench_start.set_sensitive(False)
        self._bench_animation_stage = 0
        self._bench_animation_source_id = GLib.timeout_add(500, self._tick_benchmark_animation)
        self.bench_stop.set_sensitive(True)
        self.bench_progress.set_fraction(0)
        self.bench_progress.set_text("Startet …")
        self.bench_status.set_text("Benchmark wird gestartet …")
        self._append_bench_log(f"Start: Dauer {duration} s, CPU-Threads {threads}, Speicherlast 20 %.")

        def update(message, runtime, elapsed):
            GLib.idle_add(self._benchmark_update, message, runtime, elapsed, duration)

        def worker():
            try:
                result = run_benchmark(duration, threads, on_update=update, stop_event=self.benchmark_stop)
                GLib.idle_add(self._benchmark_finished, result, duration)
            except Exception as exc:
                GLib.idle_add(self._benchmark_error, str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def _benchmark_update(self, message, status, elapsed, duration):
        self.bench_progress.set_fraction(min(1.0, elapsed / max(1, duration)))
        self.bench_progress.set_text(f"{elapsed} / {duration} s")
        self.bench_status.set_text(f"{message} · Temperatur: {_format_temperature(status.temperature_c)} · CPU: {_format_clock(status.arm_clock_mhz)}")
        return False

    def _benchmark_finished(self, result, requested_duration):
        self.benchmark_running = False
        self._stop_benchmark_animation()
        self.bench_start.set_sensitive(True)
        self.bench_stop.set_sensitive(False)
        self.bench_progress.set_fraction(min(1.0, result.duration_seconds / max(1, requested_duration)))
        self.bench_progress.set_text("Bestanden" if result.passed else "Nicht bestanden")
        self.bench_status.set_text(result.summary)
        self._append_bench_log(result.summary)
        try:
            record = save_benchmark_result(result, self.model_id or "unknown")
            self._append_bench_log("Benchmark-Ergebnis lokal gespeichert: " + record["timestamp"])
            self._refresh_benchmark_history()
        except (OSError, ValueError, TypeError) as exc:
            self._append_bench_log(f"Warnung: Ergebnis konnte nicht gespeichert werden: {exc}")
        return False

    def _benchmark_error(self, message):
        self.benchmark_running = False
        self._stop_benchmark_animation()
        self.bench_start.set_sensitive(True)
        self.bench_stop.set_sensitive(False)
        self.bench_status.set_text("Benchmark konnte nicht ausgeführt werden.")
        self._append_bench_log("Fehler: " + message)
        self.show_error(message)
        return False

    def stop_benchmark(self, _button=None):
        self.benchmark_stop.set()
        self.bench_status.set_text("Stopp angefordert …")

    def _append_bench_log(self, line):
        try:
            buffer = self.bench_log.get_buffer()
            end = buffer.get_end_iter()
            buffer.insert(end, line + "\n")
        except Exception:
            pass

    def show_error(self, message):
        dialog = Gtk.MessageDialog(transient_for=self, flags=Gtk.DialogFlags.MODAL,
                                   message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
                                   text="Takt Engine")
        dialog.format_secondary_text(translate_text(str(message), self.language))
        dialog.run()
        dialog.destroy()

    def show_info(self, message):
        dialog = Gtk.MessageDialog(transient_for=self, flags=Gtk.DialogFlags.MODAL,
                                   message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
                                   text="Takt Engine")
        dialog.format_secondary_text(translate_text(str(message), self.language))
        dialog.run()
        dialog.destroy()

    def on_close(self, *_args):
        if self.benchmark_running:
            self.benchmark_stop.set()
        if getattr(self, "_fan_animation_source_id", None) is not None:
            try:
                GLib.source_remove(self._fan_animation_source_id)
            except Exception:
                pass
            self._fan_animation_source_id = None
        self._stop_fan_save_animation()
        for source_id in list(self._clock_gradient_animation_sources.values()):
            try:
                GLib.source_remove(source_id)
            except Exception:
                pass
        self._clock_gradient_animation_sources.clear()
        return False


def main():
    apply_claude_theme()
    window = TaktEngineWindow()
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
