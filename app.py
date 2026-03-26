"""
ヒダネ AI社員チャットシステム
- Web Chat UI: http://localhost:5555
- LINE Bot Webhook: http://localhost:5555/line/webhook
- 管理画面: http://localhost:5555/admin

3モードアクセス:
  - 認証済みadmin → 全機能 + ユーザー管理
  - 認証済みuser → 自社AI社員チャット + 履歴（社内モード）
  - 未認証 → 公開デモモード（機密なし）
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, jsonify, send_from_directory, redirect
from flask_cors import CORS

from employees import (
    EMPLOYEES, route_message, get_employee, get_all_employees,
    get_departments, get_department_responder, DEPARTMENTS,
)
from knowledge import build_knowledge_context
from knowledge_admin import build_custom_context
from database import (
    init_db, save_message, get_history, log_usage, export_conversation,
    has_consent, record_consent, db_list_users,
)
from streaming import stream_claude_response, make_sse_response
from rate_limiter import rate_limit
from line_handler import handle_line_webhook
from admin_routes import admin_bp
from system_prompt import build_system_prompt
from auth import (
    create_token, authenticate_user, verify_token, register_user,
    require_auth, require_admin, _extract_token, _init_users_db,
)
from tools import get_tool_definitions

app = Flask(__name__)

# CORS: 本番ではオリジン制限
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*")
CORS(app, origins=ALLOWED_ORIGINS.split(","))

# 設定
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

# DB初期化 → ユーザーDB初期化
init_db()
_init_users_db()

# タスクキュー自動処理（APScheduler）
def _init_task_scheduler():
    """バックグラウンドでタスクキューを5分おきに巡回するスケジューラを起動。"""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from task_processor import process_pending_tasks

        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(
            process_pending_tasks,
            "interval",
            minutes=5,
            id="task_queue_processor",
            replace_existing=True,
        )
        scheduler.start()
        print("[scheduler] タスクキュー巡回ジョブを開始（5分間隔）", flush=True)
    except ImportError:
        print("[scheduler] APScheduler未インストール。タスク自動処理は無効。", flush=True)
    except Exception as e:
        print(f"[scheduler] 起動エラー: {e}", flush=True)

# gunicorn worker重複防止: 環境変数でメインプロセスのみ実行
if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not os.environ.get("WERKZEUG_RUN_MAIN"):
    _init_task_scheduler()

# 管理画面Blueprint登録
app.register_blueprint(admin_bp)


# ============================================================
# Auth helpers
# ============================================================

def _get_auth_context():
    """認証状態を判定し、(public_mode, company_id, user_id) を返す。
    認証済み → (False, JWT company_id, JWT user_id)
    未認証   → (True, "public", "guest")
    """
    # @require_auth通過後はrequest.userにペイロードがセットされている
    payload = getattr(request, "user", None)
    if payload:
        return (False, payload.get("company_id", "hidane"), payload.get("user_id", ""))
    # フォールバック：トークンを直接検証
    token = _extract_token()
    payload = verify_token(token) if token else None
    if payload:
        return (False, payload.get("company_id", "hidane"), payload.get("user_id", ""))
    return (True, "public", "guest")


# ============================================================
# Auth routes
# ============================================================

@app.route("/auth/login", methods=["GET", "POST"])
def auth_login():
    """ログインページ / ログイン処理"""
    if request.method == "GET":
        # 既にログイン済みならチャットへ
        token = request.cookies.get("auth_token")
        if verify_token(token):
            return redirect("/")
        return render_template("login.html")

    data = request.form if request.form else (request.json or {})
    email = data.get("email", "")
    password = data.get("password", "")
    token = authenticate_user(email, password)
    if not token:
        if request.form:
            return render_template("login.html", error="メールアドレスまたはパスワードが正しくありません")
        return jsonify({"error": "Invalid credentials"}), 401

    if request.form:
        resp = redirect("/")
        resp.set_cookie("auth_token", token, httponly=True, samesite="Lax", max_age=86400)
        return resp
    return jsonify({"token": token})


@app.route("/auth/logout")
def auth_logout():
    resp = redirect("/auth/login")
    resp.delete_cookie("auth_token")
    return resp


# ============================================================
# Web Chat UI
# ============================================================

@app.route("/")
def index():
    """メインチャットUI
    認証済み → チャット画面（社内モード）
    未認証 → チャット画面（公開デモモード）
    """
    return render_template("chat.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/api/auth/status")
def api_auth_status():
    """フロントエンド用：現在の認証状態を返す"""
    public_mode, company_id, user_id = _get_auth_context()
    return jsonify({
        "authenticated": not public_mode,
        "company_id": company_id,
        "user_id": user_id,
        "mode": "public" if public_mode else "internal",
    })


@app.route("/api/employees")
def api_employees():
    return jsonify(get_all_employees())


@app.route("/api/departments")
def api_departments():
    return jsonify(get_departments())


# ============================================================
# Chat API（3モード対応）
# ============================================================

@app.route("/api/chat", methods=["POST"])
@rate_limit(max_requests=30, window_seconds=60)
def api_chat():
    """チャットAPI（認証済み＝社内モード、未認証＝公開モード）"""
    start_time = time.time()
    data = request.json or {}
    message = data.get("message", "")
    target = data.get("employee")
    session_id = data.get("session_id", "default")

    if not message.strip():
        return jsonify({"error": "メッセージを入力してください"}), 400

    public_mode, company_id, user_id = _get_auth_context()

    employee_name = target if target and target in EMPLOYEES else route_message(message)
    emp = get_employee(employee_name)

    if ANTHROPIC_API_KEY:
        from claude_client import call_claude_with_tools
        history = get_history(session_id, limit=10)
        system = build_system_prompt(emp, employee_name, company_id, public_mode=public_mode)
        # @require_auth通過済み = 認証済み → ツール常に有効
        emp_tools = get_tool_definitions(emp.get("tools", []))
        response_text = call_claude_with_tools(message, history, system, tools=emp_tools)
    else:
        response_text = _generate_mock_response(message, emp)

    save_message(session_id, "user", message, employee_name, emp["id"], company_id)
    save_message(session_id, "assistant", response_text, employee_name, emp["id"], company_id)

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_usage(session_id, user_id, company_id, employee_name, len(message), len(response_text), elapsed_ms)

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

    if not message.strip():
        return jsonify({"error": "メッセージを入力してください"}), 400

    public_mode, company_id, user_id = _get_auth_context()

    employee_name = target if target and target in EMPLOYEES else route_message(message)
    emp = get_employee(employee_name)
    history = get_history(session_id, limit=10)
    system = build_system_prompt(emp, employee_name, company_id, public_mode=public_mode)
    # @require_auth通過済み = 認証済み → ツール常に有効
    emp_tools = get_tool_definitions(emp.get("tools", []))

    def on_complete(full_text):
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
        tools=emp_tools,
    )
    return make_sse_response(generator)


@app.route("/api/route", methods=["POST"])
def api_route():
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


@app.route("/api/chat/department", methods=["POST"])
@rate_limit(max_requests=30, window_seconds=60)
def api_chat_department():
    start_time = time.time()
    data = request.json or {}
    message = data.get("message", "")
    dept_name = data.get("department", "")
    session_id = data.get("session_id", f"dept_{dept_name}")

    if dept_name not in DEPARTMENTS:
        return jsonify({"error": "Unknown department"}), 400

    public_mode, company_id, user_id = _get_auth_context()

    responder_name = get_department_responder(dept_name, message)
    emp = get_employee(responder_name)

    if ANTHROPIC_API_KEY:
        history = get_history(session_id, limit=10)
        system = build_system_prompt(emp, responder_name, company_id, public_mode=public_mode)
        response_text = _call_claude_api(message, history, system)
    else:
        response_text = _generate_mock_response(message, emp)

    save_message(session_id, "user", message, responder_name, emp["id"], company_id)
    save_message(session_id, "assistant", response_text, responder_name, emp["id"], company_id)

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_usage(session_id, user_id, company_id, responder_name, len(message), len(response_text), elapsed_ms)

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
    history = get_history(channel_id, limit=50)
    return jsonify(history)


@app.route("/api/export/<session_id>")
def api_export(session_id):
    fmt = request.args.get("format", "json")
    if fmt not in ("json", "csv", "txt"):
        return jsonify({"error": "format must be json, csv, or txt"}), 400
    content = export_conversation(session_id, fmt)
    content_type = {"json": "application/json", "csv": "text/csv", "txt": "text/plain"}[fmt]
    return content, 200, {"Content-Type": f"{content_type}; charset=utf-8"}


# ============================================================
# ユーザー管理API（admin専用）
# ============================================================

@app.route("/admin/api/users", methods=["GET"])
@require_admin
def admin_list_users():
    """ユーザー一覧"""
    company_id = request.args.get("company_id")
    users = db_list_users(company_id)
    return jsonify(users)


@app.route("/admin/api/users", methods=["POST"])
@require_admin
def admin_create_user():
    """ユーザー作成"""
    data = request.json or {}
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    company_id = data.get("company_id", "hidane")
    role = data.get("role", "user")
    display_name = data.get("display_name", "")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400
    if role not in ("user", "admin"):
        return jsonify({"error": "role must be 'user' or 'admin'"}), 400

    result = register_user(email, password, company_id, display_name, role)
    if result is None:
        return jsonify({"error": "User already exists"}), 409
    return jsonify(result), 201


@app.route("/admin/api/users/<email>", methods=["PUT"])
@require_admin
def admin_update_user(email):
    """ユーザー更新"""
    from database import db_update_user
    data = request.json or {}
    result = db_update_user(email, **data)
    if result is None:
        return jsonify({"error": "User not found or no valid fields"}), 404
    return jsonify(result)


@app.route("/admin/api/users/<email>", methods=["DELETE"])
@require_admin
def admin_deactivate_user(email):
    """ユーザー無効化"""
    from database import db_deactivate_user
    if db_deactivate_user(email):
        return jsonify({"status": "deactivated", "email": email})
    return jsonify({"error": "User not found"}), 404


# ============================================================
# ファイル配信
# ============================================================

@app.route("/static/avatars/<path:filename>")
def serve_avatar(filename):
    return send_from_directory("static/avatars", filename)


@app.route("/api/generated/<path:filename>")
def serve_generated(filename):
    """AI社員が生成した文書の配信"""
    import re
    if ".." in filename or "/" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    gen_dir = Path(__file__).parent / "static" / "generated"
    file_path = gen_dir / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(str(gen_dir), filename, as_attachment=True)


@app.route("/api/files/<path:filename>")
def serve_file(filename):
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
    return handle_line_webhook(request)


# ============================================================
# デバッグ：Google Drive接続テスト
# ============================================================

@app.route("/api/debug/drive-test")
@require_admin
def debug_drive_test():
    """Google Drive接続テスト（admin専用）"""
    from tools.google_drive import execute as drive_execute
    # ルートフォルダの一覧を取得
    result = drive_execute({"action": "list"})
    return jsonify({"status": "ok", "result": result})


@app.route("/api/debug/tool-check")
@require_admin
def debug_tool_check():
    """ソウに渡されるツール定義を確認（admin専用）"""
    emp = get_employee("ソウ")
    emp_tools = get_tool_definitions(emp.get("tools", []))
    return jsonify({
        "employee": "ソウ",
        "tool_names_in_config": emp.get("tools", []),
        "tool_definitions_count": len(emp_tools),
        "tool_names_resolved": [t["name"] for t in emp_tools],
    })


# ============================================================
# Claude API 呼び出し（内部関数）
# ============================================================

def _call_claude_api(message: str, history: list, system: str) -> str:
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
║     🔥 ヒダネ AI社員チャットシステム v3.0       ║
╠══════════════════════════════════════════════════╣
║                                                  ║
║  Web Chat:  http://localhost:{port}               ║
║  管理画面:  http://localhost:{port}/admin           ║
║  LINE Bot:  http://localhost:{port}/line/webhook   ║
║                                                  ║
║  API Key: {"✅ 設定済み" if ANTHROPIC_API_KEY else "❌ 未設定（デモモード）"}              ║
║  Auth:    3モード（admin/user/guest）            ║
║                                                  ║
╚══════════════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=port, debug=True)
