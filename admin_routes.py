"""
管理画面用APIルート
Flask Blueprintとして実装。app.pyにregister_blueprint()で統合。
"""

from flask import Blueprint, render_template, request, jsonify
from auth import require_auth, require_admin
from knowledge_admin import (
    load_custom_knowledge,
    add_faq,
    remove_faq,
    add_company_info,
    remove_company_info,
    set_employee_note,
)
from file_handler import validate_file, save_upload, get_sendable_files

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@require_admin
def admin_page():
    """管理画面トップ"""
    return render_template("admin.html")


# ========== ナレッジAPI ==========

@admin_bp.route("/api/knowledge")
@require_admin
def api_knowledge():
    """カスタムナレッジ全体を取得"""
    company_id = request.args.get("company_id", "hidane")
    data = load_custom_knowledge(company_id)
    return jsonify(data)


@admin_bp.route("/api/knowledge/info", methods=["POST"])
@require_admin
def api_add_info():
    """会社情報を追加"""
    body = request.json or {}
    title = body.get("title", "").strip()
    content = body.get("content", "").strip()
    if not title or not content:
        return jsonify({"error": "タイトルと内容は必須です"}), 400

    company_id = body.get("company_id", "hidane")
    _, new_info = add_company_info(title, content, company_id)
    return jsonify(new_info)


@admin_bp.route("/api/knowledge/info/<info_id>", methods=["DELETE"])
@require_admin
def api_remove_info(info_id):
    """会社情報を削除"""
    company_id = request.args.get("company_id", "hidane")
    remove_company_info(info_id, company_id)
    return jsonify({"ok": True})


@admin_bp.route("/api/knowledge/faq", methods=["POST"])
@require_admin
def api_add_faq():
    """FAQを追加"""
    body = request.json or {}
    question = body.get("question", "").strip()
    answer = body.get("answer", "").strip()
    if not question or not answer:
        return jsonify({"error": "質問と回答は必須です"}), 400

    company_id = body.get("company_id", "hidane")
    _, new_faq = add_faq(question, answer, company_id)
    return jsonify(new_faq)


@admin_bp.route("/api/knowledge/faq/<faq_id>", methods=["DELETE"])
@require_admin
def api_remove_faq(faq_id):
    """FAQを削除"""
    company_id = request.args.get("company_id", "hidane")
    remove_faq(faq_id, company_id)
    return jsonify({"ok": True})


@admin_bp.route("/api/knowledge/employee-note", methods=["POST"])
@require_admin
def api_set_employee_note():
    """社員別追加指示を設定"""
    body = request.json or {}
    employee = body.get("employee", "").strip()
    note = body.get("note", "").strip()
    if not employee:
        return jsonify({"error": "社員名は必須です"}), 400

    company_id = body.get("company_id", "hidane")
    set_employee_note(employee, note, company_id)
    return jsonify({"ok": True, "employee": employee})


# ========== ファイルアップロードAPI ==========

@admin_bp.route("/api/upload", methods=["POST"])
@require_admin
def api_upload():
    """ファイルアップロード（PDFをAI社員送信可能フォルダに保存）"""
    if "file" not in request.files:
        return jsonify({"error": "ファイルが見つかりません"}), 400

    file = request.files["file"]
    is_valid, error = validate_file(file)
    if not is_valid:
        return jsonify({"error": error}), 400

    # PDFは送信可能フォルダに直接保存
    from pathlib import Path
    files_dir = Path(__file__).parent / "static" / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    filename = file.filename
    save_path = files_dir / filename
    file.save(str(save_path))

    size_kb = round(save_path.stat().st_size / 1024, 1)
    return jsonify({
        "filename": filename,
        "size_kb": size_kb,
        "url": f"/api/files/{filename}",
    })


# ========== 利用統計API ==========

@admin_bp.route("/api/stats")
@require_admin
def api_stats():
    """利用統計を取得"""
    try:
        from database import get_usage_stats
        company_id = request.args.get("company_id")
        days = int(request.args.get("days", 7))
        stats = get_usage_stats(company_id, days)
        return jsonify(stats)
    except ImportError:
        # database.pyがまだ統合されていない場合
        return jsonify({
            "total_messages": 0,
            "by_employee": {},
            "by_day": {},
            "avg_response_time_ms": 0,
            "note": "データベース統合後に利用可能",
        })
