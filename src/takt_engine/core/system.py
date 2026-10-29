"""Small, testable helpers for system-level actions."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable


class SystemActionError(RuntimeError):
    """An operating-system action could not be requested safely."""


def build_reboot_command(
    *,
    is_root: bool,
    systemctl_path: str,
    pkexec_path: str | None = None,
) -> list[str]:
    """Build an argument vector for reboot; never use a shell string."""
    if not systemctl_path or not Path(systemctl_path).is_absolute():
        raise SystemActionError("Der absolute Pfad zu systemctl fehlt.")
    if is_root:
        return [systemctl_path, "reboot"]
    if not pkexec_path:
        raise SystemActionError("pkexec wurde nicht gefunden. Installiere pkexec und polkitd.")
    return [pkexec_path, systemctl_path, "reboot"]


def request_system_reboot(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    which: Callable[[str], str | None] | None = None,
    geteuid: Callable[[], int] | None = None,
    timeout: float = 20,
) -> subprocess.CompletedProcess[str]:
    """Request a full Raspberry Pi reboot through systemd, elevating only this action."""
    run_command = runner or subprocess.run
    find_command = which or shutil.which
    effective_uid = geteuid or getattr(os, "geteuid", lambda: 1)

    systemctl_path = find_command("systemctl")
    if not systemctl_path and Path("/usr/bin/systemctl").is_file():
        systemctl_path = "/usr/bin/systemctl"
    if not systemctl_path:
        raise SystemActionError("systemctl wurde nicht gefunden. Ein Systemneustart ist nicht möglich.")

    root = effective_uid() == 0
    pkexec_path = None if root else find_command("pkexec")
    command = build_reboot_command(
        is_root=root,
        systemctl_path=systemctl_path,
        pkexec_path=pkexec_path,
    )

    try:
        result = run_command(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise SystemActionError(f"{command[0]} konnte nicht gestartet werden.") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemActionError(
            f"Nach {timeout:g} Sekunden kam keine Rückmeldung. Falls der Neustart nicht begonnen hat, "
            "prüfe die Systemautorisierung und versuche es erneut."
        ) from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Keine weitere Fehlermeldung.").strip()
        raise SystemActionError(f"systemctl reboot wurde abgelehnt (Code {result.returncode}).\n{detail}")
    return result
