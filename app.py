"""
ヒダネ AI社員チャットシステム
- Web Chat UI: http://localhost:5555
- LINE Bot Webhook: http://localhost:5555/line/webhook
"""

import os
import json
import hmac
import hashlib
import base64
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS

from employees import (
    EMPLOYEES, route_message, get_employee, get_all_employees,
    get_departments, get_department_responder, DEPARTMENTS,
)

app = Flask(__name__)
CORS(app)

# 設定
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

# 会話履歴（メモリ内。本番ではDBに移行）
conversations = {}

# ============================================================
# Web Chat UI
# ============================================================

@app.route("/")
def index():
    """メインチャットUI"""
    return render_template("chat.html")


@app.route("/api/employees")
def api_employees():
    """全AI社員リスト"""
    return jsonify(get_all_employees())


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """チャットAPI"""
    data = request.json
    message = data.get("message", "")
    target = data.get("employee")  # 指定なしなら自動ルーティング
    session_id = data.get("session_id", "default")

    # 社員ルーティング
    if target and target in EMPLOYEES:
        employee_name = target
    else:
        employee_name = route_message(message)

    emp = get_employee(employee_name)

    # API呼び出し or モックレスポンス
    if ANTHROPIC_API_KEY:
        response_text = call_claude_api(message, emp, session_id)
    else:
        response_text = generate_mock_response(message, emp)

    return jsonify({
        "employee": employee_name,
        "employee_id": emp["id"],
        "employee_role": emp["role"],
        "employee_color": emp["color"],
        "avatar": emp["avatar"],
        "message": response_text,
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/api/route", methods=["POST"])
def api_route():
    """メッセージの振り分け先を確認（送信前のプレビュー用）"""
    data = request.json
    message = data.get("message", "")
    dept = data.get("department")

    if dept and dept in DEPARTMENTS:
        name = get_department_responder(dept, message)
    else:
        name = route_message(message)

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
def api_chat_department():
    """部署グループチャットAPI"""
    data = request.json
    message = data.get("message", "")
    dept_name = data.get("department", "")
    session_id = data.get("session_id", f"dept_{dept_name}")

    if dept_name not in DEPARTMENTS:
        return jsonify({"error": "Unknown department"}), 400

    # 部署内で最適な回答者を選定
    responder_name = get_department_responder(dept_name, message)
    emp = get_employee(responder_name)

    if ANTHROPIC_API_KEY:
        response_text = call_claude_api(message, emp, session_id)
    else:
        response_text = generate_mock_response(message, emp)

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
    """チャネル別の会話履歴を取得"""
    history = conversations.get(channel_id, [])
    return jsonify(history)


@app.route("/static/avatars/<path:filename>")
def serve_avatar(filename):
    """アバター画像配信"""
    return send_from_directory("static/avatars", filename)


# ============================================================
# LINE Bot Webhook
# ============================================================

@app.route("/line/webhook", methods=["POST"])
def line_webhook():
    """LINE Bot Webhook受信"""
    body = request.get_data(as_text=True)

    # 署名検証
    if LINE_CHANNEL_SECRET:
        signature = request.headers.get("X-Line-Signature", "")
        if not verify_line_signature(body, signature):
            return "Invalid signature", 403

    try:
        events = json.loads(body).get("events", [])
    except json.JSONDecodeError:
        return "Bad request", 400

    for event in events:
        if event.get("type") == "message" and event["message"].get("type") == "text":
            handle_line_message(event)

    return "OK", 200


def verify_line_signature(body: str, signature: str) -> bool:
    """LINE署名検証"""
    gen_signature = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return hmac.compare_digest(signature, base64.b64encode(gen_signature).decode())


def handle_line_message(event: dict):
    """LINEメッセージ処理"""
    reply_token = event.get("replyToken", "")
    user_id = event["source"].get("userId", "unknown")
    text = event["message"]["text"]

    # 社員ルーティング
    employee_name = route_message(text)
    emp = get_employee(employee_name)

    # レスポンス生成
    if ANTHROPIC_API_KEY:
        response_text = call_claude_api(text, emp, f"line_{user_id}")
    else:
        response_text = generate_mock_response(text, emp)

    # 名前バナー付きレスポンス
    banner = f"━━━━━━━━━━━━━━━\n💬 {emp['full_name']}（{emp['role']}）\n━━━━━━━━━━━━━━━"
    full_response = f"{banner}\n\n{response_text}"

    # LINE返信
    reply_to_line(reply_token, full_response)


def reply_to_line(reply_token: str, text: str):
    """LINEにメッセージ返信"""
    import urllib.request

    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    data = json.dumps({
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text[:5000]}],
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"LINE reply error: {e}")


# ============================================================
# Claude API 呼び出し
# ============================================================

def call_claude_api(message: str, employee: dict, session_id: str) -> str:
    """Claude APIを使ってAI社員として応答"""
    import urllib.request

    # 会話履歴取得
    if session_id not in conversations:
        conversations[session_id] = []

    history = conversations[session_id][-10:]  # 直近10往復

    messages = []
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    # AI社員一覧（他社員への言及用）
    employee_list = "、".join(
        f"{v['full_name']}（{v['role']}）"
        for v in EMPLOYEES.values()
    )

    system = (
        f"{employee['system_prompt']}\n\n"
        "【重要：あなたの立場】\n"
        "あなたは株式会社ヒダネの社内チャットシステム上で動作するAI社員です。"
        "話し相手は社長の中野祐揮（なかの・ゆうき）さんです。「中野さん」と呼んでください。"
        "あなたへのメッセージは業務指示・質問・雑談・フィードバックなど様々です。"
        "メッセージの内容をよく読み、的確に応答してください。"
        "知らないことは「確認します」と答え、存在しない人名や情報を捏造しないでください。\n\n"
        "【AI社員チーム】\n"
        f"{employee_list}\n"
        "※全員AI社員です。呼ぶときは下の名前（ソウ、リサ、ルナ等）で呼んでください。\n\n"
        "【会社情報】株式会社ヒダネ（名古屋）代表：中野祐揮。"
        "法人向けAI活用研修（助成金活用）、AIコンサル、SNS運用代行の3事業。"
        "研修単価40万円/人/コース（助成金75%で企業負担10万円）。"
        "6コース準備済み（AI研修3＋動画内製化3）。\n"
        "【トーンルール】誠実・信用重視。煽らない。「ぜひ」「お得」「今だけ」「特別」「革命的」「最強」は使わない。"
        "数字は根拠を明記。推測値は「（推定）」を付ける。"
        "助成金の記載は「活用の可能性」「条件を満たせば申請可能」。"
    )

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
            response_text = result["content"][0]["text"]

            # 履歴保存
            conversations[session_id].append({"role": "user", "content": message})
            conversations[session_id].append({"role": "assistant", "content": response_text})

            # 最大50往復で切り捨て
            if len(conversations[session_id]) > 100:
                conversations[session_id] = conversations[session_id][-100:]

            return response_text
    except Exception as e:
        return f"申し訳ございません、接続エラーが発生しました: {str(e)}"


# ============================================================
# モックレスポンス（API未設定時）
# ============================================================

def generate_mock_response(message: str, employee: dict) -> str:
    """APIキー未設定時のデモレスポンス"""
    name = employee["full_name"].split()[-1]
    role = employee["role"]

    responses = {
        "ソウ": (
            f"お疲れ様です。{name}です。\n\n"
            f"「{message[:30]}」について確認しました。\n\n"
            "こちらは現在デモモードで動作しています。\n"
            "本番稼働にはANTHROPIC_API_KEYの設定が必要です。\n\n"
            "設定方法:\n"
            "export ANTHROPIC_API_KEY=sk-ant-xxxxx\n\n"
            "設定後、AI社員が実際にClaude APIを使って応答します。"
        ),
        "リサ": (
            f"中野さん！リサです！\n\n"
            f"「{message[:30]}」の件、了解しました！\n"
            "リサーチデータ集めて、提案書にまとめちゃいますね！\n\n"
            "※デモモードで動作中です。ANTHROPIC_API_KEY設定で本番稼働します。"
        ),
        "ルナ": (
            f"中野さん！ルナです！\n\n"
            f"「{message[:30]}」ですね！\n"
            "これ、バズりそうなネタですね！台本書いちゃいますよ！\n\n"
            "※デモモードで動作中です。ANTHROPIC_API_KEY設定で本番稼働します。"
        ),
        "マコト": (
            f"マコトっす！\n\n"
            f"「{message[:30]}」の件、了解っす！\n"
            "DMリストと送信テンプレ、すぐ用意しますよ！\n\n"
            "※デモモードで動作中です。ANTHROPIC_API_KEY設定で本番稼働します。"
        ),
    }

    return responses.get(name, (
        f"{employee['greeting']}\n\n"
        f"「{message[:30]}」について承りました。\n"
        f"{role}として対応いたします。\n\n"
        "※デモモードで動作中です。ANTHROPIC_API_KEY設定で本番稼働します。"
    ))


# ============================================================
# メイン
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5555))
    print(f"""
╔══════════════════════════════════════════════════╗
║     🔥 ヒダネ AI社員チャットシステム 起動        ║
╠══════════════════════════════════════════════════╣
║                                                  ║
║  Web Chat UI:  http://localhost:{port}             ║
║  LINE Webhook: http://localhost:{port}/line/webhook ║
║                                                  ║
║  API Key: {"✅ 設定済み" if ANTHROPIC_API_KEY else "❌ 未設定（デモモード）"}              ║
║  LINE:    {"✅ 設定済み" if LINE_CHANNEL_SECRET else "❌ 未設定"}              ║
║                                                  ║
╚══════════════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=port, debug=True)
