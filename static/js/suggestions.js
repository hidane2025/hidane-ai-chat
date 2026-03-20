/**
 * ヒダネ AI社員チャット - クイックリプライ候補システム
 */

const SUGGESTIONS = {
    auto: [
        "今月の売上状況は？",
        "〇〇社の提案書を作って",
        "助成金の申請状況は？",
        "SNSの投稿案を出して",
        "研修スケジュールを確認",
    ],
    ソウ: [
        "チーム全体の状況を教えて",
        "今日のタスクを整理して",
        "会議の議事録をまとめて",
    ],
    リサ: [
        "〇〇社のリサーチをして",
        "提案書を作成して",
        "商談台本を準備して",
    ],
    ルナ: [
        "TikTok投稿案を3つ出して",
        "今週のSNS戦略は？",
        "ハッシュタグを提案して",
    ],
    カナタ: [
        "助成金の申請状況は？",
        "新しい制度を調べて",
        "費用シミュレーションして",
    ],
    ハルト: [
        "研修カリキュラムを確認して",
        "eラーニング素材を作成して",
        "受講者の進捗状況は？",
    ],
    ミナト: [
        "今月のKPIを報告して",
        "経費精算の状況は？",
        "来週のスケジュールを整理して",
    ],
    アオイ: [
        "顧客満足度データを分析して",
        "問い合わせ対応状況は？",
        "フォローアップリストを出して",
    ],
};

let _suggestionsStyleInjected = false;

/**
 * スタイル要素をDOMに注入（初回のみ）
 */
function _injectSuggestionsStyle() {
    if (_suggestionsStyleInjected) return;
    _suggestionsStyleInjected = true;

    const style = document.createElement("style");
    style.textContent = `
        .suggestion-container {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            padding: 8px 0;
        }
        .suggestion-chip {
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            border-radius: 20px;
            padding: 8px 16px;
            cursor: pointer;
            font-size: 13px;
            font-family: inherit;
            transition: all 0.2s;
            white-space: nowrap;
            user-select: none;
            line-height: 1.4;
        }
        .suggestion-chip:hover {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }
        .suggestion-chip:active {
            transform: scale(0.96);
        }
    `;
    document.head.appendChild(style);
}

/**
 * サジェスチョンチップを描画
 * @param {string} channelType - "auto" | "employee" | "department"
 * @param {string|null} employeeName - 社員名（employee チャンネルの場合）
 * @param {HTMLElement} containerElement - チップを挿入するコンテナ
 */
function renderSuggestions(channelType, employeeName, containerElement) {
    _injectSuggestionsStyle();
    clearSuggestions(containerElement);

    let items = [];

    if (channelType === "auto") {
        items = SUGGESTIONS.auto || [];
    } else if (channelType === "employee" && employeeName) {
        items = SUGGESTIONS[employeeName] || SUGGESTIONS.auto || [];
    } else {
        // department の場合は auto のサジェスチョンを表示
        items = SUGGESTIONS.auto || [];
    }

    if (items.length === 0) return;

    const wrapper = document.createElement("div");
    wrapper.className = "suggestion-container";

    for (const text of items) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "suggestion-chip";
        chip.textContent = text;

        chip.addEventListener("click", () => {
            const input = document.querySelector("#messageInput");
            if (input) {
                input.value = text;
                input.focus();
                // input イベントを発火してボタン状態を更新
                input.dispatchEvent(new Event("input", { bubbles: true }));
            }

            // 送信ボタンをクリック
            const sendBtn = document.querySelector("#sendBtn");
            if (sendBtn && !sendBtn.disabled) {
                sendBtn.click();
            }

            clearSuggestions(containerElement);
        });

        wrapper.appendChild(chip);
    }

    containerElement.appendChild(wrapper);
}

/**
 * サジェスチョンを消去
 * @param {HTMLElement} containerElement
 */
function clearSuggestions(containerElement) {
    if (!containerElement) return;
    const existing = containerElement.querySelector(".suggestion-container");
    if (existing) {
        existing.remove();
    }
}
