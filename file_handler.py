"""
ファイルアップロード・画像送信・会話エクスポート機能
ユーザーからのPDF/画像アップロードを受け付け、AI社員に渡す。
"""

import os
import re
import uuid
from datetime import datetime
from pathlib import Path

# アップロード先ディレクトリ
UPLOAD_DIR = Path(__file__).parent / "static" / "uploads"
FILES_DIR = Path(__file__).parent / "static" / "files"

# 許可するファイル形式
ALLOWED_EXTENSIONS = {
    "pdf": {"application/pdf"},
    "image": {"image/png", "image/jpeg", "image/gif", "image/webp"},
    "document": {"text/plain", "text/csv", "application/json"},
}

ALL_ALLOWED = set()
for exts in ALLOWED_EXTENSIONS.values():
    ALL_ALLOWED |= exts

# ファイルサイズ上限（10MB）
MAX_FILE_SIZE = 10 * 1024 * 1024


def init_upload_dirs():
    """アップロードディレクトリを初期化"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)


def validate_file(file_storage):
    """アップロードファイルのバリデーション

    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if not file_storage or not file_storage.filename:
        return False, "ファイルが選択されていません"

    # ファイル名サニタイズ
    filename = file_storage.filename
    if ".." in filename or "/" in filename or "\\" in filename:
        return False, "不正なファイル名です"

    # 拡張子チェック
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed_exts = {"pdf", "png", "jpg", "jpeg", "gif", "webp", "txt", "csv", "json"}
    if ext not in allowed_exts:
        return False, f"対応していないファイル形式です: .{ext}"

    # Content-Typeチェック
    content_type = file_storage.content_type or ""
    if content_type not in ALL_ALLOWED:
        return False, f"対応していないファイル形式です: {content_type}"

    # サイズチェック（ヘッダーから）
    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_FILE_SIZE:
        return False, f"ファイルサイズが上限（10MB）を超えています: {size / 1024 / 1024:.1f}MB"

    return True, None


def save_upload(file_storage, company_id="hidane"):
    """ファイルを保存して情報を返す

    Returns:
        dict: {"filename", "original_name", "path", "url", "size_kb", "content_type", "uploaded_at"}
    """
    init_upload_dirs()

    original_name = file_storage.filename
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else "bin"
    unique_name = f"{company_id}_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"

    save_path = UPLOAD_DIR / unique_name
    file_storage.save(str(save_path))

    size_kb = round(save_path.stat().st_size / 1024, 1)

    return {
        "filename": unique_name,
        "original_name": original_name,
        "path": str(save_path),
        "url": f"/static/uploads/{unique_name}",
        "size_kb": size_kb,
        "content_type": file_storage.content_type or "",
        "uploaded_at": datetime.now().isoformat(),
    }


def read_text_file(filepath):
    """テキストファイルの内容を読み取る（AI社員への入力用）"""
    path = Path(filepath)
    if not path.exists():
        return ""

    try:
        content = path.read_text(encoding="utf-8")
        # 長すぎる場合は切り詰め（Claude APIのコンテキスト節約）
        if len(content) > 10000:
            return content[:10000] + "\n\n...（以下省略。全体で約{}文字）".format(len(content))
        return content
    except (UnicodeDecodeError, OSError):
        return "(バイナリファイルのため内容を読み取れません)"


def list_uploads(company_id=None):
    """アップロード済みファイル一覧"""
    if not UPLOAD_DIR.exists():
        return []

    files = []
    for f in sorted(UPLOAD_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and not f.name.startswith("."):
            if company_id and not f.name.startswith(f"{company_id}_"):
                continue
            files.append({
                "filename": f.name,
                "url": f"/static/uploads/{f.name}",
                "size_kb": round(f.stat().st_size / 1024, 1),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })

    return files


def cleanup_uploads(max_age_days=30):
    """古いアップロードファイルを削除"""
    if not UPLOAD_DIR.exists():
        return 0

    cutoff = datetime.now().timestamp() - (max_age_days * 86400)
    count = 0
    for f in UPLOAD_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink()
            count += 1

    return count


def get_sendable_files():
    """AI社員が送信可能なPDFファイル一覧"""
    if not FILES_DIR.exists():
        return []

    return [
        {
            "filename": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "url": f"/api/files/{f.name}",
        }
        for f in sorted(FILES_DIR.glob("*.pdf"))
    ]
