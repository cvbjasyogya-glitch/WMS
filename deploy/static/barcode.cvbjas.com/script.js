"use strict";

const SHEET = {
  width: 69.06,
  height: 19.05,
  labelWidth: 34.53,
  labelHeight: 19.05,
};

const DEFAULT_GAP_MM = 0.12;
const DEFAULT_LOGO_SRC = "assets/logo.png";
const DEFAULT_PREVIEW_ZOOM = 3;
const DEFAULT_INFO_Y_SINGLE_LINE = 8.02;
const DEFAULT_INFO_Y_MULTILINE = 11.17;
const SIDE_OFFSET = {
  left: { x: 0, y: 0 },
  right: { x: 0.8, y: 0 },
};
const BOX_ORDER = ["title", "price", "info", "logo"];

const DEFAULT_DATA = {
  productName: "Knee / Deker Lutut Athlet Cream",
  priceText: "Rp45.000",
  infoText: "Buy 2 = 75.000 @megasports_seturan",
};

const DEFAULT_LAYOUT = {
  title: {
    x: 0.42,
    y: 0,
    w: 33.41,
    h: 3.11,
    fontSize: 9.3,
    lineHeight: 0.95,
    fontWeight: 400,
  },
  price: {
    x: 0.6,
    y: 6.35,
    w: 23,
    h: 5.1,
    fontSize: 14,
    lineHeight: 0.9,
    fontWeight: 900,
  },
  info: {
    x: 0.6,
    y: DEFAULT_INFO_Y_MULTILINE,
    w: 23.47,
    h: 4.2,
    fontSize: 7,
    lineHeight: 0.95,
    fontWeight: 400,
  },
  logo: {
    x: 25.03,
    y: 9.33,
    w: 7.04,
    h: 4.71,
    fontSize: 7,
    lineHeight: 1,
    fontWeight: 400,
  },
};

const BOX_LABELS = {
  title: "productTitleBox",
  price: "priceBox",
  info: "infoBox",
  logo: "logoBox",
};

const MIN_SIZE = {
  title: { w: 8, h: 2 },
  price: { w: 8, h: 2.5 },
  info: { w: 10, h: 1.7 },
  logo: { w: 3, h: 3 },
};

const state = {
  data: clone(DEFAULT_DATA),
  layout: clone(DEFAULT_LAYOUT),
  settings: {
    editMode: true,
    autoStack: true,
    selectedBox: "title",
    logoSrc: DEFAULT_LOGO_SRC,
    previewZoom: DEFAULT_PREVIEW_ZOOM,
    printPages: 1,
    manualY: {
      price: false,
      info: false,
    },
  },
};

let activeDrag = null;
let isSyncingControls = false;
let autoStackFrame = 0;

const dom = {};

document.addEventListener("DOMContentLoaded", init);

function init() {
  cacheDom();
  bindControls();
  syncControlsFromState();
  initFontStatus();
  updatePreviewZoom();
  renderLabels({ skipAutoStack: true, applyAdaptiveInfoDefault: true });
}

function cacheDom() {
  dom.sheet = document.getElementById("labelSheet");
  dom.printArea = document.getElementById("printArea");
  dom.productName = document.getElementById("productName");
  dom.priceText = document.getElementById("priceText");
  dom.infoText = document.getElementById("infoText");
  dom.editMode = document.getElementById("editMode");
  dom.autoStack = document.getElementById("autoStack");
  dom.printBtn = document.getElementById("printBtn");
  dom.resetBtn = document.getElementById("resetBtn");
  dom.selectedBoxName = document.getElementById("selectedBoxName");
  dom.boxX = document.getElementById("boxX");
  dom.boxY = document.getElementById("boxY");
  dom.boxW = document.getElementById("boxW");
  dom.boxH = document.getElementById("boxH");
  dom.boxFontSize = document.getElementById("boxFontSize");
  dom.previewZoom = document.getElementById("previewZoom");
  dom.printPages = document.getElementById("printPages");
  dom.previewTitle = document.getElementById("previewTitle");
  dom.fontWarning = document.getElementById("fontWarning");
}

function bindControls() {
  bindTextInput(dom.productName, "productName");
  bindTextInput(dom.priceText, "priceText");
  bindTextInput(dom.infoText, "infoText");

  dom.editMode.addEventListener("change", () => {
    state.settings.editMode = dom.editMode.checked;
    updateModeClass();
    renderLabels({ skipAutoStack: true });
  });

  dom.autoStack.addEventListener("change", () => {
    const nextValue = dom.autoStack.checked;
    if (!nextValue) {
      state.settings.autoStack = false;
      return;
    }

    const accepted = window.confirm(
      "Auto stack akan menyusun ulang posisi priceBox dan infoBox. Lanjutkan?"
    );
    if (!accepted) {
      dom.autoStack.checked = false;
      state.settings.autoStack = false;
      return;
    }

    state.settings.autoStack = true;
    state.settings.manualY.price = false;
    state.settings.manualY.info = false;
    scheduleAutoStack();
  });

  dom.previewZoom.addEventListener("input", () => {
    state.settings.previewZoom = toNumber(dom.previewZoom.value, DEFAULT_PREVIEW_ZOOM);
    updatePreviewZoom();
  });

  dom.printPages.addEventListener("input", () => {
    const value = Number.parseInt(dom.printPages.value, 10);
    state.settings.printPages = Number.isFinite(value) ? clamp(value, 1, 100) : 1;
    dom.printPages.value = String(state.settings.printPages);
    renderPrintPages();
  });

  dom.printBtn.addEventListener("click", () => window.print());
  dom.resetBtn.addEventListener("click", resetLayout);

  [dom.boxX, dom.boxY, dom.boxW, dom.boxH, dom.boxFontSize].forEach((input) => {
    input.addEventListener("input", updateSelectedBoxFromInspector);
  });

  document.addEventListener("keydown", handleKeyboardNudge);
}

function bindTextInput(input, key) {
  input.addEventListener("input", () => {
    if (isSyncingControls) return;
    state.data[key] = input.value;
    renderLabels({ skipAutoStack: key !== "productName" });
  });
}

function renderLabels(options = {}) {
  fillLabelSheet(dom.sheet, { printMode: false });

  if (options.applyAdaptiveInfoDefault) {
    applyAdaptiveInfoDefault();
    applyBoxStyles("info");
  }

  updateModeClass();
  selectBox(state.settings.selectedBox);
  syncControlsFromState();

  if (state.settings.autoStack && !options.skipAutoStack) {
    scheduleAutoStack();
  } else {
    renderPrintPages();
  }
}

function fillLabelSheet(target, options = {}) {
  target.innerHTML = "";
  target.classList.toggle("print-sheet", Boolean(options.printMode));
  ["left", "right"].forEach((side) => {
    const label = document.createElement("section");
    label.className = "label";
    label.dataset.side = side;

    BOX_ORDER.forEach((boxType) => {
      label.appendChild(createBox(boxType, side, options));
    });

    target.appendChild(label);
  });
}

function renderPrintPages() {
  if (!dom.printArea) return;
  dom.printArea.innerHTML = "";

  for (let index = 0; index < state.settings.printPages; index += 1) {
    const printSheet = document.createElement("div");
    printSheet.className = "label-sheet print-sheet";
    fillLabelSheet(printSheet, { printMode: true });
    dom.printArea.appendChild(printSheet);
  }
}

function createBox(boxType, side, options = {}) {
  const box = document.createElement("div");
  box.className = `label-box ${boxType}-box`;
  box.dataset.box = boxType;
  box.dataset.side = side;
  if (!options.printMode) {
    box.tabIndex = 0;
  }
  applyStyleToBox(box, boxType);

  const content = document.createElement("div");
  content.className = "label-content";

  if (boxType === "logo") {
    renderLogoContent(content);
  } else {
    content.textContent = getBoxText(boxType);
  }

  box.appendChild(content);

  if (!options.printMode) {
    const handle = document.createElement("span");
    handle.className = "resize-handle";
    handle.setAttribute("aria-hidden", "true");
    box.appendChild(handle);
    bindDrag(box);
  }

  return box;
}

function renderLogoContent(content) {
  const img = document.createElement("img");
  img.src = state.settings.logoSrc || DEFAULT_LOGO_SRC;
  img.alt = "Mega Sport logo";
  img.draggable = false;
  img.addEventListener("error", () => {
    content.innerHTML = "";
    const placeholder = document.createElement("div");
    placeholder.className = "logo-placeholder";
    placeholder.textContent = "logo.png";
    content.appendChild(placeholder);
  });
  content.appendChild(img);
}

function getBoxText(boxType, side) {
  if (boxType === "title") return state.data.productName;
  if (boxType === "price") return state.data.priceText;
  if (boxType === "info") return state.data.infoText;
  return "";
}

function applyStyleToBox(box, boxType) {
  const item = state.layout[boxType];
  const side = box.dataset.side || "left";
  const offset = SIDE_OFFSET[side] || SIDE_OFFSET.left;
  box.style.left = toMm(item.x + offset.x);
  box.style.top = toMm(item.y + offset.y);
  box.style.width = toMm(item.w);
  box.style.fontSize = `${item.fontSize}pt`;
  box.style.lineHeight = String(item.lineHeight);
  box.style.fontWeight = String(item.fontWeight);

  if (boxType === "logo") {
    box.style.height = toMm(item.h);
    box.style.minHeight = "";
  } else {
    box.style.height = "auto";
    box.style.minHeight = toMm(item.h);
  }
}

function applyBoxStyles(boxType) {
  dom.sheet.querySelectorAll(`[data-box="${boxType}"]`).forEach((box) => {
    applyStyleToBox(box, boxType);
  });
}

function applyAllBoxStyles() {
  BOX_ORDER.forEach(applyBoxStyles);
}

function bindDrag(box) {
  box.addEventListener("pointerdown", (event) => {
    if (!state.settings.editMode) return;

    const boxType = box.dataset.box;
    const isResize = event.target.classList.contains("resize-handle");
    selectBox(boxType);

    activeDrag = {
      boxType,
      mode: isResize ? "resize" : "move",
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      origin: clone(state.layout[boxType]),
      didMove: false,
    };

    box.classList.add("is-dragging");
    box.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  box.addEventListener("pointermove", handlePointerMove);
  box.addEventListener("pointerup", endPointerDrag);
  box.addEventListener("pointercancel", endPointerDrag);
  box.addEventListener("click", () => selectBox(box.dataset.box));
}

function handlePointerMove(event) {
  if (!activeDrag || event.pointerId !== activeDrag.pointerId) return;

  const { boxType, mode, origin, startX, startY } = activeDrag;
  const dx = pxToMm(event.clientX - startX);
  const dy = pxToMm(event.clientY - startY);
  const item = state.layout[boxType];
  const next = {
    x: item.x,
    y: item.y,
    w: item.w,
    h: item.h,
  };

  if (mode === "resize") {
    next.w = roundMm(clamp(origin.w + dx, MIN_SIZE[boxType].w, SHEET.labelWidth - item.x));
    next.h = roundMm(clamp(origin.h + dy, MIN_SIZE[boxType].h, SHEET.labelHeight - item.y));
  } else {
    next.x = roundMm(clamp(origin.x + dx, 0, SHEET.labelWidth - item.w));
    next.y = roundMm(clamp(origin.y + dy, 0, SHEET.labelHeight - item.h));
  }

  activeDrag.didMove =
    activeDrag.didMove ||
    Math.abs(next.x - origin.x) > 0.001 ||
    Math.abs(next.y - origin.y) > 0.001 ||
    Math.abs(next.w - origin.w) > 0.001 ||
    Math.abs(next.h - origin.h) > 0.001;

  item.x = next.x;
  item.y = next.y;
  item.w = next.w;
  item.h = next.h;

  if (activeDrag.didMove && mode === "move" && (boxType === "price" || boxType === "info")) {
    state.settings.manualY[boxType] = true;
  }

  if (boxType === "info") {
    clampInfoBounds();
  }

  applyAllBoxStyles();
  if (state.settings.autoStack && (boxType === "title" || (boxType === "price" && mode === "resize"))) {
    updateAutoStack();
  }
  updateInspector();
}

function endPointerDrag(event) {
  if (!activeDrag || event.pointerId !== activeDrag.pointerId) return;
  const shouldRerender = activeDrag.didMove;
  dom.sheet.querySelectorAll(".is-dragging").forEach((node) => node.classList.remove("is-dragging"));
  activeDrag = null;
  if (shouldRerender) {
    renderPrintPages();
    renderLabels();
  }
}

function handleKeyboardNudge(event) {
  if (!state.settings.editMode || isTyping(event.target)) return;
  if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;

  const boxType = state.settings.selectedBox;
  if (!boxType) return;

  const step = event.shiftKey ? 1 : event.altKey ? 0.05 : 0.1;
  const item = state.layout[boxType];

  if (event.key === "ArrowLeft") item.x = clamp(item.x - step, 0, SHEET.labelWidth - item.w);
  if (event.key === "ArrowRight") item.x = clamp(item.x + step, 0, SHEET.labelWidth - item.w);
  if (event.key === "ArrowUp") {
    item.y = clamp(item.y - step, 0, SHEET.labelHeight - item.h);
    if (boxType === "price" || boxType === "info") {
      state.settings.manualY[boxType] = true;
    }
  }
  if (event.key === "ArrowDown") {
    item.y = clamp(item.y + step, 0, SHEET.labelHeight - item.h);
    if (boxType === "price" || boxType === "info") {
      state.settings.manualY[boxType] = true;
    }
  }

  item.x = roundMm(item.x);
  item.y = roundMm(item.y);
  if (boxType === "info") {
    clampInfoBounds();
  }
  applyAllBoxStyles();
  if (state.settings.autoStack && boxType === "title") {
    updateAutoStack();
  }
  renderPrintPages();
  updateInspector();
  event.preventDefault();
}

function scheduleAutoStack() {
  cancelAnimationFrame(autoStackFrame);
  autoStackFrame = requestAnimationFrame(() => {
    updateAutoStack();
    renderPrintPages();
    updateInspector();
  });
}

function updateAutoStack() {
  if (!state.settings.autoStack) return;
  const titleBox = firstBox("title");
  const priceBox = firstBox("price");
  if (!titleBox || !priceBox) return;

  const titleHeight = getActualHeightMm(titleBox);
  const nextPriceY = roundMm(
    clamp(state.layout.title.y + titleHeight + DEFAULT_GAP_MM, 0, SHEET.labelHeight - state.layout.price.h)
  );
  if (!state.settings.manualY.price) {
    state.layout.price.y = nextPriceY;
  }
  applyBoxStyles("price");

  if (!state.settings.manualY.info) {
    state.layout.info.y = getDefaultInfoY();
  }

  const maxInfoWidth = state.layout.logo.x - state.layout.info.x - 0.5;
  state.layout.info.w = roundMm(clamp(state.layout.info.w, MIN_SIZE.info.w, maxInfoWidth));
  clampInfoBounds();
  applyBoxStyles("info");
}

function selectBox(boxType) {
  if (!BOX_ORDER.includes(boxType)) boxType = "title";
  state.settings.selectedBox = boxType;
  dom.sheet.querySelectorAll(".label-box").forEach((box) => {
    box.classList.toggle("is-selected", box.dataset.box === boxType);
  });
  updateInspector();
}

function updateInspector() {
  const boxType = state.settings.selectedBox;
  const item = state.layout[boxType];
  if (!item) return;

  isSyncingControls = true;
  dom.selectedBoxName.value = BOX_LABELS[boxType];
  dom.boxX.value = formatNumber(item.x);
  dom.boxY.value = formatNumber(item.y);
  dom.boxW.value = formatNumber(item.w);
  dom.boxH.value = formatNumber(item.h);
  dom.boxFontSize.value = formatNumber(item.fontSize);
  isSyncingControls = false;
}

function updateSelectedBoxFromInspector() {
  if (isSyncingControls) return;
  const boxType = state.settings.selectedBox;
  const item = state.layout[boxType];
  if (!item) return;
  const oldY = item.y;

  item.x = roundMm(clamp(toNumber(dom.boxX.value, item.x), 0, SHEET.labelWidth - item.w));
  item.y = roundMm(clamp(toNumber(dom.boxY.value, item.y), 0, SHEET.labelHeight - item.h));
  item.w = roundMm(clamp(toNumber(dom.boxW.value, item.w), MIN_SIZE[boxType].w, SHEET.labelWidth - item.x));
  item.h = roundMm(clamp(toNumber(dom.boxH.value, item.h), MIN_SIZE[boxType].h, SHEET.labelHeight - item.y));
  item.fontSize = roundOne(toNumber(dom.boxFontSize.value, item.fontSize));

  if ((boxType === "price" || boxType === "info") && Math.abs(item.y - oldY) > 0.001) {
    state.settings.manualY[boxType] = true;
  }

  if (boxType === "info") {
    clampInfoBounds();
  }

  applyBoxStyles(boxType);
  if (state.settings.autoStack && (boxType === "title" || boxType === "price")) {
    updateAutoStack();
  }
  renderPrintPages();
  updateInspector();
}

function syncControlsFromState() {
  isSyncingControls = true;
  dom.productName.value = state.data.productName;
  dom.priceText.value = state.data.priceText;
  dom.infoText.value = state.data.infoText;
  dom.editMode.checked = state.settings.editMode;
  dom.autoStack.checked = state.settings.autoStack;
  dom.previewZoom.value = String(state.settings.previewZoom);
  dom.printPages.value = String(state.settings.printPages ?? 1);
  isSyncingControls = false;
  updatePreviewZoom();
  updateInspector();
}

function updateModeClass() {
  document.body.classList.toggle("edit-mode", state.settings.editMode);
}

function updatePreviewZoom() {
  const zoom = clamp(state.settings.previewZoom || DEFAULT_PREVIEW_ZOOM, 1, 4);
  state.settings.previewZoom = zoom;
  document.documentElement.style.setProperty("--preview-zoom", String(zoom));
  if (dom.previewZoom) {
    dom.previewZoom.value = String(zoom);
  }
  if (dom.previewTitle) {
    dom.previewTitle.textContent = `Preview editor ${Math.round(zoom * 100)}%`;
  }
}

function initFontStatus() {
  if (!document.fonts?.ready) {
    updateFontWarning(true);
    return;
  }

  document.fonts.ready.then(() => {
    const sairaReady = document.fonts.check('12pt "Saira Condensed"');
    const robotoReady = document.fonts.check('12pt "Roboto Condensed"');
    document.body.classList.add("fonts-loaded");
    console.log("Fonts loaded:", sairaReady, robotoReady);
    updateFontWarning(!(sairaReady && robotoReady));
  });
}

function updateFontWarning(showWarning) {
  if (!dom.fontWarning) return;
  dom.fontWarning.hidden = !showWarning;
}

function resetLayout() {
  state.data = clone(DEFAULT_DATA);
  state.layout = clone(DEFAULT_LAYOUT);
  state.settings.autoStack = true;
  state.settings.editMode = true;
  state.settings.selectedBox = "title";
  state.settings.logoSrc = DEFAULT_LOGO_SRC;
  state.settings.previewZoom = DEFAULT_PREVIEW_ZOOM;
  state.settings.printPages = 1;
  state.settings.manualY.price = false;
  state.settings.manualY.info = false;
  syncControlsFromState();
  renderLabels({ skipAutoStack: true, applyAdaptiveInfoDefault: true });
}

function mergeLayout(base, incoming) {
  BOX_ORDER.forEach((boxType) => {
    if (boxType === "info") {
      const legacyInfo = incoming.info || incoming.promo;
      if (legacyInfo) {
        base.info = { ...base.info, ...legacyInfo };
      }
      return;
    }
    if (!incoming[boxType]) return;
    base[boxType] = { ...base[boxType], ...incoming[boxType] };
  });
  return base;
}

function firstBox(boxType) {
  return dom.sheet.querySelector(`.label[data-side="left"] [data-box="${boxType}"]`);
}

function normalizeData(rawData) {
  const migratedInfo = readPresetText(
    rawData.infoText,
    `${rawData.promoText || ""} ${rawData.instagramText || ""}`.trim() || DEFAULT_DATA.infoText
  );

  return {
    productName: readPresetText(rawData.productName, DEFAULT_DATA.productName),
    priceText: readPresetText(
      rawData.priceText,
      readPresetText(rawData.priceLeft, readPresetText(rawData.priceRight, DEFAULT_DATA.priceText))
    ),
    infoText: migratedInfo,
  };
}

function readPresetText(value, fallback) {
  return value === undefined || value === null ? fallback : value;
}

function getActualHeightMm(element) {
  return pxToMm(element.getBoundingClientRect().height);
}

function applyAdaptiveInfoDefault() {
  state.layout.info.y = getDefaultInfoY();
}

function isTitleSingleLine() {
  const titleContent = firstBox("title")?.querySelector(".label-content");
  if (!titleContent) return false;
  return getRenderedLineCount(titleContent) <= 1;
}

function getDefaultInfoY() {
  return isTitleSingleLine() ? DEFAULT_INFO_Y_SINGLE_LINE : DEFAULT_INFO_Y_MULTILINE;
}

function getRenderedLineCount(element) {
  const range = document.createRange();
  range.selectNodeContents(element);
  const rects = [...range.getClientRects()].filter((rect) => rect.width > 0 && rect.height > 0);
  if (rects.length === 0) {
    return 1;
  }

  const uniqueTops = [];
  rects.forEach((rect) => {
    const top = Math.round(rect.top * 10) / 10;
    if (!uniqueTops.some((value) => Math.abs(value - top) < 0.2)) {
      uniqueTops.push(top);
    }
  });

  return uniqueTops.length;
}

function clampInfoBounds() {
  const info = state.layout.info;
  const maxInfoX = state.layout.logo.x - 0.5 - MIN_SIZE.info.w;
  info.x = roundMm(clamp(info.x, 0, maxInfoX));
  info.w = roundMm(clamp(info.w, MIN_SIZE.info.w, getInfoMaxWidth()));
}

function getInfoMaxWidth() {
  return state.layout.logo.x - state.layout.info.x - 0.5;
}

function mmToPx(mm) {
  return mm * getPxPerMm();
}

function pxToMm(px) {
  return px / getPxPerMm();
}

function getPxPerMm() {
  const width = dom.sheet?.getBoundingClientRect().width;
  return width ? width / SHEET.width : 96 / 25.4;
}

function toMm(value) {
  return `${roundMm(value)}mm`;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function toNumber(value, fallback) {
  const number = Number.parseFloat(value);
  return Number.isFinite(number) ? number : fallback;
}

function roundMm(value) {
  return Math.round(value * 100) / 100;
}

function roundOne(value) {
  return Math.round(value * 10) / 10;
}

function formatNumber(value) {
  return String(Number.parseFloat(value).toFixed(2)).replace(/\.?0+$/, "");
}

function isTyping(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}
