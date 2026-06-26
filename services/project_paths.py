from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def find_project_root() -> Path:
    current = Path(__file__).resolve()

    for parent in [current.parent, *current.parents]:
        if (parent / "data").exists():
            return parent

    return Path(__file__).resolve().parent.parent


BASE_DIR = find_project_root()

DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
IMPORTS_DIR = BASE_DIR / "imports"
LOGS_DIR = BASE_DIR / "logs"
BACKUPS_DIR = BASE_DIR / "backups"
JOBS_DIR = BASE_DIR / "jobs"
PAGES_DIR = BASE_DIR / "pages"
STATIC_DIR = BASE_DIR / "static"

LISTINGS_PATH = DATA_DIR / "listings.json"
DISTRICT_CENTERS_PATH = DATA_DIR / "district_centers.json"
USERS_PATH = DATA_DIR / "users.json"
USER_ACTIVITY_PATH = DATA_DIR / "user_activity.json"


def load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = []

    path = Path(path)

    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)