/**
 * ヒダネ AI社員チャット - 会話エクスポート
 */

let _exportStyleInjected = false;

/**
 * エクスポート用スタイルを注入（初回のみ）
 */
function _injectExportStyle() {
    if (_exportStyleInjected) return;
    _exportStyleInjected = true;

    const style = document.createElement("style");
    style.textContent = `
        .export-wrapper {
            position: relative;
            display: inline-block;
        }
        .export-btn {
            background: var(--bg-tertiary);
            color: var(--text-secondary);
            border: 1px solid var(--border);
            padding: 6px 12px;
            border-radius: var(--radius-sm);
            font-size: 13px;
            font-family: inherit;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
        }
        .export-btn:hover {
            background: var(--bg-hover);
            border-color: var(--accent);
            color: var(--text-primary);
        }
        .export-dropdown {
            position: absolute;
            top: calc(100% + 4px);
            right: 0;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            box-shadow: var(--shadow);
            z-index: 200;
            min-width: 150px;
            overflow: hidden;
            display: none;
        }
        .export-dropdown.open {
            display: block;
            animation: fadeIn 0.15s ease;
        }
        .export-dropdown button {
            display: flex;
            align-items: center;
            gap: 8px;
            width: 100%;
            background: none;
            border: none;
            color: var(--text-primary);
            padding: 10px 14px;
            font-size: 13px;
            font-family: inherit;
            cursor: pointer;
            transition: background 0.15s;
            text-align: left;
        }
        .export-dropdown button:hover {
            background: var(--bg-hover);
        }
        .export-dropdown button .export-icon {
            font-size: 15px;
            flex-shrink: 0;
        }
        .export-dropdown-divider {
            height: 1px;
            background: var(--border);
            margin: 0;
        }
    `;
    document.head.appendChild(style);
}

/**
 * 会話データをエクスポート
 * @param {string} sessionId - セッションID
 * @param {string} format - "json" | "csv" | "txt"
 * @returns {Promise<void>}
 */
async function exportConversation(sessionId, format) {
    if (!sessionId) {
        console.error("[export] sessionId is required");
        return;
    }

    const validFormats = ["json", "csv", "txt"];
    if (!validFormats.includes(format)) {
        console.error(`[export] invalid format: ${format}`);
        return;
    }

    try {
        const url = `/api/export/${encodeURIComponent(sessionId)}?format=${encodeURIComponent(format)}`;
        const response = await fetch(url);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const blob = await response.blob();
        const employeeName = _resolveEmployeeName(sessionId);
        const date = _formatDate(new Date());
        const ext = format === "txt" ? "txt" : format;
        const filename = `chat_${employeeName}_${date}.${ext}`;

        _triggerDownload(blob, filename);
    } catch (err) {
        console.error("[export] download failed:", err);
        alert("エクスポートに失敗しました。もう一度お試しください。");
    }
}

/**
 * セッションIDから社員名を推定
 * @param {string} sessionId
 * @returns {string}
 */
function _resolveEmployeeName(sessionId) {
    if (!sessionId) return "chat";
    if (sessionId === "auto") return "自動振分";
    if (sessionId.startsWith("emp_")) return sessionId.slice(4);
    if (sessionId.startsWith("dept_")) return sessionId.slice(5);
    return "chat";
}

/**
 * 日付を YYYYMMDD 形式にフォーマット
 * @param {Date} date
 * @returns {string}
 */
function _formatDate(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}${m}${d}`;
}

/**
 * Blob をダウンロードトリガー
 * @param {Blob} blob
 * @param {string} filename
 */
function _triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * エクスポートドロップダウンメニューをヘッダーに追加
 * @param {HTMLElement} headerElement - .header-actions 要素
 */
function createExportMenu(headerElement) {
    if (!headerElement) return;
    _injectExportStyle();

    const wrapper = document.createElement("div");
    wrapper.className = "export-wrapper";

    // トリガーボタン
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "export-btn";
    btn.innerHTML = `<span class="export-icon">📥</span><span>エクスポート</span>`;

    // ドロップダウン
    const dropdown = document.createElement("div");
    dropdown.className = "export-dropdown";

    const formats = [
        { format: "json", icon: "📋", label: "JSON" },
        { format: "csv", icon: "📊", label: "CSV" },
        { format: "txt", icon: "📝", label: "テキスト" },
    ];

    formats.forEach((item, index) => {
        if (index > 0) {
            const divider = document.createElement("div");
            divider.className = "export-dropdown-divider";
            dropdown.appendChild(divider);
        }

        const option = document.createElement("button");
        option.type = "button";
        option.innerHTML = `<span class="export-icon">${item.icon}</span><span>${item.label}</span>`;

        option.addEventListener("click", () => {
            dropdown.classList.remove("open");
            // state.currentChannel は chat.js のグローバル state から取得
            const sessionId =
                typeof state !== "undefined" && state.currentChannel
                    ? state.currentChannel
                    : "auto";
            exportConversation(sessionId, item.format);
        });

        dropdown.appendChild(option);
    });

    // トグル
    btn.addEventListener("click", (e) => {
        e.stopPropagation();
        dropdown.classList.toggle("open");
    });

    // 外部クリックで閉じる
    document.addEventListener("click", () => {
        dropdown.classList.remove("open");
    });

    // ドロップダウン内クリックの伝播を止める
    dropdown.addEventListener("click", (e) => {
        e.stopPropagation();
    });

    wrapper.appendChild(btn);
    wrapper.appendChild(dropdown);
    headerElement.appendChild(wrapper);
}
