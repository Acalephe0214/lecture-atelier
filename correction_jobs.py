"""Paid proofreading jobs: bounded batches, progress, no automatic retry."""
from copy import deepcopy
import threading
import time
from uuid import uuid4
from core import pipeline, redline, workflow
from note_jobs import NoteJobs, ACTIVE
from store import now


class CorrectionJobs(NoteJobs):
    def get(self, identity):
        with self.lock:
            if identity in self.jobs: return self.public(self.jobs[identity])
        job=self.store.get(identity).get("proofreading_job")
        if job and job.get("status") in ACTIVE:
            return {**job,"status":"interrupted","message":"服务重启中断了校对；原稿保留，不自动重新调用付费接口。"}
        return job

    def start(self,item,settings,cfg,selected=None):
        cfg=redline.context(cfg)
        if not item.get("segments"): raise pipeline.PipelineError("请先准备转写稿。")
        source=deepcopy(item)
        if selected is not None:
            if not isinstance(selected,list) or not selected or any(not isinstance(sid,str) for sid in selected) or len(set(selected))!=len(selected) or not set(selected)<=set(row["id"] for row in source["segments"]):
                raise pipeline.PipelineError("请选择有效的原文片段。")
            source["segments"]=[row for row in source["segments"] if row["id"] in selected]
        pipeline._configuration(settings["llm"],True,"LLM","/chat/completions")
        with self.lock:
            if self.closed.is_set() or any(job["status"] in ACTIVE for job in self.jobs.values()):
                raise pipeline.PipelineError("已有 AI 校对正在进行，请勿重复提交。")
            previous=item.get("proofreading",{})
            if selected is None and any(edit["status"]=="pending" for row in previous.get("rows",[]) for edit in row["edits"]):
                raise pipeline.PipelineError("还有待处理修改，请先接受或拒绝，避免覆盖尚未审阅的建议。")
            job={"id":"correction-"+uuid4().hex,"lecture_id":item["id"],"status":"queued","phase":"preparing","completed_units":0,"total_units":1,"message":"等待文字校对，不上传录音。","started_at":now(),"requests_started":0,"requests_finished":0,"usage_reports":0,"usage":None,"output_chars":0,"reasoning_chars":0,"_calls":[],"_current":None,"_started":time.monotonic()}
            self.jobs[item["id"]]=job
            self.store.mutate(item["id"],lambda row:row.update(proofreading_job=self.public(job),proofreading_context=cfg))
        thread=threading.Thread(target=self._run_correction,args=(job,deepcopy(item),source,deepcopy(settings),cfg),daemon=True)
        job["_thread"]=thread;thread.start()
        return self.get(item["id"])

    def _run_correction(self,job,item,source,settings,cfg):
        try:
            job["status"]="running"
            result=pipeline.propose_corrections(source["segments"],settings["llm"],settings["glossary"],allow_external=True,correction_context=cfg,on_progress=lambda event:self.report(job,event))
            session=redline.build(source,result,cfg,now())
            session["baseline_segments"]=deepcopy(item["segments"])
            if len(source["segments"])!=len(item["segments"]) and item.get("proofreading"):
                selected={row["id"] for row in source["segments"]}
                session["rows"].extend(deepcopy(row) for row in item["proofreading"]["rows"] if row["source_id"] not in selected)
                session["flags"].extend(deepcopy(flag) for flag in item["proofreading"]["flags"] if flag["source_id"] not in selected)
            with self.lock:
                if self.closed.is_set(): raise pipeline.PipelineError("服务关闭，未覆盖原稿。")
                def save(current):
                    if current["segments"]!=item["segments"] or current.get("proofreading")!=item.get("proofreading"):
                        raise pipeline.PipelineError("处理期间原文或修订状态已变化，过期结果未覆盖；请重新校对。")
                    redline.install(current,session)
                self.store.mutate(item["id"],save)
            job.update(status="completed",phase="completed",message="校对建议已在原文区标出；待确认不是已核实原话。")
        except Exception as exc:
            job.update(status="failed",message=str(exc)[:400] if isinstance(exc,pipeline.PipelineError) else "校对未完成，原稿保留；不会自动重试付费请求。")
        finally:
            job["elapsed_seconds"]=round(time.monotonic()-job["_started"],1)
            def persist(row):
                if row.get("proofreading_job",{}).get("id")==job["id"]: row["proofreading_job"]=self.public(job)
            try: self.store.mutate(item["id"],persist)
            except Exception: pass
