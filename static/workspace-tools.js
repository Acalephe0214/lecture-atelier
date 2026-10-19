/* Recoverable removal, with exact-target preview and explicit confirmation. */
window.LectureWorkspaceTools=function(ctx){
  const {$,el,button,api,showModal,closeModal,confirmAction,notify}=ctx,en=window.LectureI18n.language==="en";
  const tr=(zh,english)=>en?english:zh;let pending=false;
  async function remove(kind,id){
    if(pending||ctx.state().busy||ctx.state().loading)return;
    pending=true;
    try{
      const preview=await api(`/api/removal-preview?kind=${kind}&id=${encodeURIComponent(id)}`);
      const message=kind==="audio"?tr(`移除录音“${preview.name}”？\n文字稿和笔记保留，录音关联放入回收站，可随时恢复。`,`Remove audio “${preview.name}”?\nTranscript and notes are retained. The audio link goes to the recycle bin for recovery.`):tr(`将“${preview.name}”及 ${preview.lecture_count} 个课次移入回收站？\n相关文字稿、笔记和录音关联会一并保留，可从回收站恢复。`,`Move “${preview.name}” and ${preview.lecture_count} session(s) to the recycle bin?\nTheir transcripts, notes and audio links are retained for recovery.`);
      if(!(await confirmAction(message)))return;
      const endpoint=kind==="course"?`/api/courses/${encodeURIComponent(id)}`:`/api/lectures/${encodeURIComponent(id)}${kind==="audio"?"/audio":""}`;
      await api(endpoint,"DELETE",{confirm:true,revision:preview.revision});
      if($("modal").open)closeModal(true);
      await ctx.changed(kind,id);notify(tr("已移入回收站，可随时恢复。","Moved to the recycle bin. Restore it at any time."));
    }catch(error){notify(error.message,true,true)}finally{pending=false;refresh();}
  }
  function manage(){
    const body=el("div","course-manager");
    for(const course of ctx.state().courses){const row=el("div","management-row"),copy=el("div");const count=ctx.state().lectures.filter(l=>l.course_id===course.id).length;copy.append(el("strong","",ctx.courseLabel(course)),el("small","",tr(`${count} 个课次`,`${count} sessions`)));const control=button(tr("移除","Remove"),"button remove-button",()=>remove("course",course.id));control.dataset.courseId=course.id;row.append(copy,control);body.append(row);}
    if(!body.children.length)body.append(el("p","",tr("可从左侧创建课程。","Create a course from the left panel.")));
    body.append(el("p","field-hint",tr("移除后从回收站恢复；本机原文件保留。","Restore removed items from the recycle bin; original files are retained locally.")));
    showModal({title:tr("管理课程","Manage courses"),body,submit:tr("完成","Done"),action:()=>closeModal(true)});
  }
  async function recycle(){
    try{
      const result=await api("/api/recycle"),body=el("div","recycle-list");
      if(!result.entries.length)body.append(el("p","",tr("回收站是空的。","The recycle bin is empty.")));
      for(const entry of result.entries){const row=el("div","management-row"),copy=el("div"),kind={course:tr("课程","Course"),lecture:tr("课次","Session"),audio:tr("录音","Audio")}[entry.kind];copy.append(el("strong","",entry.name),el("small","",kind+" · "+new Date(entry.removed_at).toLocaleString(en?"en-GB":"zh-CN")));const restore=button(tr("恢复","Restore"),"button secondary",async()=>{if(pending)return;pending=true;restore.disabled=true;try{await api(`/api/recycle/${encodeURIComponent(entry.id)}/restore`,"POST",{confirm:true});closeModal(true);await ctx.changed("restore",entry.id);notify(tr("资料已恢复。","Material restored."));await recycle();}catch(error){notify(error.message,true,true)}finally{pending=false;restore.disabled=false;refresh();}});restore.dataset.recycleId=entry.id;row.append(copy,restore);body.append(row);}
      body.append(el("p","field-hint",tr("回收站保留资料和本地音频，便于恢复。","The recycle bin retains your data and local audio for recovery.")));
      showModal({title:tr("回收站","Recycle bin"),body,submit:tr("完成","Done"),action:()=>closeModal(true)});
    }catch(error){notify(error.message,true,true)}
  }
  $("manage-courses").addEventListener("click",manage);$("recycle-bin").addEventListener("click",recycle);
  $("remove-audio").addEventListener("click",()=>{if(ctx.state().lecture)remove("audio",ctx.state().lecture.id)});
  $("remove-lecture").addEventListener("click",()=>{if(ctx.state().lecture)remove("lecture",ctx.state().lecture.id)});
  function refresh(){const s=ctx.state();$("manage-courses").disabled=pending||s.busy||s.loading;$("recycle-bin").disabled=pending||s.busy||s.loading;$("remove-lecture").disabled=pending||s.busy||s.loading||!s.lecture;$("remove-audio").hidden=!s.lecture?.audio;$("remove-audio").disabled=pending||s.busy||s.loading;}
  return {refresh};
};
