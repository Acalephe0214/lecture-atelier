"use strict";

(() => {
  const I18N = window.LectureI18n;
  const { t, tt } = I18N;
  const $ = (id) => document.getElementById(id);
  $("export-format").insertBefore(option("docx", t("Word 总览与笔记")), $("export-format").options[1]);
  const categories = { question: t("核心问题"), concept: t("概念"), argument: t("论证"), example: t("例子"), objection: t("反对意见"), comment: t("课堂评论"), review: t("待核对"), decision: t("明确决议"), action: t("待办事项"), disagreement: t("讨论分歧") };
  const statuses = { unreviewed: t("未核查"), verified: t("已核查"), needs_review: t("待复核") };
  const state = { courses: [], lectures: [], settings: { llm: {}, asr: {}, glossary: [] }, courseId: "all", lecture: null, busy: false, loading: false, selectedSegment: null, audioVariant: "original", playbackStarted: false, dockDismissed: false };
  let audioLoadSequence = 0;
  let seekSequence = 0;
  let requestSequence = 0;
  let modalDirty = false;
  let modalBusy = false;
  let modalAction = null;
  let modalReturnFocus = null;
  let noticeTimer;
  let highlightTimer;
  let pendingConfirmation = null;
  let jobTimer;
  let localJob = null;
  let profiles = [];
  let outputLanguages = [{id:"zh",native:"中文"}];
  let denoiseTimer;
  let denoiseJob = null;
  let repairJob = null;
  let repairTimer;
  let repairEpoch = 0;
  const repairApplying = new Set();
  let noteJob = null;
  let noteJobTimer;
  let notesView = "overview";
  let deliveryTools;
  let revisionTools;
  let languages = { common: [{id:"auto",label:t("自动检测")},{id:"zh",label:t("中文")},{id:"en",label:t("英语")},{id:"zh_en",label:t("中英混合")},{id:"vi",label:t("越南语")},{id:"fr",label:t("法语")},{id:"de",label:t("德语")},{id:"ja",label:t("日语")}], codes: [] };

  function confirmAction(message) {
    if (pendingConfirmation) return Promise.resolve(false);
    const dialog = $("confirm-dialog");
    const returnFocus = document.activeElement;
    $("confirm-message").textContent = message;
    return new Promise((resolve) => {
      pendingConfirmation = (accepted) => {
        dialog.close();
        pendingConfirmation = null;
        if (returnFocus && returnFocus.isConnected) returnFocus.focus();
        resolve(accepted);
      };
      dialog.showModal();
      $("confirm-cancel").focus();
    });
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function button(text, className, handler) {
    const node = el("button", className, text);
    node.type = "button";
    if (handler) node.addEventListener("click", handler);
    return node;
  }
  function option(value, label) {
    const node = el("option", "", label);
    node.value = value;
    return node;
  }
  function timeLabel(seconds) {
    if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return t("未标注时间");
    const whole = Math.max(0, Math.floor(Number(seconds)));
    const h = Math.floor(whole / 3600);
    const m = Math.floor((whole % 3600) / 60);
    const s = whole % 60;
    return (h ? String(h).padStart(2, "0") + ":" : "") + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }
  function dateLabel(date) {
    if (!date) return t("日期未填写");
    const parsed = new Date(date + "T12:00:00");
    return Number.isNaN(parsed.getTime()) ? date : parsed.toLocaleDateString(I18N.locale, { year: "numeric", month: "long", day: "numeric" });
  }
  function today() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  function courseFor(id) { return state.courses.find((course) => String(course.id) === String(id)); }
  function statusTag(status) { return el("span", "status-tag " + (status || "unreviewed"), statuses[status] || t("未核查")); }

  async function api(path, method = "GET", body, extraHeaders = {}) {
    const headers = { ...extraHeaders };
    const options = { method, headers, credentials: "same-origin" };
    if (body !== undefined) {
      if (body instanceof Blob) options.body = body;
      else { options.body = JSON.stringify(body); headers["Content-Type"] = "application/json"; }
    }
    let response;
    try { response = await fetch(path, options); }
    catch (_) { throw new Error(t("无法连接本地服务。请检查启动终端是否仍在运行，再重试。")); }
    let result;
    try { result = await response.json(); }
    catch (_) { throw new Error(t("服务返回了无法读取的结果，请检查本地服务并重试。")); }
    if (!response.ok) throw new Error(result.error || tt`请求未完成（${response.status}），请重试。`);
    return result;
  }
  function notify(message, isError = false, persistent = false) {
    window.clearTimeout(noticeTimer);
    const container = $("notice");
    const content=el("span", ""); I18N.renderDiagnostic(content,message);
    container.replaceChildren(content, button("×", "", () => { container.hidden = true; }));
    container.lastChild.setAttribute("aria-label", t("关闭提示"));
    container.className = "notice" + (isError ? " error" : "");
    container.hidden = false;
    if (!persistent) noticeTimer = window.setTimeout(() => { container.hidden = true; }, isError ? 15000 : 8000);
  }
  function setBusy(value) {
    state.busy = value;
    document.querySelector(".workspace").setAttribute("aria-busy", value ? "true" : "false");
    renderControls();
  }
  async function runAction(target, busyText, action) {
    if (state.busy) return;
    const previous = target ? target.textContent : "";
    setBusy(true);
    if (target) target.textContent = busyText;
    try { await action(); }
    catch (error) { notify(error.message || t("操作失败，请重试。"), true, true); }
    finally {
      if (target && target.textContent === busyText) target.textContent = previous;
      setBusy(false);
    }
  }
  async function refreshState() {
    const data = await api("/api/state");
    state.courses = data.courses || [];
    state.lectures = data.lectures || [];
    state.settings = data.settings || { llm: {}, asr: {}, glossary: [] };
    profiles = ((data.workflow_catalog || {}).profiles || []).map(row => ({...row,label:t(row.label),description:t(row.description)}));
    outputLanguages = data.workflow_catalog?.output_languages || outputLanguages;
    languages = data.language_catalog || languages;
    languages = {...languages,common:languages.common.map(row=>({...row,label:t(row.label)})),notice:t(languages.notice || "")};
    renderLibrary();
    renderControls();
  }
  async function updateDetail(detail) {
    if (!state.lecture || String(state.lecture.id) === String(detail.id)) {
      repairJob = detail.local_repair_state || null;
      state.lecture = detail;
      renderLecture();
    }
    await refreshState();
  }
  function switchView(view) {
    document.querySelector(".workspace").dataset.mobileView = view;
    document.querySelectorAll(".mobile-tabs button").forEach((node) => {
      const active = node.dataset.view === view;
      node.classList.toggle("active", active);
      node.setAttribute("aria-current", active ? "page" : "false");
    });
    if (window.matchMedia("(max-width: 1040px)").matches) window.scrollTo({ top: 0, behavior: "instant" });
  }
  function courseLabel(course) {
    return course.id === "course-sample" && course.name === "示例课程" ? t("示例课程") : course.name;
  }

  function renderLibrary() {
    $("library-panel").classList.toggle("has-lectures", state.lectures.length > 0);
    const list = $("course-list");
    list.replaceChildren();
    const courseItems = [{ id: "all", name: t("全部课程") }, ...state.courses];
    for (const [courseIndex, course] of courseItems.entries()) {
      const count = state.lectures.filter((item) => course.id === "all" || String(item.course_id) === String(course.id)).length;
      const item = button("", "course-button" + (String(state.courseId) === String(course.id) ? " active" : ""), () => {
        state.courseId = course.id;
        renderLibrary();
      });
      item.dataset.testid = `course-${course.id}`;
      item.setAttribute("aria-pressed", String(state.courseId) === String(course.id) ? "true" : "false");
      const code = el("span", "course-code", String(courseIndex).padStart(2, "0"));
      code.setAttribute("aria-hidden", "true");
      item.append(code, el("span", "course-name", courseLabel(course)), el("span", "course-number", count));
      list.append(item);
    }
    const search = $("lecture-search").value.trim().toLocaleLowerCase();
    const lectures = state.lectures.filter((item) => (state.courseId === "all" || String(item.course_id) === String(state.courseId)) && item.title.toLocaleLowerCase().includes(search));
    $("lecture-count").textContent = tt`${lectures.length} 个课次`;
    const lectureList = $("lecture-list");
    lectureList.replaceChildren();
    if (!lectures.length) lectureList.append(el("div", "list-empty", search ? t("没有匹配的课次，试试其他关键词。") : t("这里还没有课次。新建一节课，或打开虚构示例。")));
    for (const lecture of lectures) {
      const item = button("", "lecture-button" + (state.lecture && String(state.lecture.id) === String(lecture.id) ? " active" : ""), () => openLecture(lecture.id));
      item.dataset.lectureId = lecture.id;
      item.dataset.testid = `lecture-${lecture.id}`;
      const title = el("strong", "", lecture.title);
      if (lecture.is_demo) title.append(el("span", "demo-tag", t("虚构示例")));
      const date = lecture.date ? lecture.date.replaceAll("-", ".") : t("日期未填写");
      item.append(title, el("small", "", tt`${date} · ${lecture.segment_count || 0} 段原文 · ${lecture.note_count || 0} 条笔记`));
      lectureList.append(item);
    }
    if (window.matchMedia("(min-width: 1041px)").matches) {
      window.requestAnimationFrame(() => {
        const active = lectureList.querySelector(".lecture-button.active");
        if (active) active.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
      });
    }
  }
  async function openLecture(id) {
    if (state.busy) { notify(t("当前操作尚未结束，请稍候再切换课次。")); return; }
    const sequence = ++requestSequence;
    state.loading = true;
    renderControls();
    try {
      const lecture = await api(`/api/lectures/${encodeURIComponent(id)}`);
      if (sequence !== requestSequence) return;
      state.lecture = lecture;
      localJob = null;
      denoiseJob = null;
      repairJob = null;
      repairEpoch += 1;
      noteJob = null;
      notesView = "overview";
      window.clearTimeout(noteJobTimer);
      window.clearTimeout(repairTimer);
      window.clearTimeout(jobTimer);
      window.clearTimeout(denoiseTimer);
      state.selectedSegment = null;
      $("segment-search").value = "";
      $("category-filter").value = "all";
      $("review-filter").value = "all";
      renderLibrary();
      renderLecture();
      pollLocalJob(id);
      pollDenoise(id);
      pollRepair(id);
      pollNoteJob(id);
      switchView("transcript");
    } catch (error) { notify(error.message, true, true); }
    finally { if (sequence === requestSequence) { state.loading = false; renderControls(); } }
  }
  function renderControls() {
    const available = !!state.lecture && !state.busy && !state.loading;
    const segments = state.lecture ? state.lecture.segments || [] : [];
    for (const id of ["edit-lecture", "import-button", "audio-button", "export-format", "sync-sources", "scene-select", "workflow-settings", "output-language", "output-language-settings"]) $(id).disabled = !available;
    $("add-note").disabled = !available || !segments.length;
    $("archived-notes").disabled = !available;
    const sourceFiles = state.lecture ? state.lecture.source_files || [] : [];
    const draftStale = sourceFiles.some((source) => source.kind === "transcript" && source.state !== "available");
    $("local-generate").disabled = !available || !segments.length || draftStale;
    $("llm-generate").disabled = !available || !segments.length || draftStale;
    const generatingNotes = noteJob && ["queued", "running"].includes(noteJob.status);
    if (generatingNotes) for (const id of ["scene-select", "workflow-settings", "output-language", "output-language-settings"]) $(id).disabled = true;
    if (generatingNotes) $("llm-generate").disabled = true;
    $("overview-generate").disabled = !available || !(state.lecture.notes || []).length || draftStale || generatingNotes;
    $("local-generate").disabled = $("local-generate").disabled || generatingNotes;
    $("transcribe-button").disabled = !available || !state.lecture.audio || !!localJob && ["queued", "running", "cancelling"].includes(localJob.status);
    $("ai-correct").disabled = !available || !segments.length || draftStale;
    $("review-corrections").disabled = !available;
    $("audio-version").disabled = !available || !state.lecture.audio;
    $("generate-denoised").disabled = !available || !state.lecture.audio || denoiseJob?.status === "running";
    $("resume-local-asr").disabled = !available;
    $("restart-local-asr").disabled = !available;
    for (const id of ["add-course", "new-lecture", "empty-new-lecture", "demo-button", "settings-button"]) $(id).disabled = state.busy || state.loading;
    const llm = state.settings.llm || {};
    const asr = state.settings.asr || {};
    $("model-status").textContent = (llm.configured ? tt`模型接口已配置：${llm.model}（连接未验证）` : t("模型接口未配置")) + t(" · 本地摘录无需 API");
    $("transcribe-button").title = t("本地 Whisper / 通义听悟网页协助 / 已配置 ASR 接口");
    deliveryTools?.refresh();
    revisionTools?.refresh();
  }
  function renderLecture() {
    const lecture = state.lecture;
    $("transcript-empty").hidden = !!lecture;
    $("lecture-content").hidden = !lecture;
    if (!lecture) { renderNotes(); renderControls(); return; }
    const course = courseFor(lecture.course_id);
    $("lecture-course").textContent = course ? courseLabel(course) : t("未命名课程");
    $("lecture-title").textContent = lecture.title;
    const config = lecture.workflow || { scene: "class" };
    $("scene-select").value = config.scene;
    $("output-language").replaceChildren(...outputLanguages.map(row => option(row.id, row.native)));
    $("output-language").value = config.output_language || "zh";
    $("scene-description").textContent = (profiles.find((profile) => profile.id === config.scene) || {}).description || t("选择整理用途，并可编辑自己的提示词。");
    const source = lecture.transcript_source;
    $("transcript-provenance").textContent = source ? tt`文字稿来源：${t(source.label)} · 未自动回听核验` : lecture.segments.length ? t("已有文字稿 · 不会默认重新识别") : t("尚未导入文字稿");
    const proposal = lecture.correction_proposal;
    $("review-corrections").hidden = !proposal || !proposal.corrections.length;
    $("review-corrections").textContent = tt`查看校对建议 (${proposal ? proposal.corrections.length : 0})`;
    renderJob();
    renderAsrReport();
    const langSelect = $("recording-language");
    const chosen = lecture.asr_language || state.settings.local_asr?.language || "auto";
    langSelect.replaceChildren(...languages.common.map(row => option(row.id, row.label)), option("mixed", t("多语言课程（选择组合…）")));
    if (!languages.common.some(row => row.id === chosen)) langSelect.append(option(chosen, recordingLanguageLabel(chosen)));
    langSelect.value = chosen;
    const meta = $("lecture-meta");
    meta.replaceChildren(el("span", "", dateLabel(lecture.date)), el("span", "", lecture.duration ? tt`材料时间线 ${timeLabel(lecture.duration)}` : t("未提供可靠时长")));
    if (lecture.is_demo) meta.append(el("span", "demo-pill", t("虚构示例 · 非真实课堂")));
    const player = $("audio-player");
    $("audio-container").hidden = !lecture.audio;
    $("audio-button").textContent = lecture.audio ? t("替换录音") : t("＋ 添加录音");
    if (lecture.audio) {
      $("audio-filename").textContent = lecture.audio.name;
      const sameLecture = player.dataset.lectureId === String(lecture.id);
      if (!sameLecture) {
        player.pause();
        state.audioVariant = "original";
        state.playbackStarted = false;
        state.dockDismissed = false;
        seekSequence += 1;
        player.dataset.lectureId = String(lecture.id);
      }
      renderAudioVersions();
      loadAudioVersion(sameLecture ? player.currentTime || 0 : 0, sameLecture && !player.paused);
      renderDenoise();
    } else {
      audioLoadSequence += 1;
      seekSequence += 1;
      state.playbackStarted = false;
      player.pause();
      player.removeAttribute("src");
      player.dataset.identity = "";
      $("playback-dock").hidden = true;
    }
    const warnings = $("lecture-warnings");
    warnings.replaceChildren();
    for (const warning of lecture.warnings || []) { const line=el("p", ""); I18N.renderDiagnostic(line,warning); warnings.append(line); }
    warnings.hidden = !(lecture.warnings || []).length;
    renderLocalSources();
    renderSegments();
    renderNotes();
    renderControls();
  }
  function audioVersions() {
    if (!state.lecture || !state.lecture.audio) return [];
    return state.lecture.audio_versions || [{ id: "original", label: t("原录音"), available: true,
      url: state.lecture.audio.url || `/api/lectures/${encodeURIComponent(state.lecture.id)}/audio` }];
  }
  function renderAudioVersions() {
    const versions = audioVersions();
    if (!versions.some((version) => version.id === state.audioVariant && version.available)) state.audioVariant = "original";
    const select = $("audio-version");
    select.replaceChildren();
    for (const version of versions) {
      const item = option(version.id, t(version.label) + (version.available ? "" : t("（缓存失效）")));
      item.disabled = !version.available;
      select.append(item);
    }
    if (!versions.some((version) => version.id === "denoised")) {
      const unavailable = option("denoised", t("降噪版（尚未生成）"));
      unavailable.disabled = true;
      select.append(unavailable);
    }
    select.value = state.audioVariant;
    if (!versions.some((version) => version.id === "keyboard")) {
      const pending = option("keyboard", t("键盘点击抑制（尚未生成）")); pending.disabled = true; select.append(pending);
    }
    $("audio-version-note").textContent = state.audioVariant === "keyboard" ? t("实验性瞬态点击抑制（FFmpeg adeclick），不是键盘声专用神经模型。可能损伤辅音，无法保证去掉与说话重叠的敲击声；请与原音比较。") : state.audioVariant === "denoised"
      ? t("降噪听课版可能改变音色；未裁剪或变速，可切回原音。Whisper 使用原录音，试听选择不会改变转写输入。")
      : /\.(qta|qat|qt|mov)$/i.test(state.lecture.audio?.name || "")
        ? t("QuickTime 原件已保留。本地转写与听课版使用第一条音轨，不还原空间效果或额外音层。若浏览器不能直接播放，可本机生成听课版，或从语音备忘录重新导出 M4A。")
        : t("原录音始终保留。可在本机生成独立降噪听课版；切换试听不会改动转写输入或原文件。");
    const denoised = versions.find((version) => version.id === "denoised" && version.available);
    $("generate-denoised").textContent = denoised ? t("重新生成听课版") : t("生成降噪听课版");
  }
  function loadAudioVersion(time = 0, resume = false) {
    const lecture = state.lecture;
    if (!lecture || !lecture.audio) return;
    const version = audioVersions().find((item) => item.id === state.audioVariant && item.available);
    if (!version) return;
    const player = $("audio-player");
    const identity = `${lecture.id}:${lecture.audio.name}:${lecture.audio.size}:${lecture.audio.revision || ""}:${version.id}:${version.revision || ""}`;
    if (player.dataset.identity === identity) return;
    const sequence = ++audioLoadSequence;
    seekSequence += 1;
    player.pause();
    player.dataset.identity = identity;
    player.addEventListener("loadedmetadata", () => {
      if (sequence !== audioLoadSequence) return;
      player.currentTime = Number.isFinite(player.duration) ? Math.min(time, Math.max(0, player.duration - .01)) : time;
      if (resume) player.play().catch(() => notify(t("切换后未自动播放，请点“继续”。")));
      updatePlayingSegment();
    }, { once: true });
    player.src = version.url;
    player.load();
  }
  function switchAudioVersion() {
    if (!state.lecture || state.busy) return;
    const player = $("audio-player");
    const time = player.currentTime || 0;
    const resume = !player.paused;
    state.audioVariant = $("audio-version").value;
    renderAudioVersions();
    loadAudioVersion(time, resume);
  }
  function renderLocalSources() {
    const lecture = state.lecture;
    const files = lecture ? lecture.source_files || [] : [];
    $("linked-source-card").hidden = !files.length;
    const stale = files.some((file) => file.state !== "available");
    $("source-index-summary").textContent = stale ? t("来源待检查") : tt`${files.length} 份文件已连接`;
    $("linked-source-card").classList.toggle("stale", stale);
    const list = $("linked-source-list");
    list.replaceChildren();
    const labels = { audio: t("录音"), transcript: t("文字稿"), reference: t("附记") };
    const status = { available: t("已连接"), changed: t("原文件已更新 · 待同步"), missing: t("文件已移走或不可读") };
    for (const file of files) {
      const row = el("div", "linked-source-row " + file.state);
      row.append(el("span", "source-kind", labels[file.kind] || t("来源")), el("span", "source-filename", file.name), el("span", "source-file-state", status[file.state] || t("待检查")));
      list.append(row);
    }
    const context = lecture ? lecture.source_context || {} : {};
    const body = $("source-context-body");
    body.replaceChildren();
    for (const [title, text] of [[t("原稿说明及内容导航"), context.preamble], [t("整理附记（非逐字原话）"), context.appendix], ...(context.references || []).map((reference) => [reference.name, reference.text])]) {
      if (!text) continue;
      body.append(el("h4", "", title), el("pre", "", text));
    }
    $("source-context-details").hidden = !body.childNodes.length;
  }
  async function syncLocalSources() {
    if (!state.lecture || state.busy) return;
    const identity = state.lecture.id;
    await runAction($("sync-sources"), t("检查来源中…"), async () => {
      const latest = await api(`/api/lectures/${encodeURIComponent(identity)}`);
      await updateDetail(latest);
      const draftChanged = (latest.source_files || []).some((source) => source.kind === "transcript" && source.state === "changed");
      let accepted = false;
      if (draftChanged && (latest.notes || []).length) {
        accepted = await confirmAction(t("原文字稿已更新。同步会重新解析段落，并把现有笔记保留到归档中，防止旧引用连到错误的新段落。不会改动本地原文件。是否继续？"));
        if (!accepted) return;
      }
      const detail = await api(`/api/lectures/${encodeURIComponent(identity)}/sources/sync`, "POST", { confirm_replace_transcript: accepted });
      await updateDetail(detail);
      notify(t("本地索引已同步。原文件未被修改，没有发送到任何外部接口。"));
    });
  }
  function renderSegments() {
    const lecture = state.lecture;
    const list = $("segment-list");
    list.replaceChildren();
    if (!lecture) return;
    const segments = lecture.segments || [];
    const term = $("segment-search").value.trim();
    const filtered = segments.filter((segment) => !term || segment.text.toLocaleLowerCase().includes(term.toLocaleLowerCase()));
    $("segment-count").textContent = segments.length;
    if (!segments.length) {
      const empty = el("div", "no-material");
      empty.append(el("p", "", t("还没有转写稿。可以导入已有稿，\n或添加录音后选择本地识别、通义听悟网页协助。")), button(t("导入第一份材料"), "button secondary", showImport));
      list.append(empty);
      return;
    }
    if (!filtered.length) list.append(el("div", "no-material", t("未找到匹配原文。修改关键词或清空搜索后重试。")));
    if ($("transcript-view").value === "paragraphs") {
      const groups = window.LectureParagraphs.group(segments).filter(rows => !term || rows.some(row => row.text.toLocaleLowerCase().includes(term.toLocaleLowerCase())));
      $("segment-count").textContent = tt`${groups.length} 段 / ${segments.length} 句`;
      for (const rows of groups) {
        const first = rows[0];
        const card = el("article", "paragraph-card" + (first.asr_issue ? " asr-gap" : ""));
        const top = el("div", "segment-topline");
        const play = button(t("▶ 播放"), "segment-play-button", () => {
          const active = window.LecturePlayback.segmentAt(segments, $("audio-player").currentTime);
          toggleSegmentPlayback(active && rows.some(row => row.id === active.id) ? active : first);
        });
        play.dataset.playSegmentId = first.id; play.dataset.groupIds = rows.map(row => row.id).join(" ");
        play.disabled = !lecture.audio || !Number.isFinite(first.start);
        const details = el("details", "paragraph-sources");
        details.append(el("summary", "", tt`逐句校对 · ${rows.length} 条来源`));
        top.append(button(timeLabel(first.start), "time-button", () => seekAudio(first)), play);
        top.append(button(t("边听边改"), "segment-edit-button paragraph-edit-button", () => first.asr_issue ? editSegment(first) : editParagraph(rows)));
        if (first.asr_issue) top.append(el("span", "asr-gap-label", t("转写缺口 · 非原话")));
        const text = el("p", "segment-text paragraph-text");
        let before = "";
        for (const segment of rows) {
          if (before) text.append(document.createTextNode(window.LectureParagraphs.separator(before, segment.text)));
          const span = el("span", "source-sentence"); span.id = `segment-${segment.id}`;
          span.dataset.testid = `segment-${segment.id}`;
          if (state.selectedSegment === segment.id) span.classList.add("jump-highlight");
          if (segment.asr_issue || !revisionTools?.paint(span, segment, term)) appendHighlighted(span, I18N.sourceText(segment), term);
          text.append(span); before = I18N.sourceText(segment);
          const line = el("div", "paragraph-source-row");
          line.append(el("small", "", `${timeLabel(segment.start)} · ${segment.id}`), button(segment.asr_issue ? t("回听补字") : t("校对"), "segment-edit-button", () => editSegment(segment)), button(t("换策略补转"), "text-button", () => startRepair([segment.id])), el("p", "", I18N.sourceText(segment)));
          details.append(line);
        }
        card.append(top, text, details); list.append(card);
      }
      updatePlayingSegment();
      return;
    }
    for (const segment of filtered) {
      const card = el("article", "segment-card");
      card.id = `segment-${segment.id}`;
      card.dataset.segmentId = segment.id;
      card.dataset.testid = `segment-${segment.id}`;
      if (state.selectedSegment === segment.id) card.classList.add("jump-highlight");
      if (segment.asr_issue) card.classList.add("asr-gap");
      const top = el("div", "segment-topline");
      const stamp = button(timeLabel(segment.start), "time-button", () => seekAudio(segment));
      stamp.title = segment.start === null ? t("这段原文没有真实时间戳") : t("跳到录音对应时间");
      stamp.setAttribute("aria-label", tt`原文 ${segment.id}，${timeLabel(segment.start)}，定位录音`);
      const transport = button(t("▶ 播放"), "segment-play-button", () => toggleSegmentPlayback(segment));
      transport.dataset.playSegmentId = segment.id;
      transport.disabled = !lecture.audio || segment.start === null || segment.start === undefined;
      transport.title = t("从这一段开始播放；暂停后可继续，不会重新跳回段首。");
      top.append(stamp, transport, el("span", "segment-id", segment.id), statusTag(segment.review_status), button(t("校对"), "segment-edit-button", () => editSegment(segment)));
      top.append(button(t("局部补转"), "text-button", () => startRepair([segment.id])));
      const text = el("p", "segment-text");
      if (segment.asr_issue || !revisionTools?.paint(text, segment, term)) appendHighlighted(text, I18N.sourceText(segment), term);
      card.append(top, text);
      if (segment.asr_issue) card.insertBefore(el("div", "asr-gap-label", t("转写缺口 · 系统标记，不是录音原文")), text);
      if (segment.speaker) card.insertBefore(el("div", "speaker-label", tt`${segment.speaker} · 原始标签，身份未核实`), text);
      if (segment.original_text !== undefined && segment.original_text !== segment.text) {
        const details = el("details", "original-text");
        details.append(el("summary", "", t("查看未修改的原始转写")), el("p", "", I18N.sourceText(segment,segment.original_text)));
        card.append(details);
      }
      list.append(card);
    }
    updatePlayingSegment();
  }
  function appendHighlighted(parent, text, term) {
    if (!term) { parent.textContent = text; return; }
    const normalized = text.toLocaleLowerCase();
    const needle = term.toLocaleLowerCase();
    let last = 0;
    let index;
    while ((index = normalized.indexOf(needle, last)) !== -1) {
      parent.append(document.createTextNode(text.slice(last, index)), el("mark", "", text.slice(index, index + term.length)));
      last = index + term.length;
    }
    parent.append(document.createTextNode(text.slice(last)));
  }
  function renderNotes() {
    const lecture = state.lecture;
    const list = $("notes-list");
    list.replaceChildren();
    const notes = lecture ? lecture.notes || [] : [];
    const archived = lecture ? lecture.deleted_notes || [] : [];
    $("archived-notes").hidden = !archived.length;
    $("archived-notes").textContent = tt`恢复归档 (${archived.length})`;
    $("note-count").textContent = lecture ? notes.length : "";
    const generation = lecture && lecture.generation;
    let label = t("每条重要笔记，都应能回到原文。");
    if (!lecture) label = t("先选择一节课");
    else if (generation && generation.mode === "local") label = t("本地原句摘录 · 未使用模型，不等同于智能总结");
    else if (generation && generation.mode === "llm") label = tt`${t(generation.scene_label) || t("模型整理")} · ${generation.model || t("已配置模型")} · 内容默认未核查`;
    else if (notes.length) label = t("手动笔记 · 核查状态由你确认");
    if (generation && generation.mode === "llm" && generation.scene && generation.scene !== (lecture.workflow || {}).scene) label += t("（当前用途已切换，旧笔记未重做）");
    $("generation-label").textContent = label;
    renderOverview();
    setNotesView(notesView);
    renderNoteJob();
    const category = $("category-filter").value;
    const review = $("review-filter").value;
    const filtered = notes.filter((note) => (category === "all" || note.category === category) && (review === "all" || note.review_status === review));
    if (!filtered.length) {
      const empty = el("div", "notes-empty");
      const hasSources = !!lecture && (lecture.segments || []).length > 0;
      empty.append(el("span", "empty-symbol", "⌁"), el("h3", "", notes.length ? t("这里暂时没有匹配笔记") : hasSources ? t("先读一段，再记一笔。") : t("让思路，慢慢浮现。")), el("p", "", !lecture ? t("选择或新建一节课。\n原文与结构化笔记将在这里相遇。") : notes.length ? t("更换类别或核查状态，再看看。") : hasSources ? t("原文已经就位，可以手动记录你的理解；\n也可以本地摘录，或配置模型后整理。\n重要内容请结合录音核对。") : t("先导入转写稿，再做本地原句摘录；\n也可以配置模型，或手动记录你的理解。")));
      list.append(empty);
      return;
    }
    for (const [noteIndex, note] of filtered.entries()) {
      const card = el("article", "note-card");
      card.dataset.testid = `note-${note.id}`;
      card.dataset.category = note.category;
      const top = el("div", "note-topline");
      const number = el("span", "note-index", String(noteIndex + 1).padStart(2, "0"));
      number.setAttribute("aria-hidden", "true");
      top.append(number, el("span", "category-label", categories[note.category] || note.category), statusTag(note.review_status));
      card.append(top, el("h3", "", note.title), el("div", "note-body", note.content));
      const sources = el("div", "note-sources");
      for (const id of note.source_ids || []) {
        const segment = (lecture.segments || []).find((item) => item.id === id);
        const source = button(`${timeLabel(segment ? segment.start : null)} · ${id} ↗`, "source-link", () => jumpToSource(id));
        source.dataset.sourceId = id;
        source.title = segment ? segment.text.slice(0, 180) : t("来源不存在，请重新核查");
        sources.append(source);
      }
      if (!(note.source_ids || []).length) sources.append(el("span", "status-tag needs_review", t("尚未关联来源")));
      card.append(sources);
      const footer = el("div", "note-footer");
      footer.append(button(t("编辑笔记"), "text-button", () => editNote(note)), button(note.review_status === "verified" ? t("标为待复核") : t("标为已核查"), "text-button", (event) => changeNoteStatus(note, event.currentTarget)), button(t("归档"), "text-button archive-button", (event) => archiveNote(note, event.currentTarget)));
      if (note.user_edited) footer.append(el("span", "edited-indicator", t("已手动编辑")));
      card.append(footer);
      list.append(card);
    }
  }
  function setNotesView(view) {
    notesView = view;
    $("notes-panel").dataset.notesView = view;
    $("overview-content").hidden = view !== "overview";
    $("notes-list").hidden = view !== "details";
    $("overview-tab").setAttribute("aria-selected", view === "overview" ? "true" : "false");
    $("detail-tab").setAttribute("aria-selected", view === "details" ? "true" : "false");
    $("overview-tab").tabIndex = view === "overview" ? 0 : -1;
    $("detail-tab").tabIndex = view === "details" ? 0 : -1;
  }
  function overviewSources(row) {
    const links = el("div", "note-sources");
    for (const id of row.source_ids || []) {
      const segment = state.lecture.segments.find((item) => item.id === id);
      links.append(button(`${timeLabel(segment?.start)} · ${id} ↗`, "source-link", () => jumpToSource(id)));
    }
    return links;
  }
  function renderOverview() {
    const container = $("overview-content");
    container.replaceChildren();
    const lecture = state.lecture;
    const overview = lecture?.overview;
    if (!overview) {
      const empty = el("div", "notes-empty overview-empty");
      empty.append(el("span", "eyebrow", "THE BIG PICTURE"), el("h3", "", t("先看结论，再回到讨论。")), el("p", "", t("AI 整理将先生成详细笔记，再综合整份材料的重点、最终决策、待办与未决问题。原句复制卡片不能代替这一页。")));
      if (lecture?.notes?.length) {
        empty.append(el("p", "overview-absence", t("下方按钮只综合现有详细笔记，不重新生成或删除笔记。若生成失败，这里仍会留空，请查看上方的失败原因。")));
        empty.append(button(t("保留现有笔记，仅补生成总览"), "button secondary", () => generate("overview")));
      }
      container.append(empty);
      return;
    }
    const intro = el("article", "overview-intro");
    intro.append(el("span", "eyebrow", "THE BIG PICTURE"), el("h3", "", t("核心总结")), statusTag(overview.stale ? "needs_review" : "unreviewed"));
    if (noteJob && ["queued", "running"].includes(noteJob.status)) intro.append(el("p", "overview-absence", t("正在生成新版；下方仍为上一次保存的总览，新结果通过校验后才替换。")));
    if (overview.stale) intro.append(el("p", "overview-stale", t("原文、笔记或整理用途已变化。下方总览尚未同步，请核对或重新生成。")));
    intro.append(el("div", "overview-prose", overview.summary.content), overviewSources(overview.summary));
    container.append(intro);
    const meeting = (lecture.generation?.scene || lecture.workflow?.scene) === "meeting";
    const sections = [["decisions", t("最终决策"), t("未提取到有明确原文依据的最终决策。不要把这理解为已达成共识。")], ["actions", t("行动事项"), t("未提取到明确的行动事项；负责人和截止时间不能自动推断。")], ["key_points", t("最重要的信息"), t("暂无单列重点。")], ["open_questions", t("未决问题与风险"), t("未提取到单列未决问题，不代表所有问题已经解决。")]];
    for (const [key, title, empty] of sections) {
      const rows = overview[key] || [];
      if (!meeting && ["decisions", "actions"].includes(key) && !rows.length) continue;
      const section = el("section", "overview-section overview-" + key);
      const heading = el("div", "overview-section-heading");
      heading.append(el("h3", "", title), el("span", "count", rows.length));
      section.append(heading);
      if (!rows.length) section.append(el("p", "overview-absence", empty));
      for (const row of rows) {
        const article = el("article", "overview-item");
        article.append(el("h4", "", row.title), el("div", "overview-prose", row.content));
        if (row.evidence_quote) article.append(el("blockquote", "decision-evidence", row.evidence_quote));
        article.append(overviewSources(row));
        section.append(article);
      }
      container.append(section);
    }
  }
  function renderNoteJob() {
    $("note-job").hidden = !noteJob;
    if (!noteJob) return;
    const active = ["queued", "running"].includes(noteJob.status);
    const phases = {preparing:t("准备材料"), notes:t("逐批生成详细笔记"), overview:t("全局综合与决策核对"), saving:t("验证来源并保存"), completed:t("整理完成")};
    $("note-job-title").textContent = noteJob.status === "failed" ? t("本次整理未完成") : noteJob.status === "interrupted" ? t("上次生成已中断") : phases[noteJob.phase] || t("AI 整理进度");
    $("note-job-elapsed").textContent = tt`已用时 ${Math.floor(noteJob.elapsed_seconds || 0)} 秒`;
    $("note-job-detail").textContent = tt`本阶段 ${noteJob.completed_units || 0} / ${noteJob.total_units || 1} · 已完成请求 ${noteJob.requests_finished || 0}` + (noteJob.synthesis_level ? tt` · 综合第 ${noteJob.synthesis_level} 层` : "");
    $("note-job-progress").max = noteJob.total_units || 1;
    $("note-job-progress").value = noteJob.completed_units || 0;
    $("note-job").classList.toggle("working", active);
    $("note-job").classList.toggle("failed", noteJob.status === "failed");
    $("note-job-policy").hidden = !noteJob.output_budget;
    $("note-job-policy").textContent = noteJob.output_budget ? t("当前总览单次输出额度：") + noteJob.output_budget + t(" token（额度上限，不是预计用量）。") + (noteJob.thinking_disabled ? t("本次总览使用非思考模式。") : "") : "";
    $("note-job-stream").textContent = tt`已收到输出 ${noteJob.output_chars || 0} 字符 · 思考输出 ${noteJob.reasoning_chars || 0} 字符（不是 token）`;
    const usage = noteJob.usage;
    $("note-job-usage").textContent = usage ? tt`已报告 token：输入 ${usage.prompt_tokens ?? t("未报告")} / 输出 ${usage.completion_tokens ?? t("未报告")} / 合计 ${usage.total_tokens ?? t("未报告")}` + tt` · ${noteJob.usage_reports || 0} / ${noteJob.requests_started || 0} 次请求已报告用量` : t("token 用量：接口尚未报告；通常在每次请求结束时返回。");
    I18N.renderDiagnostic($("note-job-message"),noteJob.message || "");
    $("note-job-next").hidden = noteJob.status !== "failed";
    const diagnostics = $("note-job-diagnostics");
    diagnostics.hidden = !noteJob.diagnostics_available;
    if (noteJob.diagnostics_available) diagnostics.href = `/api/lectures/${encodeURIComponent(state.lecture.id)}/notes/jobs/diagnostics`;
    else diagnostics.removeAttribute("href");
  }
  async function pollNoteJob(id) {
    window.clearTimeout(noteJobTimer);
    if (!state.lecture || state.lecture.id !== id) return;
    try {
      const previous = noteJob;
      const result = await api(`/api/lectures/${encodeURIComponent(id)}/notes/jobs`);
      if (state.lecture?.id !== id) return;
      noteJob = result.job;
      renderNoteJob();
      renderControls();
      if (noteJob && ["queued", "running"].includes(noteJob.status)) noteJobTimer = window.setTimeout(() => pollNoteJob(id), 1000);
      else if (noteJob?.status === "completed" && previous?.id === noteJob.id && ["queued", "running"].includes(previous.status)) {
        const detail = await api(`/api/lectures/${encodeURIComponent(id)}`);
        notesView = "overview";
        await updateDetail(detail);
        notify(t("总览与详细笔记已完成。请优先检查最终决策及其原文依据。"));
      }
    } catch (error) {
      if (state.lecture?.id !== id) return;
      $("note-job-message").textContent = t("进度连接暂时中断，正在重连；不会重复提交模型请求。");
      if (noteJob && ["queued", "running"].includes(noteJob.status)) noteJobTimer = window.setTimeout(() => pollNoteJob(id), 3000);
    }
  }
  function jumpToSource(id) {
    const segment = state.lecture && (state.lecture.segments || []).find((item) => item.id === id);
    if (!segment) { notify(t("这条笔记的来源未找到，请编辑并重新关联。"), true); return; }
    $("segment-search").value = "";
    state.selectedSegment = id;
    renderSegments();
    switchView("transcript");
    window.requestAnimationFrame(() => {
      const target = $("segment-" + id);
      if (target) target.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    });
    if (state.lecture.audio && segment.start !== null && segment.start !== undefined) seekAudio(segment, false);
    window.clearTimeout(highlightTimer);
    highlightTimer = window.setTimeout(() => { state.selectedSegment = null; document.querySelectorAll(".jump-highlight").forEach((node) => node.classList.remove("jump-highlight")); }, 5000);
  }
  function seekAudio(segment, play = true) {
    if (!state.lecture || !state.lecture.audio) { if (play) notify(t("尚未添加课堂录音；你仍可以根据这段原文核查笔记。")); return; }
    if (segment.start === null || segment.start === undefined) { notify(t("这份原文没有真实时间戳，不能定位录音。可导入带时间戳的 SRT/VTT。")); return; }
    const player = $("audio-player");
    const sequence = ++seekSequence;
    const seek = () => {
      if (sequence !== seekSequence) return;
      player.currentTime = Number.isFinite(player.duration) ? Math.min(segment.start, Math.max(0, player.duration - 0.01)) : segment.start;
      if (play) {
        state.playbackStarted = true;
        state.dockDismissed = false;
        player.play().catch(() => notify(t("浏览器未开始播放，请点击录音播放器中的播放按钮。")));
      }
      updatePlayingSegment();
    };
    if (player.readyState > 0) seek();
    else player.addEventListener("loadedmetadata", seek, { once: true });
  }
  function toggleSegmentPlayback(segment) {
    const player = $("audio-player");
    const active = window.LecturePlayback.segmentAt(state.lecture.segments || [], player.currentTime);
    const action = window.LecturePlayback.actionFor(segment.id, active ? active.id : null, player.paused, state.playbackStarted && !player.ended);
    if (action === "pause") player.pause();
    else if (action === "resume") {
      state.dockDismissed = false;
      player.play().catch(() => notify(t("未能继续播放，请检查录音文件或手动点击播放器。")));
    } else seekAudio(segment, true);
    updatePlayingSegment();
  }
  function updatePlayingSegment() {
    const player = $("audio-player");
    const lecture = state.lecture;
    if (!lecture) return;
    const current = player.currentTime;
    const active = lecture.audio ? window.LecturePlayback.segmentAt(lecture.segments || [], current) : null;
    document.querySelectorAll(".segment-card").forEach((node) => node.classList.toggle("playing", !player.paused && !!active && node.dataset.segmentId === active.id));
    document.querySelectorAll(".segment-play-button").forEach((node) => {
      const grouped = active && (node.dataset.groupIds || "").split(" ").includes(active.id);
      const action = window.LecturePlayback.actionFor(grouped ? active.id : node.dataset.playSegmentId, active ? active.id : null, player.paused, state.playbackStarted && !player.ended);
      const label = action === "pause" ? t("Ⅱ 暂停") : action === "resume" ? t("▶ 继续") : t("▶ 播放");
      if (node.textContent !== label) node.textContent = label;
      node.setAttribute("aria-label", tt`${action === "pause" ? t("暂停") : action === "resume" ? t("继续") : t("播放")}段落 ${node.dataset.playSegmentId}`);
      node.setAttribute("aria-pressed", action === "pause" ? "true" : "false");
    });
    $("playback-dock").hidden = !lecture.audio || !state.playbackStarted || state.dockDismissed;
    $("dock-lecture").textContent = lecture.title;
    $("dock-time").textContent = timeLabel(current);
    $("dock-toggle").textContent = player.paused ? t("▶ 继续") : t("Ⅱ 暂停");
    $("dock-toggle").setAttribute("aria-label", player.paused ? t("继续播放录音") : t("暂停播放录音"));
  }

  function field(label, control, hint) {
    const wrapper = el("label", "field");
    wrapper.append(el("span", "field-label", label), control);
    if (hint) wrapper.append(el("span", "field-hint", hint));
    return wrapper;
  }
  function input(name, value = "", type = "text", required = false) {
    const node = document.createElement("input");
    node.name = name;
    node.id = "field-" + name;
    node.type = type;
    node.value = value;
    node.required = required;
    if (type === "text") node.maxLength = 500;
    return node;
  }
  function textarea(name, value = "", rows = 7) {
    const node = document.createElement("textarea");
    node.name = name;
    node.id = "field-" + name;
    node.rows = rows;
    node.value = value;
    return node;
  }
  function select(name, entries, selected) {
    const node = document.createElement("select");
    node.name = name;
    node.id = "field-" + name;
    entries.forEach(([value, label]) => node.append(option(value, label)));
    node.value = selected;
    return node;
  }
  function check(label, name, checked = false) {
    const wrapper = el("label", "checkbox-label");
    const node = input(name, "", "checkbox");
    node.checked = checked;
    wrapper.append(node, el("span", "", label));
    return { wrapper, input: node };
  }
  function showModal({ title, subtitle, body, submit = t("保存"), action }) {
    if ($("modal").open) { if (!closeModal()) return; }
    modalReturnFocus = document.activeElement;
    $("modal-title").textContent = title;
    $("modal-subtitle").textContent = subtitle || "";
    $("modal-body").replaceChildren(...(Array.isArray(body) ? body : [body]));
    $("modal").classList.toggle("paragraph-edit-dialog", !!$("modal-body").querySelector(".paragraph-editor"));
    $("modal-error").hidden = true;
    $("modal-submit").textContent = submit;
    $("modal-submit").dataset.label = submit;
    $("modal-submit").disabled = false;
    $("modal-cancel").disabled = false;
    $("modal-close").disabled = false;
    modalAction = action;
    modalDirty = false;
    modalBusy = false;
    $("modal").showModal();
    const focus = $("modal-body").querySelector("input:not([type='checkbox']), textarea, select");
    if (focus) window.setTimeout(() => focus.focus(), 20);
  }
  function closeModal(force = false) {
    if (modalBusy && !force) return false;
    if (modalDirty && !force) {
      confirmAction(t("有尚未保存的修改，确定丢弃并关闭吗？")).then((accepted) => { if (accepted) closeModal(true); });
      return false;
    }
    $("modal-body").querySelectorAll("audio").forEach(audio => { audio.pause(); audio.removeAttribute("src"); audio.load(); });
    $("modal").close();
    $("modal-body").replaceChildren();
    modalDirty = false;
    modalBusy = false;
    modalAction = null;
    if (modalReturnFocus && modalReturnFocus.isConnected) modalReturnFocus.focus();
    return true;
  }
  async function submitModal(event) {
    event.preventDefault();
    if (modalBusy || !modalAction || !$("modal-form").reportValidity()) return;
    modalBusy = true;
    $("modal-submit").disabled = true;
    $("modal-submit").textContent = t("正在保存…");
    $("modal-cancel").disabled = true;
    $("modal-close").disabled = true;
    $("modal-error").hidden = true;
    const currentAction = modalAction;
    const oldLabel = $("modal-submit").dataset.label || t("保存");
    try { await currentAction(); }
    catch (error) {
      I18N.renderDiagnostic($("modal-error"),error.message || t("保存失败，内容仍保留，请重试。"));
      $("modal-error").hidden = false;
      $("modal-error").scrollIntoView({ block: "nearest" });
    } finally {
      if (!modalAction || modalAction === currentAction) {
        modalBusy = false;
        $("modal-submit").disabled = false;
        $("modal-submit").textContent = oldLabel;
        $("modal-cancel").disabled = false;
        $("modal-close").disabled = false;
      }
    }
  }
  function showCourse() {
    const name = input("course-name", "", "text", true);
    name.placeholder = t("例如：课程或项目名称");
    showModal({ title: t("新增课程"), subtitle: t("用课程组织材料。每节课分别保存原文、录音和笔记。"), body: field(t("课程名称"), name), submit: t("创建课程"), action: async () => {
      if (!name.value.trim()) throw new Error(t("请填写课程名称。"));
      const course = await api("/api/courses", "POST", { name: name.value.trim() });
      state.courseId = course.id;
      await refreshState();
      closeModal(true);
      notify(t("课程已创建，现在可以新建课次。"));
    } });
  }
  function showNewLecture() {
    if (!state.courses.length) { showCourse(); return; }
    const title = input("lecture-title", "", "text", true);
    title.placeholder = t("例如：第三讲 · 身体与知觉");
    const course = select("lecture-course", state.courses.map((item) => [item.id, courseLabel(item)]), state.courseId === "all" ? state.courses[0].id : state.courseId);
    const date = input("lecture-date", today(), "date", true);
    showModal({ title: t("新建课次"), subtitle: t("先建一节课，再导入转写稿或本地录音。材料不会自动上传到外部服务。"), body: [field(t("课次标题"), title), field(t("所属课程"), course), field(t("上课日期"), date)], submit: t("创建课次"), action: async () => {
      if (!title.value.trim()) throw new Error(t("请填写课次标题。"));
      const detail = await api("/api/lectures", "POST", { course_id: course.value, title: title.value.trim(), date: date.value });
      state.lecture = detail;
      state.courseId = course.value;
      await refreshState();
      renderLecture();
      closeModal(true);
      switchView("transcript");
      notify(t("课次已创建。下一步导入转写稿，或添加获准使用的录音。"));
    } });
  }
  function showEditLecture() {
    if (!state.lecture) return;
    const lecture = state.lecture;
    const title = input("edit-title", lecture.title, "text", true);
    const course = select("edit-course", state.courses.map((item) => [item.id, courseLabel(item)]), lecture.course_id);
    const date = input("edit-date", lecture.date || today(), "date", true);
    showModal({ title: t("编辑课次"), subtitle: t("更改标题、日期和所属课程，不会修改材料内容。"), body: [field(t("课次标题"), title), field(t("所属课程"), course), field(t("上课日期"), date)], action: async () => {
      if (!title.value.trim()) throw new Error(t("标题不能为空。"));
      const detail = await api(`/api/lectures/${encodeURIComponent(lecture.id)}`, "PUT", { title: title.value.trim(), date: date.value, course_id: course.value });
      await updateDetail(detail);
      closeModal(true);
      notify(t("课次信息已保存。"));
    } });
  }
  function showImport() {
    if (!state.lecture || state.busy) return;
    const lecture = state.lecture;
    const file = input("transcript-file", "", "file");
    file.accept = ".txt,.srt,.vtt,.json,text/plain,application/json,text/vtt";
    const content = textarea("transcript-content", "", 12);
    content.placeholder = t("粘贴转写稿，或先选择文件。\n\nSRT / VTT / 带时间戳的 JSON 可用于定位录音。\n普通 TXT 不会被编造时间戳。");
    content.required = true;
    const format = select("transcript-format", [["auto", t("自动识别")], ["txt", t("TXT 文本")], ["srt", t("SRT 字幕")], ["vtt", t("VTT 字幕")], ["json", "JSON segments"]], "auto");
    const provider = select("transcript-provider", [["manual", t("现成文字稿 / 手动导入")], ["tingwu", t("通义听悟")], ["other", t("其他外部转写")]], lecture.external_transcription && lecture.external_transcription.status === "prepared" ? "tingwu" : "manual");
    file.addEventListener("change", async () => {
      if (!file.files.length) return;
      const chosen = file.files[0];
      if (chosen.size > 6 * 1024 * 1024) { notify(t("转写文件过大，请先拆分为不超过 6 MiB 的文本文件。"), true); file.value = ""; return; }
      if (content.value.trim() && !(await confirmAction(t("选择文件会替换当前输入框内容，继续吗？")))) { file.value = ""; return; }
      try {
        content.value = await chosen.text();
        const ext = chosen.name.split(".").pop().toLowerCase();
        format.value = ["txt", "srt", "vtt", "json"].includes(ext) ? ext : "auto";
        modalDirty = true;
      } catch (_) { notify(t("文件读取失败，请重试或直接粘贴文本。"), true); }
    });
    const body = [];
    if ((lecture.segments || []).length) body.push(el("div", "modal-info warning", t("这节课已有转写。替换将移走当前笔记；旧稿和笔记保留在 JSON 导出的 transcript_history 中，本版不支持一键恢复。请先备份。")));
    body.push(field(t("文字稿来源"), provider), field(t("选择本地文件"), file), field(t("文件格式"), format), field(t("转写内容"), content, t("支持 TXT、SRT、VTT、segments JSON 与听悟 Transcription JSON。不导入摘要代替原稿，不会自动再识别全文。")));
    showModal({ title: t("导入转写稿"), subtitle: t("保留原始输入与来源编号，让每条笔记都能回到材料。"), body, submit: t("导入材料"), action: async () => {
      const replace = (lecture.segments || []).length > 0;
      if (replace && !(await confirmAction(t("确定替换当前转写及笔记？旧版本将保留在 JSON 导出的 transcript_history 中，但本版没有一键恢复，请先备份。")))) return;
      const detail = await api(`/api/lectures/${encodeURIComponent(lecture.id)}/transcript`, "POST", { text: content.value, format: format.value, replace, source: provider.value, filename: file.files[0]?.name || "" });
      await updateDetail(detail);
      closeModal(true);
      notify(tt`已导入 ${detail.segments.length} 段原文。尚未自动生成或核查笔记。`);
    } });
  }
  async function uploadAudio() {
    const file = $("audio-input").files[0];
    $("audio-input").value = "";
    if (!file || !state.lecture || state.busy) return;
    if (file.size > 2 * 1024 * 1024 * 1024) { notify(t("本地上传上限为 2 GiB；更大文件可通过已有本地索引使用。可选云端网关仍限制 120 MiB。"), true); return; }
    const lecture = state.lecture;
    const replace = !!lecture.audio;
    if (replace && !(await confirmAction(t("确定替换这节课的本地录音？现有转写不会自动改变，请核对它是否仍与新录音对应。")))) return;
    await runAction($("audio-button"), t("正在保存录音…"), async () => {
      const detail = await api(`/api/lectures/${encodeURIComponent(lecture.id)}/audio${replace ? "?replace=1" : ""}`, "POST", file, { "Content-Type": file.type || "application/octet-stream", "X-Filename": encodeURIComponent(file.name) });
      $("audio-player").dataset.identity = "";
      await updateDetail(detail);
      notify(t("录音已保存到本机，尚未发送到语音识别服务。") + (replace ? t("请确认它与已有转写的时间线相符。") : ""));
    });
    if (state.lecture?.id === lecture.id) showRecordingLanguage();
  }
  async function generate(mode) {
    if (!state.lecture || state.busy) return;
    const lecture = state.lecture;
    if (!(lecture.segments || []).length) { notify(t("请先导入转写稿。"), true); return; }
    if (noteJob && ["queued", "running"].includes(noteJob.status)) { notify(t("AI 整理正在进行，请勿重复提交。")); return; }
    if (["llm", "overview"].includes(mode)) {
      if (!(state.settings.llm || {}).configured) { showSettings("llm"); return; }
      if (mode === "overview" && !(lecture.notes || []).length) { notify(t("请先生成或记录详细笔记，再补生成总览。"), true); return; }
      if (mode === "llm" && (lecture.notes || []).length && !(await confirmAction(t("重新生成将替换当前详细笔记及总览，旧版本会保留在 JSON 导出的 note_history 中。是否继续？")))) return;
      if (!(await externalConsent("llm"))) return;
      if (!(await deliveryTools.confirm(mode === "overview" ? "overview" : "all"))) return;
      await runAction($("llm-generate"), t("正在启动整理…"), async () => {
        const result = await api(`/api/lectures/${encodeURIComponent(lecture.id)}/notes/jobs`, "POST", {allow_external:true, replace:mode === "llm", scope:mode === "overview" ? "overview" : "all"});
        noteJob = result.job;
        notesView = "overview";
        renderNotes();
        await pollNoteJob(lecture.id);
        switchView("notes");
      });
      return;
    }
    const replace = (lecture.notes || []).length > 0;
    if (replace && !(await confirmAction(t("已有笔记（可能包含手动修改）。重新生成将替换全部笔记，且不能撤销。是否继续？建议先导出 JSON。")))) return;
    if (mode === "llm" && !(await externalConsent("llm"))) return;
    const target = mode === "llm" ? $("llm-generate") : $("local-generate");
    await runAction(target, mode === "llm" ? t("正在调用模型…") : t("正在摘录…"), async () => {
      const detail = await api(`/api/lectures/${encodeURIComponent(lecture.id)}/notes/generate`, "POST", { mode, allow_external: mode === "llm", replace });
      notesView = "details";
      await updateDetail(detail);
      switchView("notes");
      notify(mode === "llm" ? t("模型笔记已生成，全部默认未核查。请对照原文检查归属、遗漏和事实。") : t("已生成本地原句摘录。未使用模型，也不表示已经完成总结或核查。"));
    });
  }
  function externalConsent(kind) {
    const config = state.settings[kind] || {};
    let destination = t("已配置接口");
    try { destination = new URL(config.base_url).host; } catch (_) { /* server performs validation */ }
    const content = kind === "asr" ? t("本节课的录音文件") : t("本节课的转写文字及术语表");
    return confirmAction(tt`本次将把${content}发送给你配置的接口：\n${destination}\n模型：${config.model || t("未指定")}\n\n接口可能收费，并受该服务的数据处理政策约束。请确认已获准使用这些材料。仅同意本次操作，继续吗？`);
  }
  function showWorkflow(scene = null) {
    if (!state.lecture || state.busy) return;
    const lecture = state.lecture;
    const config = {...(scene ? (lecture.workflow_presets || {})[scene] || { scene, instructions: "", prompt_override: "" } : lecture.workflow || { scene: "class" }), output_language:lecture.workflow?.output_language || "zh"};
    const profile = profiles.find((item) => item.id === config.scene);
    if (!profile) { notify(t("整理模式接口尚未加载，请重启本地服务后刷新。"), true); return; }
    const defaultPrompt = code => profile.prompts?.[code] || profile.prompt;
    const chosenLanguage = select("scene-output-language", outputLanguages.map(row => [row.id,row.native]), config.output_language);
    let previousDefault = defaultPrompt(chosenLanguage.value);
    const prompt = textarea("scene-prompt", config.prompt_override || previousDefault, 8);
    const policy = el("pre", "output-policy-preview", outputLanguages.find(row=>row.id===chosenLanguage.value)?.policy || "");
    chosenLanguage.addEventListener("change", () => {
      if (prompt.value.trim() === previousDefault.trim()) prompt.value = defaultPrompt(chosenLanguage.value);
      previousDefault = defaultPrompt(chosenLanguage.value);
      policy.textContent = outputLanguages.find(row=>row.id===chosenLanguage.value)?.policy || "";
      modalDirty = true;
    });
    prompt.maxLength = 12000;
    const instructions = textarea("scene-instructions", config.instructions || "", 4);
    instructions.maxLength = 6000;
    instructions.placeholder = t("例如：保留法语术语原文；重点梳理教师如何批评理智主义。");
    const reset = button(t("恢复本模式默认提示词"), "button secondary compact", () => { prompt.value = defaultPrompt(chosenLanguage.value); modalDirty = true; });
    const rules = el("details", "prompt-rules");
    rules.append(el("summary", "", t("不可覆盖的共同规则与输出格式")), el("p", "", t("只依据原文；不猜身份、时间或观点归属；不确定就待核对；每条内容引用真实 source_ids；严格 JSON notes。可用类别：") + Object.keys(categories).join(" / ") + t("。会议待办缺少负责人或截止时间时写“未明确”。修改用途提示词不会移除这些规则。")));
    showModal({ title: profile.label + t(" · 整理方案"), subtitle: t("每节材料各自保存。本模式的修改会保留；切换用途不会重写已有笔记，也不发送网络请求。"), body: [el("div", "modal-info", profile.description), field(t("笔记输出语言"), chosenLanguage), el("p", "modal-info", t("默认提示词随输出语言切换。自定义文字保留原文；输出语言规则独立生效，不改写转写稿或原文引句。")), field(t("实际输出语言规则（只读）"), policy), field(t("本模式提示词（可修改）"), prompt), reset, field(t("本次额外要求"), instructions), rules], submit: t("保存整理方案"), action: async () => {
      if (config.scene === "custom" && !instructions.value.trim() && prompt.value.trim() === defaultPrompt(chosenLanguage.value)) throw new Error(t("请描述自定义用途，或修改提示词。"));
      const detail = await api(`/api/lectures/${encodeURIComponent(lecture.id)}/workflow`, "PUT", { scene: config.scene, instructions: instructions.value, prompt_override: prompt.value.trim() === defaultPrompt(chosenLanguage.value) ? "" : prompt.value, output_language:chosenLanguage.value });
      await updateDetail(detail);
      closeModal(true);
      notify(t("整理方案已保存在本机，尚未调用模型；已有笔记不变。"));
    } });
  }
  async function changeScene() {
    if (!state.lecture || state.busy) return;
    const scene = $("scene-select").value;
    if (scene === "custom") { showWorkflow(scene); $("scene-select").value = (state.lecture.workflow || {}).scene || "class"; return; }
    await runAction(null, "", async () => {
      const config = {...((state.lecture.workflow_presets || {})[scene] || { scene, instructions: "", prompt_override: "" }), output_language:state.lecture.workflow?.output_language || "zh"};
      const detail = await api(`/api/lectures/${encodeURIComponent(state.lecture.id)}/workflow`, "PUT", config);
      await updateDetail(detail);
    });
  }
  async function changeOutputLanguage() {
    if (!state.lecture || state.busy) return;
    const code = $("output-language").value;
    await runAction(null, "", async () => {
      const detail = await api(`/api/lectures/${encodeURIComponent(state.lecture.id)}/workflow`, "PUT", {...state.lecture.workflow, output_language:code});
      await updateDetail(detail);
      notify(t("输出语言已保存，仅影响下次 AI 生成；已有内容未改动。"));
    });
  }
  function showTranscriptionRoutes() {
    if (!state.lecture || state.busy) return;
    const hasText = !!state.lecture.segments.length;
    const body = [el("div", "modal-info", hasText ? t("这份材料已有文字稿。可以直接校对和整理，不必再识别全文。重新转写会要求确认替换。") : t("只缺文字稿？任选一种路线。外部转写导回后，不会默认再跑一遍本地模型。"))];
    const routes = el("div", "route-options");
    const local = button("", "route-card", () => { closeModal(true); startLocalAsr(); });
    local.append(el("span", "route-number", "01 / OFFLINE"), el("strong", "", t("本地 Whisper")), el("span", "", t("复用本机模型，不上传录音；需要本地计算时间。")));
    const cloud = button("", "route-card", () => { closeModal(true); prepareExternal(); });
    cloud.append(el("span", "route-number", "02 / BROWSER ASSIST"), el("strong", "", t("通义听悟 · 浏览器协助")), el("span", "", t("准备操作说明 → 登录与确认 → 转写导出 → 导回本地。不是无人值守自动化。")));
    const gateway = button("", "route-card", () => { closeModal(true); transcribe(); });
    gateway.append(el("span", "route-number", "03 / OPTIONAL API"), el("strong", "", t("已配置 ASR 接口")), el("span", "", t("使用兼容网关，需要单次外发确认，可能收费。")));
    routes.append(local, cloud, gateway);
    body.push(routes);
    showModal({ title: t("选择转写路线"), subtitle: t("没有最佳模型的预设承诺；可根据时间、隐私与试听结果选择。"), body, submit: t("关闭"), action: async () => closeModal(true) });
  }
  async function prepareExternal() {
    if (!state.lecture || state.busy) return;
    if (!(await confirmAction(t("将生成包含这一份录音完整本地路径的浏览器 AI 操作说明，仅交给你信任的助手。此步骤不会上传录音、不会登录账号，也不会购买额度。继续准备吗？")))) return;
    await runAction(null, "", async () => {
      const result = await api(`/api/lectures/${encodeURIComponent(state.lecture.id)}/external-transcription/prepare`, "POST", { acknowledge_privacy: true });
      await updateDetail(result.lecture);
      const prompt = textarea("browser-handoff", result.prompt, 13);
      prompt.readOnly = true;
      const actions = el("div", "handoff-actions");
      const copy = button(t("复制给浏览器 AI"), "button secondary", async () => {
        try { await navigator.clipboard.writeText(prompt.value); notify(t("已复制操作说明。请交给有浏览器操作能力的 AI；App 不会自行启动助手。")); }
        catch (_) { prompt.focus(); prompt.select(); notify(t("请按 ⌘C / Ctrl+C 复制选中的操作说明。")); }
      });
      const open = el("a", "button primary", t("打开通义听悟 ↗"));
      open.href = result.url;
      open.target = "_blank";
      open.rel = "noopener noreferrer";
      actions.append(copy, open);
      showModal({ title: t("通义听悟 · 操作交接"), subtitle: t("任务仅已准备，尚未上传。你或浏览器助手完成转写后，导入 SRT / TXT / JSON；不要只导入云端摘要。"), body: [el("div", "modal-info warning", t("扫码、验证码和账号选择由你确认；上传必须明确是哪份录音。费用或额度不足时停下，不自动购买。此 App 不保存通义账号、密码或 Cookie。")), actions, field(t("可交给浏览器助手的完整说明"), prompt, t("含私人文件路径，请勿放进公开 GitHub 或分享截图。")), el("p", "", t("导回已有稿后可直接进行 AI 校对和按场景整理；本地识别只作为可选补充，不重复全文。"))], submit: t("导入已下载的文字稿"), action: async () => { closeModal(true); showImport(); } });
    });
  }
  function renderJob() {
    const active = localJob && ["queued", "running", "cancelling"].includes(localJob.status);
    $("transcription-status").hidden = !localJob;
    if (!localJob) return;
    const remaining = (state.lecture?.segments || []).filter(row => row.asr_issue).length;
    const historical = localJob.status === "completed_with_warnings" && !!state.lecture?.asr_report;
    const preparingAudio = localJob.phase === "preparing_audio";
    $("job-title").textContent = active ? preparingAudio ? t("先提取视频音轨 · 尚未开始识别") : localJob.phase === "retrying" ? t("检测到异常 · 短片段重试中") : t("Whisper 本地识别进行中") : localJob.status === "completed" ? t("本地识别已完成 · 尚待核对") : historical && !remaining ? t("初次处理完成 · 缺口已补写，仍需核对") : localJob.status === "completed_with_warnings" ? t("处理完毕 · 存在转写缺口") : t("本地任务已停止 · 可继续");
    I18N.renderDiagnostic($("job-message"), historical ? tt`初次检测 ${localJob.issue_count || 0} 处缺口；当前剩余 ${remaining} 处。补写不等于已人工核查。` : localJob.message);
    $("job-progress").value = preparingAudio ? localJob.preparation_progress || 0 : localJob.progress || 0;
    $("cancel-local-asr").hidden = !active;
    $("cancel-local-asr").disabled = localJob.status === "cancelling";
    const processed = localJob.processed_chunks ?? (["completed", "completed_with_warnings"].includes(localJob.status) ? localJob.total_chunks : localJob.completed_chunks) ?? 0;
    $("job-detail").textContent = preparingAudio ? t("音频准备阶段：16 kHz / 单声道 / WAV。进度条不是转写进度；原视频不覆盖。") : tt`已处理 ${processed} / ${localJob.total_chunks || "—"} 块 · 其中 ${localJob.completed_chunks || 0} 块无已检测异常 · 复用 ${localJob.resumed_chunks || 0} 块。进度不代表正确率。`;
    const hasGaps = remaining > 0;
    const recoverable = ["failed", "cancelled", "interrupted"].includes(localJob.status) || (localJob.status === "completed_with_warnings" && hasGaps);
    $("resume-local-asr").hidden = active || !recoverable;
    $("resume-local-asr").textContent = localJob.status === "completed_with_warnings" ? t("仅补转缺口 · 保留其他文字") : localJob.resume_available ? t("从断点继续") : t("重新尝试");
    $("restart-local-asr").hidden = active || !recoverable;
  }
  function renderAsrReport() {
    const report = state.lecture && state.lecture.asr_report;
    $("asr-report").hidden = !report && !repairJob;
    if (!report && !repairJob) return;
    const issues = (report?.issues || []).filter(row => !row.resolved);
    $("asr-report-title").textContent = issues.length ? tt`有 ${issues.length} 处转写缺口 · 回听与补转` : t("缺口与局部补转 · 文字仍需核对");
    const body = $("asr-report-body");
    if (repairJob?.id && body.dataset.shownRepairId!==repairJob.id) { $("asr-report").open=true; body.dataset.shownRepairId=repairJob.id; }
    const signature=JSON.stringify([state.lecture.id,issues,repairJob?.id,repairJob?.status,(repairJob?.results || []).map(row=>[row.segment_id,row.status,row.candidate,row.errors,row.strategy,row.attempts])]);
    if (body.dataset.signature===signature) { renderRepairProgress(); return; }
    body.dataset.signature=signature;
    body.replaceChildren(el("p", "", t("这是重复、时间码和模型置信的启发式检查，不是逐句正确性证明。系统标记没有冒充教师原话。")));
    if (repairJob) {
      const progress=el("section", "repair-progress"); progress.id="repair-progress";progress.setAttribute("aria-label",t("局部补转进度"));
      const heading=el("strong", "");heading.id="repair-progress-title";
      const count=el("p", "");count.id="repair-progress-count";
      const meter=el("progress", "");meter.id="repair-progress-bar";meter.setAttribute("aria-label",t("已处理片段数，不代表识别正确率"));
      const current=el("p", "");current.id="repair-progress-current";
      const strategy=el("p", "");strategy.id="repair-progress-strategy";
      const elapsed=el("p", "");elapsed.id="repair-progress-elapsed";
      const phase=el("p", "");phase.id="repair-progress-phase";
      const previous=el("p", "");previous.id="repair-progress-previous";
      const message=el("p", "repair-job-message");message.id="repair-progress-message";
      progress.append(heading,count,meter,current,strategy,phase,elapsed,previous,message,el("small", "",t("进度按已处理片段计数，不代表准确率。模型加载时可能暂时没有新结果；已生成候选可以先采用。")));
      if (repairJob.status==="running") progress.append(button(t("停止局部补转"), "button secondary compact", async()=>{
        try { repairJob=(await api(`/api/lectures/${encodeURIComponent(state.lecture.id)}/local-repair/cancel`,"POST",{})).job;renderAsrReport(); }
        catch(error) {notify(error.message,true);}
      }));
      body.append(progress);
      const jobId=repairJob.id;
      for (const row of repairJob.results || []) {
        const card=el("section", "repair-candidate");card.dataset.repairSegmentId=row.segment_id;
        const content=el("p", "",row.candidate || "");
        if (!row.candidate) {I18N.renderDiagnostic(content,row.errors || []);content.prepend(document.createTextNode(t("仍需人工补字：")));}
        card.append(el("strong", "",tt`${timeLabel(row.start)} — ${timeLabel(row.end)} · ${row.attempts} 种策略`),el("small", "",t(row.strategy)),content);
        if (row.status==="applied") {
          card.append(el("small", "",t("已采用 · 核查状态以原文为准")),button(t("查看对应原文"),"text-button",()=>jumpToSource(row.segment_id)));
        } else if (canApplyRepair(row)) {
          const actions=el("div","repair-candidate-actions");
          actions.append(repairApplyButton(row,jobId),button(t("回听并比较候选"),"button secondary compact",()=>showRepairCandidate(row,jobId)));
          card.append(actions,el("small","field-hint",t("只替换这一段原文并保留修改记录，采用后仍为未核查；其他段落继续补转。")));
        }
        body.append(card);
      }
    }
    if (issues.length && repairJob?.status!=="running") body.append(button(t("更换策略补转全部缺口"), "button primary compact", () => startRepair((state.lecture.segments || []).filter(row => row.asr_issue).map(row => row.id))));
    for (const issue of issues) {
      const segment = (state.lecture.segments || []).find(row => row.asr_issue && row.start === issue.start && row.end === issue.end);
      const line = el("div", "asr-issue-row");
      const reason=el("span", ""); I18N.renderDiagnostic(reason,issue.reasons);
      line.append(button(tt`${timeLabel(issue.start)} — ${timeLabel(issue.end)} ▶ 回听`, "button secondary compact", () => seekAudio({start: issue.start})), reason);
      if (segment) line.append(button(t("边听边补字"), "segment-edit-button", () => editSegment(segment)), button(t("换策略补转这一段"), "text-button", () => startRepair([segment.id])));
      const ready=segment && (repairJob?.results || []).find(row=>row.segment_id===segment.id && canApplyRepair(row));
      if (ready) line.append(repairApplyButton(ready,repairJob.id));
      body.append(line);
    }
    renderRepairProgress();
  }
  function renderRepairProgress() {
    if (!repairJob || !$("repair-progress")) return;
    const results=repairJob.results || [], completed=repairJob.completed ?? results.length,total=repairJob.total || completed || 1,current=repairJob.current;
    const ready=repairJob.candidate_count ?? results.filter(row=>row.candidate && row.status!=="applied").length;
    const failed=repairJob.unresolved_count ?? results.filter(row=>!row.candidate).length;
    const applied=repairJob.applied_count ?? results.filter(row=>row.status==="applied").length;
    $("repair-progress-title").textContent=repairJob.status==="running"?t("局部补转进行中"):repairJob.status==="completed"?t("局部补转已结束"):t("局部补转已停止 · 已生成候选仍可采用");
    $("repair-progress-count").textContent=tt`已处理 ${completed} / ${total} 段 · 可采用 ${ready} · 仍失败 ${failed} · 已采用 ${applied}`;
    $("repair-progress-bar").max=total;$("repair-progress-bar").value=completed;
    $("repair-progress-current").hidden=!current || repairJob.status!=="running";
    $("repair-progress-strategy").hidden=!current || repairJob.status!=="running";
    if (current) {
      $("repair-progress-current").textContent=tt`正在处理第 ${current.index} / ${total} 段：${current.segment_id} · ${timeLabel(current.start)} — ${timeLabel(current.end)}`;
      $("repair-progress-strategy").textContent=tt`策略 ${current.strategy_index} / ${current.strategy_total || 4}：${t(current.strategy)}`;
    }
    const phases={preparing:t("正在准备本地补转"),recognizing:t("音频准备、模型加载与识别中"),validating:t("正在检查候选与时间码"),between_passages:t("正在切换到下一段")};
    $("repair-progress-phase").hidden=repairJob.status!=="running";
    $("repair-progress-phase").textContent=phases[repairJob.phase] || t("正在运行本地识别策略");
    $("repair-progress-elapsed").textContent=repairJob.elapsed_seconds!==undefined?(current && repairJob.status==="running"?tt`已用时 ${Math.floor(repairJob.elapsed_seconds)} 秒 · 当前策略 ${Math.floor(repairJob.strategy_elapsed_seconds || 0)} 秒`:tt`已用时 ${Math.floor(repairJob.elapsed_seconds)} 秒`):t("旧任务未记录计时；候选仍可回听并采用。");
    $("repair-progress-previous").hidden=!(repairJob.last_attempt_errors || []).length;
    if (!$("repair-progress-previous").hidden) {I18N.renderDiagnostic($("repair-progress-previous"),repairJob.last_attempt_errors);$("repair-progress-previous").prepend(document.createTextNode(t("上次策略未通过：")));}
    I18N.renderDiagnostic($("repair-progress-message"),repairJob.message || "");
  }
  function canApplyRepair(row) {
    return !!row.candidate && !row.errors?.length && (row.status || "candidate")==="candidate" && ["running","completed","cancelled","interrupted","failed"].includes(repairJob?.status);
  }
  function repairApplyButton(row,jobId) {
    const node=button(t("采用到原文"),"button primary compact repair-apply",()=>{
      if (state.busy) return;
      runAction(node,t("正在采用…"),()=>saveRepairCandidate(state.lecture.id,jobId,row));
    });
    node.dataset.repairApply=row.segment_id;node.disabled=repairApplying.has(jobId+":"+row.segment_id);
    return node;
  }
  async function saveRepairCandidate(lectureId,jobId,row) {
    const key=jobId+":"+row.segment_id;
    if (repairApplying.has(key)) return;
    repairApplying.add(key);repairEpoch+=1;window.clearTimeout(repairTimer);
    try {
      const detail=await api(`/api/lectures/${encodeURIComponent(lectureId)}/local-repair/apply`,"POST",{job_id:jobId,segment_ids:[row.segment_id]});
      await updateDetail(detail);
      notify(t("补转结果已写入对应原文片段，仍标为未核查。其他文字和修改记录保留。"));
    } finally {
      repairApplying.delete(key);
      if (state.lecture?.id===lectureId) pollRepair(lectureId);
    }
  }
  async function startRepair(ids, hintText = "") {
    if (!state.lecture || !ids.length || state.busy) return;
    if (!state.settings.local_asr?.configured) { showSettings("local"); return; }
    if (!state.lecture.asr_language) { showRecordingLanguage(() => startRepair(ids, hintText)); return; }
    if (!(await confirmAction(tt`只在本机补转 ${ids.length} 个片段，语言：${state.lecture.asr_language}。依次尝试词级时间码、上下文、去点击和短窗策略，最多 4 种。通过检查后停下，仍失败则保留缺口；不自动覆盖任何文字，不调用云端。开始吗？`))) return;
    const id = state.lecture.id;
    await runAction(null, "", async () => {
      repairEpoch += 1;
      repairJob = (await api(`/api/lectures/${encodeURIComponent(id)}/local-repair`, "POST", {confirm_local:true, segment_ids:ids, language:state.lecture.asr_language,hint_text:hintText})).job;
      renderAsrReport(); $("asr-report").open = true; pollRepair(id);
    });
  }
  async function pollRepair(id) {
    window.clearTimeout(repairTimer);
    if (state.lecture?.id !== id) return;
    const epoch=repairEpoch;
    try {
      const result = await api(`/api/lectures/${encodeURIComponent(id)}/local-repair`);
      if (state.lecture?.id !== id || epoch!==repairEpoch) return;
      repairJob = result.job; renderAsrReport();
      if (repairJob?.status === "running") repairTimer = window.setTimeout(() => pollRepair(id), 1500);
    } catch (_) {
      if (state.lecture?.id===id && epoch===repairEpoch && repairJob?.status==="running") {
        notify(t("补转进度连接暂时中断，正在重连；不会重复启动识别。"),true);
        repairTimer=window.setTimeout(()=>pollRepair(id),3000);
      }
    }
  }
  function showRepairCandidate(row,jobId=repairJob.id) {
    const segment = state.lecture.segments.find(value => value.id === row.segment_id);
    if (!segment) return;
    const lectureId = state.lecture.id;
    showModal({title:t("回听并比较局部候选"), subtitle:t("通过检查不等于正确。采用后仍标为未核查，原文与补转记录保留，其他段落和笔记不被替换。"), body:[excerptPlayer(segment), el("small", "", t("现有文字")), el("p", "correction-before", segment.text), el("small", "", t("本地补转候选")), el("p", "correction-after", row.candidate)], submit:t("采用这个候选（未核查）"), action:async () => {
      await saveRepairCandidate(lectureId,jobId,row); closeModal(true);
    }});
  }
  async function pollLocalJob(id) {
    window.clearTimeout(jobTimer);
    if (!state.lecture || String(state.lecture.id) !== String(id)) return;
    try {
      const result = await api(`/api/lectures/${encodeURIComponent(id)}/local-asr`);
      if (!state.lecture || String(state.lecture.id) !== String(id)) return;
      const previous = localJob;
      localJob = result.job;
      renderJob(); renderControls();
      if (localJob && ["queued", "running", "cancelling"].includes(localJob.status)) jobTimer = window.setTimeout(() => pollLocalJob(id), 2000);
      else if (localJob && ["completed", "completed_with_warnings"].includes(localJob.status) && previous?.status !== localJob.status) await updateDetail(await api(`/api/lectures/${encodeURIComponent(id)}`));
    } catch (_) { /* Older server: other actions remain usable; restart is needed for new endpoints. */ }
  }
  async function startLocalAsr(resume = true) {
    if (!state.lecture || state.busy) return;
    if (!(state.settings.local_asr || {}).configured) { showSettings("local"); return; }
    const lecture = state.lecture;
    const gaps = lecture.segments.filter(row => row.asr_issue);
    if (resume && gaps.length) { await startRepair(gaps.map(row => row.id)); return; }
    if (!lecture.asr_language) { showRecordingLanguage(() => startLocalAsr(resume)); return; }
    const replace = !!lecture.segments.length;
    if (!(await confirmAction(t("将在本机运行 Whisper：60 秒分段、异常有限重试、无进展超时停止。") + (resume ? t("复用匹配的已完成断点，只识别剩余/异常片段。") : t("这次不复用已有断点，重新识别全文。")) + t("不调用云端、不下载权重。") + (replace ? t("\n注意：保存结果会替换当前稿（包括人工校对）及笔记，旧版本保留在 JSON 历史；请先备份。") : "") + t("\n现在开始吗？")))) return;
    await runAction(null, "", async () => {
      const result = await api(`/api/lectures/${encodeURIComponent(lecture.id)}/local-asr`, "POST", { confirm_local: true, replace, resume, language:lecture.asr_language });
      localJob = result.job;
      renderJob();
      pollLocalJob(lecture.id);
      notify(t("本地转写已启动，可以继续回听。取消或失败时原稿不变。"));
    });
  }
  function renderDenoise() {
    $("denoise-status").hidden = !denoiseJob;
    if (!denoiseJob) return;
    I18N.renderDiagnostic($("denoise-status"),denoiseJob.message);
    if (denoiseJob.status === "running") $("denoise-status").append(document.createTextNode(` ${denoiseJob.progress || 0}%`));
  }
  async function pollDenoise(id) {
    window.clearTimeout(denoiseTimer);
    if (!state.lecture || String(state.lecture.id) !== String(id)) return;
    try {
      const result = await api(`/api/lectures/${encodeURIComponent(id)}/audio/denoise`);
      if (!state.lecture || String(state.lecture.id) !== String(id)) return;
      const previous = denoiseJob;
      denoiseJob = result.job; renderDenoise(); renderControls();
      if (denoiseJob?.status === "running") denoiseTimer = window.setTimeout(() => pollDenoise(id), 1500);
      else if (denoiseJob?.status === "completed" && previous?.status !== "completed") await updateDetail(await api(`/api/lectures/${encodeURIComponent(id)}`));
    } catch (_) { /* New route requires a restarted backend. */ }
  }
  async function generateDenoised() {
    if (!state.lecture || state.busy) return;
    const id = state.lecture.id;
    const profile = select("denoise-profile", [["denoised",t("轻度连续噪声抑制")],["keyboard",t("键盘 / 瞬态点击抑制 · 实验性")]], "keyboard");
    showModal({title:t("选择本地声音处理"), subtitle:t("原音、轻度降噪、点击抑制版分开保存，时间线不变。"), body:[field(t("处理方式"), profile), el("p", "modal-info warning", t("键盘声属于瞬态噪声。点击抑制可作尝试，但与人声重叠时无法保证分离，可能伤到辅音；不是键盘声专用神经模型。建议先听原音，再对比生成版。全文处理可能需要数分钟。"))], submit:t("生成独立听课版"), action:async () => {
    await runAction(null, "", async () => {
      denoiseJob = (await api(`/api/lectures/${encodeURIComponent(id)}/audio/denoise`, "POST", {confirm_local:true, profile:profile.value})).job;
      renderDenoise(); pollDenoise(id);
    });
    closeModal(true);
    }});
  }
  async function correctTranscript() {
    if (revisionTools) { await revisionTools.start(); return; }
    if (!state.lecture || state.busy) return;
    if (!(state.settings.llm || {}).configured) { showSettings("llm"); return; }
    if (!(await externalConsent("llm"))) return;
    await runAction($("ai-correct"), t("正在提出校对建议…"), async () => {
      await updateDetail(await api(`/api/lectures/${encodeURIComponent(state.lecture.id)}/corrections/propose`, "POST", { allow_external: true }));
      showCorrections();
    });
  }
  function showCorrections() {
    if (revisionTools && state.lecture?.proofreading) { revisionTools.show(); return; }
    const lecture = state.lecture;
    const proposal = lecture && lecture.correction_proposal;
    if (!proposal) return;
    const choices = [];
    const list = el("div", "correction-list");
    for (const row of proposal.corrections) {
      const card = el("section", "correction-card");
      const choice = check(tt`${row.source_id} · 应用这条建议`, "correction-" + row.source_id);
      choice.input.value = row.source_id;
      choice.input.disabled = row.before === row.after;
      card.append(choice.wrapper, el("small", "", t("现有原文")), el("p", "correction-before", row.before), el("small", "", t("建议文字")), el("p", "correction-after", row.after), el("p", "field-hint", row.reason));
      choices.push(choice.input); list.append(card);
    }
    if (!proposal.corrections.length) list.append(el("p", "", t("模型没有提出可用修改。这不代表原稿已经正确，请继续回听核查。")));
    showModal({ title: t("逐条核对修改建议"), subtitle: proposal.warning, body: [el("div", "modal-info warning", t("默认不勾选。文字模型没有听到录音；请核对否定词、术语和发言归属。不改动 original_text，不自动标为已核查。")), list], submit: proposal.corrections.length ? t("应用选中的建议") : t("关闭"), action: async () => {
      if (!proposal.corrections.length) { closeModal(true); return; }
      const ids = choices.filter((node) => node.checked && !node.disabled).map((node) => node.value);
      if (!ids.length) throw new Error(t("请先核对并勾选要应用的建议；也可取消，原稿不变。"));
      const detail = await api(`/api/lectures/${encodeURIComponent(lecture.id)}/corrections/apply`, "POST", { proposal_id: proposal.id, source_ids: ids });
      await updateDetail(detail); closeModal(true);
      notify(tt`已应用 ${ids.length} 条建议，修改与关联笔记标为待复核；原始转写保留。`);
    } });
  }
  async function transcribe() {
    if (!state.lecture || !state.lecture.audio || state.busy) return;
    if (!(state.settings.asr || {}).configured) { showSettings("asr"); return; }
    const lecture = state.lecture;
    const replace = (lecture.segments || []).length > 0;
    if (replace && !(await confirmAction(t("语音转写将替换全部现有转写及其笔记（包括手动修改），不能撤销。是否继续？建议先导出 JSON。")))) return;
    if (!(await externalConsent("asr"))) return;
    await runAction($("transcribe-button"), t("正在转写，请稍候…"), async () => {
      const detail = await api(`/api/lectures/${encodeURIComponent(lecture.id)}/transcribe`, "POST", { allow_external: true, replace });
      await updateDetail(detail);
      notify(t("语音转写完成。专有名词、否定词和发言归属仍需回听核对。"));
    });
  }
  function excerptPlayer(segment) {
    const box = el("section", "excerpt-player");
    if (!state.lecture.audio || !Number.isFinite(segment.start)) {
      box.append(el("p", "field-hint", t("没有录音或真实时间码，可直接手动校对。"))); return box;
    }
    $("audio-player").pause();
    const next = state.lecture.segments.find(row => row.start > segment.start);
    const end = segment.end || next?.start || Math.min(segment.start + 30, state.lecture.duration || segment.start + 30);
    const audio = el("audio", ""); audio.controls = true; audio.preload = "metadata";
    audio.src = audioVersions().find(row => row.id === state.audioVariant && row.available)?.url || state.lecture.audio.url;
    const loop = check(t("循环回听这一段"), "excerpt-loop");
    const speeds = select("excerpt-speed", [["0.75","0.75×"],["1",t("正常速度")],["1.25","1.25×"]], "1");
    speeds.addEventListener("change", () => { audio.playbackRate = Number(speeds.value); });
    audio.addEventListener("loadedmetadata", () => { audio.currentTime = segment.start; });
    audio.addEventListener("play", () => { if (audio.currentTime < segment.start || audio.currentTime >= end) audio.currentTime = segment.start; });
    audio.addEventListener("timeupdate", () => { if (audio.currentTime >= end) { if (loop.input.checked) audio.currentTime = segment.start; else audio.pause(); } });
    const controls = el("div", "excerpt-controls");
    controls.append(button(t("↶ 回退 3 秒"), "button secondary compact", () => { audio.currentTime = Math.max(segment.start, audio.currentTime-3); }), button(t("从段首播放"), "button secondary compact", () => { audio.currentTime = segment.start; audio.play().catch(() => notify(t("请点击播放器的播放按钮。"))); }), field(t("速度"), speeds), loop.wrapper);
    box.append(el("strong", "", `${timeLabel(segment.start)} — ${timeLabel(end)} · ${state.audioVariant === "original" ? t("原录音") : t("当前试听版")}`), audio, controls);
    return box;
  }
  function recordingLanguageCodes(value) {
    return value === "zh_en" ? ["zh", "en"] : value.startsWith("mix:") ? value.slice(4).split(",") : [];
  }
  function recordingLanguageLabel(value) {
    const names = {zh:t("中文"), en:t("英语"), fr:t("法语"), vi:t("越南语"), de:t("德语"), ja:t("日语")};
    const codes = recordingLanguageCodes(value);
    return codes.length ? codes.map(code => names[code] || code).join(" ＋ ") : names[value] || value;
  }
  function showRecordingLanguage(after = null, forceMixed = false) {
    if (!state.lecture) return;
    const id = state.lecture.id;
    const selected = state.lecture.asr_language || state.settings.local_asr?.language || "auto";
    const selectedCodes = recordingLanguageCodes(selected);
    const choices = select("recording-language-modal", [...languages.common.map(row => [row.id,row.label]), ["mixed",t("多语言课程（选择组合…）")], ["other",t("其他语言（输入代码）")]], forceMixed || selectedCodes.length ? "mixed" : languages.common.some(row => row.id === selected) ? selected : "other");
    const custom = input("other-language-code", languages.codes.includes(selected) ? selected : "");
    const commonCodes = ["zh", "en", "fr", "vi", "de", "ja"];
    const checks = commonCodes.map(code => check(recordingLanguageLabel(code), `mixed-${code}`, selectedCodes.includes(code)));
    const mixed = el("section", "mixed-language-panel");
    const grid = el("div", "mixed-language-grid"); grid.append(...checks.map(row => row.wrapper));
    const extra = input("mixed-extra-codes", selectedCodes.filter(code => !commonCodes.includes(code)).join(", "));
    mixed.append(el("p", "field-label", t("勾选录音中实际使用的语言（2—6 种）")), grid, field(t("其他混合语言代码（可选）"), extra, t("用逗号分隔，例如 es, it。不要填 auto；只选确实会出现的语言。")), el("p", "field-hint", t("短窗按音频选择候选语言，保留原语言而非翻译。会增加本地计算；同一句混说不保证准确，判断不足会标记回听。")));
    const customField = field(t("其他语言代码"), custom, t("仅选择“其他语言”时使用。越南语 vi、日语 ja 已在常用选项中；范围外请导入其他工具的文字稿或配置转写网关。"));
    const visibility = () => { mixed.hidden = choices.value !== "mixed"; customField.hidden = choices.value !== "other"; };
    choices.addEventListener("change", visibility); visibility();
    const help = el("p", "modal-info", languages.notice || t("支持多语言 Whisper；语言支持不代表准确率保证。不会自动切换云端。"));
    const scope = el("details", "language-scope"); scope.append(el("summary", "", t("查看完整语言代码范围")), el("p", "", languages.codes.join(" · ")));
    showModal({title:t("这份录音使用什么语言？"), subtitle:t("只影响这份录音，不改其他课次。多语言可自由组合；不改变笔记输出语言，不自动翻译原文。"), body:[field(t("录音语言"), choices),mixed,customField,help,scope], submit:after ? t("保存语言并继续") : t("保存这份录音的语言"), action:async () => {
      let value = choices.value === "other" ? custom.value.trim().toLowerCase() : choices.value;
      if (value === "mixed") {
        const codes = [...checks.flatMap((row, index) => row.input.checked ? [commonCodes[index]] : []), ...extra.value.toLowerCase().split(/[,，\s]+/).filter(Boolean)];
        if (codes.length < 2 || codes.length > 6 || new Set(codes).size !== codes.length || codes.some(code => !languages.codes.includes(code))) throw new Error(t("请选择 2—6 种不同的受支持语言，不要重复或填写 auto。"));
        value = "mix:" + codes.sort().join(",");
      }
      await updateDetail(await api(`/api/lectures/${encodeURIComponent(id)}`, "PUT", {asr_language:value}));
      closeModal(true); if (after) await after();
    }});
  }
  function editSegment(segment) {
    if (!state.lecture || state.busy) return;
    const lectureId = state.lecture.id;
    const text = textarea("segment-text", segment.asr_issue ? "" : segment.text, 10);
    text.required = true;
    const review = select("segment-review", Object.entries(statuses), segment.review_status || "unreviewed");
    const source = el("div", "modal-info", tt`来源 ${segment.id} · ${timeLabel(segment.start)}\n原始转写：${I18N.sourceText(segment,segment.original_text === undefined ? segment.text : segment.original_text)}`);
    const resolve = check(t("我已根据回听补全这一处缺口"), "resolve-gap", true);
    const body = [excerptPlayer(segment), source, field(t("校对后的文字"), text), field(t("这段原文的核查状态"), review)];
    if (segment.asr_issue) body.push(resolve.wrapper);
    showModal({ title: segment.asr_issue ? t("回听并补写缺口") : t("校对原文"), subtitle: t("可以暂停、调速、循环回听。原始转写不会被覆盖；文字变化后，关联的已核查笔记需要重新复核。"), body, action: async () => {
      if (!text.value.trim()) throw new Error(t("原文内容不能为空。"));
      const detail = await api(`/api/lectures/${encodeURIComponent(lectureId)}/segments/${encodeURIComponent(segment.id)}`, "PUT", { text: text.value, review_status: review.value, expected: editSnapshot(segment), resolve_gap:!!segment.asr_issue && resolve.input.checked });
      await updateDetail(detail);
      closeModal(true);
      notify(t("原文校对已保存。原始转写仍可展开查看。"));
    } });
  }
  function editSnapshot(segment) {
    return Object.fromEntries(["text", "start", "end", "review_status", "asr_issue"].map(key => [key, segment[key] ?? null]));
  }
  function editParagraph(rows) {
    if (!state.lecture || state.busy || !rows.length) return;
    const lectureId = state.lecture.id;
    const player = excerptPlayer({...rows[0], end: rows.at(-1).end});
    const audio = player.querySelector("audio");
    const editor = el("div", "paragraph-editor");
    const fields = rows.map(segment => {
      const text = textarea(`paragraph-${segment.id}`, segment.text, 2);
      text.required = true; text.maxLength = 16000; text.dataset.sourceId = segment.id;
      const head = el("div", "paragraph-editor-heading");
      head.append(el("small", "", `${timeLabel(segment.start)} · ${segment.id}`));
      if (audio && Number.isFinite(segment.start)) head.append(button(t("播放这句"), "text-button", () => {
        audio.currentTime = segment.start; audio.play().catch(() => notify(t("请点击播放器的播放按钮。")));
      }));
      const section = el("section", "paragraph-editor-source");
      section.append(head, field(t("原文文字（可修改）"), text));
      const original = el("details", "paragraph-editor-original");
      original.append(el("summary", "", t("查看最初转写")), el("p", "", segment.original_text ?? segment.text));
      section.append(original); editor.append(section);
      return {segment, text, expected: editSnapshot(segment)};
    });
    const help = el("details", "paragraph-edit-help");
    help.append(el("summary", "", t("修改记录与核查状态")), el("p", "", t("原始转写和修改历史都会保留。修改后的句子重新标为未核查，相关笔记需要复核；可在下方输入框直接修改。")));
    showModal({title:t("边听边改这一段"), subtitle:t("正常段落也可以修改。每个输入框保留真实时间码；只保存改动的句子，不重新识别，也不调用 AI。"),
      body:[player, help, editor],
      submit:t("保存本段修改"), action:async () => {
        const edits = fields.filter(row => row.text.value !== row.expected.text).map(row => ({id:row.segment.id, text:row.text.value, expected:row.expected}));
        if (edits.some(row => !row.text.trim())) throw new Error(t("原文内容不能为空。"));
        if (edits.length) await updateDetail(await api(`/api/lectures/${encodeURIComponent(lectureId)}/segments`, "PUT", {edits}));
        closeModal(true);
        if (edits.length) notify(t("本段修改已保存，原始转写和时间码仍保留。"));
      }});
  }
  function editNote(note = null) {
    if (!state.lecture || state.busy) return;
    const lecture = state.lecture;
    if (!(lecture.segments || []).length) { notify(t("请先导入原文，再添加能关联来源的笔记。")); return; }
    const title = input("note-title", note ? note.title : "", "text", true);
    const content = textarea("note-content", note ? note.content : "", 7);
    content.required = true;
    const category = select("note-category", Object.entries(categories), note ? note.category : "comment");
    const review = select("note-review", Object.entries(statuses), note ? note.review_status : "unreviewed");
    const grid = el("div", "field-grid");
    grid.append(field(t("笔记类别"), category), field(t("核查状态"), review));
    const choices = el("div", "source-choices");
    const sourceInputs = [];
    for (const segment of lecture.segments) {
      const label = el("label", "source-choice");
      const checkbox = input(`source-${segment.id}`, segment.id, "checkbox");
      checkbox.checked = !!note && (note.source_ids || []).includes(segment.id);
      checkbox.dataset.sourceId = segment.id;
      sourceInputs.push(checkbox);
      const words = el("span", "");
      words.append(el("strong", "", `${segment.id} · ${timeLabel(segment.start)}`), document.createTextNode(segment.text.slice(0, 180) + (segment.text.length > 180 ? "…" : "")));
      label.append(checkbox, words);
      choices.append(label);
    }
    const sourceLabel = el("div", "field");
    sourceLabel.append(el("span", "field-label", t("关联原文来源（至少选择一段）")), choices, el("span", "field-hint", t("请主动选择支持这条笔记的原文。勾选来源不代表系统已经验证语义正确。")));
    showModal({ title: note ? t("编辑笔记") : t("记录一条笔记"), subtitle: t("只将课堂材料支持的内容写入课堂笔记。自己的延伸理解请在正文明确标注。"), body: [field(t("标题"), title), grid, field(t("正文"), content), sourceLabel], action: async () => {
      const sourceIds = sourceInputs.filter((node) => node.checked).map((node) => node.value);
      if (!title.value.trim() || !content.value.trim()) throw new Error(t("标题和正文不能为空。"));
      if (!sourceIds.length) throw new Error(t("请至少选择一段原文作为来源。"));
      const body = { title: title.value.trim(), content: content.value.trim(), category: category.value, review_status: review.value, source_ids: sourceIds };
      const path = `/api/lectures/${encodeURIComponent(lecture.id)}/notes` + (note ? `/${encodeURIComponent(note.id)}` : "");
      const detail = await api(path, note ? "PUT" : "POST", body);
      await updateDetail(detail);
      closeModal(true);
      notify(t("笔记已保存到本机。"));
    } });
  }
  async function changeNoteStatus(note, target) {
    if (!state.lecture || state.busy) return;
    const verified = note.review_status !== "verified";
    if (verified && !(await confirmAction(t("请确认你已对照原文（必要时回听录音）检查内容、观点归属及来源。标记为已核查吗？")))) return;
    const lectureId = state.lecture.id;
    await runAction(target, t("保存中…"), async () => {
      const detail = await api(`/api/lectures/${encodeURIComponent(lectureId)}/notes/${encodeURIComponent(note.id)}`, "PUT", { review_status: verified ? "verified" : "needs_review" });
      await updateDetail(detail);
      notify(verified ? t("已标记为人工核查通过。") : t("已标记为待复核。"));
    });
  }
  async function archiveNote(note, target) {
    if (!state.lecture || state.busy) return;
    if (!(await confirmAction(tt`归档笔记“${note.title}”？\n归档后不再显示于当前笔记列表，可通过“恢复归档”找回。不会永久删除。`))) return;
    const lectureId = state.lecture.id;
    await runAction(target, t("归档中…"), async () => {
      const detail = await api(`/api/lectures/${encodeURIComponent(lectureId)}/notes/${encodeURIComponent(note.id)}`, "DELETE");
      await updateDetail(detail);
      notify(t("笔记已归档，可随时通过“恢复归档”找回。"));
    });
  }
  function showArchived() {
    if (!state.lecture || state.busy) return;
    const lecture = state.lecture;
    const archived = lecture.deleted_notes || [];
    if (!archived.length) return;
    const picker = select("archived-note", archived.map((note) => [note.id, note.title]), archived[0].id);
    const preview = el("div", "modal-info", archived[0].content);
    picker.addEventListener("change", () => { preview.textContent = archived.find((note) => note.id === picker.value)?.content || ""; });
    showModal({ title: t("恢复归档笔记"), subtitle: t("归档不是永久删除。恢复后笔记会标记为“待复核”，请确认来源仍然有效。"), body: [field(t("选择要恢复的笔记"), picker), preview], submit: t("恢复所选笔记"), action: async () => {
      const detail = await api(`/api/lectures/${encodeURIComponent(lecture.id)}/notes/restore`, "POST", { note_id: picker.value });
      await updateDetail(detail);
      closeModal(true);
      notify(t("笔记已恢复，并标记为待复核。"));
    } });
  }
  function showSettings(focusSection = null) {
    const controls = {};
    const body = [el("div", "modal-info", t("密钥只保存于受限的本机配置文件，不会显示已有值，也不会写入浏览器存储。配置接口不等于连接成功；每次发送课堂材料前仍会单独询问。"))];
    const localConfig = state.settings.local_asr || {};
    const localSection = el("section", "settings-section");
    localSection.id = "settings-local";
    const pythonPath = input("local-python", localConfig.python_path || ""); pythonPath.maxLength = 2048;
    const modelPath = input("local-model", localConfig.model_path || ""); modelPath.maxLength = 2048;
    const backend = select("local-backend", [["mlx", "MLX · Apple Silicon"], ["faster", "faster-whisper · Mac / Windows"]], localConfig.backend || "mlx");
    const languageChoices = languages.common.map(row => [row.id,row.label]);
    if (localConfig.language && !languageChoices.some(row => row[0] === localConfig.language)) languageChoices.push([localConfig.language, recordingLanguageLabel(localConfig.language)]);
    const language = select("local-language", languageChoices, localConfig.language || "auto");
    const localCheck = button(t("检查已保存的本地环境"), "button secondary compact", async () => {
      localCheck.disabled = true;
      try { notify((await api("/api/local-asr/check", "POST", {})).message, false, true); }
      catch (error) { notify(error.message, true, true); }
      finally { localCheck.disabled = false; }
    });
    localSection.append(el("h3", "", t("本地 Whisper · 可选")), el("p", "", t("复用已有 MLX Whisper 环境，主要面向 Apple Silicon Mac。此处不安装依赖、不下载权重；其他平台可导入外部文字稿或使用网关。")), field(t("Python 可执行文件"), pythonPath, t("选择安装了 mlx-whisper 的 python3。留空使用启动 App 的 Python。")), field(t("本地模型目录"), modelPath, t("须含 config.json 与 npz / safetensors 权重。路径仅本机使用，请不要公开设置截图。")), field(t("主要语言"), language, t("自动识别不保证短句内混合外语的准确率；哲学术语仍需核对。")), localCheck);
    localSection.insertBefore(field("Whisper backend", backend), localSection.children[2]);
    localSection.children[1].textContent = I18N.language === "en" ? "MLX reuses an existing Apple Silicon setup. The share package can install faster-whisper (CPU) on Mac / Windows. Run setup-mac.command or setup-windows.bat once; all recognition is local." : "MLX 复用已有 Apple Silicon 环境；分享包可为 Mac / Windows 安装 faster-whisper（CPU）。首次运行 setup-mac.command 或 setup-windows.bat，识别过程不上传录音。";
    pythonPath.closest(".field").querySelector(".field-hint").textContent = I18N.language === "en" ? "Python with the selected backend installed; blank uses the app's interpreter. Setup fills this automatically." : "选择装有对应后端的 Python；留空使用启动 App 的解释器。首次安装会自动填写。";
    modelPath.closest(".field").querySelector(".field-hint").textContent = I18N.language === "en" ? "A local config.json plus model.bin (faster-whisper), or npz/safetensors (MLX). No model download during recognition." : "本地目录需 config.json；faster-whisper 需 model.bin，MLX 需 npz/safetensors。识别时不再下载。";
    body.push(localSection);
    for (const [kind, label] of [["llm", t("LLM · 结构化笔记")], ["asr", t("ASR · 录音转写")]]) {
      const config = state.settings[kind] || {};
      const section = el("section", "settings-section");
      section.id = `settings-${kind}`;
      section.append(el("h3", "", label), el("p", "", kind === "llm" ? t("填写兼容 Chat Completions 的 API 根地址。程序会追加 /chat/completions；支持 HTTPS，或明确配置的 localhost HTTP 网关。") : t("填写完整的 multipart POST 端点。网关需接受 file、model、response_format=verbose_json，并返回带秒数时间戳的 segments 或 SRT；并非任意厂商接口都直接兼容。")));
      const baseUrl = input(kind + "-base-url", config.base_url || "", "url");
      baseUrl.placeholder = kind === "llm" ? "https://your-provider.example/v1" : "https://your-gateway.example/v1/audio/transcriptions";
      const model = input(kind + "-model", config.model || "");
      model.placeholder = t("填写实际可用的模型名称");
      const key = input(kind + "-api-key", "", "password");
      key.autocomplete = "new-password";
      key.placeholder = t("留空保留已有密钥");
      const clear = check(t("明确删除已保存的密钥"), kind + "-clear-key");
      section.append(field(t("API 地址"), baseUrl), field(t("模型名称"), model), field("API key", key, t("已有密钥不会回传。无需鉴权的本地网关可留空。清空地址和模型可以停用接口。")), clear.wrapper);
      controls[kind] = { baseUrl, model, key, clear: clear.input };
      body.push(section);
    }
    const glossarySection = el("section", "settings-section");
    const glossary = textarea("glossary", (state.settings.glossary || []).map((item) => `${item.term} = ${item.meaning || ""}`).join("\n"), 6);
    glossary.placeholder = t("Merleau-Ponty = 梅洛-庞蒂\n意向性 = 本课程中的术语提示，不是自动纠错指令");
    glossarySection.append(el("h3", "", t("课程术语表")), field(t("每行一项：术语 = 说明"), glossary, t("帮助模型理解专有名词，不会静默改写原始转写。未核实的术语仍应人工回听。")));
    body.push(glossarySection);
    showModal({ title: t("接口与术语表"), subtitle: t("先用本地原句摘录即可开始。填好 API 后，再逐次授权模型整理或语音转写。"), body, submit: t("保存设置"), action: async () => {
      const payload = {};
      payload.local_asr = { python_path: pythonPath.value, model_path: modelPath.value, language: language.value, backend: backend.value };
      for (const kind of ["llm", "asr"]) {
        const control = controls[kind];
        payload[kind] = { base_url: control.baseUrl.value.trim(), model: control.model.value.trim(), api_key: control.key.value, clear_key: control.clear.checked };
        if (control.key.value && control.clear.checked) throw new Error(t("填写新密钥和删除密钥不能同时选择，请保留一种操作。"));
      }
      payload.glossary = glossary.value.split("\n").map((line) => line.trim()).filter(Boolean).map((line, index) => {
        const separator = line.includes("=") ? line.indexOf("=") : line.indexOf("\t");
        if (separator < 1) throw new Error(tt`术语表第 ${index + 1} 行请使用“术语 = 说明”格式。`);
        return { term: line.slice(0, separator).trim(), meaning: line.slice(separator + 1).trim() };
      });
      state.settings = await api("/api/settings", "PUT", payload);
      for (const kind of ["llm", "asr"]) controls[kind].key.value = "";
      renderControls();
      closeModal(true);
      notify(t("设置已保存在本机。尚未向任何外部接口发送材料，也未验证连接。"));
    } });
    if (focusSection) window.setTimeout(() => $("settings-" + focusSection)?.scrollIntoView({ block: "start" }), 30);
  }
  async function exportLecture() {
    const format = $("export-format").value;
    $("export-format").value = "";
    if (!format || !state.lecture || state.busy) return;
    const lecture = state.lecture;
    await runAction(null, "", async () => {
      let response;
      try { response = await fetch(`/api/lectures/${encodeURIComponent(lecture.id)}/export?format=${encodeURIComponent(format)}&ui=${I18N.language}`, { credentials: "same-origin" }); }
      catch (_) { throw new Error(t("无法连接本地服务，请重试。")); }
      if (!response.ok) { let error = {}; try { error = await response.json(); } catch (_) { /* safe default */ } throw new Error(error.error || t("导出失败，请重试。")); }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = lecture.title.replace(/[\\/:*?"<>|]/g, "_") + "." + format;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10000);
      notify(t("导出文件已准备。请检查浏览器的下载记录。"));
    });
  }
  async function openDemo() {
    await runAction($("demo-button"), t("正在打开示例…"), async () => {
      const result = await api("/api/demo", "POST", {ui_language:I18N.language});
      await refreshState();
      const detail = await api(`/api/lectures/${encodeURIComponent(result.lecture_id)}`);
      state.lecture = detail;
      state.courseId = detail.course_id;
      renderLibrary();
      renderLecture();
      switchView("transcript");
      notify(t("已打开明确虚构的演示材料。它不是真实教师录音，也不是模型生成结果。"));
    });
  }

  if (window.location.protocol === "file:") {
    renderLecture();
    $("startup-guide").hidden = false;
    $("workspace-status").textContent = t("静态预览 · 未连接服务");
    document.querySelectorAll("button, input, select").forEach((control) => {
      if (!control.closest(".mobile-tabs")) control.disabled = true;
    });
    document.querySelectorAll(".mobile-tabs button").forEach((node) => node.addEventListener("click", () => switchView(node.dataset.view)));
    switchView("transcript");
    return;
  }

  $("add-course").addEventListener("click", showCourse);
  $("ui-language").addEventListener("change", () => {
    if(state.busy || state.loading || modalDirty || modalBusy || $("modal").open || pendingConfirmation) {
      $("ui-language").value=I18N.language;
      notify(t("请先完成当前操作或关闭未保存的编辑，再切换界面语言。"),true); return;
    }
    I18N.switchTo($("ui-language").value,state.lecture?.id);
  });
  $("new-lecture").addEventListener("click", showNewLecture);
  $("empty-new-lecture").addEventListener("click", showNewLecture);
  $("edit-lecture").addEventListener("click", showEditLecture);
  $("lecture-search").addEventListener("input", renderLibrary);
  $("segment-search").addEventListener("input", renderSegments);
  $("transcript-view").addEventListener("change", renderSegments);
  $("recording-language").addEventListener("change", async () => {
    if (!state.lecture) return;
    if ($("recording-language").value === "mixed") { renderLecture(); showRecordingLanguage(null, true); return; }
    try { await updateDetail(await api(`/api/lectures/${encodeURIComponent(state.lecture.id)}`, "PUT", {asr_language:$("recording-language").value})); }
    catch (error) { notify(error.message, true); renderLecture(); }
  });
  $("language-help").addEventListener("click", () => showRecordingLanguage());
  $("category-filter").addEventListener("change", renderNotes);
  $("review-filter").addEventListener("change", renderNotes);
  $("settings-button").addEventListener("click", () => showSettings());
  $("import-button").addEventListener("click", showImport);
  $("sync-sources").addEventListener("click", syncLocalSources);
  $("audio-button").addEventListener("click", () => $("audio-input").click());
  $("audio-input").addEventListener("change", uploadAudio);
  $("audio-version").addEventListener("change", switchAudioVersion);
  $("generate-denoised").addEventListener("click", generateDenoised);
  $("resume-local-asr").addEventListener("click", () => startLocalAsr(true));
  $("restart-local-asr").addEventListener("click", () => startLocalAsr(false));
  $("dock-toggle").addEventListener("click", () => {
    const player = $("audio-player");
    if (player.paused) player.play().catch(() => notify(t("无法继续播放，请检查本地录音。")));
    else player.pause();
  });
  $("dock-stop").addEventListener("click", () => {
    seekSequence += 1;
    audioLoadSequence += 1;
    $("audio-player").pause();
    state.playbackStarted = false;
    state.dockDismissed = true;
    updatePlayingSegment();
  });
  $("transcribe-button").addEventListener("click", showTranscriptionRoutes);
  $("scene-select").addEventListener("change", changeScene);
  $("output-language").addEventListener("change", changeOutputLanguage);
  $("output-language-settings").addEventListener("click", () => showWorkflow());
  $("workflow-settings").addEventListener("click", () => showWorkflow());
  $("ai-correct").addEventListener("click", correctTranscript);
  $("review-corrections").addEventListener("click", showCorrections);
  $("cancel-local-asr").addEventListener("click", async () => {
    if (!state.lecture) return;
    try { localJob = (await api(`/api/lectures/${encodeURIComponent(state.lecture.id)}/local-asr/cancel`, "POST", {})).job; renderJob(); }
    catch (error) { notify(error.message, true); }
  });
  $("local-generate").addEventListener("click", () => generate("local"));
  $("llm-generate").addEventListener("click", () => generate("llm"));
  $("overview-generate").addEventListener("click", () => generate("overview"));
  $("overview-tab").addEventListener("click", () => setNotesView("overview"));
  $("detail-tab").addEventListener("click", () => setNotesView("details"));
  for (const id of ["overview-tab", "detail-tab"]) $(id).addEventListener("keydown", event => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const overview = event.key === "Home" || event.key !== "End" && notesView !== "overview";
      setNotesView(overview ? "overview" : "details");
      $(overview ? "overview-tab" : "detail-tab").focus();
    }
  });
  $("add-note").addEventListener("click", () => editNote());
  $("archived-notes").addEventListener("click", showArchived);
  $("export-format").addEventListener("change", exportLecture);
  $("demo-button").addEventListener("click", openDemo);
  $("modal-form").addEventListener("submit", submitModal);
  $("confirm-cancel").addEventListener("click", () => { if (pendingConfirmation) pendingConfirmation(false); });
  $("confirm-accept").addEventListener("click", () => { if (pendingConfirmation) pendingConfirmation(true); });
  $("confirm-dialog").addEventListener("cancel", (event) => { event.preventDefault(); if (pendingConfirmation) pendingConfirmation(false); });
  $("modal-form").addEventListener("input", () => { modalDirty = true; });
  $("modal-form").addEventListener("change", () => { modalDirty = true; });
  $("modal-close").addEventListener("click", () => closeModal());
  $("modal-cancel").addEventListener("click", () => closeModal());
  $("modal").addEventListener("cancel", (event) => { event.preventDefault(); closeModal(); });
  document.querySelectorAll(".mobile-tabs button").forEach((node) => node.addEventListener("click", () => switchView(node.dataset.view)));
  $("audio-player").addEventListener("timeupdate", updatePlayingSegment);
  $("audio-player").addEventListener("pause", updatePlayingSegment);
  $("audio-player").addEventListener("play", () => { state.playbackStarted = true; state.dockDismissed = false; updatePlayingSegment(); });
  $("audio-player").addEventListener("seeked", updatePlayingSegment);
  $("audio-player").addEventListener("ended", updatePlayingSegment);
  $("audio-player").addEventListener("error", () => { if (state.lecture && state.lecture.audio) notify(/\.(qta|qat|qt|mov)$/i.test(state.lecture.audio.name || "") ? t("浏览器无法直接播放这份 QuickTime 录音。原件已保存，可用本地 FFmpeg 生成听课版，或在语音备忘录中重新导出 M4A；不要只修改后缀。") : t("录音暂时无法播放。请检查文件格式，或重新添加录音；转写和笔记仍保留。"), true); });
  window.addEventListener("beforeunload", (event) => { if (modalDirty || modalBusy || state.busy) { event.preventDefault(); event.returnValue = ""; } });
  deliveryTools = window.LectureDelivery({$, el, input, select, field, button, check, showModal, closeModal, api, confirmAction, notify,
    state:() => state, setSettings:value => { state.settings = value; renderControls(); }, reloadLecture:async () => { if (state.lecture) await updateDetail(await api(`/api/lectures/${encodeURIComponent(state.lecture.id)}`)); }});
  revisionTools = window.LectureRevisions({$, el, button, field, input, textarea, select, check, api, showModal, closeModal, confirmAction, notify,
    state:() => state, updateDetail, renderSegments, showSettings, excerptPlayer, startRepair, editSegment});
  renderLecture();
  refreshState().then(async () => {
    const match = /^#lecture=([A-Za-z0-9_-]+)$/.exec(window.location.hash);
    if (match) await openLecture(match[1]);
  }).catch((error) => {
    notify(error.message + t(" 刷新页面可重新连接。"), true, true);
    $("lecture-list").replaceChildren(button(t("重新连接本地服务"), "button secondary full-width", () => refreshState().then(() => notify(t("已连接本地服务。"))).catch((err) => notify(err.message, true, true))));
  });
})();
