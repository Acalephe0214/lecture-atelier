/* Browser-local desk geometry only. Never reads or changes course data. */
(function (root) {
  "use strict";
  const STORAGE_KEY = "lecture-atelier.panel-widths.v1";
  const BASE_MINIMUMS = [190, 360, 320];
  const valid = (values) => Array.isArray(values) && values.length === 3 && values.every((n) => typeof n === "number" && Number.isFinite(n) && n > 0);
  function proportions(widths) {
    if (!valid(widths)) return null;
    const total = widths.reduce((sum, width) => sum + width, 0);
    if (!Number.isFinite(total)) return null;
    return widths.map((width) => width / total);
  }
  function readPreference(storage) {
    try {
      const saved = JSON.parse(storage.getItem(STORAGE_KEY));
      return saved && saved.version === 1 ? proportions(saved.widths) : null;
    } catch (_) { return null; }
  }
  function writePreference(storage, widths) {
    try {
      const normalized = proportions(widths);
      if (normalized) storage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, widths: normalized }));
      else storage.removeItem(STORAGE_KEY);
    } catch (_) { /* Resizing still works when browser storage is unavailable. */ }
  }
  function minimums(total) {
    const scale = Math.min(1, Math.max(0, total) / BASE_MINIMUMS.reduce((a, b) => a + b, 0));
    return BASE_MINIMUMS.map((width) => width * scale);
  }
  function fitWidths(preference, total) {
    if (!Number.isFinite(total) || total <= 0) return [0, 0, 0];
    const weights = proportions(preference) || [0.2, 0.43, 0.37];
    const mins = minimums(total);
    const slack = weights.map((weight, index) => Math.max(0, weight * total - mins[index]));
    const remaining = Math.max(0, total - mins.reduce((a, b) => a + b, 0));
    const slackTotal = slack.reduce((a, b) => a + b, 0);
    return mins.map((width, index) => width + (slackTotal ? remaining * slack[index] / slackTotal : remaining / 3));
  }
  function moveDivider(widths, index, delta) {
    if (!valid(widths) || ![0, 1].includes(index) || !Number.isFinite(delta)) return widths.slice();
    const mins = minimums(widths.reduce((a, b) => a + b, 0));
    const next = widths.slice();
    const pair = widths[index] + widths[index + 1];
    next[index] = Math.max(mins[index], Math.min(pair - mins[index + 1], widths[index] + delta));
    next[index + 1] = pair - next[index];
    return next;
  }
  const api = { STORAGE_KEY, proportions, readPreference, writePreference, minimums, fitWidths, moveDivider };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.LecturePanels = api;
  const document = root.document;
  const workspace = document.querySelector(".workspace");
  const panels = ["library-panel", "main-content", "notes-panel"].map((id) => document.getElementById(id));
  const handles = ["resize-library", "resize-notes"].map((id) => document.getElementById(id));
  const resetButton = document.getElementById("reset-layout");
  if (!workspace || panels.some((node) => !node) || handles.some((node) => !node) || !resetButton) return;
  const { t } = root.LectureI18n;
  const desktop = root.matchMedia("(min-width: 1041px)");
  let storage;
  try { storage = root.localStorage; } catch (_) { /* Private / blocked storage. */ }
  let preference = readPreference(storage);
  let widths = [];
  let drag = null;
  let frame = 0;
  function measure() { return panels.map((node) => node.getBoundingClientRect().width); }
  function updateHandles() {
    const origin = workspace.getBoundingClientRect().left;
    const mins = minimums(widths.reduce((a, b) => a + b, 0));
    handles.forEach((handle, index) => {
      const left = panels[index].getBoundingClientRect();
      const right = panels[index + 1].getBoundingClientRect();
      handle.style.left = ((left.right + right.left) / 2 - origin) + "px";
      const space = widths[index] + widths[index + 1] - mins[index] - mins[index + 1];
      handle.setAttribute("aria-valuemin", "0");
      handle.setAttribute("aria-valuemax", "100");
      handle.setAttribute("aria-valuenow", String(Math.round(space > 0 ? Math.max(0, Math.min(100, (widths[index] - mins[index]) / space * 100)) : 50)));
      handle.setAttribute("aria-valuetext", t(index === 0 ? "目录 {0} 像素，正文 {1} 像素" : "正文 {0} 像素，笔记 {1} 像素", Math.round(widths[index]), Math.round(widths[index + 1])));
    });
    panels[1].classList.toggle("is-narrow", widths[1] < 470);
    panels[2].classList.toggle("is-narrow", widths[2] < 390);
  }
  function apply(next) {
    widths = next;
    workspace.style.gridTemplateColumns = widths.map((width) => width.toFixed(3) + "px").join(" ");
    updateHandles();
  }
  function persist() {
    preference = proportions(widths);
    writePreference(storage, preference);
  }
  function finish(accept) {
    if (!drag) return;
    const finished = drag;
    drag = null;
    document.body.classList.remove("is-resizing-panels");
    handles[finished.index].classList.remove("is-dragging");
    if (accept) {
      if (finished.moved) persist();
    } else apply(finished.widths);
    if (handles[finished.index].hasPointerCapture(finished.pointerId)) handles[finished.index].releasePointerCapture(finished.pointerId);
  }
  function render() {
    finish(false);
    workspace.style.removeProperty("grid-template-columns");
    resetButton.hidden = !desktop.matches;
    workspace.dataset.panelsReady = desktop.matches ? "true" : "false";
    panels.forEach((panel) => panel.classList.remove("is-narrow"));
    if (!desktop.matches) return;
    const defaults = measure();
    const total = defaults.reduce((a, b) => a + b, 0);
    workspace.style.setProperty("--panel-bottom-space", root.getComputedStyle(workspace).paddingBottom);
    if (preference) apply(fitWidths(preference, total));
    else { widths = defaults; updateHandles(); }
  }
  function scheduleRender() {
    if (frame) return;
    frame = root.requestAnimationFrame(() => { frame = 0; render(); });
  }
  function reset() {
    finish(false);
    preference = null;
    writePreference(storage, null);
    render();
    document.getElementById("layout-announcement").textContent = t("已恢复默认布局。");
  }
  handles.forEach((handle, index) => {
    handle.dataset.hint = t("拖动调整 · 双击恢复");
    handle.addEventListener("pointerdown", (event) => {
      if (!desktop.matches || drag || event.button !== 0) return;
      event.preventDefault();
      handle.focus({ preventScroll: true });
      widths = measure();
      drag = { index, pointerId: event.pointerId, x: event.clientX, widths: widths.slice(), moved: false };
      handle.setPointerCapture(event.pointerId);
      document.body.classList.add("is-resizing-panels");
      handle.classList.add("is-dragging");
    });
    handle.addEventListener("lostpointercapture", () => finish(false));
    handle.addEventListener("dblclick", reset);
    handle.addEventListener("keydown", (event) => {
      if (!desktop.matches) return;
      if (event.key === "Escape" && drag) { event.preventDefault(); finish(false); return; }
      if (event.key === "Home") { event.preventDefault(); reset(); return; }
      if (!["ArrowLeft", "ArrowRight"].includes(event.key) || drag) return;
      event.preventDefault();
      apply(moveDivider(measure(), index, (event.key === "ArrowRight" ? 1 : -1) * (event.shiftKey ? 40 : 12)));
      persist();
    });
  });
  root.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const delta = event.clientX - drag.x;
    drag.moved = drag.moved || Math.abs(delta) > 1;
    apply(moveDivider(drag.widths, drag.index, delta));
  });
  root.addEventListener("pointerup", (event) => { if (drag && event.pointerId === drag.pointerId) finish(true); });
  root.addEventListener("pointercancel", (event) => { if (drag && event.pointerId === drag.pointerId) finish(false); });
  root.addEventListener("blur", () => finish(false));
  resetButton.addEventListener("click", reset);
  root.addEventListener("resize", scheduleRender);
  desktop.addEventListener("change", scheduleRender);
  if (root.ResizeObserver) new root.ResizeObserver(scheduleRender).observe(workspace);
  render();
})(typeof window === "undefined" ? {} : window);
