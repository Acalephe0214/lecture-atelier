"use strict";
// Local revision UI. Text-only API and audio recognition remain separate routes.
window.LectureRevisions = function(ctx) {
  const {$,el,button,field,input,textarea,select,check,api,showModal,closeModal,confirmAction,notify}=ctx;
  const en=window.LectureI18n.language==="en", tr=(zh,eng)=>window.LectureI18n.uiCopy(zh,eng);
  let lectureId=null,job=null,timer=null,polling=false,busy=false,showMarks=true,sequence=0;
  const bar=el("section","proofreading-bar");bar.id="proofreading-bar";bar.hidden=true;
  const heading=el("div","proofreading-heading"),title=el("strong","",tr("AI 校对稿","AI proofreading"));
  const marked=check(tr("显示修订标记","Show revisions"),"show-revisions",true);
  marked.input.addEventListener("change",()=>{showMarks=marked.input.checked;ctx.renderSegments();});
  heading.append(title,marked.wrapper);
  const legend=el("p","revision-legend");legend.append(el("del","",tr("原文","Original")),document.createTextNode(" → "),el("ins","",tr("最小修改","Minimal edit")),document.createTextNode(tr(" · ？表示推测，需要回听；蓝色不等于已核实。"," · ? = uncertain; listen back. Blue is not verified.")));
  const summary=el("p","proofreading-summary");summary.id="proofreading-summary";
  const actions=el("div","proofreading-actions");
  const acceptAll=button(tr("接受全部待确认修改","Accept all pending edits"),"button secondary compact",()=>bulk("accept"));acceptAll.id="accept-all-revisions";
  const rejectAll=button(tr("拒绝全部待确认修改","Reject all pending edits"),"text-button",()=>bulk("reject"));rejectAll.id="reject-all-revisions";
  actions.append(acceptAll,rejectAll);
  const progress=el("section","proofreading-progress");progress.id="proofreading-progress";progress.hidden=true;
  const phase=el("strong"),meter=el("progress"),detail=el("p"),usage=el("small");progress.append(phase,meter,detail,usage);
  const issues=el("details","proofreading-issues");issues.id="proofreading-issues";
  const issueSummary=el("summary"),issueList=el("div");issues.append(issueSummary,issueList);
  const automatic=el("details","proofreading-automatic"),autoTitle=el("summary"),autoList=el("div");automatic.append(autoTitle,autoList);
  bar.append(heading,legend,summary,actions,progress,issues,automatic);
  document.querySelector(".source-provenance").after(bar);
  const exportButton=button(tr("导出校对稿 ↗","Export transcript editions ↗"),"text-button",exports);exportButton.id="export-proofreading";$("review-corrections").after(exportButton);
  $("ai-correct").textContent=tr("AI 校对稿 ↗","AI proofread ↗");
  const session=()=>ctx.state().lecture?.proofreading;
  const rowFor=sid=>session()?.rows.find(row=>row.source_id===sid);
  const allEdits=()=>session()?.rows.flatMap(row=>row.edits.map(edit=>({...edit,source_id:row.source_id,stale:row.stale}))) || [];
  const active=()=>job&&["queued","running"].includes(job.status);
  function refresh() {
    const state=ctx.state(),lecture=state.lecture;
    if (lecture?.id!==lectureId) {lectureId=lecture?.id;sequence++;clearTimeout(timer);job=lecture?.proofreading_job||null;polling=false;}
    else if(!active()&&lecture?.proofreading_job) job=lecture.proofreading_job;
    exportButton.disabled=!lecture?.segments?.length||state.busy||state.loading;
    if(!lecture) {bar.hidden=true;return;}
    const edits=allEdits(),pending=edits.filter(e=>e.status==="pending"),auto=edits.filter(e=>e.auto_applied&&e.status==="accepted");
    bar.hidden=!session()&&!job;
    acceptAll.disabled=busy||active()||!pending.some(e=>!e.stale);rejectAll.disabled=busy||active()||!pending.length;
    $("ai-correct").disabled=state.busy||state.loading||active()||!lecture.segments.length;
    const accepted=edits.filter(e=>e.status==="accepted").length,rejected=edits.filter(e=>e.status==="rejected").length;
    summary.textContent=tr(`待确认 ${pending.length} · 已接受 ${accepted} · 已拒绝 ${rejected}。点击彩色改动逐处处理；校订稿只包含已接受修改。`,`Pending ${pending.length} · accepted ${accepted} · rejected ${rejected}. Click a colored edit to review. Revised exports include accepted edits only.`);
    if(edits.some(e=>e.stale)) summary.textContent+=tr(" 有原文已改变的旧建议，不会覆盖人工修改，可对该句重新 AI 校对。"," Some proposals are stale after source edits; re-proofread those sentences rather than overwrite them.");
    automatic.hidden=!auto.length;autoTitle.textContent=tr(`自动清理词内口吃 ${auto.length} 处（可撤销）`,`Automatic in-word stutter cleanup: ${auto.length} (undoable)`);autoList.replaceChildren();
    for(const edit of auto) autoList.append(button(`${edit.source_id} · ${edit.before || "∅"} → ${edit.after || "∅"} · ${tr("查看 / 撤销","Review / undo")}`,"text-button",()=>inspect(edit.source_id,edit.id)));
    const flags=session()?.flags||[],uncertain=edits.filter(e=>e.status==="pending"&&(e.uncertain||e.needs_audio));
    issues.hidden=!flags.length&&!uncertain.length;issueSummary.textContent=tr(`待回听疑点 ${flags.length+uncertain.length} 处`,`Listen-back issues: ${flags.length+uncertain.length}`);issueList.replaceChildren();
    for(const flag of flags) {const card=el("section","revision-flag");card.append(el("strong","",flag.source_id+" · "+tr("疑点，不改原文","Question only, source unchanged")),el("p","",flag.reason),el("small","",flag.query_terms||""),button(tr("回听 / 术语辅助补转","Listen / context-assisted ASR"),"text-button",()=>flagDialog(flag)));issueList.append(card);}
    for(const edit of uncertain) issueList.append(button(`${edit.source_id} · ${edit.reason}`,"text-button revision-issue-link",()=>inspect(edit.source_id,edit.id)));
    renderJob();
    if(active()&&!polling){polling=true;poll(lecture.id,sequence);}
  }
  function renderJob() {
    progress.hidden=!job;if(!job)return;
    const labels={queued:tr("等待校对","Queued"),running:tr("正在逐批校对","Proofreading batches"),completed:tr("校对建议已就绪","Suggestions ready"),failed:tr("校对未完成，原稿保留","Proofreading failed; source retained"),interrupted:tr("上次校对已中断","Previous run interrupted")};
    phase.textContent=labels[job.status]||job.status;meter.max=job.total_units||1;meter.value=job.completed_units||0;
    detail.textContent=`${job.completed_units||0} / ${job.total_units||1} · ${Math.floor(job.elapsed_seconds||0)}s · ${tr("收到输出字符","Output characters")} ${job.output_chars||0}`;
    const u=job.usage;usage.textContent=u?`${tr("接口已报告 token","Provider-reported tokens")}: ${u.prompt_tokens??"?"} + ${u.completion_tokens??"?"} = ${u.total_tokens??"?"}`:tr("接口尚未报告 token；未报告不是零。每秒刷新，不重复提交模型请求。","Tokens not reported yet (not zero). Refreshes every second without resubmitting requests.");
    if(job.status==="failed"||job.status==="interrupted") { const message=el("span","");window.LectureI18n.renderDiagnostic(message,job.message);detail.append(document.createTextNode(" · "),message); }
  }
  async function poll(id,seq) {
    try {
      const result=await api(`/api/lectures/${encodeURIComponent(id)}/proofreading/jobs`);
      if(seq!==sequence||ctx.state().lecture?.id!==id)return;
      job=result.job;renderJob();
      if(active()){timer=setTimeout(()=>poll(id,seq),1000);return;}
      polling=false;
      const lecture=await api(`/api/lectures/${encodeURIComponent(id)}`);
      if(seq===sequence&&ctx.state().lecture?.id===id)await ctx.updateDetail(lecture);
    } catch(error) {
      if(seq!==sequence)return;
      detail.textContent=tr("状态连接中断，正在重连；不会重新提交付费请求。","Status disconnected; reconnecting without resubmitting the paid request.");
      timer=setTimeout(()=>poll(id,seq),3000);
    }
  }
  async function start(sourceIds=null) {
    const state=ctx.state(),lecture=state.lecture;if(!lecture?.segments.length||state.busy||active())return;
    if(!state.settings.llm?.configured){ctx.showSettings("llm");return;}
    const cfg=lecture.proofreading_context||session()?.context||{};
    const topic=textarea("proofread-topic",cfg.topic||"",3);topic.maxLength=3000;topic.placeholder=tr("例：项目评审会议；用户体验、性能测试与改进计划。","Example: a project review on user experience, performance testing and planned improvements.");
    const terms=textarea("proofread-terms",cfg.terms||"",5);terms.maxLength=6000;terms.placeholder=tr("例：意向性、身体图式、前反思；或帧率、延迟、选项菜单。只提供词表，不编造原话。","Example: intentionality, body schema, pre-reflective; or frame rate, latency, options menu. Vocabulary is context, not evidence of spoken words.");
    const auto=check(tr("自动清理少量明确词内口吃（例如选选选项），保留可撤销记录","Automatically clean a small set of clear in-word stutters; keep undo history"),"proofread-auto",cfg.auto_stutter!==false);
    let estimate;
    try{estimate=await api(`/api/lectures/${encodeURIComponent(lecture.id)}/notes/estimate?scope=proofreading`);}
    catch(error){notify(error.message,true,true);return;}
    const cost=estimate.price?`${estimate.price.currency} ${estimate.price.low.toFixed(4)}–${estimate.price.high.toFixed(4)}`:tr("费率未知","Unknown rate");
    const intro=el("div","modal-info",tr("只校对文字，不做总结、不上传录音；尽量少改，术语和逻辑疑点标问号。文字模型不能确认录音里说了什么。","Text proofreading only: no summary or audio upload. Minimal edits; questionable terms/logic stay flagged. A text model cannot verify what the recording says."));
    showModal({title:tr(sourceIds?"重新校对选中片段":"AI 校对稿",sourceIds?"Re-proofread selected sentences":"AI transcript proofreading"),body:[intro,field(tr("话题 / 领域背景","Topic / domain context"),topic),field(tr("相关术语 / 姓名拼写（可留空）","Relevant terms / name spellings (optional)"),terms),auto.wrapper,el("p","field-hint",tr(`全稿粗估 ${estimate.total_tokens.join("–")} token · ${cost}，不是费用上限。选中片段通常用量更少。`,`Whole-transcript estimate: ${estimate.total_tokens.join("–")} tokens · ${cost}, not a spending cap. Selected sentences usually use less.`))],submit:tr("开始文字校对","Start text proofreading"),action:async()=>{
      const host=(()=>{try{return new URL(state.settings.llm.base_url).hostname;}catch{return state.settings.llm.base_url;}})();
      if(!(await confirmAction(tr(`将${sourceIds?"选中片段及其校对背景":"本节原文、术语表及校对背景"}发送至 ${host}（${state.settings.llm.model}）。不上传录音，可能产生 API 费用；不自动重试。${sourceIds?"选中句旧建议将归档；其他句建议保留。":"已有修订会归档，不覆盖尚未处理的待确认建议。"}继续吗？`,`Send ${sourceIds?"selected sentences":"this transcript"}, glossary and topic context to ${host} (${state.settings.llm.model})? No audio upload. API charges may apply; no automatic retries. ${sourceIds?"Selected sentences' old proposals are archived; other proposals remain.":"Existing revisions are archived; unresolved proposals must be handled first."}`))))return;
      const result=await api(`/api/lectures/${encodeURIComponent(lecture.id)}/proofreading/jobs`,"POST",{allow_external:true,context:{topic:topic.value,terms:terms.value,auto_stutter:auto.input.checked},...(sourceIds?{source_ids:sourceIds}:{})});
      job=result.job;lecture.proofreading_job=job;closeModal(true);refresh();
    }});
  }
  async function review(ids,action) {
    const state=ctx.state();if(busy||!session())return;
    busy=true;
    try{const result=await api(`/api/lectures/${encodeURIComponent(state.lecture.id)}/proofreading/review`,"POST",{session_id:session().id,edit_ids:ids,action});await ctx.updateDetail(result);}
    finally{busy=false;refresh();}
  }
  async function bulk(action) {
    const pending=allEdits().filter(e=>e.status==="pending"&&(action==="reject"||!e.stale));if(!pending.length)return;
    const unsure=pending.filter(e=>e.uncertain).length;
    if(!(await confirmAction(tr(`${action==="accept"?"接受":"拒绝"} ${pending.length} 处修改？其中 ${unsure} 处是推测。接受不等于音频核实；旧原文与审核记录保留。`,`${action==="accept"?"Accept":"Reject"} ${pending.length} edits, including ${unsure} uncertain guesses? Acceptance is not audio verification. Source snapshots and review history remain.`))))return;
    try{await review(pending.map(e=>e.id),action);}catch(error){notify(error.message,true,true);}
  }
  function hintFor(sid) {
    const cfg=ctx.state().lecture.proofreading_context||session()?.context||{};
    const flag=session()?.flags.find(f=>f.source_id===sid);
    return [cfg.topic,cfg.terms,flag?.query_terms].filter(Boolean).join("\n").slice(0,1200);
  }
  function audioTools(sid) {
    const state=ctx.state(),seg=state.lecture.segments.find(s=>s.id===sid),tools=el("div","revision-audio-tools");
    if(state.lecture.audio&&Number.isFinite(seg.start)&&Number.isFinite(seg.end)&&seg.end>seg.start&&seg.end-seg.start<=120) {
      tools.append(ctx.excerptPlayer(seg),button(tr("用术语提示重新 Whisper 补转这句","Re-run local Whisper with terminology hints"),"button secondary compact",()=>{closeModal(true);ctx.startRepair([sid],hintFor(sid));}),el("small","",tr("术语提示也会诱导误识别。先回听比较候选，采用后再点“重新 AI 核对这一句”；不会自动改写，也不上传音频。","Hints can bias ASR. Listen and compare the candidate, adopt it, then re-proofread this sentence. No automatic replacement or audio upload.")));
    } else tools.append(el("p","field-hint",tr("局部补转需要原录音及可靠起止时间，每段不超过 120 秒；缺少时可先人工校对。","Local repair requires audio and real start/end times, at most 120 seconds per sentence. Otherwise edit manually.")));
    tools.append(button(tr("重新 AI 核对这一句","Re-proofread this sentence"),"text-button",()=>{closeModal(true);start([sid]);}),button(tr("人工回听补字 / 编辑原句","Listen and edit manually"),"text-button",()=>{closeModal(true);ctx.editSegment(seg);}));
    return tools;
  }
  function inspect(sid,eid) {
    const row=rowFor(sid),edit=row?.edits.find(e=>e.id===eid);if(!edit)return;
    const body=[el("p","",edit.reason),el("small","",tr("原文片段","Original fragment")),el("p","revision-before",edit.before||tr("（此处为新增）","(insertion)")),el("small","",tr("建议替换","Replacement")),el("p","revision-after",edit.after||tr("（删除）","(deletion)"))];
    if(edit.uncertain)body.unshift(el("p","modal-info warning",tr("？这是文字推测，不是确定原话。建议先回听；接受后仍标为待复核。","? This is a text-based guess, not verified speech. Listen first; accepting keeps the sentence marked for review.")));
    if(row.stale)body.unshift(el("p","modal-info warning",tr("原句已改变，旧建议只作参考，不覆盖新文字。","Source changed. This stale proposal is reference only and will not overwrite it.")));
    if(edit.status==="pending"&&!row.stale)body.push(button(tr("拒绝这处修改","Reject this edit"),"button secondary",async()=>{try{await review([eid],"reject");closeModal(true);}catch(error){notify(error.message,true,true);}}));
    body.push(audioTools(sid));
    showModal({title:tr("逐处审阅修改","Review this edit"),body,submit:tr(row.stale||edit.status==="rejected"?"关闭":edit.status==="accepted"?"撤销这处修改":"接受这处修改",row.stale||edit.status==="rejected"?"Close":edit.status==="accepted"?"Undo this edit":"Accept this edit"),action:async()=>{if(!row.stale&&edit.status!=="rejected")await review([eid],edit.status==="accepted"?"undo":"accept");closeModal(true);}});
  }
  function flagDialog(flag) {showModal({title:tr("？待回听疑点","? Listen-back issue"),body:[el("p","",flag.reason),el("p","",flag.query_terms||""),audioTools(flag.source_id)],submit:tr("关闭","Close"),action:()=>closeModal(true)});}
  function paint(target,segment,term) {
    if(!showMarks)return false;
    const row=rowFor(segment.id),flag=session()?.flags.find(f=>f.source_id===segment.id);
    if(!row&&flag){target.replaceChildren();const mark=el("span","revision-flag-marker",segment.text);mark.tabIndex=0;mark.setAttribute("role","button");mark.append(el("sup","revision-question","？"));mark.addEventListener("click",()=>flagDialog(flag));mark.addEventListener("keydown",event=>{if(["Enter"," "].includes(event.key)){event.preventDefault();flagDialog(flag);}});target.append(mark);return true;}
    if(!row)return false;
    target.replaceChildren();let cursor=0;
    for(const edit of row.edits) {
      target.append(document.createTextNode(row.before.slice(cursor,edit.start)));
      if(row.stale){target.textContent=segment.text;return true;}
      if(edit.status==="rejected"||edit.auto_applied&&edit.status==="accepted") target.append(document.createTextNode(edit.status==="accepted"?edit.after:edit.before));
      else {
        const mark=el("span","revision-change "+edit.status);mark.tabIndex=0;mark.setAttribute("role","button");mark.dataset.editId=edit.id;mark.setAttribute("aria-label",tr("审阅此处修改","Review this edit"));
        if(edit.before)mark.append(el("del","",edit.before));if(edit.after)mark.append(el("ins","",edit.after));
        if(edit.uncertain)mark.append(el("sup","revision-question","？"));
        mark.title=edit.reason;mark.addEventListener("click",()=>inspect(segment.id,edit.id));mark.addEventListener("keydown",event=>{if(["Enter"," "].includes(event.key)){event.preventDefault();inspect(segment.id,edit.id);}});target.append(mark);
      }
      cursor=edit.end;
    }
    target.append(document.createTextNode(row.before.slice(cursor)));return true;
  }
  function exports() {
    const lecture=ctx.state().lecture;if(!lecture?.segments.length)return;
    const edition=select("transcript-edition",[["original",tr("校对前原稿（本轮快照）","Before proofreading (this pass)")],["marked",tr("带标记稿（包含待确认建议）","Marked (includes pending proposals)")],["clean",tr("校订稿（只含已接受修改）","Revised (accepted changes only)")]],"marked");
    const format=select("transcript-format",[["docx","Word (.docx)"],["pdf","PDF"],["html",tr("网页（保留颜色）","HTML (colored revisions)")],["md","Markdown"],["txt","TXT"],["json","JSON"],["srt","SRT"]],"docx");
    const layout=select("transcript-layout",[["reading",tr("阅读版 · 合并成段落（推荐）","Reading · merged paragraphs (recommended)")],["timeline",tr("时间线版 · 逐句保留编号和时间","Timeline · sentence IDs and timestamps")]],"reading");
    const timestamps=check(tr("阅读版显示每段起始时间","Show paragraph start times in reading layout"),"transcript-timestamps",false);
    const layoutHint=el("p","modal-info",tr("阅读版只合并排版，不改写文字；按停顿、说话人和篇幅分段，缺口独立保留。SRT 始终保留逐句时间码，JSON 同时保留全部原句与段落映射。","Reading layout joins text without rewriting it. Pauses, speakers and length define paragraphs; gaps stay separate. SRT always keeps sentence timing; JSON retains all source rows and paragraph mappings."));
    function sync(){const srt=Array.from(format.options).find(o=>o.value==="srt");srt.disabled=edition.value==="marked";if(srt.disabled&&format.value==="srt")format.value="docx";layout.disabled=["srt","json"].includes(format.value);timestamps.input.disabled=layout.disabled||layout.value!=="reading";}
    edition.addEventListener("change",sync);format.addEventListener("change",sync);layout.addEventListener("change",sync);sync();
    showModal({title:tr("导出三个版本的校对稿","Export transcript editions"),body:[field(tr("版本","Edition"),edition),field(tr("格式","Format"),format),field(tr("段落排版","Paragraph layout"),layout),timestamps.wrapper,layoutHint,el("p","modal-info",tr("校对前稿是本轮 AI 校对前的文字快照。带标记稿含已接受及待确认建议，拒绝的不展示。校订稿只包含已接受修改，未确认的不会混入。TXT 用 [-删除-] / [+新增+] 标记；SRT 不支持修订。","Original is the snapshot before this pass. Marked includes accepted edits and pending proposals, not rejected ones. Revised includes accepted edits only. TXT uses [-delete-] / [+insert+]; SRT does not support revisions."))],submit:tr("下载此版本","Download this edition"),action:async()=>{
      const response=await fetch(`/api/lectures/${encodeURIComponent(lecture.id)}/transcript/export?version=${edition.value}&format=${format.value}&layout=${layout.value}&timestamps=${timestamps.input.checked?"1":"0"}&ui=${en?"en":"zh"}`,{credentials:"same-origin"});
      if(!response.ok){const result=await response.json();throw new Error(result.error||tr("导出失败","Export failed"));}
      const url=URL.createObjectURL(await response.blob()),link=document.createElement("a");link.href=url;link.download=lecture.title.replace(/[\\/:*?"<>|]/g,"_")+"-"+edition.value+"."+format.value;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);closeModal(true);
    }});
  }
  return {refresh,start,paint,show:()=>{bar.hidden=false;bar.scrollIntoView({block:"center",behavior:"smooth"});}};
};
