(function initPosManualDocumentDraft(globalScope) {
    const STORAGE_KEY = "pos-manual-document-draft-v1";

    function normalizeString(value) {
        return String(value || "").trim();
    }

    function normalizeNumber(value) {
        const parsed = Number.parseFloat(String(value || "").replace(/,/g, "."));
        return Number.isFinite(parsed) ? parsed : 0;
    }

    function normalizeBoolean(value, fallback) {
        if (typeof value === "boolean") {
            return value;
        }
        if (value === "1" || value === 1 || value === "true") {
            return true;
        }
        if (value === "0" || value === 0 || value === "false") {
            return false;
        }
        return Boolean(fallback);
    }

    function normalizeItem(item) {
        return {
            desc: normalizeString(item && item.desc),
            qty: normalizeNumber(item && item.qty),
            price: normalizeNumber(item && item.price),
            discount: normalizeNumber(item && item.discount),
        };
    }

    function normalizeDraft(source, fallback) {
        const safeSource = source && typeof source === "object" ? source : {};
        const safeFallback = fallback && typeof fallback === "object" ? fallback : {};
        const itemsSource = Array.isArray(safeSource.items)
            ? safeSource.items
            : Array.isArray(safeFallback.items)
                ? safeFallback.items
                : [];

        return {
            business_name: normalizeString(safeSource.business_name || safeFallback.business_name),
            business_address: normalizeString(safeSource.business_address || safeFallback.business_address),
            business_phone: normalizeString(safeSource.business_phone || safeFallback.business_phone),
            logo_data_url: normalizeString(safeSource.logo_data_url || safeFallback.logo_data_url),
            logo_filename: normalizeString(safeSource.logo_filename || safeFallback.logo_filename),
            use_global_discount: normalizeBoolean(safeSource.use_global_discount, safeFallback.use_global_discount),
            global_discount_type: normalizeString(safeSource.global_discount_type || safeFallback.global_discount_type || "amount") || "amount",
            global_discount_value: normalizeNumber(safeSource.global_discount_value || safeFallback.global_discount_value),
            use_tax: normalizeBoolean(safeSource.use_tax, safeFallback.use_tax),
            tax_type: normalizeString(safeSource.tax_type || safeFallback.tax_type || "percent") || "percent",
            tax_value: normalizeNumber(safeSource.tax_value || safeFallback.tax_value || 11),
            invoice_no: normalizeString(safeSource.invoice_no || safeFallback.invoice_no),
            invoice_date: normalizeString(safeSource.invoice_date || safeFallback.invoice_date),
            due_date: normalizeString(safeSource.due_date || safeFallback.due_date),
            customer_name: normalizeString(safeSource.customer_name || safeFallback.customer_name),
            customer_phone: normalizeString(safeSource.customer_phone || safeFallback.customer_phone),
            customer_address: normalizeString(safeSource.customer_address || safeFallback.customer_address),
            description: normalizeString(safeSource.description || safeFallback.description),
            payment_note: normalizeString(safeSource.payment_note || safeFallback.payment_note),
            items: itemsSource.map(normalizeItem).filter((item) => {
                return item.desc || item.qty > 0 || item.price > 0 || item.discount > 0;
            }),
            updated_at: Number.isFinite(Number(safeSource.updated_at))
                ? Number(safeSource.updated_at)
                : Number.isFinite(Number(safeFallback.updated_at))
                    ? Number(safeFallback.updated_at)
                    : 0,
        };
    }

    function loadDraft(fallback) {
        const normalizedFallback = normalizeDraft({}, fallback);
        try {
            const raw = globalScope.localStorage.getItem(STORAGE_KEY);
            if (!raw) {
                return normalizedFallback;
            }
            const parsed = JSON.parse(raw);
            return normalizeDraft(parsed, normalizedFallback);
        } catch (error) {
            return normalizedFallback;
        }
    }

    function saveDraft(source, fallback) {
        const normalized = normalizeDraft(source, fallback);
        normalized.updated_at = Date.now();
        try {
            globalScope.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
        } catch (error) {
            return normalized;
        }
        return normalized;
    }

    function subscribe(listener, fallback) {
        if (typeof listener !== "function") {
            return function noop() {};
        }
        const handler = function handleStorage(event) {
            if (event.key !== STORAGE_KEY) {
                return;
            }
            listener(loadDraft(fallback));
        };
        globalScope.addEventListener("storage", handler);
        return function unsubscribe() {
            globalScope.removeEventListener("storage", handler);
        };
    }

    globalScope.posManualDocumentDraft = {
        storageKey: STORAGE_KEY,
        loadDraft,
        saveDraft,
        subscribe,
        normalizeDraft,
    };
})(window);
