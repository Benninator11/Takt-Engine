#!/usr/bin/env python3
"""Systemd timer helper: revert an unconfirmed tuning trial after a reboot.

This can only act after Linux and systemd start. It cannot recover firmware
failures that prevent the operating system from booting at all.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

STATE_DIR = Path("/var/lib/takt-engine/rollback")
PENDING = STATE_DIR / "pending.json"
BACKUP = STATE_DIR / "config.txt.before-trial.bak"
ALLOWED_PATHS = {Path("/boot/firmware/config.txt"), Path("/boot/config.txt")}


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return "unknown"


def atomic_restore(target: Path, content: bytes, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".takt-engine-rollback-", dir=str(target.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, target)
    except Exception:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def main() -> int:
    if not PENDING.is_file():
        return 0
    try:
        state = json.loads(PENDING.read_text(encoding="utf-8"))
        target = Path(state["config_path"])
        armed_boot = str(state["armed_boot_id"])
        if state.get("confirmed"):
            PENDING.unlink(missing_ok=True)
            BACKUP.unlink(missing_ok=True)
            print("Takt Engine: Teststart wurde bereits bestätigt; Rollback nicht erforderlich.")
            return 0
        if target not in ALLOWED_PATHS:
            raise ValueError("Nicht erlaubter Boot-Konfigurationspfad im Rollback-Status.")
        if boot_id() == armed_boot:
            # The timer may fire during the same boot where the user changed
            # config.txt. Only the first boot after that change is a trial.
            return 0
        if not BACKUP.is_file() or not target.is_file():
            raise FileNotFoundError("Rollback-Sicherung oder config.txt fehlt; keine automatische Änderung durchgeführt.")
        mode = target.stat().st_mode & 0o777
        atomic_restore(target, BACKUP.read_bytes(), mode)
        PENDING.unlink(missing_ok=True)
        BACKUP.unlink(missing_ok=True)
        print(f"Takt Engine: Testprofil nicht innerhalb des Zeitfensters bestätigt. Vorherige Konfiguration wurde nach {target} zurückgespielt.")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Takt Engine Rollback-Fehler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
