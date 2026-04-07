(function () {
    if (window.WmsChatUi) {
        return;
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function normalizeChatText(rootNode) {
        const target = rootNode || document.body;
        if (!target || !window.NodeFilter || !document.createTreeWalker) {
            return;
        }

        const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
        let node = walker.nextNode();
        while (node) {
            if (node.nodeValue) {
                node.nodeValue = node.nodeValue
                    .replace(/ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¢/g, "|")
                    .replace(/ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â¦/g, "...")
                    .replace(/ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢/g, "|")
                    .replace(/ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¦/g, "...");
            }
            node = walker.nextNode();
        }
    }

    function normalizeTimestamp(rawValue) {
        const raw = String(rawValue || "").trim();
        if (!raw) {
            return "";
        }
        const normalized = raw.replace("T", " ");
        return normalized.length === 16 ? `${normalized}:00` : normalized;
    }

    function parseTimestamp(rawValue) {
        const normalized = normalizeTimestamp(rawValue);
        if (!normalized) {
            return null;
        }
        const withTimezone = normalized.includes("Z") ? normalized : normalized.replace(" ", "T");
        const parsed = new Date(withTimezone);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    function buildMessageContent(message) {
        if ((message.message_type || "text") === "attachment") {
            return `
                <div class="chat-message-attachment">
                    <div>
                        <strong>${escapeHtml(message.attachment_name || "Lampiran")}</strong>
                        <span>${escapeHtml(message.attachment_size_label || "")}</span>
                    </div>
                    <a href="${escapeHtml(message.attachment_url || "#")}" target="_blank" rel="noopener">Buka</a>
                </div>
                ${message.body ? `<p>${escapeHtml(message.body)}</p>` : ""}
            `;
        }

        if ((message.message_type || "text") === "sticker") {
            const stickerLabel = (message.sticker && message.sticker.label) || message.body || "Sticker";
            const stickerImageUrl = message.sticker_image_url || message.attachment_url || "";
            return `
                <div class="chat-sticker-bubble ${stickerImageUrl ? "has-image" : ""}">
                    ${stickerImageUrl
                        ? `<img src="${escapeHtml(stickerImageUrl)}" alt="${escapeHtml(stickerLabel)}" loading="lazy">`
                        : `<span>${escapeHtml((message.sticker && message.sticker.emoji) || "\u{1F7E6}")}</span>
                           <strong>${escapeHtml(stickerLabel)}</strong>`}
                </div>
            `;
        }

        if ((message.message_type || "text") === "call") {
            return `
                <div class="chat-call-bubble">
                    <strong>${escapeHtml(message.call_label || "Telp")}</strong>
                    <p>${escapeHtml(message.body || "")}</p>
                </div>
            `;
        }

        return `<p>${escapeHtml(message.body || "")}</p>`;
    }

    function buildReplyPreviewMarkup(replyPreview) {
        if (!replyPreview || !replyPreview.id) {
            return "";
        }

        return `
            <button
                type="button"
                class="chat-reply-quote"
                data-chat-jump-message-id="${escapeHtml(replyPreview.id)}"
                aria-label="Lihat pesan yang dikutip"
            >
                <span class="chat-reply-quote-bar" aria-hidden="true"></span>
                <span class="chat-reply-quote-copy">
                    <strong>${escapeHtml(replyPreview.sender_name || "Pesan")}</strong>
                    <span>${escapeHtml(replyPreview.preview || "")}</span>
                </span>
            </button>
        `;
    }

    function shouldGroupMessage(previousMessage, currentMessage) {
        if (!previousMessage || !currentMessage) {
            return false;
        }
        if (Number(previousMessage.sender_id || 0) !== Number(currentMessage.sender_id || 0)) {
            return false;
        }
        if (String(previousMessage.day_key || "") !== String(currentMessage.day_key || "")) {
            return false;
        }
        if ((previousMessage.message_type || "text") === "call" || (currentMessage.message_type || "text") === "call") {
            return false;
        }

        const previousTime = parseTimestamp(previousMessage.created_at);
        const currentTime = parseTimestamp(currentMessage.created_at);
        if (!previousTime || !currentTime) {
            return false;
        }

        const gapMs = currentTime.getTime() - previousTime.getTime();
        return gapMs >= 0 && gapMs <= 5 * 60 * 1000;
    }

    function renderMessageTimeline(messages) {
        if (!Array.isArray(messages) || !messages.length) {
            return "";
        }

        let html = "";
        let currentDayKey = "";
        let previousMessage = null;

        messages.forEach((message) => {
            const dayKey = String(message.day_key || "");
            if (dayKey && dayKey !== currentDayKey) {
                currentDayKey = dayKey;
                html += `
                    <div class="chat-day-separator" data-day-key="${escapeHtml(dayKey)}">
                        <span>${escapeHtml(message.day_label || "-")}</span>
                    </div>
                `;
            }

            const grouped = shouldGroupMessage(previousMessage, message);
            const mineClass = message.is_mine ? "mine" : "other";
            const senderMeta = (message.is_mine || grouped) ? "" : `
                <div class="chat-message-sender">
                    <span class="chat-avatar mini">${escapeHtml(message.sender_initials || "?")}</span>
                    <strong>${escapeHtml(message.sender_name || "-")}</strong>
                </div>
            `;

            html += `
                <article class="chat-message-row ${mineClass}${grouped ? " is-grouped" : ""}" data-message-id="${escapeHtml(message.id || "")}">
                    ${senderMeta}
                    <div class="chat-message-bubble chat-message-type-${escapeHtml(message.message_type || "text")}">
                        ${buildReplyPreviewMarkup(message.reply_preview)}
                        ${buildMessageContent(message)}
                        <div class="chat-message-meta-row">
                            <time>${escapeHtml(message.created_label || "-")}</time>
                            <button
                                type="button"
                                class="chat-message-action"
                                data-chat-reply-message-id="${escapeHtml(message.id || "")}"
                            >
                                Balas
                            </button>
                        </div>
                    </div>
                </article>
            `;
            previousMessage = message;
        });

        return html;
    }

    function mergeMessages(existingMessages, incomingMessages) {
        const merged = [];
        const seenIds = new Set();

        (Array.isArray(existingMessages) ? existingMessages : []).forEach((message) => {
            const messageId = Number(message && message.id);
            if (messageId > 0 && seenIds.has(messageId)) {
                return;
            }
            if (messageId > 0) {
                seenIds.add(messageId);
            }
            merged.push(message);
        });

        (Array.isArray(incomingMessages) ? incomingMessages : []).forEach((message) => {
            const messageId = Number(message && message.id);
            if (messageId > 0 && seenIds.has(messageId)) {
                return;
            }
            if (messageId > 0) {
                seenIds.add(messageId);
            }
            merged.push(message);
        });

        merged.sort((left, right) => Number(left.id || 0) - Number(right.id || 0));
        return merged;
    }

    function draftStorageKey(threadId) {
        const safeThreadId = Number(threadId || 0);
        return safeThreadId > 0 ? `wms-chat-draft:${safeThreadId}` : "";
    }

    function loadDraft(threadId) {
        const key = draftStorageKey(threadId);
        if (!key) {
            return "";
        }
        try {
            return String(localStorage.getItem(key) || "");
        } catch (error) {
            return "";
        }
    }

    function saveDraft(threadId, value) {
        const key = draftStorageKey(threadId);
        if (!key) {
            return;
        }
        try {
            const normalized = String(value || "");
            if (!normalized.trim()) {
                localStorage.removeItem(key);
                return;
            }
            localStorage.setItem(key, normalized);
        } catch (error) {
        }
    }

    function clearDraft(threadId) {
        const key = draftStorageKey(threadId);
        if (!key) {
            return;
        }
        try {
            localStorage.removeItem(key);
        } catch (error) {
        }
    }

    window.WmsChatUi = {
        escapeHtml,
        normalizeChatText,
        renderMessageTimeline,
        mergeMessages,
        loadDraft,
        saveDraft,
        clearDraft,
    };
})();
