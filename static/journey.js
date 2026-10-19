/* Five stops, real controls. Opening the map never submits a model request. */
(function(root){
  "use strict";
  const STEPS=[
    {id:1,title:["收集素材","Gather material"],result:["录音或文字稿","Audio or transcript"],where:["左侧新建课次；中间点「添加录音」或「导入转写稿」。","Create a session on the left, then choose Add audio or Import transcript in the middle."],output:["一份独立保存的课程、讲座或会议材料。","A saved session with your lecture, talk or meeting material."],action:["前往添加素材","Go to material"]},
    {id:2,title:["获得文字","Get a transcript"],result:["带时间码的转写稿","A timed transcript"],where:["点「选择转写路线」：本地 Whisper，或听悟网页转写后导回。已有稿可直接去第 3 站。","Choose a transcription route: local Whisper, or Tingwu on the web followed by import. With an existing transcript, continue to stop 3."],output:["可阅读、搜索，并按真实时间码回听的文字。","Readable, searchable text linked to audio when real timestamps are available."],action:["打开转写路线","Open transcription routes"]},
    {id:3,title:["回听校对","Listen & review"],result:["可追溯的校订稿","A reviewed transcript"],where:["中间点「边听边改」编辑文字；也可点「AI 校对稿」审阅修改建议。","Use Listen & edit in the middle panel, or AI proofread to review proposed corrections."],output:["保留原稿、修改记录和已接受修订的文字稿。","An editable transcript with original text, revision history and accepted changes."],action:["前往原文校对","Go to transcript review"]},
    {id:4,title:["提炼笔记","Create notes"],result:["重点、决策、详细笔记","Key points, decisions & notes"],where:["右侧选用途和输出语言，点「AI 总览与详细笔记」；模型接口在右上角设置。","Choose the purpose and output language on the right, then AI overview + detailed notes. Configure the model in Settings."],output:["带原文出处的笔记与总览；会议可单列决策和行动。","Source-linked notes and an overview, with decisions and actions for meetings."],action:["前往笔记设置","Go to note settings"]},
    {id:5,title:["带走成果","Take it with you"],result:["文稿、笔记或 Notion 页面","Documents, notes or a Notion page"],where:["中间「导出校对稿」保存完整文稿；右侧「导出」保存笔记，也可发送到 Notion。","Export transcript editions in the middle; Export notes on the right, or send them to Notion."],output:["Word、PDF、Markdown 等文件，或一个 Notion 子页面。","Word, PDF, Markdown and other files, or a child page in Notion."],action:["前往导出成果","Go to export"]},
  ];
  function plan(state){
    const item=state.lecture,segments=item?.segments||[],hasText=segments.length>0;
    const hasMaterial=!!item?.audio||hasText,hasNotes=!!item?.overview||item?.generation?.mode==="llm";
    const reviewed=hasText&&segments.every(s=>s.review_status==="verified");
    return {current:!hasMaterial?1:!hasText?2:!reviewed?3:!hasNotes?4:5,
      available:[true,!!item?.audio||hasText,hasText,hasText,hasText||!!item?.notes?.length],
      complete:[hasMaterial,hasText,reviewed,hasNotes,false]};
  }
  if(typeof module!=="undefined"&&module.exports){module.exports={STEPS,plan};return;}
  root.LectureJourney=function(ctx){
    const {$,el,button}=ctx,en=root.LectureI18n.language==="en",text=pair=>pair[en?1:0];
    const dialog=el("dialog","journey-dialog");dialog.id="journey-dialog";dialog.setAttribute("aria-labelledby","journey-title");
    const head=el("div","journey-header"),heading=el("div");heading.append(el("span","journey-kicker","A LITTLE EXPEDITION"));
    const title=el("h2","",en?"Your map to clearer notes":"沿着线索，找到你的笔记");title.id="journey-title";
    heading.append(title,el("p","",en?"Five stops. Choose a numbered marker to see where to click and what you get.":"五站小旅程。点选数字标记，看看在哪里操作、会得到什么。"));
    const close=button("×","journey-close",()=>dialog.close());close.setAttribute("aria-label",en?"Close journey map":"关闭流程地图");head.append(heading,close);
    const map=el("div","treasure-map");
    // Static local SVG, separate from all user-supplied material.
    map.innerHTML='<svg class="map-landscape" viewBox="0 0 1000 500" preserveAspectRatio="none" aria-hidden="true"><defs><pattern id="map-grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#cdbd9666" stroke-width=".6"/></pattern></defs><rect width="1000" height="500" fill="url(#map-grid)"/><path class="map-trail-shadow" d="M155 105C255 20 275 180 495 105S865 5 835 115C950 305 320 205 465 370S105 495 145 365"/><path class="map-trail" d="M155 105C255 20 275 180 495 105S865 5 835 115C950 305 320 205 465 370S105 495 145 365"/><g class="map-sketch" fill="none" stroke="#81916c" stroke-width="1.6"><path d="m30 273 35-64 35 64m-53-30 18 9 15-9M894 389l26-49 28 49m-39-30 11 6 12-6M40 434q24-15 48 0t48 0m-96 11q24-15 48 0t48 0M582 234v-28a22 22 0 0 1 44 0v28m-34 0v-28a12 12 0 0 1 24 0M660 434l15-22 15 22m-15-22v40m-12-8h24M255 226q15-27 30 0h-30m13-22v-13"/></g><g transform="translate(936 62)" stroke="#8f7952" fill="none"><circle r="24"/><path d="M0-33V33M-33 0H33m-16-17L17 17m0-34L-17 17"/><path d="m0-22 6 22-6 22-6-22Z" fill="#bc815a" stroke-width=".8"/><text y="-40" text-anchor="middle" fill="#806b45" stroke="none" font-size="10">N</text></g><g transform="translate(765 388)" fill="none" stroke="#b27d4b" stroke-width="2"><path d="M-17 0h34v25h-34ZM-17 0q0-19 17-19T17 0M-2 0v25M-23 32h46"/><circle cx="0" cy="12" r="3" fill="#e7cc83"/></g><text x="732" y="457" font-size="11" letter-spacing="3" fill="#917950">THE TREASURE IS YOURS</text></svg>';
    const cards=STEPS.map(step=>{const card=button("","map-stop stop-"+step.id,()=>select(step.id));card.dataset.step=step.id;card.setAttribute("aria-controls","journey-detail");card.append(el("span","map-number",String(step.id).padStart(2,"0")),el("strong","",text(step.title)),el("span","map-result",text(step.result)),el("span","map-status",""));map.append(card);return card;});
    const detail=el("section","journey-detail");detail.id="journey-detail";detail.setAttribute("aria-live","polite");
    const footer=el("div","journey-footer"),help=el("a","",en?"Full user guide ↗":"完整使用说明 ↗");help.href="/help?ui="+root.LectureI18n.language;help.target="_blank";help.rel="noopener";
    footer.append(el("span","",en?"Explore at your own pace. Each stop is available separately.":"按自己的节奏前进，各站都可单独使用。"),help);dialog.append(head,map,detail,footer);document.body.append(dialog);
    let selected=1,returnFocus=null;
    function select(id){
      selected=id;const step=STEPS[id-1],p=plan(ctx.state());
      cards.forEach((card,i)=>{card.classList.toggle("selected",i===id-1);card.setAttribute("aria-pressed",String(i===id-1));card.querySelector('.map-status').textContent=p.complete[i]?(en?"Ready ✓":"已就绪 ✓"):p.current===i+1?(en?"You are here":"你在这里"):"";});
      detail.replaceChildren();const copy=el("div","journey-instructions");copy.append(el("span","journey-kicker",en?"WHERE TO CLICK":"点哪里"),el("p","",text(step.where)),el("span","journey-kicker",en?"WHAT YOU GET":"得到什么"),el("p","",text(step.output)));
      const actionLabel=id===2&&!ctx.state().lecture?.audio&&ctx.state().lecture?.segments?.length?(en?"Open existing transcript":"查看已有文字稿"):text(step.action);
      const actions=el("div","journey-actions"),go=button(actionLabel,"button primary",()=>{dialog.close();ctx.go(id);});go.id="journey-go";go.disabled=ctx.state().busy||ctx.state().loading||!p.available[id-1];actions.append(go);
      if(!p.available[id-1])actions.append(el("small","",en?"Start by adding material at stop 1.":"先在第 1 站添加所需材料。"));detail.append(copy,actions);
    }
    function open(id){if(dialog.open)return;returnFocus=document.activeElement;select(id||plan(ctx.state()).current);dialog.showModal();close.focus();}
    dialog.addEventListener("click",event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
    dialog.addEventListener("close",()=>{if(returnFocus?.isConnected)returnFocus.focus();});
    $("journey-button").addEventListener("click",()=>open());
    const shortNames=en?["Material","Transcript","Review","Notes","Export"]:["素材","转写","校对","笔记","导出"];
    const strip=$("workflow-strip");strip.replaceChildren(...STEPS.map(step=>{const node=button("","journey-chip",()=>open(step.id));node.dataset.step=step.id;node.title=text(step.title);node.append(el("b","",String(step.id).padStart(2,"0")),el("span","",shortNames[step.id-1]));return node;}));
    function refresh(){const p=plan(ctx.state());for(const node of strip.children){const id=Number(node.dataset.step);node.classList.toggle("is-current",id===p.current);node.classList.toggle("is-ready",p.complete[id-1]);if(id===p.current)node.setAttribute("aria-current","step");else node.removeAttribute("aria-current");}if(dialog.open)select(selected);}
    refresh();return {refresh,open};
  };
})(typeof window==="undefined"?{}:window);
