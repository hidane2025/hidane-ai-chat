"""
Database layer for Hidane AI chat system.

Supports PostgreSQL (production/Render) and SQLite (local dev).
Backend is selected automatically:
  - If DATABASE_URL env var is set -> PostgreSQL via psycopg2
  - Otherwise -> SQLite at DATABASE_PATH (default: data/chat.db)

Thread-safe via connection-per-call pattern.
"""

import csv
import io
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Optional PostgreSQL support
# ---------------------------------------------------------------------------
try:
    import psycopg2
    import psycopg2.extras
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "data/chat.db")


def _use_postgres() -> bool:
    """Return True when PostgreSQL should be used."""
    return DATABASE_URL is not None and _HAS_PSYCOPG2


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _db_path() -> str:
    """Resolve SQLite DB path and ensure parent directory exists."""
    path = Path(DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _get_connection():
    """Return a DB-API 2.0 connection (PostgreSQL or SQLite)."""
    if _use_postgres():
        url = DATABASE_URL
        # Render may provide postgres:// but psycopg2 needs postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url)
    return sqlite3.connect(_db_path())


def _placeholder() -> str:
    """Return the parameter placeholder for the active backend."""
    return "%s" if _use_postgres() else "?"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    employee_name TEXT,
    employee_id TEXT,
    company_id TEXT DEFAULT 'hidane',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS usage_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    user_id TEXT,
    company_id TEXT DEFAULT 'hidane',
    employee_name TEXT,
    message_length INTEGER,
    response_length INTEGER,
    response_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conv_session
    ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conv_company
    ON conversations(company_id);
CREATE INDEX IF NOT EXISTS idx_usage_session
    ON usage_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_usage_company
    ON usage_logs(company_id);

CREATE TABLE IF NOT EXISTS user_consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    consent_type TEXT NOT NULL DEFAULT 'terms',
    version TEXT NOT NULL DEFAULT '1.0',
    consented_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    company_id TEXT NOT NULL DEFAULT 'hidane',
    role TEXT NOT NULL DEFAULT 'user',
    display_name TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email
    ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_company
    ON users(company_id);
"""

_POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    employee_name TEXT,
    employee_id TEXT,
    company_id TEXT DEFAULT 'hidane',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS usage_logs (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    user_id TEXT,
    company_id TEXT DEFAULT 'hidane',
    employee_name TEXT,
    message_length INTEGER,
    response_length INTEGER,
    response_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conv_session
    ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conv_company
    ON conversations(company_id);
CREATE INDEX IF NOT EXISTS idx_usage_session
    ON usage_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_usage_company
    ON usage_logs(company_id);

CREATE TABLE IF NOT EXISTS user_consents (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    consent_type TEXT NOT NULL DEFAULT 'terms',
    version TEXT NOT NULL DEFAULT '1.0',
    consented_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    company_id TEXT NOT NULL DEFAULT 'hidane',
    role TEXT NOT NULL DEFAULT 'user',
    display_name TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email
    ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_company
    ON users(company_id);
"""


# ---------------------------------------------------------------------------
# Row helper – normalise rows to dicts regardless of backend
# ---------------------------------------------------------------------------

def _fetchall_dicts(cursor, columns: List[str]) -> List[Dict]:
    """Convert cursor rows to a list of dicts using given column names."""
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _fetchone_dict(cursor, columns: List[str]) -> Optional[Dict]:
    """Convert a single cursor row to a dict (or None)."""
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip(columns, row))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create tables and indexes if they do not exist."""
    conn = _get_connection()
    try:
        if _use_postgres():
            cursor = conn.cursor()
            cursor.execute(_POSTGRES_SCHEMA)
            conn.commit()
        else:
            conn.executescript(_SQLITE_SCHEMA)
    finally:
        conn.close()


def save_message(
    session_id: str,
    role: str,
    content: str,
    employee_name: str = None,
    employee_id: str = None,
    company_id: str = "hidane",
) -> dict:
    """Insert a message and return it as a new dict."""
    ph = _placeholder()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        if _use_postgres():
            cursor.execute(
                f"""INSERT INTO conversations
                   (session_id, role, content, employee_name, employee_id, company_id)
                   VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                   RETURNING id""",
                (session_id, role, content, employee_name, employee_id, company_id),
            )
            last_id = cursor.fetchone()[0]
        else:
            cursor.execute(
                f"""INSERT INTO conversations
                   (session_id, role, content, employee_name, employee_id, company_id)
                   VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})""",
                (session_id, role, content, employee_name, employee_id, company_id),
            )
            last_id = cursor.lastrowid
        conn.commit()
        return {
            "id": last_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "employee_name": employee_name,
            "employee_id": employee_id,
            "company_id": company_id,
        }
    finally:
        conn.close()


def get_history(session_id: str, limit: int = 20) -> List[Dict]:
    """Return recent messages for a session, compatible with in-memory format.

    Returns list of {"role": ..., "content": ...} dicts (newest last).
    """
    ph = _placeholder()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""SELECT role, content FROM conversations
               WHERE session_id = {ph}
               ORDER BY id DESC LIMIT {ph}""",
            (session_id, limit),
        )
        rows = _fetchall_dicts(cursor, ["role", "content"])
    finally:
        conn.close()
    # Reverse so oldest-first (matches in-memory conversation order)
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def log_usage(
    session_id: str,
    user_id: str,
    company_id: str,
    employee_name: str,
    msg_len: int,
    resp_len: int,
    resp_time_ms: int,
) -> dict:
    """Record a usage event and return it as a new dict."""
    ph = _placeholder()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        if _use_postgres():
            cursor.execute(
                f"""INSERT INTO usage_logs
                   (session_id, user_id, company_id, employee_name,
                    message_length, response_length, response_time_ms)
                   VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                   RETURNING id""",
                (session_id, user_id, company_id, employee_name,
                 msg_len, resp_len, resp_time_ms),
            )
            last_id = cursor.fetchone()[0]
        else:
            cursor.execute(
                f"""INSERT INTO usage_logs
                   (session_id, user_id, company_id, employee_name,
                    message_length, response_length, response_time_ms)
                   VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})""",
                (session_id, user_id, company_id, employee_name,
                 msg_len, resp_len, resp_time_ms),
            )
            last_id = cursor.lastrowid
        conn.commit()
        return {
            "id": last_id,
            "session_id": session_id,
            "user_id": user_id,
            "company_id": company_id,
            "employee_name": employee_name,
            "message_length": msg_len,
            "response_length": resp_len,
            "response_time_ms": resp_time_ms,
        }
    finally:
        conn.close()


def get_usage_stats(company_id: str = None, days: int = 7) -> dict:
    """Aggregate usage statistics over the given period. Returns a new dict."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    ph = _placeholder()

    conn = _get_connection()
    try:
        cursor = conn.cursor()

        where = f"WHERE created_at >= {ph}"
        params = [since]  # type: List
        if company_id is not None:
            where += f" AND company_id = {ph}"
            params.append(company_id)

        # total count
        cursor.execute(
            f"SELECT COUNT(*) AS cnt FROM usage_logs {where}", params,
        )
        total = cursor.fetchone()[0]

        # by employee
        cursor.execute(
            f"""SELECT employee_name, COUNT(*) AS cnt
                FROM usage_logs {where}
                GROUP BY employee_name""",
            params,
        )
        by_employee_rows = _fetchall_dicts(cursor, ["employee_name", "cnt"])

        # by day – DATE() works in both SQLite and PostgreSQL
        cursor.execute(
            f"""SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                FROM usage_logs {where}
                GROUP BY DATE(created_at)
                ORDER BY day""",
            params,
        )
        by_day_rows = _fetchall_dicts(cursor, ["day", "cnt"])

        # average response time
        cursor.execute(
            f"SELECT AVG(response_time_ms) AS avg_ms FROM usage_logs {where}",
            params,
        )
        avg_ms = cursor.fetchone()[0]
    finally:
        conn.close()

    return {
        "total_messages": total,
        "by_employee": {
            (r["employee_name"] or "unknown"): r["cnt"] for r in by_employee_rows
        },
        "by_day": {str(r["day"]): r["cnt"] for r in by_day_rows},
        "avg_response_time_ms": round(avg_ms or 0),
    }


def export_conversation(session_id: str, fmt: str = "json") -> str:
    """Export a conversation as JSON, CSV, or plain text string."""
    ph = _placeholder()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""SELECT role, content, employee_name, created_at
               FROM conversations
               WHERE session_id = {ph}
               ORDER BY id""",
            (session_id,),
        )
        messages = _fetchall_dicts(
            cursor, ["role", "content", "employee_name", "created_at"],
        )
    finally:
        conn.close()

    # Ensure created_at is a string (PostgreSQL returns datetime objects)
    for m in messages:
        if not isinstance(m.get("created_at"), str):
            m = dict(m, created_at=str(m["created_at"]))

    if fmt == "json":
        # Normalise datetime objects to strings for JSON serialisation
        serialisable = []
        for m in messages:
            row = dict(m)
            if not isinstance(row.get("created_at"), str):
                row["created_at"] = str(row["created_at"])
            serialisable.append(row)
        return json.dumps(serialisable, ensure_ascii=False, indent=2)

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=["role", "content", "employee_name", "created_at"],
        )
        writer.writeheader()
        csv_rows = []
        for m in messages:
            row = dict(m)
            if not isinstance(row.get("created_at"), str):
                row["created_at"] = str(row["created_at"])
            csv_rows.append(row)
        writer.writerows(csv_rows)
        return buf.getvalue()

    # plain text
    lines = []
    for m in messages:
        speaker = m.get("employee_name") or m["role"]
        ts = m["created_at"] if isinstance(m["created_at"], str) else str(m["created_at"])
        lines.append(f"[{ts}] {speaker}: {m['content']}")
    return "\n".join(lines)


def record_consent(user_id: str, consent_type: str = "terms", version: str = "1.0") -> dict:
    """Record user's consent to terms/privacy."""
    ph = _placeholder()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO user_consents (user_id, consent_type, version) VALUES ({ph}, {ph}, {ph})",
            (user_id, consent_type, version),
        )
        conn.commit()
    finally:
        conn.close()
    return {"user_id": user_id, "consent_type": consent_type, "version": version}


def has_consent(user_id: str, consent_type: str = "terms", version: str = "1.0") -> bool:
    """Check if user has given consent."""
    ph = _placeholder()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT id FROM user_consents WHERE user_id = {ph} AND consent_type = {ph} AND version = {ph}",
            (user_id, consent_type, version),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    return row is not None


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

_USER_COLUMNS = ["id", "email", "password_hash", "company_id", "role",
                 "display_name", "is_active", "created_at", "updated_at"]


def db_create_user(email: str, password_hash: str, company_id: str = "hidane",
                   role: str = "user", display_name: str = None) -> Optional[Dict]:
    """Insert a new user. Returns user dict (without password_hash) or None if email exists."""
    ph = _placeholder()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        if _use_postgres():
            cursor.execute(
                f"""INSERT INTO users (email, password_hash, company_id, role, display_name)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT (email) DO NOTHING
                    RETURNING id, email, company_id, role, display_name, is_active, created_at""",
                (email, password_hash, company_id, role, display_name),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            conn.commit()
            cols = ["id", "email", "company_id", "role", "display_name", "is_active", "created_at"]
            return dict(zip(cols, row))
        else:
            try:
                cursor.execute(
                    f"""INSERT INTO users (email, password_hash, company_id, role, display_name)
                        VALUES ({ph}, {ph}, {ph}, {ph}, {ph})""",
                    (email, password_hash, company_id, role, display_name),
                )
                conn.commit()
                return {
                    "id": cursor.lastrowid, "email": email, "company_id": company_id,
                    "role": role, "display_name": display_name, "is_active": True,
                }
            except sqlite3.IntegrityError:
                return None
    finally:
        conn.close()


def db_get_user_by_email(email: str) -> Optional[Dict]:
    """Fetch a user by email. Returns full user dict including password_hash, or None."""
    ph = _placeholder()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {', '.join(_USER_COLUMNS)} FROM users WHERE email = {ph}",
            (email,),
        )
        return _fetchone_dict(cursor, _USER_COLUMNS)
    finally:
        conn.close()


def db_list_users(company_id: str = None) -> List[Dict]:
    """List users, optionally filtered by company_id. Never includes password_hash."""
    safe_cols = [c for c in _USER_COLUMNS if c != "password_hash"]
    ph = _placeholder()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        if company_id:
            cursor.execute(
                f"SELECT {', '.join(safe_cols)} FROM users WHERE company_id = {ph} ORDER BY created_at",
                (company_id,),
            )
        else:
            cursor.execute(f"SELECT {', '.join(safe_cols)} FROM users ORDER BY created_at")
        return _fetchall_dicts(cursor, safe_cols)
    finally:
        conn.close()


def db_update_user(email: str, **fields) -> Optional[Dict]:
    """Update user fields. Only allows: role, display_name, is_active, password_hash.
    Returns updated user dict (without password_hash) or None if not found."""
    allowed = {"role", "display_name", "is_active", "password_hash"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return None
    ph = _placeholder()
    set_clause = ", ".join(f"{k} = {ph}" for k in updates)
    values = list(updates.values()) + [email]
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE email = {ph}",
            values,
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
    finally:
        conn.close()
    # Return updated user (without password_hash)
    user = db_get_user_by_email(email)
    if user:
        return {k: v for k, v in user.items() if k != "password_hash"}
    return None


def db_deactivate_user(email: str) -> bool:
    """Soft-delete a user by setting is_active=False. Returns True if found."""
    result = db_update_user(email, is_active=False)
    return result is not None


def db_migrate_from_json(json_path: str) -> int:
    """Migrate users from a users.json file into the database. Returns count migrated."""
    import json as _json
    path = Path(json_path)
    if not path.exists():
        return 0
    with open(path, "r", encoding="utf-8") as f:
        users = _json.load(f)
    count = 0
    for email, data in users.items():
        existing = db_get_user_by_email(email)
        if existing is None:
            db_create_user(
                email=email,
                password_hash=data["password_hash"],
                company_id=data.get("company_id", "hidane"),
                role=data.get("role", "user"),
                display_name=data.get("display_name"),
            )
            count += 1
    return count


def cleanup_old(days: int = 90) -> int:
    """Delete records older than the given number of days. Return count deleted."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    ph = _placeholder()
    total_deleted = 0

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"DELETE FROM conversations WHERE created_at < {ph}", (cutoff,),
        )
        total_deleted += cursor.rowcount

        cursor.execute(
            f"DELETE FROM usage_logs WHERE created_at < {ph}", (cutoff,),
        )
        total_deleted += cursor.rowcount
        conn.commit()
    finally:
        conn.close()

    return total_deleted
