"""Config parsing, managed block generation, and timestamped backups."""
from datetime import datetime
from pathlib import Path
import os
import re
import shutil
import tempfile
from typing import Mapping

from .limits import validate_values

BEGIN_MARKER = "# BEGIN TAKT ENGINE MANAGED BLOCK - Do not edit this block in the app"
END_MARKER = "# END TAKT ENGINE MANAGED BLOCK"
KEY_ORDER = ("arm_freq", "v3d_freq", "core_freq", "over_voltage_delta")
CONFIG_KEYS = frozenset(KEY_ORDER)


def parse_config_values(original: str, model_id: str, defaults: Mapping[str, int]) -> dict[str, int]:
    """Read the last applicable Takt Engine setting for a Pi model.

    Raspberry Pi config.txt uses filters such as [all], [pi4] and [pi5].
    Values in non-matching sections are ignored; the last assignment in an
    applicable section wins, matching the usual config.txt override pattern.
    Values absent from the file use the model's standard values supplied by
    ``defaults``. Included config files are intentionally not followed here.
    """
    if model_id not in {"pi4", "pi5"}:
        raise ValueError(f"Nicht unterstütztes Modell für config.txt: {model_id!r}")

    values = {key: int(value) for key, value in defaults.items() if key in CONFIG_KEYS}
    section_applies = True  # Lines before the first filter apply to all models.

    for raw_line in original.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if line.startswith("[") and "]" in line:
            closing = line.find("]")
            section_name = line[1:closing].strip().lower()
            section_applies = section_name in {"all", model_id}
            continue

        if not section_applies or "=" not in line:
            continue

        key, raw_value = (part.strip() for part in line.split("=", 1))
        if key not in values:
            continue
        # Clock/offset settings in config.txt are decimal integers in normal
        # use; also accept hex values for completeness.
        try:
            try:
                value = int(raw_value, 10)
            except ValueError:
                value = int(raw_value, 0)
        except ValueError:
            continue
        values[key] = value

    return values


def read_config(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def render_managed_config(original: str, model_id: str, values: Mapping[str, int]) -> str:
    """Preserve the user's config and replace only the Takt Engine-managed block."""
    normalized = validate_values(model_id, values)
    # Remove only a previous complete managed block. If markers are damaged,
    # refuse to edit rather than accidentally deleting a large section.
    begin_count = original.count(BEGIN_MARKER)
    end_count = original.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("Der Takt-Engine-Konfigurationsblock ist beschädigt oder doppelt vorhanden. Datei bitte manuell prüfen.")
    cleaned = original
    if begin_count == 1:
        pattern = re.compile(
            re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER) + r"\s*",
            re.DOTALL,
        )
        cleaned = pattern.sub("", original, count=1)
    cleaned = cleaned.rstrip()
    lines = ["", BEGIN_MARKER, f"[{model_id}]"]
    for key in KEY_ORDER:
        if key in normalized:
            lines.append(f"{key}={normalized[key]}")
    lines.append(END_MARKER)
    result = cleaned + "\n" + "\n".join(lines) + "\n"
    if any(len(line) > 98 for line in result.splitlines()):
        raise ValueError("Eine config.txt-Zeile überschreitet das Firmware-Limit von 98 Zeichen.")
    return result


def create_backup(config_path: Path, backup_dir: Path | None = None) -> Path:
    """Create a timestamped backup before making privileged changes."""
    if not config_path.is_file():
        raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {config_path}")
    if backup_dir is None:
        backup_dir = Path.home() / ".config" / "takt-engine" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / f"{config_path.name}.{stamp}.bak"
    shutil.copy2(config_path, backup_path)
    return backup_path


def restore_backup(backup_path: Path, target_path: Path) -> None:
    """Restore a selected backup to a file already writable by the caller."""
    if not backup_path.is_file():
        raise FileNotFoundError(f"Sicherung nicht gefunden: {backup_path}")
    target_path.write_bytes(backup_path.read_bytes())


def write_config_atomically(path: Path, content: str) -> None:
    """Atomic write helper used by tests and the privileged writer."""
    original_mode = None
    try:
        original_mode = path.stat().st_mode & 0o777
    except OSError:
        pass
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if original_mode is not None:
            try:
                os.chmod(temporary, original_mode)
            except OSError:
                pass
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
