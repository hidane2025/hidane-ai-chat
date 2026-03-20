"""JWT authentication module for Hidane AI chat system."""

import json
import os
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import bcrypt
import jwt
from flask import request, jsonify

JWT_SECRET = os.environ.get("JWT_SECRET", "hidane-dev-secret-do-not-use-in-prod")
TOKEN_EXPIRY_SECONDS = 86400  # 24 hours
USERS_FILE = Path(__file__).parent / "users.json"


def _read_users():
    """Read users from JSON file. Returns a dict."""
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_users(users):
    """Write users dict to JSON file."""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _init_default_admin():
    """Create users.json with default admin if it doesn't exist."""
    if USERS_FILE.exists():
        return
    hashed = bcrypt.hashpw("hidane2026".encode("utf-8"), bcrypt.gensalt())
    users = {
        "admin@hidane.co.jp": {
            "password_hash": hashed.decode("utf-8"),
            "company_id": "hidane",
            "role": "admin",
            "display_name": "Admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    _write_users(users)


def create_token(user_id, company_id, role="user"):
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


def verify_token(token):
    """Verify and decode a JWT token. Returns payload dict or None."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def _extract_token():
    """Extract token from Authorization header or cookie. Returns str or None."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.cookies.get("auth_token")


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


def authenticate_user(email, password):
    """Authenticate user by email and password. Returns token string or None."""
    users = _read_users()
    user = users.get(email)
    if user is None:
        return None
    if not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        return None
    return create_token(
        user_id=email,
        company_id=user["company_id"],
        role=user.get("role", "user"),
    )


def register_user(email, password, company_id, display_name):
    """Register a new user. Returns new user dict (without password) or None if exists."""
    users = _read_users()
    if email in users:
        return None
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    new_user = {
        "password_hash": hashed.decode("utf-8"),
        "company_id": company_id,
        "role": "user",
        "display_name": display_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Immutable: create new dict instead of mutating
    updated_users = {**users, email: new_user}
    _write_users(updated_users)
    # Return user info without password hash
    return {
        "email": email,
        "company_id": company_id,
        "role": "user",
        "display_name": display_name,
    }


# Initialize default admin on import
_init_default_admin()
