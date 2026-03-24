"""
Google Drive 検索・読み取り・整理ツール
サービスアカウント経由で指定フォルダ内のファイルを検索・閲覧・整理する。
"""

import os
import json
import io
from typing import Optional

TOOL_DEF = {
    "name": "google_drive",
    "description": (
        "Google Driveのファイルを検索・閲覧・整理するツール。"
        "商談先の資料、提案書、契約書、研修資料などを検索して内容を読み取れます。"
        "フォルダ作成・ファイル移動・名前変更・コピー・削除も可能です。"
        "action: search, read, list, create_folder, move, rename, copy, delete"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "search", "read", "list",
                    "create_folder", "move", "rename", "copy", "delete",
                ],
                "description": (
                    "実行するアクション。"
                    "search=キーワード検索、read=ファイル読み取り、list=フォルダ内一覧、"
                    "create_folder=フォルダ作成、move=ファイル移動、"
                    "rename=名前変更、copy=コピー、delete=ゴミ箱へ移動"
                ),
            },
            "query": {
                "type": "string",
                "description": "検索キーワード（action=searchの場合）",
            },
            "file_id": {
                "type": "string",
                "description": "対象ファイル/フォルダのID（read, move, rename, copy, deleteで使用）",
            },
            "folder_id": {
                "type": "string",
                "description": "フォルダID（list=対象フォルダ、move=移動先、create_folder=親フォルダ）",
            },
            "name": {
                "type": "string",
                "description": "新しい名前（create_folder=フォルダ名、rename=新ファイル名）",
            },
            "max_results": {
                "type": "integer",
                "description": "最大取得件数（デフォルト: 10）",
            },
        },
        "required": ["action"],
    },
}

# ルートフォルダID（環境変数 or デフォルト）
ROOT_FOLDER_ID = os.environ.get(
    "GOOGLE_DRIVE_FOLDER_ID",
    "1ldU_588zYPJVybNjiy2D6GvBXu88qk7d",
)

# サービスアカウント認証情報
# 優先順位: 1. Secret File  2. 環境変数JSON文字列
_SECRET_FILE_PATH = "/etc/secrets/google_service_account.json"
_SERVICE_ACCOUNT_KEY = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY", "")

# 書き込みスコープ（フォルダ整理に必要）
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

# キャッシュ: Drive API サービスインスタンス
_drive_service = None


def _get_drive_service():
    """Google Drive APIサービスのシングルトンを返す。"""
    global _drive_service
    if _drive_service is not None:
        return _drive_service

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        # Secret File があればそちらを優先（PEMエスケープ問題を回避）
        if os.path.exists(_SECRET_FILE_PATH):
            credentials = service_account.Credentials.from_service_account_file(
                _SECRET_FILE_PATH,
                scopes=_DRIVE_SCOPES,
            )
        elif _SERVICE_ACCOUNT_KEY:
            # 環境変数からJSON文字列として読む
            key_data = json.loads(_SERVICE_ACCOUNT_KEY)
            if "private_key" in key_data:
                key_data["private_key"] = key_data["private_key"].replace("\\n", "\n")
            credentials = service_account.Credentials.from_service_account_info(
                key_data,
                scopes=_DRIVE_SCOPES,
            )
        else:
            return None

        _drive_service = build("drive", "v3", credentials=credentials)
        return _drive_service
    except Exception as e:
        print(f"[google_drive] サービス初期化エラー: {e}")
        return None


# ============================================================
# 読み取り系アクション
# ============================================================

def _search_files(query: str, max_results: int = 10) -> str:
    """キーワードでDrive内を検索する。"""
    service = _get_drive_service()
    if service is None:
        return _fallback_message()

    try:
        q_parts = [
            f"fullText contains '{_escape_query(query)}'",
            "trashed = false",
        ]
        q_string = " and ".join(q_parts)

        results = (
            service.files()
            .list(
                q=q_string,
                pageSize=min(max_results, 20),
                fields="files(id, name, mimeType, modifiedTime, parents, size)",
                orderBy="relevance",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )

        files = results.get("files", [])
        if not files:
            return f"「{query}」に一致するファイルは見つかりませんでした。"

        lines = [f"検索結果: {len(files)}件（キーワード: {query}）", ""]
        for i, f in enumerate(files, 1):
            size_str = _format_size(f.get("size"))
            mod_time = f.get("modifiedTime", "不明")[:10]
            mime = _friendly_mime(f.get("mimeType", ""))
            lines.append(
                f"{i}. {f['name']}\n"
                f"   種類: {mime} | 更新日: {mod_time} | サイズ: {size_str}\n"
                f"   ID: {f['id']}"
            )
        return "\n".join(lines)

    except Exception as e:
        return f"検索エラー: {str(e)}"


def _list_folder(folder_id: Optional[str] = None, max_results: int = 20) -> str:
    """フォルダ内のファイル一覧を取得する。"""
    service = _get_drive_service()
    if service is None:
        return _fallback_message()

    target_id = folder_id or ROOT_FOLDER_ID

    try:
        results = (
            service.files()
            .list(
                q=f"'{target_id}' in parents and trashed = false",
                pageSize=min(max_results, 50),
                fields="files(id, name, mimeType, modifiedTime, size)",
                orderBy="name",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )

        files = results.get("files", [])
        if not files:
            return "このフォルダにファイルはありません。"

        folders = [f for f in files if f["mimeType"] == "application/vnd.google-apps.folder"]
        docs = [f for f in files if f["mimeType"] != "application/vnd.google-apps.folder"]

        lines = [f"フォルダ内容: {len(files)}件", ""]

        if folders:
            lines.append("📁 フォルダ:")
            for f in folders:
                lines.append(f"  - {f['name']}  (ID: {f['id']})")
            lines.append("")

        if docs:
            lines.append("📄 ファイル:")
            for f in docs:
                mime = _friendly_mime(f.get("mimeType", ""))
                size_str = _format_size(f.get("size"))
                mod_time = f.get("modifiedTime", "")[:10]
                lines.append(
                    f"  - {f['name']}  [{mime}] {size_str} ({mod_time})  ID: {f['id']}"
                )

        return "\n".join(lines)

    except Exception as e:
        return f"フォルダ一覧エラー: {str(e)}"


def _read_file(file_id: str) -> str:
    """ファイルの内容を読み取る。"""
    service = _get_drive_service()
    if service is None:
        return _fallback_message()

    try:
        meta = (
            service.files()
            .get(fileId=file_id, fields="id, name, mimeType, size")
            .execute()
        )
        mime = meta.get("mimeType", "")
        name = meta.get("name", "不明")
        size = int(meta.get("size", 0))

        # Google Docs → テキスト export
        if mime == "application/vnd.google-apps.document":
            content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
            text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
            return _truncate(f"📄 {name}\n\n{text}", 8000)

        # Google Slides → テキスト抽出
        if mime == "application/vnd.google-apps.presentation":
            content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
            text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
            return _truncate(f"📊 {name}（スライド）\n\n{text}", 8000)

        # Google Sheets → CSV export
        if mime == "application/vnd.google-apps.spreadsheet":
            content = service.files().export(fileId=file_id, mimeType="text/csv").execute()
            text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
            return _truncate(f"📊 {name}（スプレッドシート）\n\n{text}", 8000)

        # テキスト系ファイル
        text_extensions = (".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".html")
        if any(name.lower().endswith(ext) for ext in text_extensions):
            if size > 500_000:
                return f"⚠️ {name} はサイズが大きすぎます（{_format_size(str(size))}）。"
            from googleapiclient.http import MediaIoBaseDownload
            req = service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            text = buffer.getvalue().decode("utf-8", errors="replace")
            return _truncate(f"📄 {name}\n\n{text}", 8000)

        # バイナリファイル
        return (
            f"📎 {name}\n"
            f"種類: {_friendly_mime(mime)} | サイズ: {_format_size(meta.get('size'))}\n"
            f"※ バイナリファイルのため内容の直接表示はできません。"
        )

    except Exception as e:
        return f"ファイル読み取りエラー: {str(e)}"


# ============================================================
# 書き込み系アクション（フォルダ整理）
# ============================================================

def _create_folder(name: str, parent_id: Optional[str] = None) -> str:
    """フォルダを作成する。"""
    service = _get_drive_service()
    if service is None:
        return _fallback_message()

    if not name:
        return "フォルダ名を指定してください。"

    target_parent = parent_id or ROOT_FOLDER_ID

    try:
        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [target_parent],
        }
        folder = service.files().create(
            body=metadata,
            fields="id, name, webViewLink",
            supportsAllDrives=True,
        ).execute()

        return (
            f"✅ フォルダを作成しました\n"
            f"名前: {folder['name']}\n"
            f"ID: {folder['id']}"
        )

    except Exception as e:
        return f"フォルダ作成エラー: {str(e)}"


def _move_file(file_id: str, dest_folder_id: str) -> str:
    """ファイルを別のフォルダに移動する。"""
    service = _get_drive_service()
    if service is None:
        return _fallback_message()

    if not file_id or not dest_folder_id:
        return "ファイルIDと移動先フォルダIDを指定してください。"

    try:
        # 現在の親フォルダを取得
        file_meta = service.files().get(
            fileId=file_id,
            fields="name, parents",
            supportsAllDrives=True,
        ).execute()

        current_parents = ",".join(file_meta.get("parents", []))
        file_name = file_meta.get("name", "不明")

        # 移動（親フォルダを変更）
        updated = service.files().update(
            fileId=file_id,
            addParents=dest_folder_id,
            removeParents=current_parents,
            fields="id, name, parents",
            supportsAllDrives=True,
        ).execute()

        return f"✅ 「{file_name}」を移動しました（ID: {updated['id']}）"

    except Exception as e:
        return f"ファイル移動エラー: {str(e)}"


def _rename_file(file_id: str, new_name: str) -> str:
    """ファイル・フォルダの名前を変更する。"""
    service = _get_drive_service()
    if service is None:
        return _fallback_message()

    if not file_id or not new_name:
        return "ファイルIDと新しい名前を指定してください。"

    try:
        # 現在の名前を取得
        old_meta = service.files().get(
            fileId=file_id,
            fields="name",
            supportsAllDrives=True,
        ).execute()
        old_name = old_meta.get("name", "不明")

        updated = service.files().update(
            fileId=file_id,
            body={"name": new_name},
            fields="id, name",
            supportsAllDrives=True,
        ).execute()

        return f"✅ 名前を変更しました\n「{old_name}」→「{updated['name']}」"

    except Exception as e:
        return f"名前変更エラー: {str(e)}"


def _copy_file(file_id: str, dest_folder_id: Optional[str] = None) -> str:
    """ファイルをコピーする。"""
    service = _get_drive_service()
    if service is None:
        return _fallback_message()

    if not file_id:
        return "コピー元のファイルIDを指定してください。"

    try:
        body = {}
        if dest_folder_id:
            body["parents"] = [dest_folder_id]

        copied = service.files().copy(
            fileId=file_id,
            body=body,
            fields="id, name, parents",
            supportsAllDrives=True,
        ).execute()

        return (
            f"✅ コピーしました\n"
            f"名前: {copied['name']}\n"
            f"ID: {copied['id']}"
        )

    except Exception as e:
        return f"コピーエラー: {str(e)}"


def _delete_file(file_id: str) -> str:
    """ファイルをゴミ箱に移動する（完全削除ではない）。"""
    service = _get_drive_service()
    if service is None:
        return _fallback_message()

    if not file_id:
        return "削除するファイルIDを指定してください。"

    try:
        # 名前を取得してから削除
        meta = service.files().get(
            fileId=file_id,
            fields="name, mimeType",
            supportsAllDrives=True,
        ).execute()
        name = meta.get("name", "不明")
        is_folder = meta.get("mimeType") == "application/vnd.google-apps.folder"
        item_type = "フォルダ" if is_folder else "ファイル"

        # ゴミ箱へ移動（trashed=True）
        service.files().update(
            fileId=file_id,
            body={"trashed": True},
            supportsAllDrives=True,
        ).execute()

        return (
            f"🗑️ {item_type}「{name}」をゴミ箱に移動しました\n"
            f"※ Google Driveのゴミ箱から30日間は復元可能です"
        )

    except Exception as e:
        return f"削除エラー: {str(e)}"


# ============================================================
# ユーティリティ
# ============================================================

def _escape_query(q: str) -> str:
    """Drive API クエリ用にエスケープ。"""
    return q.replace("\\", "\\\\").replace("'", "\\'")


def _format_size(size_str) -> str:
    """バイト数を読みやすい形式に変換。"""
    if not size_str:
        return "-"
    try:
        size = int(size_str)
        if size < 1024:
            return f"{size}B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        return f"{size / (1024 * 1024):.1f}MB"
    except (ValueError, TypeError):
        return "-"


def _friendly_mime(mime: str) -> str:
    """MIMEタイプを日本語ラベルに変換。"""
    mime_map = {
        "application/vnd.google-apps.document": "Google ドキュメント",
        "application/vnd.google-apps.spreadsheet": "Google スプレッドシート",
        "application/vnd.google-apps.presentation": "Google スライド",
        "application/vnd.google-apps.folder": "フォルダ",
        "application/pdf": "PDF",
        "text/plain": "テキスト",
        "text/csv": "CSV",
        "application/json": "JSON",
        "image/png": "PNG画像",
        "image/jpeg": "JPEG画像",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
    }
    return mime_map.get(mime, mime.split("/")[-1] if "/" in mime else "不明")


def _truncate(text: str, max_chars: int) -> str:
    """テキストを最大文字数で切り詰める。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n...（以降省略、全{len(text)}文字）"


def _fallback_message() -> str:
    """サービスアカウント未設定時のメッセージ。"""
    return (
        "Google Driveへの接続が設定されていません。\n"
        "管理者にGOOGLE_SERVICE_ACCOUNT_KEY環境変数の設定を依頼してください。"
    )


# ============================================================
# メインディスパッチャー
# ============================================================

def execute(params: dict) -> str:
    """ツール実行のエントリーポイント。"""
    action = params.get("action", "search")
    max_results = params.get("max_results", 10)

    # 読み取り系
    if action == "search":
        query = params.get("query", "")
        if not query:
            return "検索キーワードを指定してください。"
        return _search_files(query, max_results)

    if action == "list":
        folder_id = params.get("folder_id")
        return _list_folder(folder_id, max_results)

    if action == "read":
        file_id = params.get("file_id", "")
        if not file_id:
            return "ファイルIDを指定してください。"
        return _read_file(file_id)

    # 書き込み系
    if action == "create_folder":
        name = params.get("name", "")
        folder_id = params.get("folder_id")
        return _create_folder(name, folder_id)

    if action == "move":
        file_id = params.get("file_id", "")
        folder_id = params.get("folder_id", "")
        return _move_file(file_id, folder_id)

    if action == "rename":
        file_id = params.get("file_id", "")
        name = params.get("name", "")
        return _rename_file(file_id, name)

    if action == "copy":
        file_id = params.get("file_id", "")
        folder_id = params.get("folder_id")
        return _copy_file(file_id, folder_id)

    if action == "delete":
        file_id = params.get("file_id", "")
        return _delete_file(file_id)

    return f"不明なアクション: {action}"
