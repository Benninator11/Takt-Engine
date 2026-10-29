"""Read-only diagnostics, config inspection, compatibility and tuning guidance."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from typing import Any, Mapping

from .limits import LIMITS, PI5_CONSERVATIVE_THRESHOLDS, validate_values

MANAGED_TUNING_KEYS = {"arm_freq", "v3d_freq", "core_freq", "over_voltage_delta"}


def inspect_config_text(config_text: str, model_id: str | None) -> list[dict[str, Any]]:
    """Inspect config.txt for likely tuning mistakes without changing it."""
    findings: list[dict[str, Any]] = []

    def add(level: str, line_no: int | str, message: str) -> None:
        findings.append({"level": level, "line": line_no, "message": message})

    if model_id not in LIMITS:
        add("WARNUNG", "–", "Hardwaremodell nicht unterstützt; Taktwerte können nicht gegen App-Grenzen geprüft werden.")
    limits = LIMITS.get(model_id or "")
    section = "all"
    seen: dict[tuple[str, str], int] = {}
    key_latest: dict[str, tuple[int, str, int | None]] = {}

    for line_no, raw_line in enumerate(config_text.splitlines(), 1):
        if len(raw_line) > 98:
            add("WARNUNG", line_no, f"Zeile ist {len(raw_line)} Zeichen lang; das übliche Firmware-Zeilenlimit von 98 Zeichen wird überschritten.")
        stripped = raw_line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith("["):
            if not stripped.endswith("]") or len(stripped) < 3:
                add("FEHLER", line_no, "Abschnittsfilter ist unvollständig; erwartet wird z. B. [all] oder [pi5].")
                continue
            section = stripped[1:-1].strip().lower()
            if not section:
                add("FEHLER", line_no, "Leerer Abschnittsfilter.")
            continue
        if stripped.lower().startswith("include="):
            add("HINWEIS", line_no, "Include-Datei erkannt. Dieser Inspector prüft die referenzierte Datei nicht mit; dort können weitere Einstellungen stehen.")
        if "=" not in stripped:
            if re.match(r"^(arm_freq|v3d_freq|core_freq|over_voltage_delta)\b", stripped):
                add("FEHLER", line_no, "Takt-/Spannungsoption hat kein '='-Wertpaar.")
            continue
        key, raw_value = (part.strip() for part in stripped.split("=", 1))
        key = key.lower()
        if key in MANAGED_TUNING_KEYS:
            duplicate_key = (section, key)
            if duplicate_key in seen:
                add("WARNUNG", line_no, f"{key} wurde im Abschnitt [{section}] bereits in Zeile {seen[duplicate_key]} gesetzt; der spätere Wert gewinnt wahrscheinlich.")
            else:
                seen[duplicate_key] = line_no
            if section in {"all", model_id} or (section == "" and model_id):
                try:
                    value = int(raw_value, 0 if raw_value.lower().startswith("0x") else 10)
                except ValueError:
                    add("FEHLER", line_no, f"{key}={raw_value!r} ist kein gültiger Ganzzahlwert.")
                    key_latest[key] = (line_no, section, None)
                    continue
                if limits:
                    if key == "arm_freq":
                        low, high = limits.arm_min, limits.arm_max
                    elif key == "v3d_freq":
                        low, high = limits.v3d_min, limits.v3d_max
                    elif key == "core_freq":
                        low, high = limits.core_min, limits.core_max
                    else:
                        low, high = limits.voltage_delta_min, limits.voltage_delta_max
                    if low is None or high is None:
                        add("WARNUNG", line_no, f"{key} wird für {limits.display_name} nicht von Takt Engine unterstützt.")
                    elif not low <= value <= high:
                        add("WARNUNG", line_no, f"{key}={value} liegt außerhalb des Takt-Engine-Bereichs {low}–{high}; die App wird diesen Wert nicht anwenden.")
                    elif model_id == "pi5" and key in PI5_CONSERVATIVE_THRESHOLDS and value > PI5_CONSERVATIVE_THRESHOLDS[key]:
                        threshold = PI5_CONSERVATIVE_THRESHOLDS[key]
                        add("WARNUNG", line_no, f"{key}={value} liegt im experimentellen Pi-5-Bereich oberhalb der konservativen Empfehlungsschwelle {threshold} MHz; Funktion und Stabilität sind nicht garantiert.")
                key_latest[key] = (line_no, section, value)
        elif key in {"force_turbo", "sdram_freq", "over_voltage"}:
            add("HINWEIS", line_no, f"{key} ist eine nicht von Takt Engine verwaltete Einstellung. Vor einer Änderung separat auf Modellkompatibilität prüfen.")

    # Layered [all] plus model-specific settings are valid. Report them as context,
    # but reserve warnings for duplicate values within the same matching section.
    expected = {"arm_freq", "v3d_freq", "over_voltage_delta"}
    if model_id == "pi4":
        expected.add("core_freq")
    missing = sorted(key for key in expected if key not in key_latest)
    if missing:
        add("HINWEIS", "–", "Nicht explizit gesetzte Optionen verwenden Firmware-/App-Standardwerte: " + ", ".join(missing) + ".")
    for key in sorted(expected):
        if key in key_latest:
            line_no, section_name, value = key_latest[key]
            if value is not None:
                add("WIRKSAM", line_no, f"Nach dem zuletzt gefundenen passenden Abschnitt ist {key}={value} aktiv vorgesehen (Abschnitt [{section_name}]).")
    if not findings:
        add("OK", "–", "Keine offensichtlichen Konflikte in den verwalteten Taktwerten gefunden. Das ist keine vollständige Firmware-Konfigurationsvalidierung.")
    return findings


def build_tuning_recommendation(
    model_id: str | None,
    current_values: Mapping[str, int] | None,
    status: Any,
    goal: str,
) -> dict[str, Any]:
    """Offer a cautious next step; never writes config.txt or raises limits."""
    limits = LIMITS.get(model_id or "")
    if limits is None:
        return {"title": "Modell nicht unterstützt", "message": "Erst Pi 4 oder Pi 5 eindeutig erkennen. Es werden keine Änderungen empfohlen.", "values": None}
    current = dict(current_values or limits.defaults)
    try:
        current = validate_values(model_id or "", current)
    except (TypeError, ValueError):
        # If config.txt contains out-of-app-range values, recommend from a
        # conservative baseline rather than carrying the invalid values forward.
        current = dict(limits.defaults)
    if getattr(status, "temperature_c", None) is None:
        return {"title": "Messwerte fehlen", "message": "Erst die Telemetrie prüfen. Ohne Temperaturmessung keine Taktsteigerung ausprobieren.", "values": None}
    if status.temperature_c >= 75 or getattr(status, "active_throttling", False) or getattr(status, "undervoltage", False):
        reasons = []
        if status.temperature_c >= 75:
            reasons.append(f"Temperatur {status.temperature_c:.1f} °C")
        if getattr(status, "active_throttling", False):
            reasons.append("Drosselung")
        if getattr(status, "undervoltage", False):
            reasons.append("Unterspannung")
        return {"title": "Erst Stabilität herstellen", "message": "Keine Taktsteigerung empfehlen: " + ", ".join(reasons) + ". Kühlung/Netzteil prüfen und mit dem letzten stabilen Profil vergleichen.", "values": None}

    proposed = {key: int(value) for key, value in current.items() if key in limits.defaults}
    if goal == "Kühl und leise":
        proposed = dict(limits.defaults)
        message = "Konservatives Modell-Standardprofil verwenden. Das senkt nicht automatisch die Lüfterlautstärke; anschließend einen vergleichbaren Benchmark durchführen."
    elif goal == "Mehr Leistung":
        # Keep automatic suggestions conservative even though manual Pi 5 sliders
        # can be moved further into an explicitly experimental range.
        cpu_high = min(limits.arm_max, PI5_CONSERVATIVE_THRESHOLDS.get("arm_freq", limits.arm_max))
        v3d_high = min(limits.v3d_max, PI5_CONSERVATIVE_THRESHOLDS.get("v3d_freq", limits.v3d_max))
        # If the current config is already experimental, do not repeat those values
        # as an assistant recommendation; bring the suggestion back to the threshold.
        proposed["arm_freq"] = min(proposed.get("arm_freq", limits.arm_default), cpu_high)
        proposed["v3d_freq"] = min(proposed.get("v3d_freq", limits.v3d_default), v3d_high)
        if proposed.get("arm_freq", limits.arm_default) < cpu_high:
            proposed["arm_freq"] = min(cpu_high, proposed.get("arm_freq", limits.arm_default) + 50)
        if proposed.get("v3d_freq", limits.v3d_default) < v3d_high:
            proposed["v3d_freq"] = min(v3d_high, proposed.get("v3d_freq", limits.v3d_default) + 20)
        if model_id == "pi4":
            proposed["core_freq"] = min(limits.core_max or limits.core_default or 500,
                                         proposed.get("core_freq", limits.core_default or 500) + 10)
        proposed["over_voltage_delta"] = 0 if proposed.get("over_voltage_delta", 0) < 0 else proposed.get("over_voltage_delta", 0)
        message = "Nur kleine Schritte innerhalb der App-Grenzen vorschlagen. Jede Änderung einzeln anwenden, neu starten und denselben Benchmark wiederholen. Nicht automatisch angewendet."
    else:
        proposed = dict(limits.defaults)
        message = "Ausgewogenes Ausgangsprofil. Erst Baseline messen, dann nur eine Einstellung pro Versuch verändern."
    return {"title": f"Vorschlag: {goal}", "message": message, "values": proposed}


def _command_output(command: list[str], timeout: float = 3.0) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def build_compatibility_report(hardware: Any) -> dict[str, Any]:
    revision = "nicht verfügbar"
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="ascii", errors="ignore").splitlines():
            if line.lower().startswith("revision"):
                revision = line.split(":", 1)[-1].strip()
                break
    except OSError:
        pass
    firmware = _command_output(["vcgencmd", "version"]) or "vcgencmd/Firmware-Info nicht verfügbar"
    return {
        "model": getattr(hardware, "model_name", "unbekannt"),
        "model_id": getattr(hardware, "model_id", None),
        "revision": revision,
        "os": getattr(hardware, "os_name", "unbekannt"),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "firmware": firmware,
        "vcgencmd": shutil.which("vcgencmd") or "nicht installiert",
        "stress_ng": shutil.which("stress-ng") or "nicht installiert",
        "pkexec": shutil.which("pkexec") or "nicht installiert",
    }


def rollback_timer_ready() -> bool:
    required = (
        Path("/usr/local/libexec/takt-engine-rollback-check.py").is_file(),
        Path("/etc/systemd/system/takt-engine-rollback.service").is_file(),
        Path("/etc/systemd/system/takt-engine-rollback.timer").is_file(),
        shutil.which("systemctl") is not None,
    )
    if not all(required):
        return False
    return _command_output(["systemctl", "is-enabled", "takt-engine-rollback.timer"]) == "enabled"


def run_self_test(hardware: Any) -> list[dict[str, Any]]:
    """Run harmless environment checks. Never edits config.txt or stress-tests hardware."""
    results: list[dict[str, Any]] = []

    def add(name: str, ok: bool, details: str) -> None:
        results.append({"name": name, "ok": bool(ok), "details": details})

    add("Python", sys.version_info >= (3, 10), platform.python_version())
    launcher = shutil.which("takt-engine")
    add("Takt-Engine-Starter", launcher is not None, launcher or "Nicht im PATH; installiere das Projekt mit scripts/install-deps.sh")
    add("GTK/PyGObject", importlib.util.find_spec("gi") is not None, "GTK-Import verfügbar" if importlib.util.find_spec("gi") else "Python-Modul gi fehlt")
    add("Raspberry Pi erkannt", bool(getattr(hardware, "is_raspberry_pi", False)), getattr(hardware, "model_name", "unbekannt"))
    config_path = getattr(hardware, "config_path", None)
    try:
        readable = bool(config_path and Path(config_path).is_file() and os.access(config_path, os.R_OK))
    except (OSError, TypeError):
        readable = False
    add("Boot-config lesbar", readable, str(config_path or "Kein unterstützter Pfad gefunden"))
    add("vcgencmd", shutil.which("vcgencmd") is not None, "Telemetrie verfügbar" if shutil.which("vcgencmd") else "Live-Telemetrie eingeschränkt")
    add("stress-ng", shutil.which("stress-ng") is not None, "Benchmark-Werkzeug verfügbar" if shutil.which("stress-ng") else "Benchmark kann nicht gestartet werden")
    add("pkexec", shutil.which("pkexec") is not None, "Rechteabfrage verfügbar" if shutil.which("pkexec") else "Konfigurationsänderungen können nicht authentifiziert werden")
    rollback_ready = rollback_timer_ready()
    add("Rollback-Timer", rollback_ready, "Systemd-Timer aktiviert" if rollback_ready else "Nicht bereit/aktiviert; sichere Testprofile sind deaktiviert")
    return results
