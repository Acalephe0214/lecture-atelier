"use strict";
// Explicit UI translations only; source material and prompts stay untouched.
window.LectureDelivery = function (ctx) {
  const { $, el, input, select, field, button, check, showModal, closeModal, api, confirmAction, notify } = ctx;
  const en = window.LectureI18n.language === "en";
  const tr = (zh, english) => en ? english : zh;
  let signature = "", seq = 0;
  const panel = el("section", "usage-preview"); panel.id = "usage-preview"; panel.hidden = true;
  const heading = el("div", "usage-heading");
  const scope = select("estimate-scope", [["all", tr("总览 + 详细笔记", "Overview + details")], ["overview", tr("仅总览", "Overview only")]], "all");
  const complexity = select("estimate-complexity", [["light", tr("简单", "Light")], ["standard", tr("标准", "Standard")], ["deep", tr("复杂讨论 / 深入整理", "Complex / in-depth")]], "standard");
  heading.append(el("strong", "", tr("运行前预估", "Before you run")), button(tr("费率与 Notion ↗", "Rates & Notion ↗"), "text-button", settings));
  const options = el("div", "usage-options"); options.append(field(tr("预估任务", "Task"), scope), field(tr("预估复杂度", "Complexity estimate"), complexity));
  const numbers = el("div", "usage-numbers"); numbers.id = "usage-estimate-numbers";
  const price = el("p", "usage-price"); price.id = "usage-estimate-price";
  panel.append(heading, options, numbers, price, el("p", "usage-caveat", tr("字符法粗估，不是预算上限；包含再次提交原文作综合。复杂度只调整预估，不修改提示词。长推理可能超出区间；实际用量以接口账单为准。", "Character-based estimate, not a budget cap. Includes resubmitting source evidence. Complexity adjusts the estimate, not prompts. Long reasoning may exceed it; provider billing is authoritative.")));
  document.querySelector(".main-generate").before(panel);
  const opt = el("option", "", tr("PDF · 排版笔记", "PDF · designed notes")); opt.value = "pdf"; $("export-format").insertBefore(opt, $("export-format").options[1]);
  const notion = button(tr("发送到 Notion ↗", "Send to Notion ↗"), "text-button notion-export", exportNotion); notion.id = "notion-export"; document.querySelector(".notes-toolbar").after(notion);
  const number = n => Number(n || 0).toLocaleString(en ? "en-US" : "zh-CN");
  const range = r => r.map(number).join(" – ");
  const money = n => n < .01 ? n.toFixed(5) : n.toFixed(3);
  const label = d => `${d.model || tr("未选择模型", "No model")} · ${range(d.total_tokens)} token` + (d.price ? ` · ${d.price.currency} ${money(d.price.low)} – ${money(d.price.high)}` : "");
  async function fetchEstimate(chosenScope = scope.value) {
    const state = ctx.state(); if (!state.lecture) return null;
    return api(`/api/lectures/${encodeURIComponent(state.lecture.id)}/notes/estimate?scope=${chosenScope}&complexity=${complexity.value}`);
  }
  async function refresh(force = false) {
    const state = ctx.state(); panel.hidden = !state.lecture?.segments?.length; notion.disabled = !state.lecture || state.busy || state.loading;
    if (panel.hidden) { signature = ""; seq++; return; }
    const key = JSON.stringify([state.lecture.id, state.lecture.updated_at, state.lecture.workflow, state.lecture.segments, state.lecture.notes, state.settings.llm, state.settings.billing, scope.value, complexity.value]);
    if (!force && key === signature) return;
    signature = key; const id = ++seq; numbers.textContent = tr("正在本地估算…", "Estimating locally…"); price.textContent = "";
    try {
      const d = await fetchEstimate(); if (id !== seq) return;
      if (d.can_run === false) {
        numbers.replaceChildren(el("strong","usage-total",tr("当前任务无法开始","This task cannot start")));
        if (d.blocked_reason) {const reason=el("p");window.LectureI18n.renderDiagnostic(reason,d.blocked_reason);numbers.append(reason);}
        price.textContent=tr("没有调用模型，也不会按零费用承诺；请先处理上述问题。","No model was called. This is not a zero-cost quote; resolve the issue above first.");
        return;
      }
      numbers.replaceChildren(el("span", "usage-model", `${d.model || tr("未选择模型", "No model")} · ${number(d.source_chars)} ${tr("字 / 字符", "characters")}`), el("strong", "usage-total", `${range(d.total_tokens)} token`), el("small", "", `${tr("输入", "Input")} ${range(d.input_tokens)} · ${tr("输出", "Output")} ${range(d.output_tokens)}`), el("small", "", `${tr("预计请求", "Estimated requests")} ${range(d.requests)}`));
      for (const stage of d.stages || []) numbers.append(el("small","usage-stage",`${stage.name==="details"?tr("详细笔记阶段","Detail extraction"):stage.name==="overview"?tr("总览综合阶段","Overview synthesis"):tr("AI 校对阶段","AI proofreading")} · ${range(stage.requests)} ${tr("次请求","requests")} · ${range(stage.input_tokens.map((v,i)=>v+stage.output_tokens[i]))} token`));
      for (const warning of d.warnings || []) {const line=el("small","usage-plan-warning");window.LectureI18n.renderDiagnostic(line,warning);numbers.append(line);}
      if (d.price) {
        const p = d.price, r = p.rates;
        price.textContent = `${tr("费用粗估", "Estimated cost")} ${p.currency} ${money(p.low)} – ${money(p.high)} · ${r.as_of} · ${tr("按未命中缓存，不含税费 / 平台加价", "Uncached; excludes taxes / reseller fees")}`;
        if (r.source.startsWith("https://")) { const link = el("a", "", tr(" 官方费率 ↗", " Official rates ↗")); link.href = r.source; link.target = "_blank"; link.rel = "noopener noreferrer"; price.append(link); }
      } else price.textContent = tr("该模型费率未知，仅估算 token；可在“费率与 Notion”中填入每百万 token 单价。", "Unknown model rate: tokens only. Enter per-million rates in Rates & Notion.");
    } catch (error) { if (id === seq) { signature = ""; window.LectureI18n.renderDiagnostic(numbers,error.message); } }
  }
  function settings() {
    const saved = ctx.state().settings, billing = saved.billing || {}, ns = saved.notion || {};
    const enabled = check(tr("使用手动费率（仅适用于当前模型和地址）", "Use manual rates for this model and endpoint"), "manual-rates"); enabled.input.checked = !!billing.enabled;
    const currency = select("price-currency", ["USD", "CNY", "EUR", "GBP"].map(x => [x, x]), billing.currency || "USD");
    const fields = {}, body = [el("div", "modal-info", tr("本地保存，不会发起模型请求。费率单位为每百万 token；固定单价上下界填相同数值。", "Saved locally without model requests. Rates are per million tokens; use equal bounds for a fixed price.")), enabled.wrapper, field(tr("币种", "Currency"), currency)];
    for (const [name, zh, english] of [["input_low", "输入下界", "Input low"], ["input_high", "输入上界", "Input high"], ["output_low", "输出下界", "Output low"], ["output_high", "输出上界", "Output high"]]) {
      const node = input(name, billing[name] ?? "", "number"); node.min = "0"; node.step = "any"; fields[name] = node; body.push(field(tr(zh, english), node));
    }
    const parent = input("notion-parent", ns.parent_page_id || ""), token = input("notion-token", "", "password"); token.autocomplete = "new-password"; token.placeholder = tr("留空保留已有 token", "Leave blank to retain existing token");
    const clear = check(tr("删除已保存的 Notion token", "Delete saved Notion token"), "notion-clear");
    const guide = el("a", "", tr("创建 Notion connection / integration ↗", "Create a Notion connection / integration ↗")); guide.href = "https://app.notion.com/developers/connections"; guide.target = "_blank"; guide.rel = "noopener noreferrer";
    body.push(el("h3", "", tr("Notion · 单向页面导出", "Notion · one-way page export")), el("p", "", tr("创建有写入权限的 internal connection，并在目标父页面 Connections 中添加它。只发送总览和详细笔记，不上传录音或整份转写；每次确认后新建子页面。", "Create an internal connection with write access, then add it under the parent page’s Connections. Only overview and notes are sent, not audio or the full transcript. Each confirmed export creates a child page.")), guide, field(tr("目标父页面链接 / ID", "Parent page link / ID"), parent), field(tr("Connection token（不是 LLM API key）", "Connection token (not your LLM API key)"), token), clear.wrapper);
    showModal({title:tr("费率与 Notion", "Rates & Notion"), body, submit:tr("保存", "Save"), action:async () => {
      if (token.value && clear.input.checked) throw new Error(tr("新 token 与删除不能同时选择。", "A new token and deletion cannot both be selected."));
      if (enabled.input.checked && Object.values(fields).some(node => node.value === "")) throw new Error(tr("请填写四个费率数值。", "Enter all four rate values."));
      const llm = ctx.state().settings.llm || {}, payload = {billing:{enabled:enabled.input.checked,currency:currency.value,model:llm.model || "",base_url:llm.base_url || ""},notion:{parent_page_id:parent.value,token:token.value,clear_key:clear.input.checked}};
      for (const name of Object.keys(fields)) payload.billing[name] = Number(fields[name].value || 0);
      ctx.setSettings(await api("/api/settings", "PUT", payload)); token.value = ""; closeModal(true); refresh(true); notify(tr("已保存，未向外部发送材料。", "Saved. No content sent externally."));
    }});
  }
  async function exportNotion() {
    const state = ctx.state(), lecture = state.lecture; if (!lecture || state.busy) return;
    if (!state.settings.notion?.configured || !state.settings.notion?.parent_page_id) { settings(); return; }
    notion.disabled = true;
    try {
      const preview = await api(`/api/lectures/${encodeURIComponent(lecture.id)}/notion/preview?ui=${en ? "en" : "zh"}`);
      if (!(await confirmAction(`${tr("将总览与详细笔记发送到 Notion，新建子页面。不上传录音或整份转写。", "Send overview and notes to a new Notion child page. No audio or full transcript.")}\n\n${preview.title}\n${tr("父页面", "Parent")}: ${preview.parent_page_id}\n${preview.blocks} blocks · ${preview.requests} requests`))) return;
      const previous = lecture.notion_export; let acknowledge_previous;
      if (previous && ["unknown", "sending"].includes(previous.status)) {
        if (!(await confirmAction(tr("上次导出结果未确认，可能已有部分页面。请先在 Notion 检查。你确认仍要另建新页面吗？", "The last export is unconfirmed and may have created a partial page. Check Notion first. Do you explicitly want another new page?")))) return;
        acknowledge_previous = previous.id;
      }
      lecture.notion_export = await api(`/api/lectures/${encodeURIComponent(lecture.id)}/notion/export`, "POST", {allow_external:true,parent_page_id:preview.parent_page_id,ui:en ? "en" : "zh",acknowledge_previous});
      const link = el("a", "notion-result", tr("在 Notion 打开已创建页面 ↗", "Open the created Notion page ↗")); link.href = lecture.notion_export.url; link.target = "_blank"; link.rel = "noopener noreferrer"; $("notion-result")?.remove(); link.id = "notion-result"; notion.after(link); notify(tr("Notion 页面已创建。", "Notion page created."));
    } catch (error) { notify(error.message, true, true); await ctx.reloadLecture(); }
    finally { notion.disabled = false; }
  }
  scope.addEventListener("change", () => refresh(true)); complexity.addEventListener("change", () => refresh(true));
  return { refresh, async confirm(scopeName) {
    scope.value=scopeName;refresh(true);
    const d=await fetchEstimate(scopeName);if(!d)return false;
    if(d.can_run===false){notify(d.blocked_reason||tr("当前任务无法开始","This task cannot start"),true,true);return false;}
    const warnings=(d.warnings||[]).map(value=>window.LectureI18n.diagnostic(value)).join("\n");
    const task=scopeName==="overview"?tr("仅生成总览，保留现有详细笔记。","Generate only the overview; retain existing detailed notes."):tr("重新生成详细笔记，再生成总览。","Regenerate detailed notes, then synthesize the overview.");
    return confirmAction(`${tr("本次粗略预估（不是费用上限）", "Rough estimate for this run (not a spending cap)")}:\n${label(d)}\n\n${task}\n${warnings}\n\n${tr("长推理可能超出区间；接口账单为准。失败请求不自动重试。继续吗？","Long reasoning may exceed this range; provider billing is authoritative. No automatic retries. Continue?")}`);
  } };
};
