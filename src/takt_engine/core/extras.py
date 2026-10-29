"""Persistence, diagnostics and comparison helpers for Takt Engine.

All persistence is local to the current user. JSON writes are atomic so an
interrupted write does not leave a half-written profile or benchmark history.
"""
from __future__ import annotations

from datetime import datetime, timezone
import difflib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping
import uuid

from .limits import validate_values

MAX_CUSTOM_PROFILES = 50
MAX_BENCHMARK_HISTORY = 50



def build_config_diff(original: str, updated: str) -> list[str]:
    """Return a unified diff suitable for a human-readable config preview."""
    return list(difflib.unified_diff(
        original.splitlines(), updated.splitlines(),
        fromfile="config.txt (aktuell)", tofile="config.txt (geplant)", lineterm="",
    ))


def _config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "takt-engine"


def _data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "takt-engine"


def default_profiles_path() -> Path:
    return _config_dir() / "profiles.json"


def default_benchmark_history_path() -> Path:
    return _data_dir() / "benchmark-history.json"


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_custom_profiles(path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(path) if path is not None else default_profiles_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    profiles = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        model = item.get("model")
        values = item.get("values")
        profile_id = item.get("id")
        if not isinstance(name, str) or not name.strip() or model not in {"pi4", "pi5"}:
            continue
        if not isinstance(values, dict) or not isinstance(profile_id, str) or not profile_id:
            continue
        try:
            normalized = validate_values(model, values)
        except (TypeError, ValueError):
            continue
        profiles.append({
            "id": profile_id,
            "name": name.strip()[:40],
            "model": model,
            "values": normalized,
            "created_at": str(item.get("created_at", "")),
        })
    return profiles[-MAX_CUSTOM_PROFILES:]


def save_custom_profile(
    name: str,
    model_id: str,
    values: Mapping[str, Any],
    path: Path | None = None,
) -> dict[str, Any]:
    clean_name = " ".join(str(name).split())
    if not clean_name:
        raise ValueError("Bitte einen Namen für das Profil eingeben.")
    if len(clean_name) > 40:
        raise ValueError("Profilnamen dürfen höchstens 40 Zeichen lang sein.")
    normalized = validate_values(model_id, values)
    target = Path(path) if path is not None else default_profiles_path()
    profiles = load_custom_profiles(target)
    if any(p["model"] == model_id and p["name"].casefold() == clean_name.casefold() for p in profiles):
        raise ValueError("Für dieses Modell existiert bereits ein Profil mit diesem Namen.")
    if len(profiles) >= MAX_CUSTOM_PROFILES:
        raise ValueError(f"Es können höchstens {MAX_CUSTOM_PROFILES} eigene Profile gespeichert werden.")
    profile = {
        "id": uuid.uuid4().hex,
        "name": clean_name,
        "model": model_id,
        "values": normalized,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    profiles.append(profile)
    _write_json_atomic(target, profiles)
    return profile


def delete_custom_profile(profile_id: str, path: Path | None = None) -> bool:
    target = Path(path) if path is not None else default_profiles_path()
    profiles = load_custom_profiles(target)
    updated = [profile for profile in profiles if profile["id"] != profile_id]
    if len(updated) == len(profiles):
        return False
    _write_json_atomic(target, updated)
    return True


def _status_dict(status: Any) -> dict[str, Any]:
    return {
        "temperature_c": getattr(status, "temperature_c", None),
        "arm_clock_mhz": getattr(status, "arm_clock_mhz", None),
        "v3d_clock_mhz": getattr(status, "v3d_clock_mhz", None),
        "cpu_usage_percent": getattr(status, "cpu_usage_percent", None),
        "throttled_hex": getattr(status, "throttled_hex", None),
        "active_throttling": bool(getattr(status, "active_throttling", False)),
        "undervoltage": bool(getattr(status, "undervoltage", False)),
        "historical_flags": bool(getattr(status, "historical_flags", False)),
        "note": str(getattr(status, "note", "")),
        "fan_rpm": getattr(status, "fan_rpm", None),
        "cooling_states": getattr(status, "cooling_states", None),
    }


def load_benchmark_history(path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(path) if path is not None else default_benchmark_history_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    allowed = {"timestamp", "model", "passed", "duration_seconds", "requested_duration_seconds", "threads",
               "peak_temperature_c", "cpu_clock_mhz", "v3d_clock_mhz", "cpu_usage_percent", "throttled_hex",
               "return_code", "summary"}
    return [item for item in data[-MAX_BENCHMARK_HISTORY:] if isinstance(item, dict) and allowed.issuperset(item)]


def save_benchmark_result(result: Any, model_id: str, path: Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_benchmark_history_path()
    latest = getattr(result, "final_status", None)
    record = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": model_id,
        "passed": bool(getattr(result, "passed", False)),
        "duration_seconds": int(getattr(result, "duration_seconds", 0)),
        "requested_duration_seconds": int(getattr(result, "requested_duration_seconds", getattr(result, "duration_seconds", 0))),
        "threads": int(getattr(result, "threads", 1)),
        "peak_temperature_c": getattr(result, "peak_temperature_c", None),
        "cpu_clock_mhz": getattr(latest, "arm_clock_mhz", None),
        "v3d_clock_mhz": getattr(latest, "v3d_clock_mhz", None),
        "cpu_usage_percent": getattr(latest, "cpu_usage_percent", None),
        "throttled_hex": getattr(latest, "throttled_hex", None),
        "return_code": int(getattr(result, "return_code", -1)),
        "summary": str(getattr(result, "summary", ""))[:500],
    }
    history = load_benchmark_history(target)
    history.append(record)
    _write_json_atomic(target, history[-MAX_BENCHMARK_HISTORY:])
    return record


def build_benchmark_comparison(history: list[Mapping[str, Any]], model_id: str) -> str:
    relevant = [dict(record) for record in history if record.get("model") == model_id]
    if not relevant:
        return "Noch keine gespeicherten Benchmarks für dieses Modell."
    latest = relevant[-1]
    lines = ["Letzte Benchmark-Ergebnisse (neueste zuerst):"]
    for record in reversed(relevant[-5:]):
        state = "BESTANDEN" if record.get("passed") else "NICHT BESTANDEN"
        temp = record.get("peak_temperature_c")
        temp_text = f"{temp:.1f} °C" if isinstance(temp, (int, float)) else "n. v."
        when = str(record.get("timestamp", ""))
        lines.append(f"{when} · {state} · {record.get('duration_seconds', '?')} s · Spitze {temp_text}")
    previous = relevant[-2] if len(relevant) > 1 else None
    if previous is not None:
        same_settings = (
            latest.get("requested_duration_seconds") == previous.get("requested_duration_seconds")
            and latest.get("threads") == previous.get("threads")
        )
        if same_settings:
            old_temp, new_temp = previous.get("peak_temperature_c"), latest.get("peak_temperature_c")
            if isinstance(old_temp, (int, float)) and isinstance(new_temp, (int, float)):
                delta = new_temp - old_temp
                lines.append(f"Temperaturvergleich bei gleicher Testdauer/Thread-Zahl: {delta:+.1f} °C.")
        else:
            lines.append("Temperaturwerte sind nur eingeschränkt vergleichbar: Testdauer oder Thread-Zahl weicht ab.")
        if latest.get("cpu_clock_mhz") is not None and previous.get("cpu_clock_mhz") is not None:
            delta = int(latest["cpu_clock_mhz"]) - int(previous["cpu_clock_mhz"])
            lines.append(f"Gemessener CPU-Taktvergleich: {delta:+d} MHz (Momentaufnahme am Testende).")
        if latest.get("passed") != previous.get("passed"):
            lines.append("Achtung: Der Pass/Fail-Status hat sich gegenüber dem letzten Lauf geändert.")
    return "\n".join(lines)


def build_diagnostic_report(
    hardware: Any,
    status: Any,
    config_values: Mapping[str, Any],
    benchmark_history: list[Mapping[str, Any]],
    app_version: str = "1.1.0",
) -> dict[str, Any]:
    """Build a privacy-conscious report without exporting unrelated config.txt lines."""
    return {
        "app": {"name": "Takt Engine", "version": app_version},
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "hardware": {
            "model_id": getattr(hardware, "model_id", None),
            "model_name": getattr(hardware, "model_name", "unknown"),
            "is_raspberry_pi": bool(getattr(hardware, "is_raspberry_pi", False)),
            "os_name": getattr(hardware, "os_name", "unknown"),
            "config_path": str(getattr(hardware, "config_path", "") or "Not found"),
        },
        "runtime": _status_dict(status),
        "config_values": {str(key): int(value) for key, value in config_values.items()},
        "config_note": "Nur verwaltete Taktwerte werden exportiert; andere config.txt-Zeilen werden nicht aufgenommen.",
        "recent_benchmarks": [dict(entry) for entry in benchmark_history[-10:]],
        "throttling_flags_interpretation": {
            "active_throttling": "Aktuelle Temperatur- oder Leistungsdrosselung erkannt.",
            "undervoltage": "Aktuelle Unterspannung erkannt.",
            "historical_flags": "Seit dem letzten Neustart wurde mindestens ein Warnflag gespeichert.",
        },
    }


def format_diagnostic_report(report: Mapping[str, Any]) -> str:
    app = report.get("app", {})
    hw = report.get("hardware", {})
    rt = report.get("runtime", {})
    config = report.get("config_values", {})
    lines = [
        f"{app.get('name', 'Takt Engine')} Diagnosebericht",
        f"Version: {app.get('version', 'unbekannt')}",
        f"Erstellt: {report.get('generated_at', 'unbekannt')}",
        "",
        "HARDWARE",
        f"Modell: {hw.get('model_name', 'unbekannt')} ({hw.get('model_id') or 'nicht unterstützt'})",
        f"Raspberry Pi erkannt: {'Ja' if hw.get('is_raspberry_pi') else 'Nein'}",
        f"Betriebssystem: {hw.get('os_name', 'unbekannt')}",
        f"config.txt-Pfad: {hw.get('config_path', 'unbekannt')}",
        "",
        "LIVE-TELEMETRIE",
        f"Temperatur: {rt.get('temperature_c') if rt.get('temperature_c') is not None else 'nicht verfügbar'} °C",
        f"CPU-Takt: {rt.get('arm_clock_mhz') if rt.get('arm_clock_mhz') is not None else 'nicht verfügbar'} MHz",
        f"V3D-Takt: {rt.get('v3d_clock_mhz') if rt.get('v3d_clock_mhz') is not None else 'nicht verfügbar'} MHz",
        f"CPU-Auslastung: {rt.get('cpu_usage_percent') if rt.get('cpu_usage_percent') is not None else 'nicht verfügbar'} %",
        f"get_throttled: {rt.get('throttled_hex') or 'nicht verfügbar'}",
        f"Aktive Drosselung: {'Ja' if rt.get('active_throttling') else 'Nein / nicht erkannt'}",
        f"Aktive Unterspannung: {'Ja' if rt.get('undervoltage') else 'Nein / nicht erkannt'}",
        f"Historische Flags: {'Ja' if rt.get('historical_flags') else 'Nein / nicht erkannt'}",
        f"Lüfterdrehzahl: {rt.get('fan_rpm') if rt.get('fan_rpm') is not None else 'nicht verfügbar'} RPM",
        f"Kühlungsstatus: {rt.get('cooling_states') or 'nicht verfügbar'}",
        f"Telemetrie-Hinweis: {rt.get('note') or 'keiner'}",
        "",
        "KONFIGURIERTE TAKTWERTE (keine komplette config.txt)",
    ]
    lines.extend(f"{key} = {value}" for key, value in config.items())
    lines.extend(["", "LETZTE BENCHMARKS"])
    benchmarks = report.get("recent_benchmarks", [])
    if not benchmarks:
        lines.append("Keine gespeicherten Benchmark-Ergebnisse.")
    else:
        for entry in benchmarks:
            temp = entry.get("peak_temperature_c")
            temp_text = f"{temp:.1f} °C" if isinstance(temp, (int, float)) else "nicht verfügbar"
            lines.append(
                f"{entry.get('timestamp', '?')} · {'BESTANDEN' if entry.get('passed') else 'NICHT BESTANDEN'} · "
                f"{entry.get('duration_seconds', '?')} s · max. {temp_text} · {entry.get('model', '?')}"
            )
    lines.extend(["", str(report.get("config_note", ""))])
    return "\n".join(lines) + "\n"

# ---------------------------------------------------------------------------
# Additional diagnostics and persistence introduced in Takt Engine 1.2.0
# ---------------------------------------------------------------------------
MAX_TUNING_HISTORY = 200


def default_tuning_history_path() -> Path:
    return _data_dir() / "tuning-history.json"


def default_reboot_state_path() -> Path:
    return _config_dir() / "reboot-state.json"


def current_boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return "unknown"


def load_tuning_history(path: Path | None = None) -> list[dict[str, Any]]:
    target = Path(path) if path is not None else default_tuning_history_path()
    try:
        records = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(records, list):
        return []
    safe_records = []
    allowed = {"timestamp", "model", "old_values", "new_values", "changed_keys", "temperature_c", "backup", "note"}
    for record in records[-MAX_TUNING_HISTORY:]:
        if not isinstance(record, dict) or set(record) - allowed:
            continue
        if record.get("model") not in {"pi4", "pi5"}:
            continue
        if not isinstance(record.get("old_values"), dict) or not isinstance(record.get("new_values"), dict):
            continue
        safe_records.append(record)
    return safe_records


def record_tuning_change(
    model_id: str,
    old_values: Mapping[str, Any],
    new_values: Mapping[str, Any],
    temperature_c: float | None = None,
    backup: str | None = None,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Store only managed tuning values; never copy arbitrary config.txt lines."""
    old = {key: int(value) for key, value in old_values.items() if key in {"arm_freq", "v3d_freq", "core_freq", "over_voltage_delta"}}
    new = {key: int(value) for key, value in new_values.items() if key in {"arm_freq", "v3d_freq", "core_freq", "over_voltage_delta"}}
    changed = sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
    if not changed:
        return None
    record = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": model_id,
        "old_values": old,
        "new_values": new,
        "changed_keys": changed,
        "temperature_c": float(temperature_c) if isinstance(temperature_c, (int, float)) else None,
        "backup": Path(backup).name if backup else None,
        "note": "config.txt wurde über Takt Engine geändert; Neustart kann erforderlich sein.",
    }
    target = Path(path) if path is not None else default_tuning_history_path()
    history = load_tuning_history(target)
    history.append(record)
    _write_json_atomic(target, history[-MAX_TUNING_HISTORY:])
    return record


def format_tuning_history(records: list[Mapping[str, Any]], limit: int = 20) -> str:
    if not records:
        return "Noch keine Änderungen über Takt Engine protokolliert."
    lines = ["Änderungsverlauf (neueste zuerst):"]
    for record in reversed(records[-limit:]):
        old_values = record.get("old_values", {})
        new_values = record.get("new_values", {})
        changed = record.get("changed_keys", [])
        details = []
        for key in changed:
            before = old_values.get(key, "–")
            after = new_values.get(key, "–")
            details.append(f"{key}: {before} → {after}")
        temp = record.get("temperature_c")
        temp_text = f" · Temperatur {temp:.1f} °C" if isinstance(temp, (int, float)) else ""
        lines.append(f"{record.get('timestamp', '?')} · {record.get('model', '?').upper()} · " + ", ".join(details) + temp_text)
    return "\n".join(lines)


def save_pending_apply(
    model_id: str,
    values: Mapping[str, Any],
    trial_rollback: bool = False,
    path: Path | None = None,
    boot_id: str | None = None,
) -> dict[str, Any]:
    state = {
        "model": model_id,
        "values": {str(key): int(value) for key, value in values.items()},
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "boot_id": boot_id if boot_id is not None else current_boot_id(),
        "trial_rollback": bool(trial_rollback),
        "verification": "reboot_pending",
        "verification_note": "Konfiguration wurde geschrieben; Neustart-Verifikation steht aus.",
    }
    target = Path(path) if path is not None else default_reboot_state_path()
    _write_json_atomic(target, state)
    return state


def load_pending_apply(path: Path | None = None) -> dict[str, Any] | None:
    target = Path(path) if path is not None else default_reboot_state_path()
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or state.get("model") not in {"pi4", "pi5"} or not isinstance(state.get("values"), dict):
        return None
    return state


def verify_pending_apply(
    state: Mapping[str, Any],
    now_boot_id: str,
    firmware_values: Mapping[str, Any] | None,
    config_values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify config-file consistency, reboot, then values exposed by firmware."""
    expected = state.get("values", {})
    config_values = config_values or {}
    config_mismatched = [key for key, value in expected.items()
                         if key in config_values and str(config_values[key]) != str(value)]
    if config_mismatched:
        return {
            "status": "config_mismatch",
            "message": "Die aktuelle config.txt weicht vom zuletzt angewendeten Profil ab: " + ", ".join(config_mismatched) + ". Manuelle Änderung oder Wiederherstellung prüfen.",
            "matched": [], "mismatched": config_mismatched, "unknown": [],
        }
    if state.get("boot_id") == now_boot_id:
        return {"status": "reboot_pending", "message": "Noch kein Neustart seit dem letzten Anwenden erkannt.", "matched": [], "mismatched": [], "unknown": []}
    firmware_values = firmware_values or {}
    matched, mismatched, unknown = [], [], []
    for key, value in expected.items():
        if key not in firmware_values or firmware_values.get(key) is None:
            unknown.append(key)
        elif str(firmware_values[key]).strip() == str(value):
            matched.append(key)
        else:
            mismatched.append(key)
    if mismatched:
        status = "mismatch"
        message = "Nach dem Neustart weichen auslesbare Firmwarewerte ab: " + ", ".join(mismatched) + ". Bitte config.txt und Firmware-Ausgabe prüfen."
    elif unknown:
        status = "partial"
        message = "Neustart erkannt. Firmware bestätigt nicht alle Einstellungen lesbar; tatsächlichen Takt und Statuswerte zusätzlich prüfen."
    else:
        status = "confirmed"
        message = "Neustart erkannt; alle geprüften Firmwarewerte stimmen mit den gespeicherten Sollwerten überein."
    return {"status": status, "message": message, "matched": matched, "mismatched": mismatched, "unknown": unknown}


def update_pending_verification(result: Mapping[str, Any], path: Path | None = None) -> None:
    state = load_pending_apply(path)
    if state is None:
        return
    state["verification"] = str(result.get("status", "unknown"))
    state["verification_note"] = str(result.get("message", ""))[:500]
    state["verification_checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    target = Path(path) if path is not None else default_reboot_state_path()
    _write_json_atomic(target, state)


def export_custom_profile(profile: Mapping[str, Any], target_path: Path) -> Path:
    """Export one sanitized profile as a portable JSON file."""
    model = profile.get("model")
    values = validate_values(str(model), profile.get("values", {}))
    name = " ".join(str(profile.get("name", "Profil")).split())[:40] or "Profil"
    payload = {
        "format": "takt-engine-profile",
        "schema_version": 1,
        "profile": {"name": name, "model": model, "values": values},
    }
    target = Path(target_path)
    _write_json_atomic(target, payload)
    return target


def import_custom_profile(source_path: Path, model_id: str, profiles_path: Path | None = None) -> dict[str, Any]:
    """Validate a small JSON profile and store it locally for the selected model."""
    source = Path(source_path)
    if source.stat().st_size > 64 * 1024:
        raise ValueError("Profil-Datei ist zu groß (maximal 64 KiB).")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Ungültige JSON-Profil-Datei: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != "takt-engine-profile" or payload.get("schema_version") != 1:
        raise ValueError("Datei ist kein unterstütztes Takt-Engine-Profil (Schema-Version 1).")
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("Profilobjekt fehlt.")
    if profile.get("model") != model_id:
        raise ValueError(f"Dieses Profil ist für {profile.get('model')!r}, erkannt wurde {model_id!r}.")
    return save_custom_profile(str(profile.get("name", "")), model_id, profile.get("values", {}), path=profiles_path)


def update_reboot_state_fields(fields: Mapping[str, Any], path: Path | None = None) -> None:
    """Update selected metadata without altering the original apply timestamp/boot ID."""
    state = load_pending_apply(path)
    if state is None:
        return
    for key, value in fields.items():
        if key in {"trial_rollback", "verification", "verification_note", "verification_checked_at", "trial_confirmed_at"}:
            state[key] = value
    target = Path(path) if path is not None else default_reboot_state_path()
    _write_json_atomic(target, state)
