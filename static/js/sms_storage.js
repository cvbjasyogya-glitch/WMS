(() => {
  const bootstrap = window.SMS_STORAGE_BOOTSTRAP || {};
  const endpoints = bootstrap.endpoints || {};

  const state = {
    section: bootstrap.initialPath ? "drive" : "home",
    currentPath: bootstrap.initialPath || "",
    items: [],
    breadcrumbs: [],
    summary: { fileCount: 0, folderCount: 0 },
    stats: bootstrap.storageStats || {},
    activity: [],
    search: "",
    viewMode: "list",
    selectedKeys: [],
    homeData: {
      starredItems: [],
      recentItems: [],
      rootFolders: [],
      sharedItems: [],
      shortcutItems: []
    },
    uploadQueue: [],
    activeUploads: 0,
    contextMenu: {
      key: "",
      x: 0,
      y: 0
    },
    sharedContext: {
      shareId: "",
      currentPath: "",
      ownerUsername: "",
      label: ""
    },
    shareDialog: {
      recipients: [],
      search: "",
      selectedUserIds: [],
      targets: [],
      isSubmitting: false
    },
    moveDialog: {
      mode: "move",
      items: [],
      destinationPath: "",
      search: "",
      isSubmitting: false
    }
  };

  const elements = {
    appShell: document.getElementById("app-shell"),
    sidebarPanel: document.getElementById("sidebarPanel"),
    sidebarMenuButton: document.getElementById("sidebarMenuButton"),
    searchInput: document.getElementById("search-input"),
    quotaChip: document.getElementById("quotaChip"),
    navHome: document.getElementById("nav-home"),
    navDrive: document.getElementById("nav-drive"),
    navRecent: document.getElementById("nav-recent"),
    navStarred: document.getElementById("nav-starred"),
    navShared: document.getElementById("nav-shared"),
    navShortcuts: document.getElementById("nav-shortcuts"),
    navAll: document.getElementById("nav-all"),
    navTrash: document.getElementById("nav-trash"),
    navTrashCount: document.getElementById("nav-trash-count"),
    sidebarUpload: document.getElementById("sidebar-upload"),
    usagePercent: document.getElementById("usage-percent"),
    usageText: document.getElementById("usage-text"),
    statFiles: document.getElementById("stat-files"),
    statFolders: document.getElementById("stat-folders"),
    statTrash: document.getElementById("stat-trash"),
    statUpdated: document.getElementById("stat-updated"),
    storageProgressBar: document.getElementById("storageProgressBar"),
    activityRefresh: document.getElementById("activity-refresh"),
    activityList: document.getElementById("activity-list"),
    workspaceKicker: document.getElementById("workspace-kicker"),
    currentViewTitle: document.getElementById("current-view-title"),
    sectionSubtitle: document.getElementById("section-subtitle"),
    uploadBtn: document.getElementById("upload-btn"),
    folderBtn: document.getElementById("folder-btn"),
    refreshBtn: document.getElementById("refresh-btn"),
    shareBtn: document.getElementById("share-btn"),
    shortcutBtn: document.getElementById("shortcut-btn"),
    downloadBtn: document.getElementById("download-btn"),
    moveBtn: document.getElementById("move-btn"),
    renameBtn: document.getElementById("rename-btn"),
    restoreBtn: document.getElementById("restore-btn"),
    deleteBtn: document.getElementById("delete-btn"),
    emptyTrashBtn: document.getElementById("empty-trash-btn"),
    viewListBtn: document.getElementById("view-list-btn"),
    viewGridBtn: document.getElementById("view-grid-btn"),
    currentPathLabel: document.getElementById("current-path-label"),
    folderContents: document.getElementById("folder-contents"),
    overviewUsageText: document.getElementById("overview-usage-text"),
    overviewUsageMode: document.getElementById("overview-usage-mode"),
    uploadLimitLabel: document.getElementById("upload-limit-label"),
    surfaceBadge: document.getElementById("surface-badge"),
    categoryBreakdown: document.getElementById("category-breakdown"),
    breadcrumbs: document.getElementById("breadcrumbs"),
    selectionStatus: document.getElementById("selection-status"),
    selectionBar: document.getElementById("selection-bar"),
    selectionBarTitle: document.getElementById("selection-bar-title"),
    selectionBarSubtitle: document.getElementById("selection-bar-subtitle"),
    selectionOpenBtn: document.getElementById("selection-open-btn"),
    selectionDownloadBtn: document.getElementById("selection-download-btn"),
    selectionStarBtn: document.getElementById("selection-star-btn"),
    selectionShareBtn: document.getElementById("selection-share-btn"),
    selectionShortcutBtn: document.getElementById("selection-shortcut-btn"),
    selectionMoveBtn: document.getElementById("selection-move-btn"),
    selectionRenameBtn: document.getElementById("selection-rename-btn"),
    selectionRestoreBtn: document.getElementById("selection-restore-btn"),
    selectionDeleteBtn: document.getElementById("selection-delete-btn"),
    selectionClearBtn: document.getElementById("selection-clear-btn"),
    feedbackBar: document.getElementById("feedback-bar"),
    homeDashboard: document.getElementById("home-dashboard"),
    homeQuickAccess: document.getElementById("home-quick-access"),
    homeRecentList: document.getElementById("home-recent-list"),
    homeFolderList: document.getElementById("home-folder-list"),
    homeSharedList: document.getElementById("home-shared-list"),
    homeShortcutList: document.getElementById("home-shortcut-list"),
    dropzone: document.getElementById("dropzone"),
    folderCards: document.getElementById("folder-cards"),
    fileList: document.getElementById("file-list"),
    emptyState: document.getElementById("empty-state"),
    fileInput: document.getElementById("file-input"),
    previewDialog: document.getElementById("preview-dialog"),
    previewTitle: document.getElementById("preview-title"),
    previewBody: document.getElementById("preview-body"),
    shareDialog: document.getElementById("share-dialog"),
    shareDialogTitle: document.getElementById("shareDialogTitle"),
    shareDialogTargetSummary: document.getElementById("shareDialogTargetSummary"),
    shareDialogSearchInput: document.getElementById("shareDialogSearchInput"),
    shareDialogSelectedCount: document.getElementById("shareDialogSelectedCount"),
    shareDialogList: document.getElementById("shareDialogList"),
    shareDialogCloseButton: document.getElementById("shareDialogCloseButton"),
    shareDialogCancelButton: document.getElementById("shareDialogCancelButton"),
    shareDialogSubmitButton: document.getElementById("shareDialogSubmitButton"),
    moveDialog: document.getElementById("move-dialog"),
    moveDialogTitle: document.getElementById("moveDialogTitle"),
    moveDialogTargetSummary: document.getElementById("moveDialogTargetSummary"),
    moveDialogSearchInput: document.getElementById("moveDialogSearchInput"),
    moveDialogSelectedPath: document.getElementById("moveDialogSelectedPath"),
    moveDialogList: document.getElementById("moveDialogList"),
    moveDialogCloseButton: document.getElementById("moveDialogCloseButton"),
    moveDialogCancelButton: document.getElementById("moveDialogCancelButton"),
    moveDialogSubmitButton: document.getElementById("moveDialogSubmitButton"),
    queuePanel: document.getElementById("queue-panel"),
    queueSummary: document.getElementById("queue-summary"),
    queueList: document.getElementById("queue-list"),
    queueClear: document.getElementById("queue-clear"),
    contextMenu: document.getElementById("context-menu"),
    contextOpenBtn: document.getElementById("context-open-btn"),
    contextDownloadBtn: document.getElementById("context-download-btn"),
    contextStarBtn: document.getElementById("context-star-btn"),
    contextShareBtn: document.getElementById("context-share-btn"),
    contextShortcutBtn: document.getElementById("context-shortcut-btn"),
    contextShortcutTargetBtn: document.getElementById("context-shortcut-target-btn"),
    contextMoveBtn: document.getElementById("context-move-btn"),
    contextRenameBtn: document.getElementById("context-rename-btn"),
    contextRestoreBtn: document.getElementById("context-restore-btn"),
    contextDeleteBtn: document.getElementById("context-delete-btn")
  };

  const numberFormatter = new Intl.NumberFormat("id-ID");
  const dateFormatter = new Intl.DateTimeFormat("id-ID", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatBytes(bytes) {
    const safeBytes = Number(bytes || 0);
    if (!safeBytes) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = safeBytes;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    const precision = unitIndex === 0 ? 0 : value >= 100 ? 0 : value >= 10 ? 1 : 2;
    return `${value.toFixed(precision)} ${units[unitIndex]}`;
  }

  function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    return dateFormatter.format(date);
  }

  function buildUrl(endpoint, params = {}) {
    const url = new URL(endpoint, window.location.origin);
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") return;
      url.searchParams.set(key, value);
    });
    return url.toString();
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    const text = await response.text();
    let payload = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = { message: text };
      }
    }
    if (!response.ok) {
      throw new Error(payload.message || payload.error || "Permintaan gagal diproses.");
    }
    return payload;
  }

  function getCurrentSectionLabel() {
    if (state.section === "shared" && state.sharedContext.shareId) {
      return state.sharedContext.currentPath
        ? state.sharedContext.currentPath.split("/").pop()
        : state.sharedContext.label || "Shared";
    }
    if (state.section === "trash") return "Trash";
    if (state.section === "recent") return "Recent";
    if (state.section === "starred") return "Starred";
    if (state.section === "shared") return "Shared";
    if (state.section === "shortcuts") return "Shortcuts";
    if (state.section === "all") return "Semua File";
    if (state.currentPath) return state.currentPath.split("/").pop();
    return "My Drive";
  }

  function getCurrentSectionSubtitle() {
    if (state.section === "shared" && state.sharedContext.shareId) {
      return `Membuka item yang dibagikan oleh ${state.sharedContext.ownerUsername || "rekan kerja"} dalam mode baca.`;
    }
    if (state.section === "trash") return "Kelola item yang sudah dipindahkan ke trash atau hapus permanen bila sudah tidak dibutuhkan.";
    if (state.section === "recent") return "Kumpulan file terakhir yang berubah di ruang storage pribadimu.";
    if (state.section === "starred") return "Daftar file dan folder penting yang kamu tandai untuk akses cepat lintas workspace.";
    if (state.section === "shared") return "Kumpulan file dan folder yang kamu bagikan atau kamu terima dari user lain.";
    if (state.section === "shortcuts") return "Daftar jalan pintas ke file dan folder penting tanpa perlu bolak-balik cari lokasi aslinya.";
    if (state.section === "all") return "Index seluruh file dan folder milik akun aktif.";
    if (state.section === "home") return "Ringkasan workspace dan folder yang paling sering kamu buka.";
    return "Kelola file dan folder di drive pribadimu.";
  }

  function getWorkspaceKicker() {
    if (state.section === "shared" && state.sharedContext.shareId) return "Shared Access";
    if (state.section === "trash") return "Recycle";
    if (state.section === "recent") return "Recent";
    if (state.section === "starred") return "Starred";
    if (state.section === "shared") return "Shared";
    if (state.section === "shortcuts") return "Shortcut";
    if (state.section === "all") return "Library";
    return "Workspace";
  }

  function getItemKey(item) {
    return String(item?.id || item?.path || "");
  }

  function isTrashView() {
    return state.section === "trash";
  }

  function isShortcutsView() {
    return state.section === "shortcuts";
  }

  function getItemResolvedPath(item) {
    return item?.shortcutTargetPath || item?.shortcut_target_path || item?.path || "";
  }

  function isExternalSharedItem(item) {
    return Boolean(item?.sharedExternal || item?.shared_external);
  }

  function canManageShareItem(item) {
    if (!item) return false;
    return !isExternalSharedItem(item) || Boolean(item?.canManageShare || item?.can_manage_share);
  }

  function getShortcutParentPath(item) {
    return item?.shortcutParentPath || item?.shortcut_parent_path || "";
  }

  function getItemLocationLabel(item) {
    if (isExternalSharedItem(item)) {
      const owner = item?.sharedOwnerUsername || item?.shared_owner_username || "rekan kerja";
      const sharePath = item?.shareRelativePath || item?.share_relative_path || "";
      return sharePath ? `Dibagikan oleh ${owner} | ${sharePath}` : `Dibagikan oleh ${owner}`;
    }
    if (item?.sharedDirection === "outgoing" || item?.shared_direction === "outgoing") {
      const recipients = Array.isArray(item?.sharedRecipients || item?.shared_recipients)
        ? (item.sharedRecipients || item.shared_recipients)
        : [];
      return recipients.length ? `Shared ke ${recipients.length} user` : (item?.path || "My Drive");
    }
    if (!item?.shortcut) {
      return item?.path || "My Drive";
    }
    const parentPath = getShortcutParentPath(item) || "My Drive";
    const targetPath = getItemResolvedPath(item) || "My Drive";
    return `Shortcut: ${parentPath} | Target: ${targetPath}`;
  }

  function canMutateCurrentLocation() {
    return state.section === "home" || state.section === "drive";
  }

  function getVisibleItems() {
    const query = state.search.trim().toLowerCase();
    if (!query) return state.items;
    return state.items.filter((item) => {
      const haystack = `${item.name || ""} ${item.path || ""} ${item.category || ""}`.toLowerCase();
      return haystack.includes(query);
    });
  }

  function getSelectedItems() {
    const selectedSet = new Set(state.selectedKeys);
    return state.items.filter((item) => selectedSet.has(getItemKey(item)));
  }

  function canToggleSharedSelection() {
    const selectedItems = getSelectedItems();
    return (
      selectedItems.length > 0 &&
      !isTrashView() &&
      selectedItems.every((item) => !item.shortcut && canManageShareItem(item))
    );
  }

  function canCreateShortcutSelection() {
    return getSelectedItems().filter((item) => !item.shortcut && !isExternalSharedItem(item)).length > 0 && !isTrashView();
  }

  function canMoveSelection() {
    return getSelectedItems().filter((item) => !item.shortcut && !isExternalSharedItem(item)).length > 0 && !isTrashView();
  }

  function clearSelection() {
    closeContextMenu();
    state.selectedKeys = [];
    renderFileList();
    renderSelectionState();
  }

  function syncNavState() {
    [
      [elements.navHome, "home"],
      [elements.navDrive, "drive"],
      [elements.navRecent, "recent"],
      [elements.navStarred, "starred"],
      [elements.navShared, "shared"],
      [elements.navShortcuts, "shortcuts"],
      [elements.navAll, "all"],
      [elements.navTrash, "trash"]
    ].forEach(([element, section]) => {
      element.classList.toggle("is-active", state.section === section);
    });
  }

  function showFeedback(message, type = "info") {
    if (!elements.feedbackBar) return;
    elements.feedbackBar.textContent = message || "";
    elements.feedbackBar.classList.remove("hidden", "is-error");
    if (type === "error") {
      elements.feedbackBar.classList.add("is-error");
    }
  }

  function hideFeedback() {
    if (!elements.feedbackBar) return;
    elements.feedbackBar.classList.add("hidden");
    elements.feedbackBar.classList.remove("is-error");
    elements.feedbackBar.textContent = "";
  }

  function renderStats() {
    const stats = state.stats || {};
    const usagePercent = Number(stats.usagePercent || 0);
    elements.usagePercent.textContent = stats.quotaBytes
      ? `${Math.round(usagePercent)}%`
      : "0%";
    elements.usageText.textContent = `${stats.total_size_label || formatBytes(stats.totalBytes)} terpakai dari ${stats.quota_label || formatBytes(stats.quotaBytes)}`;
    elements.statFiles.textContent = numberFormatter.format(Number(stats.totalFiles || stats.total_files || 0));
    elements.statFolders.textContent = numberFormatter.format(Number(stats.totalFolders || stats.total_folders || 0));
    elements.statTrash.textContent = numberFormatter.format(Number(stats.trashCount || stats.trash_count || 0));
    elements.statUpdated.textContent = stats.latestUpdate || stats.latest_update
      ? `Update terakhir ${formatDate(stats.latestUpdate || stats.latest_update)}`
      : "Belum ada aktivitas";
    elements.storageProgressBar.style.width = `${Math.max(0, Math.min(100, usagePercent))}%`;
    elements.navTrashCount.textContent = numberFormatter.format(Number(stats.trashCount || stats.trash_count || 0));
    elements.navTrashCount.classList.toggle("hidden", Number(stats.trashCount || stats.trash_count || 0) === 0);
    elements.quotaChip.textContent = `${stats.quota_label || "500 MB"} / user`;
    elements.overviewUsageText.textContent = stats.total_size_label || formatBytes(stats.totalBytes);
    elements.overviewUsageMode.textContent = "Quota";
    elements.uploadLimitLabel.textContent = stats.max_upload_label || formatBytes(stats.maxUploadBytes);

    const categoryBreakdown = stats.categoryBreakdown || stats.category_breakdown || {};
    const entries = [
      ["Dokumen", categoryBreakdown.document || 0],
      ["Gambar", categoryBreakdown.image || 0],
      ["Video", categoryBreakdown.video || 0],
      ["Audio", categoryBreakdown.audio || 0],
      ["Teks", categoryBreakdown.text || 0],
      ["Lainnya", categoryBreakdown.other || 0]
    ];
    elements.categoryBreakdown.innerHTML = entries
      .map(([label, value]) => `
        <article class="category-item">
          <span>${escapeHtml(label)}</span>
          <strong>${numberFormatter.format(Number(value || 0))}</strong>
        </article>
      `)
      .join("");
  }

  function renderActivity() {
    const activity = state.activity || [];
    if (!activity.length) {
      elements.activityList.innerHTML = '<p class="section-note">Belum ada aktivitas.</p>';
      return;
    }
    elements.activityList.innerHTML = activity.slice(0, 10).map((item) => `
      <article class="activity-item">
        <strong>${escapeHtml(String(item.action || "update").replace(/(^\w)/, (match) => match.toUpperCase()))}</strong>
        <span>${escapeHtml(item.target_path || item.targetPath || "My Drive")}</span>
      </article>
    `).join("");
  }

  function renderHeader() {
    elements.workspaceKicker.textContent = getWorkspaceKicker();
    elements.currentViewTitle.textContent = getCurrentSectionLabel();
    elements.sectionSubtitle.textContent = getCurrentSectionSubtitle();
    elements.currentPathLabel.textContent = getCurrentSectionLabel();
    elements.surfaceBadge.textContent = isTrashView()
      ? "Trash"
      : state.section === "starred"
        ? "Focus"
        : state.section === "shared"
          ? "Shared"
          : state.section === "shortcuts"
            ? "Shortcut"
        : "Ready";
    const summary = state.summary || {};
    const fileCount = Number(summary.fileCount || summary.file_count || 0);
    const folderCount = Number(summary.folderCount || summary.folder_count || 0);
    const totalItems = fileCount + folderCount;
    elements.folderContents.textContent = `${numberFormatter.format(totalItems)} item | ${numberFormatter.format(folderCount)} folder | ${numberFormatter.format(fileCount)} file`;
  }

  function renderBreadcrumbs() {
    let breadcrumbs = state.breadcrumbs || [];
    if (!breadcrumbs.length) {
      breadcrumbs = [{ label: getCurrentSectionLabel(), path: "" }];
    }
    elements.breadcrumbs.innerHTML = breadcrumbs.map((crumb, index) => {
      const last = index === breadcrumbs.length - 1;
      return `
        ${index > 0 ? '<span>/</span>' : ""}
        ${last
          ? `<span>${escapeHtml(crumb.label)}</span>`
          : `<button type="button" class="breadcrumb-btn" data-path="${escapeHtml(crumb.path || "")}">${escapeHtml(crumb.label)}</button>`}
      `;
    }).join("");
  }

  function getIconLabel(item) {
    if (item.kind === "folder") return "DIR";
    const category = item.category || "other";
    if (category === "image") return "IMG";
    if (category === "video") return "VID";
    if (category === "audio") return "AUD";
    if (category === "archive") return "ZIP";
    if (category === "document") return "DOC";
    if (category === "text") return "TXT";
    return "FILE";
  }

  function buildRowActions(item) {
    if (isTrashView()) {
      return `
        <button type="button" class="file-action-btn" data-action="restore" data-key="${escapeHtml(getItemKey(item))}">Restore</button>
        <button type="button" class="file-action-btn" data-action="delete" data-key="${escapeHtml(getItemKey(item))}">Delete</button>
      `;
    }
    const openLabel = item.kind === "folder" ? "Buka" : (item.previewable ? "Preview" : "Download");
    const starLabel = item.starred ? "Lepas Bintang" : "Bintangi";
    const shareLabel = isExternalSharedItem(item)
      ? "Read only"
      : (item.shared ? "Kelola Shared" : "Bagikan");
    const shortcutLabel = item.shortcut ? "Hapus Shortcut" : "Shortcut Cepat";
    if (item.shortcut) {
      return `
        <button type="button" class="file-action-btn" data-action="open" data-key="${escapeHtml(getItemKey(item))}">${openLabel}</button>
        <button type="button" class="file-action-btn ${item.shared ? "is-shared" : ""}" data-action="toggle-shared" data-key="${escapeHtml(getItemKey(item))}" disabled>${shareLabel}</button>
        <button type="button" class="file-action-btn is-shortcut" data-action="toggle-shortcut" data-key="${escapeHtml(getItemKey(item))}">${shortcutLabel}</button>
        <button type="button" class="file-action-btn" data-action="download" data-key="${escapeHtml(getItemKey(item))}">Download</button>
        <button type="button" class="file-action-btn" data-action="delete" data-key="${escapeHtml(getItemKey(item))}">Hapus</button>
      `;
    }
    return `
      <button type="button" class="file-action-btn" data-action="open" data-key="${escapeHtml(getItemKey(item))}">${openLabel}</button>
      <button type="button" class="file-action-btn ${item.starred ? "is-starred" : ""}" data-action="toggle-star" data-key="${escapeHtml(getItemKey(item))}" ${isExternalSharedItem(item) ? "disabled" : ""}>${starLabel}</button>
      <button type="button" class="file-action-btn ${item.shared ? "is-shared" : ""}" data-action="toggle-shared" data-key="${escapeHtml(getItemKey(item))}" ${!canManageShareItem(item) ? "disabled" : ""}>${shareLabel}</button>
      <button type="button" class="file-action-btn ${item.shortcut ? "is-shortcut" : ""}" data-action="toggle-shortcut" data-key="${escapeHtml(getItemKey(item))}">${shortcutLabel}</button>
      <button type="button" class="file-action-btn" data-action="download" data-key="${escapeHtml(getItemKey(item))}">Download</button>
      <button type="button" class="file-action-btn" data-action="move" data-key="${escapeHtml(getItemKey(item))}" ${isExternalSharedItem(item) ? "disabled" : ""}>Pindah</button>
      <button type="button" class="file-action-btn" data-action="delete" data-key="${escapeHtml(getItemKey(item))}" ${isExternalSharedItem(item) ? "disabled" : ""}>Delete</button>
    `;
  }

  function renderFolderCards(items) {
    const folders = items.filter((item) => item.kind === "folder").slice(0, 4);
    elements.folderCards.classList.toggle("hidden", folders.length === 0 || isTrashView());
    elements.folderCards.innerHTML = folders.map((folder) => `
      <article class="folder-card">
        <button type="button" data-action="open" data-key="${escapeHtml(getItemKey(folder))}">
          <div class="file-main">
            <div class="file-icon">${escapeHtml(getIconLabel(folder))}</div>
            <div class="folder-card-copy">
              <strong>${escapeHtml(folder.name)}</strong>
              <span title="${escapeHtml(getItemLocationLabel(folder))}">${escapeHtml(getItemLocationLabel(folder))}</span>
            </div>
          </div>
        </button>
      </article>
    `).join("");
  }

  function renderFileList() {
    const visibleItems = getVisibleItems();
    const selectedSet = new Set(state.selectedKeys);
    elements.fileList.classList.toggle("is-grid", state.viewMode === "grid");
    elements.emptyState.classList.toggle("hidden", visibleItems.length > 0);

    if (!visibleItems.length) {
      elements.fileList.innerHTML = "";
      renderFolderCards([]);
      return;
    }

    renderFolderCards(visibleItems);

    if (state.viewMode === "grid") {
      elements.fileList.innerHTML = visibleItems.map((item) => `
        <article class="file-card ${selectedSet.has(getItemKey(item)) ? "is-selected" : ""}" data-key="${escapeHtml(getItemKey(item))}">
          <div class="file-card-main">
            <input class="file-select" type="checkbox" data-key="${escapeHtml(getItemKey(item))}" ${selectedSet.has(getItemKey(item)) ? "checked" : ""}>
            <div class="file-icon">${escapeHtml(getIconLabel(item))}</div>
            <div class="file-name">
              <strong>${escapeHtml(item.name)}</strong>
              <span title="${escapeHtml(getItemLocationLabel(item))}">${escapeHtml(getItemLocationLabel(item))}</span>
            </div>
          </div>
          <div class="file-meta">${escapeHtml(item.kind === "folder" ? "Folder" : item.category || "File")} | ${escapeHtml(item.size_label || (item.kind === "folder" ? "-" : formatBytes(item.size)))}</div>
          <div class="file-meta">${escapeHtml(formatDate(item.updatedAt || item.updated_at))}</div>
          <div class="file-actions">${buildRowActions(item)}</div>
        </article>
      `).join("");
      return;
    }

    elements.fileList.innerHTML = visibleItems.map((item) => `
      <article class="file-row ${selectedSet.has(getItemKey(item)) ? "is-selected" : ""}" data-key="${escapeHtml(getItemKey(item))}">
        <div class="file-main">
          <input class="file-select" type="checkbox" data-key="${escapeHtml(getItemKey(item))}" ${selectedSet.has(getItemKey(item)) ? "checked" : ""}>
          <div class="file-icon">${escapeHtml(getIconLabel(item))}</div>
          <div class="file-name">
            <strong>${escapeHtml(item.name)}</strong>
            <span title="${escapeHtml(getItemLocationLabel(item))}">${escapeHtml(getItemLocationLabel(item))}</span>
          </div>
        </div>
        <div class="file-meta">${escapeHtml(item.kind === "folder" ? "Folder" : item.category || "File")}</div>
        <div class="file-meta">${escapeHtml(item.size_label || (item.kind === "folder" ? "-" : formatBytes(item.size)))}</div>
        <div class="file-meta">${escapeHtml(formatDate(item.updatedAt || item.updated_at))}</div>
        <div class="file-actions">${buildRowActions(item)}</div>
      </article>
    `).join("");
  }

  function renderSelectionState() {
    const selectedItems = getSelectedItems();
    elements.selectionStatus.textContent = `${numberFormatter.format(selectedItems.length)} item dipilih`;

    const canUpload = canMutateCurrentLocation();
    const canRename = selectedItems.length === 1 && !isTrashView() && !isExternalSharedItem(selectedItems[0]);
    const canDownload = selectedItems.length === 1 && !isTrashView();
    const canMove = canMoveSelection();
    const canShare = canToggleSharedSelection();
    const canShortcut = canCreateShortcutSelection();
    const canRestore = isTrashView() && selectedItems.length > 0;
    const canDelete = isTrashView()
      ? selectedItems.length > 0
      : selectedItems.length > 0 && selectedItems.every((item) => !isExternalSharedItem(item));
    const canOpen = selectedItems.length === 1;
    const allSelectedAreShortcuts = selectedItems.length > 0 && selectedItems.every((item) => item.shortcut);

    elements.uploadBtn.disabled = !canUpload;
    elements.sidebarUpload.disabled = !canUpload;
    elements.folderBtn.disabled = !canUpload;
    elements.downloadBtn.disabled = !canDownload;
    elements.moveBtn.disabled = !canMove;
    elements.shareBtn.disabled = !canShare;
    elements.shortcutBtn.disabled = !canShortcut && !isShortcutsView();
    elements.renameBtn.disabled = !canRename;
    elements.restoreBtn.disabled = !canRestore;
    elements.deleteBtn.disabled = !canDelete;
    elements.refreshBtn.disabled = false;

    elements.restoreBtn.classList.toggle("hidden", !isTrashView());
    elements.emptyTrashBtn.classList.toggle("hidden", !isTrashView());
    elements.emptyTrashBtn.disabled = !isTrashView() || Number(state.stats.trashCount || state.stats.trash_count || 0) === 0;
    elements.shortcutBtn.textContent = allSelectedAreShortcuts ? "Hapus Shortcut" : "Shortcut ke Folder";

    elements.selectionBar.classList.toggle("hidden", selectedItems.length === 0);
    elements.selectionBarTitle.textContent = selectedItems.length === 1
      ? selectedItems[0].name
      : `${numberFormatter.format(selectedItems.length)} item dipilih`;
    elements.selectionBarSubtitle.textContent = isTrashView()
      ? "Gunakan restore atau hapus permanen untuk item di trash."
      : selectedItems.some((item) => isExternalSharedItem(item))
        ? "Item shared dari user lain hanya bisa dibuka atau diunduh."
        : selectedItems.some((item) => item.shortcut)
        ? "Shortcut bisa dibuka, dibagikan, atau dihapus dari daftar."
        : "Kelola item terpilih tanpa perlu kembali ke toolbar utama.";
    elements.selectionOpenBtn.disabled = !canOpen;
    elements.selectionDownloadBtn.disabled = !canDownload;
    elements.selectionStarBtn.disabled = isTrashView() || selectedItems.length === 0 || selectedItems.some((item) => isExternalSharedItem(item));
    elements.selectionShareBtn.disabled = !canShare;
    elements.selectionShortcutBtn.disabled = !canShortcut && !selectedItems.every((item) => item.shortcut);
    elements.selectionShortcutBtn.textContent = allSelectedAreShortcuts ? "Hapus Shortcut" : "Shortcut ke Folder";
    elements.selectionMoveBtn.disabled = !canMove;
    elements.selectionRenameBtn.disabled = !canRename;
    elements.selectionRestoreBtn.disabled = !canRestore;
    elements.selectionDeleteBtn.disabled = !canDelete;
    elements.selectionRestoreBtn.classList.toggle("hidden", !isTrashView());
  }

  function closeContextMenu() {
    state.contextMenu.key = "";
    elements.contextMenu.classList.add("hidden");
  }

  function getContextMenuItem() {
    return findItemByKey(state.contextMenu.key);
  }

  function openContextMenu(item, x, y) {
    if (!item) return;
    state.contextMenu.key = getItemKey(item);
    state.selectedKeys = [getItemKey(item)];
    renderSelectionState();
    renderFileList();

    elements.contextOpenBtn.textContent = item.kind === "folder" ? "Buka Folder" : "Buka";
    elements.contextStarBtn.textContent = item.starred ? "Lepas Starred" : "Tambahkan Starred";
    elements.contextShareBtn.textContent = item.shortcut ? "Shortcut" : (isExternalSharedItem(item) ? "Read only" : (item.shared ? "Kelola Shared" : "Bagikan"));
    elements.contextShortcutBtn.textContent = item.shortcut ? "Hapus Shortcut" : "Shortcut Cepat";
    elements.contextStarBtn.disabled = isExternalSharedItem(item);
    elements.contextMoveBtn.disabled = item.shortcut || isTrashView() || isExternalSharedItem(item);
    elements.contextRenameBtn.disabled = item.shortcut || isTrashView() || isExternalSharedItem(item);
    elements.contextShortcutTargetBtn.disabled = item.shortcut || isTrashView() || isExternalSharedItem(item);
    elements.contextShareBtn.disabled = item.shortcut || !canManageShareItem(item);
    elements.contextRestoreBtn.classList.toggle("hidden", !isTrashView());
    elements.contextDeleteBtn.textContent = isTrashView() ? "Hapus Permanen" : (item.shortcut ? "Hapus Shortcut" : "Delete");

    const menuWidth = 240;
    const menuHeight = 360;
    const left = Math.max(12, Math.min(x, window.innerWidth - menuWidth - 12));
    const top = Math.max(12, Math.min(y, window.innerHeight - menuHeight - 12));
    elements.contextMenu.style.left = `${left}px`;
    elements.contextMenu.style.top = `${top}px`;
    elements.contextMenu.classList.remove("hidden");
  }

  function renderHomePanelItems(container, items, emptyMessage, metaBuilder) {
    if (!container) return;
    if (!items.length) {
      container.innerHTML = `<p class="section-note">${escapeHtml(emptyMessage)}</p>`;
      return;
    }
    container.innerHTML = items.map((item) => `
      <button type="button" class="home-item-btn" data-key="${escapeHtml(getItemKey(item))}">
        <div class="home-item-copy">
          <strong>${escapeHtml(item.name || "My Drive")}</strong>
          <span title="${escapeHtml(getItemLocationLabel(item))}">${escapeHtml(getItemLocationLabel(item))}</span>
        </div>
        <span class="home-item-meta">${escapeHtml(metaBuilder(item))}</span>
      </button>
    `).join("");
  }

  function renderHomeDashboard() {
    const isHomeSection = state.section === "home";
    if (elements.homeDashboard) {
      elements.homeDashboard.classList.toggle("hidden", !isHomeSection);
    }
    if (!isHomeSection) return;

    renderHomePanelItems(
      elements.homeQuickAccess,
      state.homeData.starredItems,
      "Belum ada item berbintang. Gunakan tombol Bintangi pada file atau folder penting.",
      (item) => item.kind === "folder" ? "Folder favorit" : item.size_label || formatBytes(item.size)
    );
    renderHomePanelItems(
      elements.homeRecentList,
      state.homeData.recentItems,
      "Belum ada file terbaru yang bisa ditampilkan.",
      (item) => formatDate(item.updatedAt || item.updated_at)
    );
    renderHomePanelItems(
      elements.homeFolderList,
      state.homeData.rootFolders,
      "Folder utama di root akan muncul di sini setelah kamu membuatnya.",
      (item) => item.kind === "folder" ? "Buka folder" : item.category || "File"
    );
    renderHomePanelItems(
      elements.homeSharedList,
      state.homeData.sharedItems,
      "Belum ada item yang ditandai shared.",
      (item) => item.kind === "folder" ? "Folder shared" : item.size_label || formatBytes(item.size)
    );
    renderHomePanelItems(
      elements.homeShortcutList,
      state.homeData.shortcutItems,
      "Belum ada shortcut aktif untuk file atau folder penting.",
      (item) => {
        const parentPath = getShortcutParentPath(item) || "My Drive";
        return item.shortcut ? `Shortcut di ${parentPath}` : "Akses cepat";
      }
    );
  }

  function renderUploadQueue() {
    const tasks = state.uploadQueue || [];
    const visibleTasks = tasks.filter((task) => task.status !== "cleared");
    elements.queuePanel.classList.toggle("hidden", visibleTasks.length === 0);
    if (!visibleTasks.length) {
      elements.queueSummary.textContent = "Belum ada upload aktif.";
      elements.queueList.innerHTML = "";
      elements.queueClear.disabled = true;
      return;
    }

    const activeCount = visibleTasks.filter((task) => ["queued", "uploading"].includes(task.status)).length;
    const doneCount = visibleTasks.filter((task) => task.status === "done").length;
    elements.queueSummary.textContent = activeCount > 0
      ? `${numberFormatter.format(activeCount)} upload sedang berjalan.`
      : `${numberFormatter.format(doneCount)} upload selesai.`;
    elements.queueClear.disabled = visibleTasks.every((task) => ["queued", "uploading"].includes(task.status));
    elements.queueList.innerHTML = visibleTasks.map((task) => {
      const statusLabel = task.status === "done"
        ? "Selesai"
        : task.status === "error"
          ? "Gagal"
          : task.status === "uploading"
            ? "Uploading"
            : "Menunggu";
      const badgeClass = task.status === "done"
        ? "is-done"
        : task.status === "error"
          ? "is-error"
          : "";
      return `
        <article class="queue-item">
          <div class="queue-item-head">
            <div class="queue-item-copy">
              <strong>${escapeHtml(task.name)}</strong>
              <span>${escapeHtml(task.path || "My Drive")} | ${escapeHtml(formatBytes(task.size))}</span>
            </div>
            <span class="queue-badge ${badgeClass}">${statusLabel}</span>
          </div>
          <div class="queue-progress"><span style="width:${Math.max(0, Math.min(100, task.progress || 0))}%"></span></div>
          <div class="queue-item-meta">
            <span>${Math.round(task.progress || 0)}%</span>
            <span>${escapeHtml(task.error || (task.status === "done" ? "Upload berhasil" : "Menunggu giliran"))}</span>
          </div>
        </article>
      `;
    }).join("");
  }

  function renderAll() {
    syncNavState();
    renderStats();
    renderActivity();
    renderHeader();
    renderBreadcrumbs();
    renderHomeDashboard();
    renderUploadQueue();
    renderFileList();
    renderSelectionState();
  }

  async function refreshStats() {
    const payload = await requestJson(endpoints.stats);
    state.stats = payload.stats || {};
    renderStats();
    renderSelectionState();
  }

  async function refreshActivity() {
    const payload = await requestJson(endpoints.activity);
    state.activity = payload.activity || [];
    renderActivity();
  }

  async function loadWorkspace() {
    hideFeedback();
    let payload;
    if (state.section === "recent") {
      payload = await requestJson(endpoints.recent);
    } else if (state.section === "starred") {
      payload = await requestJson(endpoints.starred);
    } else if (state.section === "shared") {
      if (state.sharedContext.shareId) {
        payload = await requestJson(
          buildUrl(endpoints.sharedBrowse, {
            share_id: state.sharedContext.shareId,
            path: state.sharedContext.currentPath || ""
          })
        );
      } else {
        payload = await requestJson(endpoints.shared);
      }
    } else if (state.section === "shortcuts") {
      payload = await requestJson(endpoints.shortcuts);
    } else if (state.section === "all") {
      payload = await requestJson(endpoints.index);
    } else if (state.section === "trash") {
      payload = await requestJson(endpoints.trash);
    } else {
      payload = await requestJson(buildUrl(endpoints.list, { path: state.currentPath }));
    }

    state.items = Array.isArray(payload.items) ? payload.items : [];
    state.breadcrumbs = Array.isArray(payload.breadcrumbs) ? payload.breadcrumbs : [];
    state.summary = payload.summary || { fileCount: 0, folderCount: 0 };
    if (state.section === "shared" && state.sharedContext.shareId) {
      state.sharedContext.ownerUsername = payload.sharedOwnerUsername || payload.shared_owner_username || state.sharedContext.ownerUsername;
      state.sharedContext.label = payload.sharedLabel || payload.shared_label || state.sharedContext.label;
      state.sharedContext.currentPath = payload.currentPath || payload.current_path || state.sharedContext.currentPath;
    }
    if (state.section === "home") {
      state.homeData.rootFolders = state.items.filter((item) => item.kind === "folder").slice(0, 5);
    }
    state.selectedKeys = state.selectedKeys.filter((key) => state.items.some((item) => getItemKey(item) === key));
    renderAll();
  }

  async function refreshHomeData() {
    if (state.section !== "home") return;
    const [starredPayload, recentPayload, sharedPayload, shortcutPayload] = await Promise.all([
      requestJson(endpoints.starred),
      requestJson(endpoints.recent),
      requestJson(endpoints.shared),
      requestJson(endpoints.shortcuts)
    ]);
    state.homeData.starredItems = Array.isArray(starredPayload.items) ? starredPayload.items.slice(0, 5) : [];
    state.homeData.recentItems = Array.isArray(recentPayload.items) ? recentPayload.items.slice(0, 5) : [];
    state.homeData.sharedItems = Array.isArray(sharedPayload.items) ? sharedPayload.items.slice(0, 5) : [];
    state.homeData.shortcutItems = Array.isArray(shortcutPayload.items) ? shortcutPayload.items.slice(0, 5) : [];
    renderHomeDashboard();
  }

  async function refreshWorkspace() {
    await loadWorkspace();
    await Promise.all([refreshStats(), refreshActivity(), refreshHomeData()]);
  }

  function setSection(section) {
    state.section = section;
    if (section !== "shared") {
      state.sharedContext = {
        shareId: "",
        currentPath: "",
        ownerUsername: "",
        label: ""
      };
    } else {
      state.sharedContext = {
        shareId: "",
        currentPath: "",
        ownerUsername: "",
        label: ""
      };
    }
    if (section === "home") {
      state.currentPath = "";
    }
    if (section === "drive" && !state.currentPath) {
      state.currentPath = "";
    }
    clearSelection();
    refreshWorkspace().catch(handleError);
  }

  function navigateTo(pathValue) {
    if (state.section === "shared" && state.sharedContext.shareId) {
      state.sharedContext.currentPath = pathValue || "";
      clearSelection();
      refreshWorkspace().catch(handleError);
      return;
    }
    state.section = "drive";
    state.currentPath = pathValue || "";
    clearSelection();
    refreshWorkspace().catch(handleError);
  }

  function findItemByKey(key) {
    return state.items.find((item) => getItemKey(item) === key) || null;
  }

  function toggleSelection(key, checked) {
    if (!key) return;
    const selected = new Set(state.selectedKeys);
    if (checked) {
      selected.add(key);
    } else {
      selected.delete(key);
    }
    state.selectedKeys = Array.from(selected);
    renderSelectionState();
    renderFileList();
  }

  function handleError(error) {
    showFeedback(error?.message || "Terjadi kendala saat memproses permintaan.", "error");
  }

  async function openPreview(item) {
    if (!item) return;
    elements.previewTitle.textContent = item.name || "Preview";

    const previewUrl = isExternalSharedItem(item)
      ? buildUrl(endpoints.sharedPreview, {
        share_id: item.shareId || item.share_id,
        path: item.shareRelativePath || item.share_relative_path || ""
      })
      : buildUrl(endpoints.preview, { path: getItemResolvedPath(item) });
    if (item.kind === "folder") {
      elements.previewBody.innerHTML = `
        <div class="preview-meta">
          <strong>${escapeHtml(item.name)}</strong>
          <span>Folder aktif. Buka folder ini untuk melihat isinya.</span>
        </div>
      `;
    } else if (item.category === "image") {
      elements.previewBody.innerHTML = `<img src="${escapeHtml(previewUrl)}" alt="${escapeHtml(item.name)}">`;
    } else if (item.category === "video") {
      elements.previewBody.innerHTML = `<video controls src="${escapeHtml(previewUrl)}"></video>`;
    } else if (item.category === "audio") {
      elements.previewBody.innerHTML = `<audio controls src="${escapeHtml(previewUrl)}"></audio>`;
    } else if (item.category === "document") {
      elements.previewBody.innerHTML = `<iframe src="${escapeHtml(previewUrl)}" title="${escapeHtml(item.name)}"></iframe>`;
    } else if (item.previewable) {
      const response = await fetch(previewUrl);
      const text = await response.text();
      elements.previewBody.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
    } else {
      elements.previewBody.innerHTML = `
        <div class="preview-meta">
          <strong>Preview belum tersedia</strong>
          <span>Gunakan tombol download untuk membuka file ini.</span>
        </div>
      `;
    }

    if (typeof elements.previewDialog.showModal === "function") {
      elements.previewDialog.showModal();
    }
  }

  function downloadItem(item) {
    if (!item) return;
    if (isExternalSharedItem(item)) {
      window.location.href = buildUrl(endpoints.sharedDownload, {
        share_id: item.shareId || item.share_id,
        path: item.shareRelativePath || item.share_relative_path || ""
      });
      return;
    }
    window.location.href = buildUrl(endpoints.download, { path: getItemResolvedPath(item) });
  }

  async function openItem(item) {
    if (!item) return;
    if (isExternalSharedItem(item) && item.kind === "folder") {
      state.section = "shared";
      state.sharedContext.shareId = item.shareId || item.share_id || "";
      state.sharedContext.currentPath = item.shareRelativePath || item.share_relative_path || "";
      state.sharedContext.ownerUsername = item.sharedOwnerUsername || item.shared_owner_username || "";
      state.sharedContext.label = item.name || "";
      clearSelection();
      await refreshWorkspace();
      return;
    }
    if (item.kind === "folder") {
      navigateTo(getItemResolvedPath(item));
      return;
    }
    if (item.previewable) {
      await openPreview(item);
      return;
    }
    downloadItem(item);
  }

  function getShareDialogVisibleRecipients() {
    const query = state.shareDialog.search.trim().toLowerCase();
    if (!query) return state.shareDialog.recipients;
    return state.shareDialog.recipients.filter((item) => {
      const haystack = `${item.username || ""} ${item.role || ""} ${item.label || ""}`.toLowerCase();
      return haystack.includes(query);
    });
  }

  function renderShareDialog() {
    const visibleRecipients = getShareDialogVisibleRecipients();
    const selectedSet = new Set(state.shareDialog.selectedUserIds);
    const targetCount = state.shareDialog.targets.length;
    elements.shareDialogTitle.textContent = targetCount > 1 ? "Bagikan Beberapa Item" : "Bagikan Item";
    elements.shareDialogTargetSummary.textContent = targetCount > 1
      ? `${targetCount} item akan dibagikan ke user yang kamu pilih.`
      : `Pilih user yang bisa melihat ${state.shareDialog.targets[0]?.name || "item ini"}.`;
    elements.shareDialogSelectedCount.textContent = `${selectedSet.size} user`;
    elements.shareDialogSubmitButton.textContent = state.shareDialog.isSubmitting
      ? "Menyimpan..."
      : (selectedSet.size ? "Simpan Shared" : "Cabut Shared");
    elements.shareDialogSubmitButton.disabled = state.shareDialog.isSubmitting;

    if (!visibleRecipients.length) {
      elements.shareDialogList.innerHTML = '<div class="move-dialog-empty">Belum ada user lain yang bisa dipilih.</div>';
      return;
    }

    elements.shareDialogList.innerHTML = visibleRecipients.map((recipient) => `
      <label class="move-dialog-item ${selectedSet.has(recipient.userId || recipient.user_id) ? "is-selected" : ""}">
        <div class="move-dialog-item-copy">
          <strong>${escapeHtml(recipient.username)}</strong>
          <span class="move-dialog-item-path">${escapeHtml(recipient.role || "user")}</span>
        </div>
        <span class="move-dialog-item-badge">
          <input
            type="checkbox"
            class="share-dialog-check"
            data-user-id="${escapeHtml(String(recipient.userId || recipient.user_id))}"
            ${selectedSet.has(recipient.userId || recipient.user_id) ? "checked" : ""}
          >
        </span>
      </label>
    `).join("");
  }

  async function openShareDialog(targetItems = null) {
    const selectedItems = Array.isArray(targetItems) && targetItems.length ? targetItems : getSelectedItems();
    const manageableItems = selectedItems.filter((item) => !item.shortcut && canManageShareItem(item));
    if (!manageableItems.length) {
      throw new Error("Pilih file atau folder milikmu yang ingin dibagikan.");
    }
    const recipientsPayload = await requestJson(endpoints.shareRecipients);
    state.shareDialog.recipients = Array.isArray(recipientsPayload.items) ? recipientsPayload.items : [];
    state.shareDialog.search = "";
    state.shareDialog.targets = manageableItems.map((item) => ({
      key: getItemKey(item),
      name: item.name || "Item",
      path: getItemResolvedPath(item),
      recipients: Array.isArray(item.sharedRecipients || item.shared_recipients) ? (item.sharedRecipients || item.shared_recipients) : []
    }));
    if (state.shareDialog.targets.length === 1) {
      state.shareDialog.selectedUserIds = state.shareDialog.targets[0].recipients
        .map((recipient) => Number(recipient.userId || recipient.user_id || 0))
        .filter((value) => Number.isFinite(value) && value > 0);
    } else {
      state.shareDialog.selectedUserIds = [];
    }
    state.shareDialog.isSubmitting = false;
    elements.shareDialogSearchInput.value = "";
    renderShareDialog();
    if (typeof elements.shareDialog.showModal === "function") {
      elements.shareDialog.showModal();
    }
  }

  function closeShareDialog() {
    state.shareDialog.isSubmitting = false;
    if (elements.shareDialog.open) {
      elements.shareDialog.close();
    }
  }

  async function submitShareDialog() {
    if (!state.shareDialog.targets.length) {
      throw new Error("Tidak ada item yang dipilih untuk dibagikan.");
    }
    state.shareDialog.isSubmitting = true;
    renderShareDialog();
    try {
      await requestJson(endpoints.shared, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          paths: state.shareDialog.targets.map((item) => item.path),
          recipient_user_ids: state.shareDialog.selectedUserIds
        })
      });
      const selectedCount = state.shareDialog.selectedUserIds.length;
      closeShareDialog();
      showFeedback(
        selectedCount
          ? `${state.shareDialog.targets.length} item dibagikan ke ${selectedCount} user.`
          : `Akses shared untuk ${state.shareDialog.targets.length} item dicabut.`
      );
      clearSelection();
      await refreshWorkspace();
    } catch (error) {
      state.shareDialog.isSubmitting = false;
      renderShareDialog();
      throw error;
    }
  }

  async function createFolder() {
    if (!canMutateCurrentLocation()) {
      throw new Error("Folder baru hanya bisa dibuat di My Drive atau folder aktif.");
    }
    const name = window.prompt("Nama folder baru:");
    if (!name) return;
    await requestJson(endpoints.folder, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.currentPath, name })
    });
    showFeedback(`Folder ${name} berhasil dibuat.`);
    await refreshWorkspace();
  }

  function getMoveDialogVisibleItems() {
    const query = state.moveDialog.search.trim().toLowerCase();
    if (!query) return state.moveDialog.items;
    return state.moveDialog.items.filter((item) => {
      const haystack = `${item.name || ""} ${item.path || ""}`.toLowerCase();
      return haystack.includes(query);
    });
  }

  function renderMoveDialog() {
    const visibleItems = getMoveDialogVisibleItems();
    const selectedPath = state.moveDialog.destinationPath || "";
    const selectedItems = getSelectedItems();
    const isShortcutMode = state.moveDialog.mode === "shortcut";
    elements.moveDialogTitle.textContent = isShortcutMode ? "Buat Shortcut" : "Pindahkan Item";
    elements.moveDialogSelectedPath.textContent = selectedPath || "My Drive";
    elements.moveDialogTargetSummary.textContent = isShortcutMode
      ? (
        selectedItems.length === 1
          ? `Buat shortcut ${selectedItems[0].name} dan tempatkan di folder tujuan.`
          : `Buat ${selectedItems.length} shortcut dan tempatkan di folder tujuan.`
      )
      : (
        selectedItems.length === 1
          ? `Pindahkan ${selectedItems[0].name} ke folder tujuan baru.`
          : `Pindahkan ${selectedItems.length} item ke folder tujuan baru.`
      );
    elements.moveDialogSubmitButton.textContent = state.moveDialog.isSubmitting
      ? (isShortcutMode ? "Membuat..." : "Memindahkan...")
      : (isShortcutMode ? "Buat Shortcut" : "Pindahkan");
    elements.moveDialogSubmitButton.disabled = state.moveDialog.isSubmitting;

    if (!visibleItems.length) {
      elements.moveDialogList.innerHTML = '<div class="move-dialog-empty">Folder tujuan tidak ditemukan.</div>';
      return;
    }

    elements.moveDialogList.innerHTML = visibleItems.map((item) => {
      const itemPath = item.path || "";
      return `
        <button
          type="button"
          class="move-dialog-item ${itemPath === selectedPath ? "is-selected" : ""}"
          data-path="${escapeHtml(itemPath)}"
        >
          <div class="move-dialog-item-copy">
            <strong>${escapeHtml(item.name || "My Drive")}</strong>
            <span class="move-dialog-item-path">${escapeHtml(itemPath || "My Drive")}</span>
          </div>
          <span class="move-dialog-item-badge">${itemPath === selectedPath ? "Dipilih" : "Pilih"}</span>
        </button>
      `;
    }).join("");
  }

  async function openMoveDialog(mode = "move") {
    const isShortcutMode = mode === "shortcut";
    const selectedItems = getSelectedItems().filter((item) => !item.shortcut);
    if (!selectedItems.length) {
      throw new Error(isShortcutMode ? "Pilih item yang ingin dibuatkan shortcut." : "Pilih item yang ingin dipindahkan.");
    }
    if (isTrashView()) {
      throw new Error(isShortcutMode ? "Item di trash tidak bisa dibuatkan shortcut." : "Item di trash tidak memakai fitur pindah. Gunakan restore.");
    }
    const payload = await requestJson(endpoints.index);
    const folderItems = Array.isArray(payload.items) ? payload.items.filter((item) => item.kind === "folder") : [];
    state.moveDialog.mode = mode;
    state.moveDialog.items = [{ name: "My Drive", path: "" }, ...folderItems];
    state.moveDialog.destinationPath = state.currentPath || "";
    state.moveDialog.search = "";
    state.moveDialog.isSubmitting = false;
    elements.moveDialogSearchInput.value = "";
    renderMoveDialog();
    if (typeof elements.moveDialog.showModal === "function") {
      elements.moveDialog.showModal();
    }
  }

  function closeMoveDialog() {
    state.moveDialog.isSubmitting = false;
    state.moveDialog.mode = "move";
    if (elements.moveDialog.open) {
      elements.moveDialog.close();
    }
  }

  async function submitMoveSelection() {
    const selectedItems = getSelectedItems().filter((item) => !item.shortcut);
    if (!selectedItems.length) {
      throw new Error(state.moveDialog.mode === "shortcut" ? "Pilih item untuk shortcut." : "Pilih item yang ingin dipindahkan.");
    }
    const actionMode = state.moveDialog.mode;
    state.moveDialog.isSubmitting = true;
    renderMoveDialog();
    try {
      if (actionMode === "shortcut") {
        await requestJson(endpoints.shortcuts, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            paths: selectedItems.map((item) => getItemResolvedPath(item)),
            parent_path: state.moveDialog.destinationPath || ""
          })
        });
      } else {
        await requestJson(endpoints.move, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            paths: selectedItems.map((item) => item.path),
            destination_path: state.moveDialog.destinationPath || ""
          })
        });
      }
      closeMoveDialog();
      showFeedback(
        actionMode === "shortcut"
          ? (
            selectedItems.length === 1
              ? `Shortcut ${selectedItems[0].name} berhasil dibuat.`
              : `${selectedItems.length} shortcut berhasil dibuat.`
          )
          : (
            selectedItems.length === 1
              ? `${selectedItems[0].name} berhasil dipindahkan.`
              : `${selectedItems.length} item berhasil dipindahkan.`
          )
      );
      clearSelection();
      await refreshWorkspace();
    } catch (error) {
      state.moveDialog.isSubmitting = false;
      renderMoveDialog();
      throw error;
    }
  }

  async function toggleStarred(item) {
    if (!item || !getItemResolvedPath(item)) return;
    if (isExternalSharedItem(item)) {
      throw new Error("Item shared dari user lain tidak bisa diubah status starred-nya dari sini.");
    }
    const shouldStar = !item.starred;
    await requestJson(endpoints.starred, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        paths: [getItemResolvedPath(item)],
        starred: shouldStar
      })
    });
    showFeedback(
      shouldStar
        ? `${item.name} ditambahkan ke Starred.`
        : `${item.name} dihapus dari Starred.`
    );
    await refreshWorkspace();
  }

  async function toggleShared(item) {
    if (!item) return;
    if (!canManageShareItem(item)) {
      throw new Error("Item shared dari user lain hanya bisa dilihat, tidak bisa diatur ulang.");
    }
    await openShareDialog([item]);
  }

  async function toggleShortcut(item) {
    if (!item) return;
    if (isExternalSharedItem(item)) {
      throw new Error("Item shared dari user lain tidak bisa dibuatkan shortcut langsung.");
    }
    if (item.shortcut) {
      await requestJson(endpoints.shortcuts, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: [item.shortcutId || item.shortcut_id] })
      });
      showFeedback(`Shortcut ${item.name} dihapus.`);
      await refreshWorkspace();
      return;
    }
    const targetPath = getItemResolvedPath(item);
    if (!targetPath) return;
    await requestJson(endpoints.shortcuts, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        paths: [targetPath],
        parent_path: state.currentPath || ""
      })
    });
    showFeedback(`Shortcut ${item.name} berhasil dibuat.`);
    await refreshWorkspace();
  }

  async function renameSelection() {
    const selected = getSelectedItems();
    if (selected.length !== 1) {
      throw new Error("Pilih satu item yang ingin di-rename.");
    }
    const item = selected[0];
    if (item.shortcut) {
      throw new Error("Rename target asli dilakukan dari lokasi file aslinya, bukan dari view shortcuts.");
    }
    const newName = window.prompt("Nama baru:", item.name || "");
    if (!newName || newName === item.name) return;
    await requestJson(endpoints.rename, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: getItemResolvedPath(item), new_name: newName })
    });
    showFeedback(`Nama ${item.name} berhasil diubah.`);
    await refreshWorkspace();
  }

  async function deleteSelection() {
    const selected = getSelectedItems();
    if (!selected.length) {
      throw new Error(isTrashView() ? "Pilih item trash yang ingin dihapus." : "Pilih item yang ingin dipindahkan ke trash.");
    }

    if (isTrashView()) {
      const confirmed = window.confirm(`Hapus permanen ${selected.length} item dari trash?`);
      if (!confirmed) return;
      await requestJson(endpoints.deleteTrash, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: selected.map((item) => item.id) })
      });
      showFeedback(`${selected.length} item dihapus permanen dari trash.`);
      clearSelection();
      await refreshWorkspace();
      return;
    }

    const shortcutOnlyItems = selected.filter((item) => item.shortcut);
    const realItems = selected.filter((item) => !item.shortcut);
    if (shortcutOnlyItems.length && !realItems.length) {
      const confirmedShortcutDelete = window.confirm(`Hapus ${shortcutOnlyItems.length} shortcut dari daftar?`);
      if (!confirmedShortcutDelete) return;
      await requestJson(endpoints.shortcuts, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: shortcutOnlyItems.map((item) => item.shortcutId || item.shortcut_id) })
      });
      showFeedback(`${shortcutOnlyItems.length} shortcut dihapus dari daftar.`);
      clearSelection();
      await refreshWorkspace();
      return;
    }

    const confirmed = window.confirm(
      shortcutOnlyItems.length
        ? `Pindahkan ${realItems.length} item ke trash dan hapus ${shortcutOnlyItems.length} shortcut?`
        : `Pindahkan ${realItems.length} item ke trash?`
    );
    if (!confirmed) return;
    if (shortcutOnlyItems.length) {
      await requestJson(endpoints.shortcuts, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: shortcutOnlyItems.map((item) => item.shortcutId || item.shortcut_id) })
      });
    }
    await requestJson(endpoints.delete, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: realItems.map((item) => getItemResolvedPath(item)) })
    });
    showFeedback(
      shortcutOnlyItems.length
        ? `${realItems.length} item dipindahkan ke trash dan ${shortcutOnlyItems.length} shortcut dihapus.`
        : `${realItems.length} item dipindahkan ke trash.`
    );
    clearSelection();
    await refreshWorkspace();
  }

  async function restoreSelection() {
    const selected = getSelectedItems();
    if (!selected.length || !isTrashView()) {
      throw new Error("Pilih item trash yang ingin dipulihkan.");
    }
    await requestJson(endpoints.restore, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: selected.map((item) => item.id) })
    });
    showFeedback(`${selected.length} item berhasil dipulihkan.`);
    clearSelection();
    await refreshWorkspace();
  }

  async function emptyTrash() {
    if (!isTrashView()) {
      throw new Error("Fitur ini hanya tersedia di Trash.");
    }
    const confirmed = window.confirm("Kosongkan seluruh isi trash?");
    if (!confirmed) return;
    await requestJson(endpoints.emptyTrash, { method: "POST" });
    showFeedback("Trash berhasil dikosongkan.");
    clearSelection();
    await refreshWorkspace();
  }

  function queueUploadFiles(files) {
    if (!files?.length) return;
    if (!canMutateCurrentLocation()) {
      throw new Error("Upload hanya tersedia saat berada di My Drive atau folder aktif.");
    }
    Array.from(files).forEach((file) => {
      state.uploadQueue.push({
        id: `upload-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
        name: file.name,
        size: Number(file.size || 0),
        path: state.currentPath || "",
        file,
        progress: 0,
        status: "queued",
        error: ""
      });
    });
    elements.fileInput.value = "";
    renderUploadQueue();
    processUploadQueue().catch(handleError);
  }

  function clearFinishedUploads() {
    state.uploadQueue = state.uploadQueue.filter((task) => ["queued", "uploading"].includes(task.status));
    renderUploadQueue();
  }

  async function processUploadQueue() {
    const availableSlots = Math.max(0, 3 - state.activeUploads);
    if (availableSlots <= 0) {
      renderUploadQueue();
      return;
    }
    const pendingTasks = state.uploadQueue.filter((task) => task.status === "queued").slice(0, availableSlots);
    if (!pendingTasks.length) {
      renderUploadQueue();
      return;
    }
    pendingTasks.forEach((task) => {
      uploadTask(task).catch(handleError);
    });
  }

  function uploadTask(task) {
    task.status = "uploading";
    task.progress = 0;
    task.error = "";
    state.activeUploads += 1;
    renderUploadQueue();

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", endpoints.upload, true);
      xhr.responseType = "text";
      xhr.upload.addEventListener("progress", (event) => {
        if (!event.lengthComputable) return;
        task.progress = (event.loaded / event.total) * 100;
        renderUploadQueue();
      });
      xhr.addEventListener("load", async () => {
        state.activeUploads = Math.max(0, state.activeUploads - 1);
        if (xhr.status >= 200 && xhr.status < 300) {
          task.status = "done";
          task.progress = 100;
          renderUploadQueue();
          await refreshWorkspace();
          processUploadQueue().catch(handleError);
          resolve();
          return;
        }
        let message = "Upload gagal diproses.";
        try {
          const payload = JSON.parse(xhr.responseText || "{}");
          message = payload.message || payload.error || message;
        } catch {
          message = xhr.responseText || message;
        }
        task.status = "error";
        task.error = message;
        renderUploadQueue();
        processUploadQueue().catch(handleError);
        reject(new Error(message));
      });
      xhr.addEventListener("error", () => {
        state.activeUploads = Math.max(0, state.activeUploads - 1);
        task.status = "error";
        task.error = "Koneksi upload terputus.";
        renderUploadQueue();
        processUploadQueue().catch(handleError);
        reject(new Error(task.error));
      });
      const formData = new FormData();
      formData.append("path", task.path || "");
      formData.append("files", task.file);
      xhr.send(formData);
    });
  }

  function bindFileActions() {
    elements.fileList.addEventListener("click", (event) => {
      const actionButton = event.target.closest("[data-action]");
      if (actionButton) {
        const item = findItemByKey(actionButton.dataset.key);
        if (!item) return;
        const action = actionButton.dataset.action;
        if (action === "open") {
          openItem(item).catch(handleError);
        } else if (action === "download") {
          downloadItem(item);
        } else if (action === "toggle-star") {
          toggleStarred(item).catch(handleError);
        } else if (action === "toggle-shared") {
          toggleShared(item).catch(handleError);
        } else if (action === "toggle-shortcut") {
          toggleShortcut(item).catch(handleError);
        } else if (action === "move") {
          state.selectedKeys = [getItemKey(item)];
          renderSelectionState();
          renderFileList();
          openMoveDialog().catch(handleError);
        } else if (action === "delete") {
          state.selectedKeys = [getItemKey(item)];
          deleteSelection().catch(handleError);
        } else if (action === "restore") {
          state.selectedKeys = [getItemKey(item)];
          restoreSelection().catch(handleError);
        }
        return;
      }

      const checkbox = event.target.closest(".file-select");
      if (checkbox) {
        toggleSelection(checkbox.dataset.key, checkbox.checked);
        return;
      }

      const row = event.target.closest(".file-row, .file-card");
      if (row) {
        const key = row.dataset.key;
        const currentlySelected = state.selectedKeys.includes(key);
        toggleSelection(key, !currentlySelected);
      }
    });

    elements.fileList.addEventListener("contextmenu", (event) => {
      const row = event.target.closest(".file-row, .file-card");
      if (!row) return;
      event.preventDefault();
      const item = findItemByKey(row.dataset.key);
      openContextMenu(item, event.clientX, event.clientY);
    });

    elements.folderCards.addEventListener("click", (event) => {
      const button = event.target.closest("[data-action='open']");
      if (!button) return;
      const item = findItemByKey(button.dataset.key);
      openItem(item).catch(handleError);
    });

    elements.folderCards.addEventListener("contextmenu", (event) => {
      const button = event.target.closest("[data-action='open']");
      if (!button) return;
      event.preventDefault();
      const item = findItemByKey(button.dataset.key);
      openContextMenu(item, event.clientX, event.clientY);
    });
  }

  function bindBreadcrumbs() {
    elements.breadcrumbs.addEventListener("click", (event) => {
      const button = event.target.closest(".breadcrumb-btn");
      if (!button) return;
      navigateTo(button.dataset.path || "");
    });
  }

  function bindToolbar() {
    elements.sidebarMenuButton.addEventListener("click", () => {
      elements.appShell.classList.toggle("sidebar-open");
    });
    elements.navHome.addEventListener("click", () => setSection("home"));
    elements.navDrive.addEventListener("click", () => setSection("drive"));
    elements.navRecent.addEventListener("click", () => setSection("recent"));
    elements.navStarred.addEventListener("click", () => setSection("starred"));
    elements.navShared.addEventListener("click", () => setSection("shared"));
    elements.navShortcuts.addEventListener("click", () => setSection("shortcuts"));
    elements.navAll.addEventListener("click", () => setSection("all"));
    elements.navTrash.addEventListener("click", () => setSection("trash"));
    elements.sidebarUpload.addEventListener("click", () => elements.fileInput.click());
    elements.uploadBtn.addEventListener("click", () => elements.fileInput.click());
    elements.folderBtn.addEventListener("click", () => createFolder().catch(handleError));
    elements.refreshBtn.addEventListener("click", () => refreshWorkspace().catch(handleError));
    elements.shareBtn.addEventListener("click", () => {
      const selected = getSelectedItems();
      if (!selected.length) {
        handleError(new Error("Pilih item yang ingin dibagikan."));
        return;
      }
      openShareDialog(selected).catch(handleError);
    });
    elements.shortcutBtn.addEventListener("click", () => {
      const shortcutItems = getSelectedItems().filter((item) => item.shortcut);
      if (shortcutItems.length && shortcutItems.length === getSelectedItems().length) {
        requestJson(endpoints.shortcuts, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: shortcutItems.map((item) => item.shortcutId || item.shortcut_id) })
        }).then(() => {
          showFeedback(`${shortcutItems.length} shortcut dihapus.`);
          clearSelection();
          return refreshWorkspace();
        }).catch(handleError);
        return;
      }
      if (!getSelectedItems().filter((item) => !item.shortcut).length) {
        handleError(new Error("Pilih item yang ingin dibuatkan shortcut."));
        return;
      }
      openMoveDialog("shortcut").catch(handleError);
    });
    elements.downloadBtn.addEventListener("click", () => {
      const selected = getSelectedItems();
      if (selected.length !== 1) {
        handleError(new Error("Pilih satu item untuk diunduh."));
        return;
      }
      downloadItem(selected[0]);
    });
    elements.moveBtn.addEventListener("click", () => openMoveDialog("move").catch(handleError));
    elements.renameBtn.addEventListener("click", () => renameSelection().catch(handleError));
    elements.restoreBtn.addEventListener("click", () => restoreSelection().catch(handleError));
    elements.deleteBtn.addEventListener("click", () => deleteSelection().catch(handleError));
    elements.emptyTrashBtn.addEventListener("click", () => emptyTrash().catch(handleError));
    elements.selectionOpenBtn.addEventListener("click", () => {
      const selected = getSelectedItems();
      if (selected.length !== 1) {
        handleError(new Error("Pilih satu item untuk dibuka."));
        return;
      }
      openItem(selected[0]).catch(handleError);
    });
    elements.selectionDownloadBtn.addEventListener("click", () => {
      const selected = getSelectedItems();
      if (selected.length !== 1) {
        handleError(new Error("Pilih satu item untuk diunduh."));
        return;
      }
      downloadItem(selected[0]);
    });
    elements.selectionStarBtn.addEventListener("click", () => {
      const selected = getSelectedItems();
      if (!selected.length) {
        handleError(new Error("Pilih item untuk diatur status starred-nya."));
        return;
      }
      const shouldStar = selected.some((item) => !item.starred);
      requestJson(endpoints.starred, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          paths: selected.map((item) => getItemResolvedPath(item)),
          starred: shouldStar
        })
      }).then(() => {
        showFeedback(shouldStar ? `${selected.length} item ditambahkan ke Starred.` : `${selected.length} item dihapus dari Starred.`);
        clearSelection();
        return refreshWorkspace();
      }).catch(handleError);
    });
    elements.selectionShareBtn.addEventListener("click", () => elements.shareBtn.click());
    elements.selectionShortcutBtn.addEventListener("click", () => {
      const shortcutItems = getSelectedItems().filter((item) => item.shortcut);
      if (shortcutItems.length && shortcutItems.length === getSelectedItems().length) {
        elements.shortcutBtn.click();
        return;
      }
      openMoveDialog("shortcut").catch(handleError);
    });
    elements.selectionMoveBtn.addEventListener("click", () => openMoveDialog("move").catch(handleError));
    elements.selectionRenameBtn.addEventListener("click", () => renameSelection().catch(handleError));
    elements.selectionRestoreBtn.addEventListener("click", () => restoreSelection().catch(handleError));
    elements.selectionDeleteBtn.addEventListener("click", () => deleteSelection().catch(handleError));
    elements.selectionClearBtn.addEventListener("click", clearSelection);
    elements.viewListBtn.addEventListener("click", () => {
      state.viewMode = "list";
      elements.viewListBtn.classList.add("is-active");
      elements.viewGridBtn.classList.remove("is-active");
      renderFileList();
      renderSelectionState();
    });
    elements.viewGridBtn.addEventListener("click", () => {
      state.viewMode = "grid";
      elements.viewGridBtn.classList.add("is-active");
      elements.viewListBtn.classList.remove("is-active");
      renderFileList();
      renderSelectionState();
    });
    elements.searchInput.addEventListener("input", (event) => {
      state.search = event.target.value || "";
      renderFileList();
      renderSelectionState();
    });
    elements.fileInput.addEventListener("change", (event) => {
      try {
        queueUploadFiles(event.target.files);
      } catch (error) {
        handleError(error);
      }
    });
    elements.activityRefresh.addEventListener("click", () => refreshActivity().catch(handleError));
    elements.queueClear.addEventListener("click", clearFinishedUploads);
    elements.moveDialogSearchInput.addEventListener("input", (event) => {
      state.moveDialog.search = event.target.value || "";
      renderMoveDialog();
    });
    elements.shareDialogSearchInput.addEventListener("input", (event) => {
      state.shareDialog.search = event.target.value || "";
      renderShareDialog();
    });
    elements.shareDialogList.addEventListener("change", (event) => {
      const checkbox = event.target.closest(".share-dialog-check");
      if (!checkbox) return;
      const userId = Number(checkbox.dataset.userId || 0);
      const selected = new Set(state.shareDialog.selectedUserIds);
      if (checkbox.checked) {
        selected.add(userId);
      } else {
        selected.delete(userId);
      }
      state.shareDialog.selectedUserIds = Array.from(selected);
      renderShareDialog();
    });
    elements.moveDialogList.addEventListener("click", (event) => {
      const button = event.target.closest(".move-dialog-item");
      if (!button) return;
      state.moveDialog.destinationPath = button.dataset.path || "";
      renderMoveDialog();
    });
    elements.shareDialogCancelButton.addEventListener("click", closeShareDialog);
    elements.shareDialogCloseButton.addEventListener("click", closeShareDialog);
    elements.shareDialogSubmitButton.addEventListener("click", () => submitShareDialog().catch(handleError));
    elements.moveDialogCancelButton.addEventListener("click", closeMoveDialog);
    elements.moveDialogCloseButton.addEventListener("click", closeMoveDialog);
    elements.moveDialogSubmitButton.addEventListener("click", () => submitMoveSelection().catch(handleError));
    elements.contextOpenBtn.addEventListener("click", () => {
      const item = getContextMenuItem();
      closeContextMenu();
      openItem(item).catch(handleError);
    });
    elements.contextDownloadBtn.addEventListener("click", () => {
      const item = getContextMenuItem();
      closeContextMenu();
      downloadItem(item);
    });
    elements.contextStarBtn.addEventListener("click", () => {
      const item = getContextMenuItem();
      closeContextMenu();
      toggleStarred(item).catch(handleError);
    });
    elements.contextShareBtn.addEventListener("click", () => {
      const item = getContextMenuItem();
      closeContextMenu();
      toggleShared(item).catch(handleError);
    });
    elements.contextShortcutBtn.addEventListener("click", () => {
      const item = getContextMenuItem();
      closeContextMenu();
      toggleShortcut(item).catch(handleError);
    });
    elements.contextShortcutTargetBtn.addEventListener("click", () => {
      closeContextMenu();
      openMoveDialog("shortcut").catch(handleError);
    });
    elements.contextMoveBtn.addEventListener("click", () => {
      closeContextMenu();
      openMoveDialog("move").catch(handleError);
    });
    elements.contextRenameBtn.addEventListener("click", () => {
      closeContextMenu();
      renameSelection().catch(handleError);
    });
    elements.contextRestoreBtn.addEventListener("click", () => {
      closeContextMenu();
      restoreSelection().catch(handleError);
    });
    elements.contextDeleteBtn.addEventListener("click", () => {
      closeContextMenu();
      deleteSelection().catch(handleError);
    });
    elements.homeDashboard.addEventListener("click", (event) => {
      const button = event.target.closest(".home-item-btn");
      if (!button) return;
      const targetItem = [
        ...state.homeData.starredItems,
        ...state.homeData.recentItems,
        ...state.homeData.rootFolders,
        ...state.homeData.sharedItems,
        ...state.homeData.shortcutItems
      ].find((item) => getItemKey(item) === (button.dataset.key || ""));
      if (!targetItem) return;
      openItem(targetItem).catch(handleError);
    });
    document.addEventListener("click", (event) => {
      if (elements.contextMenu.classList.contains("hidden")) return;
      if (elements.contextMenu.contains(event.target)) return;
      closeContextMenu();
    });
    window.addEventListener("resize", closeContextMenu);
    window.addEventListener("scroll", closeContextMenu, true);
  }

  function bindDropzone() {
    ["dragenter", "dragover"].forEach((eventName) => {
      elements.dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        elements.dropzone.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach((eventName) => {
      elements.dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        elements.dropzone.classList.remove("is-dragover");
      });
    });
    elements.dropzone.addEventListener("drop", (event) => {
      const files = event.dataTransfer?.files;
      try {
        queueUploadFiles(files);
      } catch (error) {
        handleError(error);
      }
    });
  }

  function bindPreviewDialog() {
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !elements.contextMenu.classList.contains("hidden")) {
        closeContextMenu();
        return;
      }
      if (event.key === "Escape" && elements.shareDialog.open) {
        closeShareDialog();
        return;
      }
      if (event.key === "Escape" && elements.previewDialog.open) {
        elements.previewDialog.close();
        return;
      }
      if (event.key === "Escape" && elements.moveDialog.open) {
        closeMoveDialog();
      }
    });
  }

  bindToolbar();
  bindFileActions();
  bindBreadcrumbs();
  bindDropzone();
  bindPreviewDialog();
  renderStats();
  refreshWorkspace().catch(handleError);
})();
