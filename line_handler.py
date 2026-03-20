"""
LINE Bot Webhook処理モジュール
app.pyからLINE関連ロジックを分離。
"""

import os
import re
import json
import hmac
import time
import hashlib
import base64
import urllib.request
from datetime import datetime

from employees import EMPLOYEES, route_message, get_employee
from knowledge import build_knowledge_context
from database import save_message, get_history, log_usage
from system_prompt import build_system_prompt

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://hidane-ai-chat.onrender.com")


def handle_line_webhook(request):
    """LINE Bot Webhook受信のメイン処理"""
    body = request.get_data(as_text=True)

    # 署名検証
    if LINE_CHANNEL_SECRET:
        signature = request.headers.get("X-Line-Signature", "")
        if not _verify_signature(body, signature):
            return "Invalid signature", 403

    try:
        events = json.loads(body).get("events", [])
    except json.JSONDecodeError:
        return "Bad request", 400

    for event in events:
        if event.get("type") == "message" and event["message"].get("type") == "text":
            _handle_message(event)

    return "OK", 200


def _verify_signature(body: str, signature: str) -> bool:
    """LINE署名検証"""
    gen_signature = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return hmac.compare_digest(signature, base64.b64encode(gen_signature).decode())


def _handle_message(event: dict):
    """LINEメッセージ処理"""
    start_time = time.time()
    reply_token = event.get("replyToken", "")
    user_id = event["source"].get("userId", "unknown")
    text = event["message"]["text"]
    session_id = f"line_{user_id}"

    # 社員ルーティング
    employee_name = route_message(text)
    emp = get_employee(employee_name)

    # レスポンス生成
    if ANTHROPIC_API_KEY:
        history = get_history(session_id, limit=10)
        system = build_system_prompt(emp, employee_name)
        response_text = _call_api(text, history, system)
    else:
        response_text = f"{emp['greeting']}\n\nデモモードで動作中です。"

    # DB保存
    save_message(session_id, "user", text, employee_name, emp["id"])
    save_message(session_id, "assistant", response_text, employee_name, emp["id"])

    elapsed_ms = int((time.time() - start_time) * 1000)
    log_usage(session_id, user_id, "hidane", employee_name, len(text), len(response_text), elapsed_ms)

    # 名前バナー付きレスポンス
    banner = f"━━━━━━━━━━━━━━━\n💬 {emp['full_name']}（{emp['role']}）\n━━━━━━━━━━━━━━━"

    # PDF添付を検出
    pdf_attachments = _extract_pdf_tags(response_text)
    clean_text = _strip_pdf_tags(response_text)
    full_response = f"{banner}\n\n{clean_text}"

    # LINE返信
    messages = [{"type": "text", "text": full_response[:5000]}]
    for pdf in pdf_attachments[:2]:
        messages.append(_build_pdf_flex(pdf["filename"], pdf["title"]))

    _reply_multi(reply_token, messages)


def _call_api(message: str, history: list, system: str) -> str:
    """Claude API呼び出し"""
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})

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

    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            result = json.loads(res.read().decode())
            return result["content"][0]["text"]
    except Exception as e:
        return f"申し訳ございません、接続エラーが発生しました: {str(e)}"


def _extract_pdf_tags(text: str) -> list:
    """テキストから [PDF:filename:title] タグを抽出"""
    return [
        {"filename": m.group(1), "title": m.group(2)}
        for m in re.finditer(r'\[PDF:([^\]:]+\.pdf):([^\]]+)\]', text)
    ]


def _strip_pdf_tags(text: str) -> str:
    """テキストから [PDF:...] タグを除去"""
    cleaned = re.sub(r'\[PDF:[^\]:]+\.pdf:[^\]]+\]', '', text)
    return re.sub(r'\n{3,}', '\n\n', cleaned).strip()


def _build_pdf_flex(filename: str, title: str) -> dict:
    """LINE Flex MessageでPDFカードを構築"""
    pdf_url = f"{BASE_URL}/api/files/{filename}"
    return {
        "type": "flex",
        "altText": f"📄 {title}",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": "📄", "size": "xxl", "flex": 0, "gravity": "center"},
                    {
                        "type": "box", "layout": "vertical", "flex": 1, "margin": "md",
                        "contents": [
                            {"type": "text", "text": title, "weight": "bold", "size": "sm", "wrap": True},
                            {"type": "text", "text": filename, "size": "xxs", "color": "#888888"},
                        ],
                    },
                ],
                "paddingAll": "lg",
            },
            "footer": {
                "type": "box", "layout": "horizontal", "paddingAll": "md",
                "contents": [{
                    "type": "button",
                    "action": {"type": "uri", "label": "PDFを開く", "uri": pdf_url},
                    "style": "primary", "height": "sm", "color": "#6C5CE7",
                }],
            },
        },
    }


def _reply_multi(reply_token: str, messages: list):
    """LINEに複数メッセージ返信"""
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    data = json.dumps({
        "replyToken": reply_token,
        "messages": messages[:5],
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"LINE reply error: {e}")
