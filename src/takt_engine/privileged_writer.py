"""Root helper called through pkexec; deliberately accepts only known config paths."""
import argparse
import json
import os
from pathlib import Path
import pwd
import sys
import tempfile
from datetime import datetime, timezone

# Running this file directly puts .../takt_engine on sys.path, not .../src.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from takt_engine.core.config import read_config, render_managed_config, write_config_atomically  # noqa: E402
from takt_engine.core.limits import ValidationError, validate_values  # noqa: E402

ALLOWED_CONFIG_PATHS = {Path("/boot/firmware/config.txt"), Path("/boot/config.txt")}
ROLLBACK_DIR = Path("/var/lib/takt-engine/rollback")
ROLLBACK_PENDING = ROLLBACK_DIR / "pending.json"
ROLLBACK_BACKUP = ROLLBACK_DIR / "config.txt.before-trial.bak"
ROLLBACK_CHECKER = Path("/usr/local/libexec/takt-engine-rollback-check.py")
ROLLBACK_TIMER = Path("/etc/systemd/system/takt-engine-rollback.timer")


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return "unknown"


def _atomic_bytes(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    except Exception:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _clear_rollback_state(requester_uid: int | None = None) -> None:
    if not ROLLBACK_PENDING.exists():
        return
    state = json.loads(ROLLBACK_PENDING.read_text(encoding="utf-8"))
    if requester_uid is not None and int(state.get("requester_uid", -1)) != requester_uid:
        raise ValueError("Dieser Teststart gehört einem anderen Desktop-Benutzer.")
    ROLLBACK_PENDING.unlink(missing_ok=True)
    ROLLBACK_BACKUP.unlink(missing_ok=True)


def _arm_rollback(path: Path, original: str) -> None:
    requester = os.environ.get("PKEXEC_UID")
    if requester is None or not requester.isdigit():
        raise ValueError("Benutzeridentität konnte nicht geprüft werden; automatischer Rollback wird nicht aktiviert.")
    if not ROLLBACK_CHECKER.is_file() or not ROLLBACK_TIMER.is_file():
        raise ValueError("Rollback-Dienst nicht installiert. Bitte den Installer erneut ausführen; config.txt wurde zurückgesetzt.")
    if ROLLBACK_PENDING.exists():
        raise ValueError("Ein Testprofil wartet bereits auf Bestätigung. Bestätige es oder warte auf den Rollback, bevor du weitere Werte anwendest.")
    _atomic_bytes(ROLLBACK_BACKUP, original.encode("utf-8", errors="replace"), 0o600)
    state = {
        "config_path": str(path),
        "armed_boot_id": _boot_id(),
        "armed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requester_uid": int(requester),
        "confirmed": False,
    }
    _atomic_bytes(ROLLBACK_PENDING, (json.dumps(state, indent=2) + "\n").encode("utf-8"), 0o600)


def _confirm_rollback() -> None:
    requester = os.environ.get("PKEXEC_UID")
    if requester is None or not requester.isdigit():
        raise ValueError("Benutzeridentität konnte nicht geprüft werden.")
    if not ROLLBACK_PENDING.is_file():
        raise ValueError("Kein aktives Testprofil zur Bestätigung gefunden. Es wurde möglicherweise bereits zurückgerollt.")
    _clear_rollback_state(int(requester))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validierter Takt-Engine-Konfigurationsschreiber")
    parser.add_argument("--config")
    parser.add_argument("--model", choices=("pi4", "pi5"))
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--values", help="JSON-Objekt mit freigegebenen Werten")
    operation.add_argument("--restore-backup", help="Pfad zu einer Takt-Engine-Sicherung")
    operation.add_argument("--confirm-rollback", action="store_true", help="Teststart bestätigen und automatischen Rollback deaktivieren")
    parser.add_argument("--arm-rollback", action="store_true", help="Vorherige Konfiguration als Teststart-Sicherung hinterlegen")
    args = parser.parse_args()
    try:
        if args.confirm_rollback:
            if args.config or args.model or args.arm_rollback:
                raise ValueError("Ungültige Kombination für --confirm-rollback.")
            _confirm_rollback()
            print("Teststart bestätigt; automatische Rückkehr deaktiviert.")
            return 0
        if not args.config or not args.model:
            raise ValueError("--config und --model sind für diese Operation erforderlich.")
        path = Path(args.config)
        if path not in ALLOWED_CONFIG_PATHS:
            raise ValueError("Aus Sicherheitsgründen sind nur die üblichen Raspberry-Pi-Bootpfade erlaubt.")
        if not path.is_file():
            raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {path}")
        if args.restore_backup:
            if args.arm_rollback:
                raise ValueError("Rollback-Armierung und Wiederherstellung können nicht kombiniert werden.")
            requester = os.environ.get("PKEXEC_UID")
            if requester is None or not requester.isdigit():
                raise ValueError("Die Identität des aufrufenden Desktop-Benutzers konnte nicht geprüft werden.")
            requester_uid = int(requester)
            requester_home = Path(pwd.getpwuid(requester_uid).pw_dir)
            expected_dir = (requester_home / ".config" / "takt-engine" / "backups").resolve()
            backup = Path(args.restore_backup).resolve()
            if backup.parent != expected_dir or not backup.name.startswith("config.txt.") or not backup.name.endswith(".bak"):
                raise ValueError("Es dürfen nur Takt-Engine-Sicherungen aus dem Benutzer-Backupordner wiederhergestellt werden.")
            if not backup.is_file() or backup.stat().st_uid != requester_uid:
                raise ValueError("Sicherung fehlt oder gehört nicht dem aufrufenden Benutzer.")
            write_config_atomically(path, backup.read_text(encoding="utf-8", errors="replace"))
            _clear_rollback_state(requester_uid)
            print(f"Sicherung {backup.name} wurde nach {path} zurückgespielt. Ein Neustart ist erforderlich.")
            return 0
        if ROLLBACK_PENDING.exists():
            raise ValueError("Ein sicheres Testprofil wartet noch auf Bestätigung oder Rückkehr. Weitere Änderungen sind bis dahin gesperrt.")
        values = json.loads(args.values)
        if not isinstance(values, dict):
            raise ValueError("Werte müssen ein JSON-Objekt sein.")
        normalized = validate_values(args.model, values)
        current = read_config(path)
        updated = render_managed_config(current, args.model, normalized)
        write_config_atomically(path, updated)
        if args.arm_rollback:
            try:
                _arm_rollback(path, current)
            except Exception:
                # If the rollback state cannot be armed, restore the exact
                # original bytes so the user is never left with an unprotected trial.
                write_config_atomically(path, current)
                raise
    except (OSError, ValueError, json.JSONDecodeError, ValidationError, KeyError) as exc:
        print(f"Takt Engine: {exc}", file=sys.stderr)
        return 2
    print(f"{path} wurde aktualisiert. Ein Neustart ist erforderlich.")
    if args.arm_rollback:
        print("Sicheres Testprofil aktiviert: Nach einem Neustart muss innerhalb von 120 Sekunden bestätigt werden, sonst wird die vorherige config.txt zurückgespielt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
