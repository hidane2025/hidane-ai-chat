"""
ナレッジベース管理モジュール
knowledge.pyのCOMPANY_COREやEMPLOYEE_KNOWLEDGEを
Web管理画面から編集可能にする。
カスタムFAQ・社内情報をJSON形式で保存・読み込み。
"""

import json
from datetime import datetime
from pathlib import Path

# カスタムナレッジの保存先
KNOWLEDGE_DIR = Path(__file__).parent / "data" / "knowledge"


def init_knowledge_dir():
    """ナレッジディレクトリを初期化"""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    # デフォルトのcustom_knowledge.jsonがなければ作成
    default_path = KNOWLEDGE_DIR / "custom_knowledge.json"
    if not default_path.exists():
        default_data = {
            "company_info": [],
            "faq": [],
            "employee_notes": {},
            "updated_at": datetime.now().isoformat(),
        }
        default_path.write_text(
            json.dumps(default_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_custom_knowledge(company_id="hidane"):
    """カスタムナレッジをJSONから読み込む"""
    init_knowledge_dir()
    path = KNOWLEDGE_DIR / f"{company_id}_knowledge.json"
    if not path.exists():
        path = KNOWLEDGE_DIR / "custom_knowledge.json"
    if not path.exists():
        return {"company_info": [], "faq": [], "employee_notes": {}}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, OSError):
        return {"company_info": [], "faq": [], "employee_notes": {}}


def save_custom_knowledge(data, company_id="hidane"):
    """カスタムナレッジをJSONに保存"""
    init_knowledge_dir()
    path = KNOWLEDGE_DIR / f"{company_id}_knowledge.json"

    # タイムスタンプを付加した新しいデータを作成（元データは変更しない）
    save_data = {
        **data,
        "updated_at": datetime.now().isoformat(),
    }

    path.write_text(
        json.dumps(save_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return save_data


def add_faq(question, answer, company_id="hidane"):
    """FAQ項目を追加"""
    data = load_custom_knowledge(company_id)
    new_faq = {
        "id": f"faq_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "question": question,
        "answer": answer,
        "created_at": datetime.now().isoformat(),
    }
    updated_data = {
        **data,
        "faq": [*data.get("faq", []), new_faq],
    }
    return save_custom_knowledge(updated_data, company_id), new_faq


def remove_faq(faq_id, company_id="hidane"):
    """FAQ項目を削除"""
    data = load_custom_knowledge(company_id)
    updated_data = {
        **data,
        "faq": [f for f in data.get("faq", []) if f.get("id") != faq_id],
    }
    return save_custom_knowledge(updated_data, company_id)


def add_company_info(title, content, company_id="hidane"):
    """会社情報を追加"""
    data = load_custom_knowledge(company_id)
    new_info = {
        "id": f"info_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "title": title,
        "content": content,
        "created_at": datetime.now().isoformat(),
    }
    updated_data = {
        **data,
        "company_info": [*data.get("company_info", []), new_info],
    }
    return save_custom_knowledge(updated_data, company_id), new_info


def remove_company_info(info_id, company_id="hidane"):
    """会社情報を削除"""
    data = load_custom_knowledge(company_id)
    updated_data = {
        **data,
        "company_info": [i for i in data.get("company_info", []) if i.get("id") != info_id],
    }
    return save_custom_knowledge(updated_data, company_id)


def set_employee_note(employee_name, note, company_id="hidane"):
    """社員別の追加ノートを設定"""
    data = load_custom_knowledge(company_id)
    updated_notes = {
        **data.get("employee_notes", {}),
        employee_name: {
            "note": note,
            "updated_at": datetime.now().isoformat(),
        },
    }
    updated_data = {
        **data,
        "employee_notes": updated_notes,
    }
    return save_custom_knowledge(updated_data, company_id)


def build_custom_context(employee_name=None, company_id="hidane"):
    """カスタムナレッジからコンテキスト文字列を構築

    knowledge.pyのbuild_knowledge_contextに追加注入される。
    """
    data = load_custom_knowledge(company_id)
    parts = []

    # 会社追加情報
    company_info = data.get("company_info", [])
    if company_info:
        info_lines = [f"- {i['title']}: {i['content']}" for i in company_info]
        parts.append("【追加の会社情報】\n" + "\n".join(info_lines))

    # FAQ
    faq = data.get("faq", [])
    if faq:
        faq_lines = [f"Q: {f['question']}\nA: {f['answer']}" for f in faq]
        parts.append("【よくある質問（社内FAQ）】\n" + "\n\n".join(faq_lines))

    # 社員別ノート
    if employee_name:
        notes = data.get("employee_notes", {})
        emp_note = notes.get(employee_name, {})
        if emp_note and emp_note.get("note"):
            parts.append(f"【{employee_name}への追加指示】\n{emp_note['note']}")

    return "\n\n".join(parts) if parts else ""
