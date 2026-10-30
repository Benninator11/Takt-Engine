"""Safe application path: validate, back up, then ask for elevation on demand."""
import json
from pathlib import Path
import subprocess
import sys
from typing import Mapping

from .config import create_backup
from .limits import validate_values
from .fan_curve import validate_fan_curve


def apply_settings(config_path: Path, model_id: str, values: Mapping[str, int], arm_rollback: bool = False) -> tuple[Path, subprocess.CompletedProcess[str]]:
    normalized = validate_values(model_id, values)
    backup = create_backup(config_path)
    helper = Path(__file__).resolve().parents[1] / "privileged_writer.py"
    command = [
        "pkexec", sys.executable, str(helper),
        "--config", str(config_path),
        "--model", model_id,
        "--values", json.dumps(normalized, separators=(",", ":")),
    ]
    if arm_rollback:
        command.append("--arm-rollback")
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("pkexec wurde nicht gefunden. Installiere pkexec und polkitd oder nutze das Installationsskript.") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Abgebrochen oder fehlgeschlagen.").strip()
        raise RuntimeError(f"Konfiguration wurde nicht angewendet. Sicherung bleibt erhalten: {backup}\n{detail}")
    return backup, result



def apply_fan_curve(config_path: Path, points, hysteresis_c: float = 5.0) -> tuple[Path, subprocess.CompletedProcess[str]]:
    """Back up config.txt, then ask the root helper to write native Pi 5 fan params."""
    normalized = validate_fan_curve(points, hysteresis_c)
    config_path = Path(config_path)
    backup = create_backup(config_path)
    helper = Path(__file__).resolve().parents[1] / "privileged_writer.py"
    command = [
        "pkexec", sys.executable, str(helper),
        "--config", str(config_path),
        "--model", "pi5",
        "--fan-curve", json.dumps(normalized, separators=(",", ":")),
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=35)
    except FileNotFoundError as exc:
        raise RuntimeError("pkexec wurde nicht gefunden. Installiere pkexec und polkitd oder nutze das Installationsskript.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Die Lüfterkurve konnte nicht rechtzeitig gespeichert werden.") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Abgebrochen oder fehlgeschlagen.").strip()
        raise RuntimeError(f"Lüfterkurve wurde nicht gespeichert. Sicherung bleibt erhalten: {backup}\n{detail}")
    return backup, result


def restore_config_backup(config_path: Path, model_id: str, backup_path: Path) -> tuple[Path, subprocess.CompletedProcess[str]]:
    """Restore one Takt Engine backup, keeping a fresh backup of current settings."""
    backup_path = Path(backup_path).resolve()
    backup_dir = (Path.home() / ".config" / "takt-engine" / "backups").resolve()
    if backup_path.parent != backup_dir or not backup_path.name.startswith("config.txt.") or not backup_path.name.endswith(".bak"):
        raise ValueError("Es dürfen nur Sicherungen aus ~/.config/takt-engine/backups/ ausgewählt werden.")
    if not backup_path.is_file():
        raise FileNotFoundError(f"Sicherung nicht gefunden: {backup_path}")
    current_backup = create_backup(config_path)
    helper = Path(__file__).resolve().parents[1] / "privileged_writer.py"
    command = [
        "pkexec", sys.executable, str(helper),
        "--config", str(config_path),
        "--model", model_id,
        "--restore-backup", str(backup_path),
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("pkexec wurde nicht gefunden. Installiere pkexec und polkitd oder nutze das Installationsskript.") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Abgebrochen oder fehlgeschlagen.").strip()
        raise RuntimeError(f"Wiederherstellung fehlgeschlagen. Aktuelle Konfiguration ist gesichert: {current_backup}\n{detail}")
    return current_backup, result


def confirm_boot_rollback() -> subprocess.CompletedProcess[str]:
    """Ask the privileged helper to confirm a boot test for the current user."""
    helper = Path(__file__).resolve().parents[1] / "privileged_writer.py"
    command = ["pkexec", sys.executable, str(helper), "--confirm-rollback"]
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Rollback-Bestätigung konnte nicht ausgeführt werden: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Abgebrochen oder fehlgeschlagen.").strip()
        raise RuntimeError(detail)
    return result
