"""
Gmail ツール
メールの検索・閲覧・下書き作成・送信を行う。
"""

import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from tools.google_auth import get_user_credentials, is_configured

TOOL_DEF = {
    "name": "gmail",
    "description": (
        "Gmailでメールの検索・閲覧・下書き作成・送信を行うツール。"
        "フォローメール・日報・お礼メールなどを作成・送信できます。"
        "action: search（検索）、read（閲覧）、draft（下書き作成）、send（送信）、reply（返信）"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "read", "draft", "send", "reply"],
                "description": (
                    "search=メール検索、read=メール閲覧、"
                    "draft=下書き作成、send=メール送信、reply=返信"
                ),
            },
            "query": {
                "type": "string",
                "description": "検索クエリ（Gmail検索構文対応。例: from:xxx subject:yyy）",
            },
            "message_id": {
                "type": "string",
                "description": "メールID（read, replyで使用）",
            },
            "to": {
                "type": "string",
                "description": "宛先メールアドレス（draft, sendで使用。カンマ区切りで複数可）",
            },
            "subject": {
                "type": "string",
                "description": "件名（draft, sendで使用）",
            },
            "body": {
                "type": "string",
                "description": "本文（draft, send, replyで使用）",
            },
            "cc": {
                "type": "string",
                "description": "CC（カンマ区切り）",
            },
            "max_results": {
                "type": "integer",
                "description": "検索結果の最大件数（デフォルト: 5）",
            },
        },
        "required": ["action"],
    },
}

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]

_gmail_service = None


def _get_gmail_service():
    """Gmail APIサービスを返す。"""
    global _gmail_service
    if _gmail_service is not None:
        return _gmail_service

    creds = get_user_credentials(_SCOPES)
    if creds is None:
        return None

    try:
        from googleapiclient.discovery import build
        _gmail_service = build("gmail", "v1", credentials=creds)
        return _gmail_service
    except Exception as e:
        print(f"[gmail] サービス初期化エラー: {e}")
        return None


def _search_emails(query: str, max_results: int = 5) -> str:
    """メールを検索する。"""
    service = _get_gmail_service()
    if service is None:
        return _fallback()

    try:
        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=min(max_results, 20),
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return f"「{query}」に一致するメールは見つかりませんでした。"

        lines = [f"検索結果: {len(messages)}件", ""]
        for msg_ref in messages:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            snippet = msg.get("snippet", "")[:80]
            lines.append(
                f"📧 {headers.get('Subject', '(件名なし)')}\n"
                f"   From: {headers.get('From', '不明')} | {headers.get('Date', '')}\n"
                f"   {snippet}...\n"
                f"   ID: {msg_ref['id']}"
            )

        return "\n".join(lines)

    except Exception as e:
        return f"メール検索エラー: {str(e)}"


def _read_email(message_id: str) -> str:
    """メールの内容を読む。"""
    service = _get_gmail_service()
    if service is None:
        return _fallback()

    if not message_id:
        return "メールIDを指定してください。"

    try:
        msg = service.users().messages().get(
            userId="me",
            id=message_id,
            format="full",
        ).execute()

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body_text = _extract_body(msg.get("payload", {}))

        return (
            f"📧 {headers.get('Subject', '(件名なし)')}\n"
            f"From: {headers.get('From', '不明')}\n"
            f"To: {headers.get('To', '不明')}\n"
            f"Date: {headers.get('Date', '不明')}\n"
            f"{'─' * 40}\n"
            f"{body_text[:5000]}"
        )

    except Exception as e:
        return f"メール読み取りエラー: {str(e)}"


def _create_draft(to: str, subject: str, body: str, cc: str = "") -> str:
    """下書きを作成する。"""
    service = _get_gmail_service()
    if service is None:
        return _fallback()

    if not to or not subject or not body:
        return "宛先(to)、件名(subject)、本文(body)を指定してください。"

    try:
        message = _build_message(to, subject, body, cc)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        draft = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}},
        ).execute()

        return (
            f"✅ 下書きを作成しました\n"
            f"宛先: {to}\n"
            f"件名: {subject}\n"
            f"下書きID: {draft['id']}\n"
            f"※ Gmailの下書きフォルダで確認・編集・送信できます"
        )

    except Exception as e:
        return f"下書き作成エラー: {str(e)}"


def _send_email(to: str, subject: str, body: str, cc: str = "") -> str:
    """メールを送信する。"""
    service = _get_gmail_service()
    if service is None:
        return _fallback()

    if not to or not subject or not body:
        return "宛先(to)、件名(subject)、本文(body)を指定してください。"

    try:
        message = _build_message(to, subject, body, cc)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        sent = service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()

        return (
            f"✅ メールを送信しました\n"
            f"宛先: {to}\n"
            f"件名: {subject}\n"
            f"メッセージID: {sent['id']}"
        )

    except Exception as e:
        return f"メール送信エラー: {str(e)}"


def _reply_email(message_id: str, body: str) -> str:
    """メールに返信する。"""
    service = _get_gmail_service()
    if service is None:
        return _fallback()

    if not message_id or not body:
        return "メールID(message_id)と本文(body)を指定してください。"

    try:
        # 元メールの情報を取得
        original = service.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "To", "Subject", "Message-ID"],
        ).execute()

        headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}
        reply_to = headers.get("From", "")
        subject = headers.get("Subject", "")
        if not subject.startswith("Re:"):
            subject = f"Re: {subject}"
        original_msg_id = headers.get("Message-ID", "")
        thread_id = original.get("threadId", "")

        message = _build_message(reply_to, subject, body)
        if original_msg_id:
            message["In-Reply-To"] = original_msg_id
            message["References"] = original_msg_id

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        sent = service.users().messages().send(
            userId="me",
            body={"raw": raw, "threadId": thread_id},
        ).execute()

        return (
            f"✅ 返信を送信しました\n"
            f"宛先: {reply_to}\n"
            f"件名: {subject}"
        )

    except Exception as e:
        return f"返信エラー: {str(e)}"


def _build_message(to: str, subject: str, body: str, cc: str = "") -> MIMEText:
    """MIMEメッセージを構築する。"""
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = to
    message["subject"] = subject
    if cc:
        message["cc"] = cc
    return message


def _extract_body(payload: dict) -> str:
    """メールペイロードからテキスト本文を抽出する。"""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        # multipart の再帰
        if part.get("parts"):
            result = _extract_body(part)
            if result:
                return result

    return "(本文を取得できませんでした)"


def _fallback() -> str:
    return (
        "Gmail連携が設定されていません。\n"
        "管理者にGOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET / "
        "GOOGLE_OAUTH_REFRESH_TOKEN 環境変数の設定を依頼してください。"
    )


def execute(params: dict) -> str:
    """ツール実行のエントリーポイント。"""
    action = params.get("action", "search")

    if action == "search":
        query = params.get("query", "")
        max_results = params.get("max_results", 5)
        if not query:
            return "検索クエリを指定してください。"
        return _search_emails(query, max_results)

    if action == "read":
        return _read_email(params.get("message_id", ""))

    if action == "draft":
        return _create_draft(
            params.get("to", ""),
            params.get("subject", ""),
            params.get("body", ""),
            params.get("cc", ""),
        )

    if action == "send":
        return _send_email(
            params.get("to", ""),
            params.get("subject", ""),
            params.get("body", ""),
            params.get("cc", ""),
        )

    if action == "reply":
        return _reply_email(
            params.get("message_id", ""),
            params.get("body", ""),
        )

    return f"不明なアクション: {action}"
