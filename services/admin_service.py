from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
IMPORTS_DIR = BASE_DIR / "imports"
LOGS_DIR = BASE_DIR / "logs"

USERS_PATH = DATA_DIR / "users.json"
LISTINGS_PATH = DATA_DIR / "listings.json"

LAST_RUN_PATH = IMPORTS_DIR / "daily_pipeline_last_run.json"
ADDED_PATH = IMPORTS_DIR / "emlakjet_added_apply.json"
PENDING_PATH = IMPORTS_DIR / "emlakjet_pending.json"
REJECTED_PATH = IMPORTS_DIR / "emlakjet_rejected.json"
SKIPPED_PATH = IMPORTS_DIR / "emlakjet_skipped.json"

IMPORT_STATUS_PATH = IMPORTS_DIR / "admin_import_status.json"

AUTOMATION_SCRIPT = BASE_DIR / "jobs" / "otomatik_veri_cekme.py"

DEFAULT_ADMIN_EMAIL = "admin@houseai.com"
DEFAULT_ADMIN_PASSWORD = "HouseAI123"


_import_lock = threading.Lock()
_import_thread: Optional[threading.Thread] = None


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def password_hash(password: str) -> str:
    secret = "houseai-local-demo-salt"
    return hashlib.sha256((secret + password).encode("utf-8")).hexdigest()


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
        "created_at": user.get("created_at"),
        "last_login": user.get("last_login"),
    }


def ensure_users_file() -> None:
    if USERS_PATH.exists():
        users = load_json(USERS_PATH, [])

        if isinstance(users, list) and users:
            return

    users = [
        {
            "id": 1,
            "name": "HouseAI Admin",
            "email": DEFAULT_ADMIN_EMAIL,
            "password_hash": password_hash(DEFAULT_ADMIN_PASSWORD),
            "role": "admin",
            "created_at": now_text(),
            "last_login": None,
        }
    ]

    save_json(USERS_PATH, users)


def load_users() -> List[Dict[str, Any]]:
    ensure_users_file()

    users = load_json(USERS_PATH, [])

    if not isinstance(users, list):
        users = []

    return users


def save_users(users: List[Dict[str, Any]]) -> None:
    save_json(USERS_PATH, users)


def verify_login(email: str, password: str) -> Optional[Dict[str, Any]]:
    email = str(email or "").strip().lower()
    password = str(password or "")

    users = load_users()

    for user in users:
        if str(user.get("email", "")).strip().lower() != email:
            continue

        if user.get("password_hash") != password_hash(password):
            return None

        user["last_login"] = now_text()
        save_users(users)

        return public_user(user)

    return None


def is_admin(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False

    return user.get("role") == "admin"


def get_users_summary() -> Dict[str, Any]:
    users = load_users()

    total_users = len(users)
    admin_count = sum(1 for user in users if user.get("role") == "admin")
    normal_user_count = sum(1 for user in users if user.get("role") == "user")

    latest_users = sorted(
        users,
        key=lambda x: str(x.get("created_at", "")),
        reverse=True,
    )[:10]

    return {
        "total_users": total_users,
        "admin_count": admin_count,
        "normal_user_count": normal_user_count,
        "latest_users": [public_user(user) for user in latest_users],
    }


def get_listings() -> List[Dict[str, Any]]:
    listings = load_json(LISTINGS_PATH, [])

    if not isinstance(listings, list):
        listings = []

    return listings


def get_latest_added_listings(limit: int = 30) -> List[Dict[str, Any]]:
    added = load_json(ADDED_PATH, [])

    if isinstance(added, list) and added:
        return added[:limit]

    listings = get_listings()

    emlakjet_items = [
        item for item in listings
        if item.get("source") == "emlakjet" or item.get("emlakjet_listing_id")
    ]

    emlakjet_items = sorted(
        emlakjet_items,
        key=lambda x: int(x.get("id", 0) or 0),
        reverse=True,
    )

    return emlakjet_items[:limit]


def get_last_run_summary() -> Dict[str, Any]:
    summary = load_json(LAST_RUN_PATH, {})

    if not isinstance(summary, dict):
        summary = {}

    return summary


def get_import_status() -> Dict[str, Any]:
    status = load_json(IMPORT_STATUS_PATH, {})

    if not isinstance(status, dict):
        status = {}

    default_status = {
        "running": False,
        "started_at": None,
        "finished_at": None,
        "success": None,
        "message": "Henüz veri çekme işlemi başlatılmadı.",
        "log_file": None,
        "summary": get_last_run_summary(),
    }

    default_status.update(status)

    return default_status


def set_import_status(status: Dict[str, Any]) -> None:
    save_json(IMPORT_STATUS_PATH, status)


def count_today_users(users: List[Dict[str, Any]]) -> int:
    today = datetime.now().strftime("%Y-%m-%d")

    return sum(
        1 for user in users
        if str(user.get("created_at", "")).startswith(today)
    )


def build_admin_stats() -> Dict[str, Any]:
    listings = get_listings()
    users = load_users()
    user_summary = get_users_summary()

    last_run = get_last_run_summary()
    added = load_json(ADDED_PATH, [])
    rejected = load_json(REJECTED_PATH, [])
    skipped = load_json(SKIPPED_PATH, [])

    if not isinstance(added, list):
        added = []

    if not isinstance(rejected, list):
        rejected = []

    if not isinstance(skipped, list):
        skipped = []

    emlakjet_count = sum(
        1 for item in listings
        if item.get("source") == "emlakjet" or item.get("emlakjet_listing_id")
    )

    with_coord_count = sum(
        1 for item in listings
        if item.get("lat") is not None and item.get("lng") is not None
    )

    return {
        "total_listings": len(listings),
        "emlakjet_listings": emlakjet_count,
        "with_coord_count": with_coord_count,
        "total_users": user_summary["total_users"],
        "admin_count": user_summary["admin_count"],
        "normal_user_count": user_summary["normal_user_count"],
        "today_users": count_today_users(users),
        "last_added_count": len(added),
        "last_rejected_count": len(rejected),
        "last_skipped_count": len(skipped),
        "last_run": last_run,
        "import_status": get_import_status(),
    }


def run_import_job() -> None:
    global _import_thread

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)

    started_at = now_text()
    log_name = f"admin_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_path = LOGS_DIR / log_name

    set_import_status({
        "running": True,
        "started_at": started_at,
        "finished_at": None,
        "success": None,
        "message": "Veri çekme işlemi çalışıyor...",
        "log_file": str(log_path),
        "summary": get_last_run_summary(),
    })

    try:
        if not AUTOMATION_SCRIPT.exists():
            raise FileNotFoundError(
                f"otomatik_veri_cekme.py bulunamadı: {AUTOMATION_SCRIPT}"
            )

        with open(log_path, "w", encoding="utf-8") as log_file:
            log_file.write("HOUSEAI ADMIN IMPORT START\n")
            log_file.write(f"Started at: {started_at}\n")
            log_file.write("=" * 80 + "\n\n")

            process = subprocess.run(
                [sys.executable, str(AUTOMATION_SCRIPT)],
                cwd=str(BASE_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=60 * 60,
            )

            log_file.write("\n" + "=" * 80 + "\n")
            log_file.write(f"Exit code: {process.returncode}\n")
            log_file.write(f"Finished at: {now_text()}\n")

        success = process.returncode == 0
        summary = get_last_run_summary()

        if success:
            message = "Veri çekme işlemi tamamlandı."
        else:
            message = "Veri çekme işlemi hata ile bitti. Log dosyasını kontrol et."

        set_import_status({
            "running": False,
            "started_at": started_at,
            "finished_at": now_text(),
            "success": success,
            "message": message,
            "log_file": str(log_path),
            "summary": summary,
        })

    except Exception as error:
        set_import_status({
            "running": False,
            "started_at": started_at,
            "finished_at": now_text(),
            "success": False,
            "message": f"Hata oluştu: {str(error)}",
            "log_file": str(log_path),
            "summary": get_last_run_summary(),
        })


def start_import_background() -> Dict[str, Any]:
    global _import_thread

    with _import_lock:
        status = get_import_status()

        if status.get("running"):
            return {
                "success": False,
                "message": "Veri çekme işlemi zaten çalışıyor.",
                "status": status,
            }

        _import_thread = threading.Thread(
            target=run_import_job,
            daemon=True,
        )

        _import_thread.start()

        return {
            "success": True,
            "message": "Veri çekme işlemi başlatıldı.",
            "status": get_import_status(),
        }