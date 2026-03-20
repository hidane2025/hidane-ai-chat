"""
SQLite database layer for Hidane AI chat system.

Provides persistent storage for conversations and usage analytics.
Thread-safe via connection-per-call pattern.
"""

import csv
import io
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DATABASE_PATH = os.environ.get("DATABASE_PATH", "data/chat.db")


def _db_path() -> str:
    """Resolve DB path and ensure parent directory exists."""
    path = Path(DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def init_db() -> None:
    """Create tables and indexes if they do not exist."""
    with sqlite3.connect(_db_path()) as conn:
        conn.executescript("""
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
        """)


def save_message(
    session_id: str,
    role: str,
    content: str,
    employee_name: str = None,
    employee_id: str = None,
    company_id: str = "hidane",
) -> dict:
    """Insert a message and return it as a new dict."""
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.execute(
            """INSERT INTO conversations
               (session_id, role, content, employee_name, employee_id, company_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, role, content, employee_name, employee_id, company_id),
        )
        return {
            "id": cursor.lastrowid,
            "session_id": session_id,
            "role": role,
            "content": content,
            "employee_name": employee_name,
            "employee_id": employee_id,
            "company_id": company_id,
        }


def get_history(session_id: str, limit: int = 20) -> list[dict]:
    """Return recent messages for a session, compatible with in-memory format.

    Returns list of {"role": ..., "content": ...} dicts (newest last).
    """
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT role, content FROM conversations
               WHERE session_id = ?
               ORDER BY id DESC LIMIT ?""",
            (session_id, limit),
        ).fetchall()
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
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.execute(
            """INSERT INTO usage_logs
               (session_id, user_id, company_id, employee_name,
                message_length, response_length, response_time_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, user_id, company_id, employee_name,
             msg_len, resp_len, resp_time_ms),
        )
        return {
            "id": cursor.lastrowid,
            "session_id": session_id,
            "user_id": user_id,
            "company_id": company_id,
            "employee_name": employee_name,
            "message_length": msg_len,
            "response_length": resp_len,
            "response_time_ms": resp_time_ms,
        }


def get_usage_stats(company_id: str = None, days: int = 7) -> dict:
    """Aggregate usage statistics over the given period. Returns a new dict."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()

    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        where = "WHERE created_at >= ?"
        params: list = [since]
        if company_id is not None:
            where += " AND company_id = ?"
            params.append(company_id)

        total = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM usage_logs {where}", params,
        ).fetchone()["cnt"]

        by_employee_rows = conn.execute(
            f"""SELECT employee_name, COUNT(*) AS cnt
                FROM usage_logs {where}
                GROUP BY employee_name""",
            params,
        ).fetchall()

        by_day_rows = conn.execute(
            f"""SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                FROM usage_logs {where}
                GROUP BY DATE(created_at)
                ORDER BY day""",
            params,
        ).fetchall()

        avg_row = conn.execute(
            f"SELECT AVG(response_time_ms) AS avg_ms FROM usage_logs {where}",
            params,
        ).fetchone()

    return {
        "total_messages": total,
        "by_employee": {
            (r["employee_name"] or "unknown"): r["cnt"] for r in by_employee_rows
        },
        "by_day": {r["day"]: r["cnt"] for r in by_day_rows},
        "avg_response_time_ms": round(avg_row["avg_ms"] or 0),
    }


def export_conversation(session_id: str, fmt: str = "json") -> str:
    """Export a conversation as JSON, CSV, or plain text string."""
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT role, content, employee_name, created_at
               FROM conversations
               WHERE session_id = ?
               ORDER BY id""",
            (session_id,),
        ).fetchall()

    messages = [dict(r) for r in rows]

    if fmt == "json":
        return json.dumps(messages, ensure_ascii=False, indent=2)

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=["role", "content", "employee_name", "created_at"],
        )
        writer.writeheader()
        writer.writerows(messages)
        return buf.getvalue()

    # plain text
    lines = []
    for m in messages:
        speaker = m.get("employee_name") or m["role"]
        lines.append(f"[{m['created_at']}] {speaker}: {m['content']}")
    return "\n".join(lines)


def record_consent(user_id: str, consent_type: str = "terms", version: str = "1.0") -> dict:
    """Record user's consent to terms/privacy."""
    with sqlite3.connect(_db_path()) as conn:
        conn.execute(
            "INSERT INTO user_consents (user_id, consent_type, version) VALUES (?, ?, ?)",
            (user_id, consent_type, version),
        )
        conn.commit()
    return {"user_id": user_id, "consent_type": consent_type, "version": version}


def has_consent(user_id: str, consent_type: str = "terms", version: str = "1.0") -> bool:
    """Check if user has given consent."""
    with sqlite3.connect(_db_path()) as conn:
        row = conn.execute(
            "SELECT id FROM user_consents WHERE user_id = ? AND consent_type = ? AND version = ?",
            (user_id, consent_type, version),
        ).fetchone()
    return row is not None


def cleanup_old(days: int = 90) -> int:
    """Delete records older than the given number of days. Return count deleted."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    total_deleted = 0

    with sqlite3.connect(_db_path()) as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE created_at < ?", (cutoff,),
        )
        total_deleted += cur.rowcount

        cur = conn.execute(
            "DELETE FROM usage_logs WHERE created_at < ?", (cutoff,),
        )
        total_deleted += cur.rowcount

    return total_deleted
