from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from services.db import get_db_connection

DEFAULT_ADMIN_EMAIL = "admin@houseai.com"
DEFAULT_ADMIN_PASSWORD = "HouseAI123"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def password_hash(password: str) -> str:
    secret = "houseai-local-demo-salt"
    return hashlib.sha256((secret + password).encode("utf-8")).hexdigest()


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
        "created_at": str(user.get("created_at")) if user.get("created_at") else None,
        "last_login": str(user.get("last_login")) if user.get("last_login") else None,
    }


def ensure_database_tables() -> None:
    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            email VARCHAR(150) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'user',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_activity (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NULL,
            user_name VARCHAR(150),
            user_email VARCHAR(150),
            user_role VARCHAR(50),
            action_type VARCHAR(100),
            description TEXT,
            meta JSON,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()


def ensure_admin_user() -> None:
    ensure_database_tables()

    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE email = %s", (DEFAULT_ADMIN_EMAIL,))
    admin = cursor.fetchone()

    if not admin:
        cursor.execute("""
            INSERT INTO users (name, email, password_hash, role, created_at, last_login)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            "HouseAI Admin",
            DEFAULT_ADMIN_EMAIL,
            password_hash(DEFAULT_ADMIN_PASSWORD),
            "admin",
            now_text(),
            None
        ))

        conn.commit()

    cursor.close()
    conn.close()


def load_users() -> List[Dict[str, Any]]:
    ensure_admin_user()

    conn = get_db_connection()
    if not conn:
        return []

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users ORDER BY id ASC")
    users = cursor.fetchall()

    cursor.close()
    conn.close()

    return users


def find_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    ensure_admin_user()

    email = str(email or "").strip().lower()

    conn = get_db_connection()
    if not conn:
        return None

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()

    cursor.close()
    conn.close()

    return user


def register_user(name: str, email: str, password: str) -> Dict[str, Any]:
    ensure_admin_user()

    name = str(name or "").strip()
    email = str(email or "").strip().lower()
    password = str(password or "")

    if len(name) < 2:
        return {"success": False, "message": "Ad soyad en az 2 karakter olmalı."}

    if "@" not in email or "." not in email:
        return {"success": False, "message": "Geçerli bir e-posta adresi gir."}

    if len(password) < 6:
        return {"success": False, "message": "Şifre en az 6 karakter olmalı."}

    if find_user_by_email(email):
        return {"success": False, "message": "Bu e-posta ile zaten kayıt var."}

    conn = get_db_connection()
    if not conn:
        return {"success": False, "message": "Veritabanı bağlantı hatası."}

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        INSERT INTO users (name, email, password_hash, role, created_at, last_login)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        name,
        email,
        password_hash(password),
        "user",
        now_text(),
        None
    ))

    conn.commit()
    user_id = cursor.lastrowid

    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    cursor.close()
    conn.close()

    log_activity(
        user=public_user(user),
        action_type="register",
        description="Kullanıcı kayıt oldu.",
        meta={},
    )

    return {
        "success": True,
        "message": "Kayıt başarılı.",
        "user": public_user(user),
    }


def verify_user_login(email: str, password: str) -> Optional[Dict[str, Any]]:
    ensure_admin_user()

    email = str(email or "").strip().lower()
    password = str(password or "")

    user = find_user_by_email(email)

    if not user:
        return None

    if user.get("password_hash") != password_hash(password):
        return None

    conn = get_db_connection()
    if not conn:
        return None

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        UPDATE users
        SET last_login = %s
        WHERE id = %s
    """, (now_text(), user["id"]))

    conn.commit()

    cursor.execute("SELECT * FROM users WHERE id = %s", (user["id"],))
    updated_user = cursor.fetchone()

    cursor.close()
    conn.close()

    public = public_user(updated_user)

    log_activity(
        user=public,
        action_type="login",
        description="Kullanıcı giriş yaptı.",
        meta={},
    )

    return public


def log_activity(
    user: Optional[Dict[str, Any]],
    action_type: str,
    description: str,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    if not user:
        return

    ensure_database_tables()

    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO user_activity
        (user_id, user_name, user_email, user_role, action_type, description, meta, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        user.get("id"),
        user.get("name"),
        user.get("email"),
        user.get("role"),
        action_type,
        description,
        json.dumps(meta or {}, ensure_ascii=False),
        now_text()
    ))

    conn.commit()
    cursor.close()
    conn.close()


def get_user_activities(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    ensure_database_tables()

    conn = get_db_connection()
    if not conn:
        return []

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT *
        FROM user_activity
        WHERE user_id = %s
        ORDER BY id DESC
        LIMIT %s
    """, (int(user_id), int(limit)))

    activities = cursor.fetchall()

    cursor.close()
    conn.close()

    return activities


def get_recent_activities(limit: int = 50) -> List[Dict[str, Any]]:
    ensure_database_tables()

    conn = get_db_connection()
    if not conn:
        return []

    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT *
        FROM user_activity
        ORDER BY id DESC
        LIMIT %s
    """, (int(limit),))

    activities = cursor.fetchall()

    cursor.close()
    conn.close()

    return activities


def get_activity_summary() -> Dict[str, Any]:
    ensure_admin_user()

    conn = get_db_connection()
    if not conn:
        return {
            "total_activities": 0,
            "today_activities": 0,
            "price_prediction_count": 0,
            "seller_analysis_count": 0,
            "map_chat_count": 0,
            "today_registered_count": 0,
            "active_user_count": 0,
            "recent_activities": [],
        }

    cursor = conn.cursor(dictionary=True)

    today = today_text() + "%"

    cursor.execute("SELECT COUNT(*) AS count FROM user_activity")
    total_activities = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) AS count FROM user_activity WHERE created_at LIKE %s", (today,))
    today_activities = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) AS count FROM user_activity WHERE action_type = 'price_prediction'")
    price_prediction_count = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) AS count FROM user_activity WHERE action_type = 'seller_analysis'")
    seller_analysis_count = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) AS count FROM user_activity WHERE action_type = 'map_chat'")
    map_chat_count = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) AS count FROM users WHERE created_at LIKE %s", (today,))
    today_registered_count = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(DISTINCT user_id) AS count FROM user_activity WHERE user_id IS NOT NULL")
    active_user_count = cursor.fetchone()["count"]

    cursor.execute("""
        SELECT *
        FROM user_activity
        ORDER BY id DESC
        LIMIT 20
    """)
    recent_activities = cursor.fetchall()

    cursor.close()
    conn.close()

    return {
        "total_activities": total_activities,
        "today_activities": today_activities,
        "price_prediction_count": price_prediction_count,
        "seller_analysis_count": seller_analysis_count,
        "map_chat_count": map_chat_count,
        "today_registered_count": today_registered_count,
        "active_user_count": active_user_count,
        "recent_activities": recent_activities,
    }