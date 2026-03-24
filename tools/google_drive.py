"""
Google Drive 検索・読み取りツール
サービスアカウント経由で指定フォルダ内のファイルを検索・閲覧する。
"""

import os
import json
import io
from typing import Optional

TOOL_DEF = {
    "name": "google_drive",
    "description": (
        "Google Driveのファイルを検索・閲覧するツール。"
        "商談先の資料、提案書、契約書、研修資料などを検索して内容を読み取れます。"
        "action: search（キーワード検索）、read（ファイル内容読み取り）、list（フォルダ内一覧）"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "read", "list"],
                "description": "実行するアクション。search=キーワード検索、read=ファイル読み取り、list=フォルダ内一覧",
            },
            "query": {
                "type": "string",
                "description": "検索キーワード（action=searchの場合に使用）",
            },
            "file_id": {
                "type": "string",
                "description": "読み取るファイルのID（action=readの場合に使用）",
            },
            "folder_id": {
                "type": "string",
                "description": "一覧を取得するフォルダのID（action=listの場合。省略時はルートフォルダ）",
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

# OAuth認証情報（リフレッシュトークン方式）
_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
_OAUTH_REFRESH_TOKEN = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN", "")

# キャッシュ: Drive API サービスインスタンス
_drive_service = None


def _get_drive_service():
    """Google Drive APIサービスのシングルトンを返す（OAuth認証）。"""
    global _drive_service
    if _drive_service is not None:
        return _drive_service

    if not all([_OAUTH_CLIENT_ID, _OAUTH_CLIENT_SECRET, _OAUTH_REFRESH_TOKEN]):
        return None

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        credentials = Credentials(
            token=None,
            refresh_token=_OAUTH_REFRESH_TOKEN,
            client_id=_OAUTH_CLIENT_ID,
            client_secret=_OAUTH_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
        )
        _drive_service = build("drive", "v3", credentials=credentials)
        return _drive_service
    except Exception as e:
        print(f"[google_drive] OAuth初期化エラー: {e}")
        return None


def _search_files(query: str, max_results: int = 10) -> str:
    """キーワードでDrive内を検索する。"""
    service = _get_drive_service()
    if service is None:
        return _fallback_message("search")

    try:
        # ルートフォルダ配下のみ検索（サブフォルダ含む）
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
                fields="files(id, name, mimeType, modifiedTime, parents, size, webViewLink)",
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
        return _fallback_message("list")

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
                lines.append(f"  - {f['name']}  [{mime}] {size_str} ({mod_time})  ID: {f['id']}")

        return "\n".join(lines)

    except Exception as e:
        return f"フォルダ一覧エラー: {str(e)}"


def _read_file(file_id: str) -> str:
    """ファイルの内容を読み取る。Google DocsはテキストExport、その他はダウンロード。"""
    service = _get_drive_service()
    if service is None:
        return _fallback_message("read")

    try:
        # ファイルのメタデータ取得
        meta = (
            service.files()
            .get(fileId=file_id, fields="id, name, mimeType, size")
            .execute()
        )
        mime = meta.get("mimeType", "")
        name = meta.get("name", "不明")
        size = int(meta.get("size", 0))

        # Google Docsはテキストとしてexport
        if mime == "application/vnd.google-apps.document":
            content = (
                service.files()
                .export(fileId=file_id, mimeType="text/plain")
                .execute()
            )
            text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
            return _truncate(f"📄 {name}\n\n{text}", 8000)

        # Google Slidesはテキスト抽出
        if mime == "application/vnd.google-apps.presentation":
            content = (
                service.files()
                .export(fileId=file_id, mimeType="text/plain")
                .execute()
            )
            text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
            return _truncate(f"📊 {name}（スライド）\n\n{text}", 8000)

        # Google Sheetsはcsv export
        if mime == "application/vnd.google-apps.spreadsheet":
            content = (
                service.files()
                .export(fileId=file_id, mimeType="text/csv")
                .execute()
            )
            text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
            return _truncate(f"📊 {name}（スプレッドシート）\n\n{text}", 8000)

        # テキスト系ファイル（md, txt, csv, json）
        text_extensions = (".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".html")
        if any(name.lower().endswith(ext) for ext in text_extensions):
            if size > 500_000:
                return f"⚠️ {name} はサイズが大きすぎます（{_format_size(str(size))}）。概要のみ参照してください。"
            from googleapiclient.http import MediaIoBaseDownload
            request = service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            text = buffer.getvalue().decode("utf-8", errors="replace")
            return _truncate(f"📄 {name}\n\n{text}", 8000)

        # PDF等のバイナリファイル
        return (
            f"📎 {name}\n"
            f"種類: {_friendly_mime(mime)} | サイズ: {_format_size(meta.get('size'))}\n"
            f"※ バイナリファイルのため内容の直接表示はできません。\n"
            f"Google Driveで開いて確認してください。"
        )

    except Exception as e:
        return f"ファイル読み取りエラー: {str(e)}"


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


def _fallback_message(action: str) -> str:
    """サービスアカウント未設定時のメッセージ。"""
    return (
        "Google Driveへの接続が設定されていません。\n"
        "管理者にGOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET / GOOGLE_OAUTH_REFRESH_TOKEN 環境変数の設定を依頼してください。"
    )


def execute(params: dict) -> str:
    """ツール実行のエントリーポイント。"""
    action = params.get("action", "search")
    max_results = params.get("max_results", 10)

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

    return f"不明なアクション: {action}。search / read / list のいずれかを指定してください。"
