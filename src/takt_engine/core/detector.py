"""Raspberry Pi model and boot configuration detection."""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class HardwareInfo:
    model_id: Optional[str]
    model_name: str
    is_raspberry_pi: bool
    config_path: Optional[Path]
    os_name: str


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").replace("\x00", "").strip()
    except (OSError, PermissionError):
        return ""


def detect_model(model_text: str, cpuinfo_text: str = "") -> tuple[Optional[str], str, bool]:
    """Return (model_id, display name, is_raspberry_pi)."""
    combined = f"{model_text}\n{cpuinfo_text}".lower()
    if "raspberry pi 5" in combined or "bcm2712" in combined:
        return "pi5", "Raspberry Pi 5", True
    if "raspberry pi 4" in combined or "bcm2711" in combined:
        return "pi4", "Raspberry Pi 4", True
    if "raspberry pi" in combined:
        return None, model_text or "Nicht unterstützter Raspberry Pi", True
    return None, model_text or "Kein Raspberry Pi erkannt", False


def detect_hardware(
    model_path: Path = Path("/proc/device-tree/model"),
    cpuinfo_path: Path = Path("/proc/cpuinfo"),
    os_release_path: Path = Path("/etc/os-release"),
    firmware_config: Path = Path("/boot/firmware/config.txt"),
    legacy_config: Path = Path("/boot/config.txt"),
) -> HardwareInfo:
    model_text = _read_text(model_path)
    cpuinfo_text = _read_text(cpuinfo_path)
    model_id, model_name, is_pi = detect_model(model_text, cpuinfo_text)
    config_path = firmware_config if firmware_config.is_file() else legacy_config if legacy_config.is_file() else None

    os_release = _read_text(os_release_path)
    os_name = "Raspberry Pi OS / Debian"
    for line in os_release.splitlines():
        if line.startswith("PRETTY_NAME="):
            os_name = line.split("=", 1)[1].strip().strip('"')
            break
    return HardwareInfo(model_id, model_name, is_pi, config_path, os_name)
