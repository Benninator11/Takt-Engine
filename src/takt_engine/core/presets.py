"""Load the bundled model-specific profiles."""
import json
from pathlib import Path
from typing import Any


def load_presets(path: Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        root = Path(__file__).resolve().parents[3]
        project_copy = root / "data" / "presets.json"
        package_copy = Path(__file__).resolve().parents[1] / "data" / "presets.json"
        path = project_copy if project_copy.is_file() else package_copy
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) != 10:
        raise ValueError("presets.json muss genau zehn Profile enthalten.")
    return data
