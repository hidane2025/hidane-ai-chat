"""JWT authentication module for Hidane AI chat system.

Uses database-backed user storage (PostgreSQL/SQLite).
Falls back to users.json migration on first run.
"""

import os
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import bcrypt
import jwt
from flask import request, jsonify

from database import (
    db_get_user_by_email, db_create_user, db_migrate_from_json,
)

JWT_SECRET = os.environ.get("JWT_SECRET", "hidane-dev-secret-do-not-use-in-prod")
TOKEN_EXPIRY_SECONDS = 86400  # 24 hours
USERS_JSON_PATH = Path(__file__).parent / "users.json"


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def create_token(user_id: str, company_id: str, role: str = "user") -> str:
    """Create a JWT token. Returns a token string."""
    now = int(time.time())
    payload = {
        "user_id": user_id,
        "company_id": company_id,
        "role": role,
        "iat": now,
        "exp": now + TOKEN_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_token(token: str) -> dict:
    """Verify and decode a JWT token. Returns payload dict or None."""
    if not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def _extract_token() -> str:
    """Extract token from Authorization header or cookie. Returns str or None."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.cookies.get("auth_token")


# ---------------------------------------------------------------------------
# Flask decorators
# ---------------------------------------------------------------------------

def require_auth(f):
    """Flask decorator that requires valid JWT authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_token()
        if token is None:
            return jsonify({"error": "Authentication required"}), 401
        payload = verify_token(token)
        if payload is None:
            return jsonify({"error": "Invalid or expired token"}), 401
        request.user = payload
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """Flask decorator that requires admin role."""
    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        if request.user.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# User authentication (DB-backed)
# ---------------------------------------------------------------------------

def authenticate_user(email: str, password: str) -> str:
    """Authenticate user by email and password. Returns token string or None."""
    user = db_get_user_by_email(email)
    if user is None:
        return None
    if not user.get("is_active", True):
        return None
    if not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        return None
    return create_token(
        user_id=email,
        company_id=user["company_id"],
        role=user.get("role", "user"),
    )


def register_user(email: str, password: str, company_id: str,
                   display_name: str = None, role: str = "user") -> dict:
    """Register a new user. Returns user dict (without password) or None if exists."""
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return db_create_user(
        email=email,
        password_hash=hashed.decode("utf-8"),
        company_id=company_id,
        role=role,
        display_name=display_name,
    )


# ---------------------------------------------------------------------------
# Initialization: migrate users.json → DB on first run
# ---------------------------------------------------------------------------

def _init_users_db():
    """Ensure at least the default admin exists in the database."""
    # Migrate from users.json if it exists
    if USERS_JSON_PATH.exists():
        migrated = db_migrate_from_json(str(USERS_JSON_PATH))
        if migrated > 0:
            print(f"[auth] Migrated {migrated} users from users.json to database")

    # Ensure default admin exists
    admin = db_get_user_by_email("admin@hidane.co.jp")
    if admin is None:
        hashed = bcrypt.hashpw("hidane2026".encode("utf-8"), bcrypt.gensalt())
        db_create_user(
            email="admin@hidane.co.jp",
            password_hash=hashed.decode("utf-8"),
            company_id="hidane",
            role="admin",
            display_name="Admin",
        )
        print("[auth] Default admin created: admin@hidane.co.jp")


# Run on import (after database.init_db() has been called from app.py)
# Defer to avoid circular import — called explicitly from app.py
