"""
ヒダネ AI社員チャットシステム
- Web Chat UI: http://localhost:5555
- LINE Bot Webhook: http://localhost:5555/line/webhook
- 管理画面: http://localhost:5555/admin
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory, redirect
from flask_cors import CORS

from employees import (
    EMPLOYEES, route_message, get_employee, get_all_employees,
    get_departments, get_department_responder, DEPARTMENTS,
)
from knowledge import build_knowledge_context
from knowledge_admin import build_custom_context
from database import init_db, save_message, get_history, log_usage, export_conversation, has_consent, record_consent
from streaming import stream_claude_response, make_sse_response
from rate_limiter import rate_limit
from line_handler import handle_line_webhook
from admin_routes import admin_bp
from system_prompt import build_system_prompt
from auth import create_token, authenticate_user, verify_token, require_auth, require_admin, _read_users, _extract_token

app = Flask(__name__)

# CORS: 本番ではオリジン制限
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*")
CORS(app, origins=ALLOWED_ORIGINS.split(","))

# 設定
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

# DB初期化
init_db()

# 管理画面Blueprint登録
app.register_blueprint(admin_bp)


# ============================================================
# Auth
# ============================================================

@app.route("/auth/login", methods=["GET", "POST"])
def auth_login():
    if request.method == "GET":
        return render_template("login.html")
    data = request.form if request.form else (request.json or {})
    email = data.get("email", "")
    password = data.get("password", "")
    token = authenticate_user(email, password)
    if not token:
        if request.form:
            return render_template("login.html", error="メールアドレスまたはパスワードが正しくありません")
        return jsonify({"error": "Invalid credentials"}), 401
    # Read user info for JSON response
    users = _read_users()
    user_info = users.get(email, {})
    if request.form:
        resp = redirect("/")
        resp.set_cookie("auth_token", token, httponly=True, samesite="Lax", max_age=86400)
        return resp
    return jsonify({"token": token, "user": {"email": email, "role": user_info.get("role", "user")}})


@app.route("/auth/logout")
def auth_logout():
    resp = redirect("/auth/login")
    resp.delete_cookie("auth_token")
    return resp


# ============================================================
# Web Chat UI
# ============================================================

CONSENT_VERSION = "1.0"


@app.route("/")
def index():
    """メインチャットUI（ログイン不要・公開）"""
    return render_template("chat.html")


def _user_has_full_consent(user_id: str) -> bool:
    """Check if user has consented to both terms and privacy policy."""
    return (
        has_consent(user_id, "terms", CONSENT_VERSION)
        and has_consent(user_id, "privacy", CONSENT_VERSION)
    )


@app.route("/terms")
def terms():
    """利用規約"""
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    """プライバシーポリシー"""
    return render_template("privacy.html")


@app.route("/consent")
def consent_page():
    """同意画面（認証済み・未同意ユーザー向け）"""
    token = request.cookies.get("auth_token")
    payload = verify_token(token) if token else None
    if not payload:
        return redirect("/auth/login")
    user_id = payload.get("user_id", "")
    if _user_has_full_consent(user_id):
        return redirect("/")
    return render_template("consent.html")


@app.route("/api/consent/status")
def api_consent_status():
    """現在のユーザーの同意状況を返す"""
    token = _extract_token()
    payload = verify_token(token) if token else None
    if not payload:
        return jsonify({"error": "Authentication required"}), 401
    user_id = payload.get("user_id", "")
    return jsonify({
        "terms": has_consent(user_id, "terms", CONSENT_VERSION),
        "privacy": has_consent(user_id, "privacy", CONSENT_VERSION),
        "version": CONSENT_VERSION,
    })


@app.route("/api/consent/agree", methods=["POST"])
def api_consent_agree():
    """ユーザーの同意を記録する"""
    token = _extract_token()
    payload = verify_token(token) if token else None
    if not payload:
        return jsonify({"error": "Authentication required"}), 401
    user_id = payload.get("user_id", "")
    if not has_consent(user_id, "terms", CONSENT_VERSION):
        record_consent(user_id, "terms", CONSENT_VERSION)
    if not has_consent(user_id, "privacy", CONSENT_VERSION):
        record_consent(user_id, "privacy", CONSENT_VERSION)
    return jsonify({"status": "ok", "user_id": user_id})


@app.route("/api/employees")
def api_employees():
    """全AI社員リスト"""
    return jsonify(get_all_employees())


@app.route("/api/chat", methods=["POST"])
@rate_limit(max_requests=30, window_seconds=60)
def api_chat():
    """チャットAPI"""
    start_time = time.time()
    data = request.json or {}
    message = data.get("message", "")
    target = data.get("employee")
    session_id = data.get("session_id", "default")
    company_id = data.get("company_id", "hidane")

    if not message.strip():
        return jsonify({"error": "メッセージを入力してください"}), 400

    # 社員ルーティング
    employee_name = target if target and target in EMPLOYEES else route_message(message)
    emp = get_employee(employee_name)

    # API呼び出し
    if ANTHROPIC_API_KEY:
        # DB履歴を使用（メモリ内ではなくSQLiteから取得）
        history = get_history(session_id, limit=10)
        system = build_system_prompt(emp, employee_name, company_id)
        response_text = _call_claude_api(message, history, system)
    else:
        response_text = _generate_mock_response(message, emp)

    # DB保存
    save_message(session_id, "user", message, employee_name, emp["id"], company_id)
    save_message(session_id, "assistant", response_text, employee_name, emp["id"], company_id)

    # 利用ログ
    elapsed_ms = int((time.time() - start_time) * 1000)
    log_usage(session_id, "web", company_id, employee_name, len(message), len(response_text), elapsed_ms)

    return jsonify({
        "employee": employee_name,
        "employee_id": emp["id"],
        "employee_role": emp["role"],
        "employee_color": emp["color"],
        "avatar": emp["avatar"],
        "message": response_text,
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/chat/stream", methods=["POST"])
@rate_limit(max_requests=30, window_seconds=60)
def api_chat_stream():
    """SSEストリーミングチャットAPI"""
    data = request.json or {}
    message = data.get("message", "")
    target = data.get("employee")
    session_id = data.get("session_id", "default")
    company_id = data.get("company_id", "hidane")

    if not message.strip():
        return jsonify({"error": "メッセージを入力してください"}), 400

    employee_name = target if target and target in EMPLOYEES else route_message(message)
    emp = get_employee(employee_name)
    history = get_history(session_id, limit=10)
    system = build_system_prompt(emp, employee_name, company_id)

    def on_complete(full_text):
        """ストリーム完了時にDB保存"""
        save_message(session_id, "user", message, employee_name, emp["id"], company_id)
        save_message(session_id, "assistant", full_text, employee_name, emp["id"], company_id)

    generator = stream_claude_response(
        message=message,
        employee=emp,
        session_id=session_id,
        employee_name=employee_name,
        history=history,
        system_prompt=system,
        on_complete=on_complete,
    )
    return make_sse_response(generator)


@app.route("/api/route", methods=["POST"])
def api_route():
    """メッセージの振り分け先を確認"""
    data = request.json or {}
    message = data.get("message", "")
    dept = data.get("department")

    name = get_department_responder(dept, message) if dept and dept in DEPARTMENTS else route_message(message)
    emp = get_employee(name)

    return jsonify({
        "employee": name,
        "employee_id": emp["id"],
        "role": emp["role"],
        "color": emp["color"],
    })


@app.route("/api/departments")
def api_departments():
    """部署グループ一覧"""
    return jsonify(get_departments())


@app.route("/api/chat/department", methods=["POST"])
@rate_limit(max_requests=30, window_seconds=60)
def api_chat_department():
    """部署グループチャットAPI"""
    start_time = time.time()
    data = request.json or {}
    message = data.get("message", "")
    dept_name = data.get("department", "")
    session_id = data.get("session_id", f"dept_{dept_name}")
    company_id = data.get("company_id", "hidane")

    if dept_name not in DEPARTMENTS:
        return jsonify({"error": "Unknown department"}), 400

    responder_name = get_department_responder(dept_name, message)
    emp = get_employee(responder_name)

    if ANTHROPIC_API_KEY:
        history = get_history(session_id, limit=10)
        system = build_system_prompt(emp, responder_name, company_id)
        response_text = _call_claude_api(message, history, system)
    else:
        response_text = _generate_mock_response(message, emp)

    save_message(session_id, "user", message, responder_name, emp["id"], company_id)
    save_message(session_id, "assistant", response_text, responder_name, emp["id"], company_id)

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_usage(session_id, "web", company_id, responder_name, len(message), len(response_text), elapsed_ms)

    return jsonify({
        "employee": responder_name,
        "employee_id": emp["id"],
        "employee_role": emp["role"],
        "employee_color": emp["color"],
        "avatar": emp["avatar"],
        "department": dept_name,
        "message": response_text,
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/history/<channel_id>")
def api_history(channel_id):
    """チャネル別の会話履歴を取得（DBから）"""
    history = get_history(channel_id, limit=50)
    return jsonify(history)


@app.route("/api/export/<session_id>")
def api_export(session_id):
    """会話エクスポート"""
    fmt = request.args.get("format", "json")
    if fmt not in ("json", "csv", "txt"):
        return jsonify({"error": "format must be json, csv, or txt"}), 400

    content = export_conversation(session_id, fmt)
    content_type = {
        "json": "application/json",
        "csv": "text/csv",
        "txt": "text/plain",
    }[fmt]
    return content, 200, {"Content-Type": f"{content_type}; charset=utf-8"}


# ============================================================
# ファイル配信
# ============================================================

@app.route("/static/avatars/<path:filename>")
def serve_avatar(filename):
    """アバター画像配信"""
    return send_from_directory("static/avatars", filename)


@app.route("/api/files/<path:filename>")
def serve_file(filename):
    """PDF等ファイル配信"""
    import re
    if ".." in filename or "/" in filename or not re.match(r'^[\w\-. ]+\.pdf$', filename, re.UNICODE):
        return jsonify({"error": "Invalid filename"}), 400

    file_dir = Path(__file__).parent / "static" / "files"
    file_path = file_dir / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404

    return send_from_directory(str(file_dir), filename, as_attachment=False)


@app.route("/api/files")
def list_files():
    """利用可能なファイル一覧"""
    file_dir = Path(__file__).parent / "static" / "files"
    if not file_dir.exists():
        return jsonify([])

    return jsonify([
        {"filename": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
        for f in sorted(file_dir.glob("*.pdf"))
    ])


@app.route("/api/upload", methods=["POST"])
@rate_limit(max_requests=10, window_seconds=60)
def api_upload():
    """ファイルアップロード（ユーザー→AI社員）"""
    from file_handler import validate_file, save_upload
    if "file" not in request.files:
        return jsonify({"error": "ファイルが見つかりません"}), 400

    file = request.files["file"]
    is_valid, error = validate_file(file)
    if not is_valid:
        return jsonify({"error": error}), 400

    result = save_upload(file)
    return jsonify(result)


# ============================================================
# LINE Bot Webhook
# ============================================================

@app.route("/line/webhook", methods=["POST"])
def line_webhook():
    """LINE Bot Webhook受信"""
    return handle_line_webhook(request)


# ============================================================
# Claude API 呼び出し（内部関数）
# ============================================================

def _call_claude_api(message: str, history: list, system: str) -> str:
    """Claude APIを使ってAI社員として応答"""
    import urllib.request

    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2048,
        "system": system,
        "messages": messages,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            result = json.loads(res.read().decode())
            return result["content"][0]["text"]
    except Exception as e:
        return f"申し訳ございません、接続エラーが発生しました: {str(e)}"


def _generate_mock_response(message: str, employee: dict) -> str:
    """APIキー未設定時のデモレスポンス"""
    name = employee["full_name"].split()[-1]
    defaults = {
        "ソウ": f"お疲れ様です。{name}です。\n\n「{message[:30]}」について確認しました。\n\nデモモードで動作中です。",
        "リサ": f"中野さん！リサです！\n\n「{message[:30]}」の件、了解しました！\n\nデモモードで動作中です。",
        "ルナ": f"中野さん！ルナです！\n\n「{message[:30]}」ですね！\n\nデモモードで動作中です。",
    }
    return defaults.get(name, f"{employee['greeting']}\n\n「{message[:30]}」について承りました。\n\nデモモードで動作中です。")


# ============================================================
# メイン
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5555))
    print(f"""
╔══════════════════════════════════════════════════╗
║     🔥 ヒダネ AI社員チャットシステム v2.0       ║
╠══════════════════════════════════════════════════╣
║                                                  ║
║  Web Chat:  http://localhost:{port}               ║
║  管理画面:  http://localhost:{port}/admin           ║
║  LINE Bot:  http://localhost:{port}/line/webhook   ║
║                                                  ║
║  API Key: {"✅ 設定済み" if ANTHROPIC_API_KEY else "❌ 未設定（デモモード）"}              ║
║  DB:      SQLite (data/chat.db)                  ║
║                                                  ║
╚══════════════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=port, debug=True)
