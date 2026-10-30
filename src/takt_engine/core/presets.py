"""Load the bundled model-specific profiles."""
import json
from pathlib import Path
from typing import Any


PROFILE_CATEGORIES = {"standard", "performance", "undervolting"}


def load_presets(path: Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        path = Path(__file__).resolve().parents[1] / "data" / "presets.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("presets.json muss mindestens ein Profil enthalten.")

    seen_ids = set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Jeder Eintrag in presets.json muss ein Profilobjekt sein.")
        required = ("id", "name", "description", "model", "values", "warning")
        if any(not item.get(key) for key in required):
            raise ValueError("Ein Profil in presets.json enthält Pflichtfelder nicht.")
        profile_id = str(item["id"])
        if profile_id in seen_ids:
            raise ValueError(f"Profil-ID ist doppelt vorhanden: {profile_id}")
        seen_ids.add(profile_id)
        if item.get("category") not in PROFILE_CATEGORIES:
            item["category"] = "performance"
    return data
