#!/usr/bin/env python3
"""Loopback-only local lecture workspace. Requires Python 3.10+."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import mimetypes
import os
from pathlib import Path
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from store import Store, StoreError, now
from core import pipeline, paragraphs
from core import workflow
from local_sources import LocalSourceError, public_sources, sync_sources, audio_metadata
from audio_processing import processed_path, fingerprint, DenoiseJobs
from local_transcription import Jobs, probe
from local_repair import RepairJobs, resolve_issue
from core.languages import catalog as language_catalog, language
from note_jobs import NoteJobs
from core.word_export import export_docx
from core.pdf_export import export_pdf
from core import usage_estimate, notion_export
from core import redline
from correction_jobs import CorrectionJobs

ROOT = Path(__file__).resolve().parent
MAX_JSON = 8 * 1024 * 1024
MAX_AUDIO = 2 * 1024 * 1024 * 1024  # Local streamed upload; cloud gateway keeps its own 120 MiB cap.
REVIEWS = {"unreviewed", "verified", "needs_review"}
EDIT_SNAPSHOT_FIELDS = ("text", "start", "end", "review_status", "asr_issue")


class APIError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def edit_segments(lecture, edits, require_snapshot=False):
    """Validate the entire batch first; Store.mutate commits all edits atomically."""
    if not isinstance(edits, list) or not 1 <= len(edits) <= 1000:
        raise APIError("请选择 1—1000 条需要保存的原文。")
    by_id = {row["id"]: row for row in lecture["segments"]}
    seen, checked = set(), []
    for edit in edits:
        if not isinstance(edit, dict) or not isinstance(edit.get("id"), str) or edit["id"] in seen or edit["id"] not in by_id:
            raise APIError("原文编号无效或重复，请重新打开编辑窗口。", 409)
        seen.add(edit["id"])
        segment = by_id[edit["id"]]
        if require_snapshot or "expected" in edit:
            expected = edit.get("expected")
            if not isinstance(expected, dict) or set(expected) != set(EDIT_SNAPSHOT_FIELDS) or any(expected[key] != segment.get(key) for key in EDIT_SNAPSHOT_FIELDS):
                raise APIError("编辑期间原文或核查状态已变化，未覆盖新内容；请保留修改并重新打开此段。", 409)
        if "review_status" in edit and (not isinstance(edit["review_status"], str) or edit["review_status"] not in REVIEWS):
            raise APIError("审核状态无效。")
        value = edit.get("text", segment["text"])
        if not isinstance(value, str) or not value.strip() or len(value) > pipeline.MAX_SEGMENT_CHARS:
            raise APIError("转写内容不能为空，单段不能超过 16000 字符。")
        if edit.get("resolve_gap") is True and (not segment.get("asr_issue") or value.startswith("【转写缺口")):
            raise APIError("请先把缺口标记换成回听后补写的真实文字。")
        checked.append((segment, edit, value))
    for segment, edit, value in checked:
        before = deepcopy(segment)
        changed = value != segment["text"]
        if changed:
            segment.setdefault("original_text", segment["text"])
            segment["text"] = value
            segment["review_status"] = "unreviewed"
            segment["user_edited"] = True
            for note in lecture.get("notes", []):
                if segment["id"] in note["source_ids"] and note["review_status"] == "verified":
                    note["review_status"] = "needs_review"
            warning = "转写已修改，关联笔记需要重新核对；原始文本仍保留。"
            if warning not in lecture.setdefault("warnings", []):
                lecture["warnings"].append(warning)
        if "review_status" in edit:
            segment["review_status"] = edit["review_status"]
        if edit.get("resolve_gap") is True:
            resolve_issue(lecture, segment, "manual")
        if before != segment:
            lecture.setdefault("transcript_edit_history", []).append({"segment_id": segment["id"], "before": before, "after": deepcopy(segment), "edited_at": now()})


def install_transcript(item, parsed, original, replace=False):
    if item["segments"] and replace is not True:
        raise APIError("已有转写稿。替换会清除现有笔记，请确认后再替换。", 409)
    if item["segments"]:
        item.setdefault("transcript_history", []).append({key: item.get(key) for key in
            ("segments", "notes", "overview", "generation", "original_transcript", "transcript_source", "warnings", "source_context", "correction_history", "asr_report", "local_repair_state", "asr_repair_history", "proofreading", "proofreading_history", "proofreading_job", "transcript_edit_history")})
        item["transcript_history"][-1]["archived_at"] = now()
    item["correction_history"] = []
    item["transcript_edit_history"] = []
    item.pop("correction_proposal", None)
    for key in ("proofreading", "proofreading_history", "proofreading_job"):
        item.pop(key,None)
    item.pop("asr_report", None)
    item.pop("local_repair_state", None)
    item.pop("local_repair_private", None)
    item.pop("asr_repair_history", None)
    item["transcript_source"] = {"provider": "manual", "label": "手动导入", "filename": ""}
    item["segments"] = parsed["segments"]
    item["duration"] = parsed.get("duration", 0)
    item["transcript_format"] = parsed.get("format", "json")
    item["original_transcript"] = original
    item["warnings"] = parsed.get("warnings", [])
    item["notes"] = []
    item.pop("overview", None)
    item["generation"] = {"mode": "", "model": "", "created_at": ""}
    if item.get("local_sources"):
        item["local_sources"].pop("transcript", None)
        for key in list(item["local_sources"]):
            if key.startswith("reference-"):
                item["local_sources"].pop(key)
        item.pop("source_context", None)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, address, store):
        if address[0] != "127.0.0.1":
            raise ValueError("This application only binds to 127.0.0.1")
        self.store = store
        self.jobs = Jobs(store)
        self.repair_jobs = RepairJobs(store)
        self.asr_lock = threading.Lock()
        self.denoise_jobs = DenoiseJobs(store)
        self.note_jobs = NoteJobs(store)
        self.correction_jobs = CorrectionJobs(store)
        super().__init__(address, Handler)

    def server_close(self):
        self.jobs.close()
        self.repair_jobs.close()
        self.denoise_jobs.close()
        self.note_jobs.close()
        self.correction_jobs.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LectureAtelier"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def log_message(self, *_args):
        pass

    def _headers(self, status, content_type, length, **extra):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in extra.items():
            self.send_header(key.replace("_", "-"), str(value))
        self.end_headers()

    def _json(self, payload, status=200):
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(content))
        self.wfile.write(content)

    def _guard(self):
        expected = {"127.0.0.1:" + str(self.server.server_port), "localhost:" + str(self.server.server_port)}
        host = self.headers.get("Host", "").lower()
        if host not in expected:
            raise APIError("仅接受本机地址访问。", 403)
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + candidate for candidate in expected}:
            raise APIError("已拒绝来自其他网站的访问。", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise APIError("已拒绝来自其他网站的访问。", 403)
        if self.headers.get("Transfer-Encoding"):
            raise APIError("不支持分块上传，请提供明确文件大小。", 400)

    def _body_length(self, limit):
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            raise APIError("请求大小无效。") from None
        if size < 0:
            raise APIError("请求缺少内容大小。", 411)
        if size > limit:
            raise APIError("文件或请求过大。", 413)
        return size

    def _body(self):
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise APIError("请使用 JSON 请求。", 415)
        size = self._body_length(MAX_JSON)
        content = self.rfile.read(size)
        if len(content) != size:
            raise APIError("请求内容不完整。")
        try:
            value = json.loads(content)
        except (ValueError, UnicodeError):
            raise APIError("JSON 格式不正确。") from None
        if not isinstance(value, dict):
            raise APIError("请求内容必须为对象。")
        return value

    def _public(self, lecture):
        return self.server.store.public_lecture(lecture)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):
        self._dispatch("OPTIONS")

    def _dispatch(self, method):
        try:
            self._guard()
            parsed_url = urlsplit(self.path)
            path = unquote(parsed_url.path)
            query = parse_qs(parsed_url.query)
            store = self.server.store
            if method == "GET" and path == "/api/health":
                return self._json({"ok": True})
            if method == "GET" and path in {"/help", "/FRIEND-GUIDE.html", "/FRIEND-GUIDE-EN.html", "/START-HERE.html"}:
                if path == "/help":
                    filename = "FRIEND-GUIDE-EN.html" if query.get("ui") == ["en"] else "FRIEND-GUIDE.html"
                else:
                    filename = path[1:]
                content = (ROOT / filename).read_bytes()
                self._headers(200, "text/html; charset=utf-8", len(content))
                self.wfile.write(content)
                return
            if method == "GET" and path == "/api/state":
                return self._json({"courses": store.courses(), "lectures": store.lectures(), "settings": store.public_settings(), "workflow_catalog": workflow.catalog(), "language_catalog": language_catalog(), "version": "1.2"})
            if method == "POST" and path == "/api/local-asr/check":
                self._body()
                try:
                    return self._json(probe(store.private_settings()["local_asr"]))
                except ValueError as exc:
                    raise APIError(str(exc)) from None
            if method == "POST" and path == "/api/courses":
                return self._json(store.add_course(self._body().get("name")), 201)
            if method == "PUT" and path == "/api/settings":
                return self._json(store.update_settings(self._body()))
            if method == "POST" and path == "/api/demo":
                body = self._body()
                ui = body.get("ui_language", "zh")
                if not isinstance(ui, str) or ui not in {"zh", "en"}:
                    raise APIError("Interface language must be zh or en.")
                return self._json(self._demo(ui))
            if method == "POST" and path == "/api/lectures":
                body = self._body()
                result = store.create(body.get("course_id"), body.get("title"), body.get("date"))
                return self._json(self._public(result), 201)
            match = re.fullmatch(r"/api/lectures/([A-Za-z0-9_-]+)(?:/(.*))?", path)
            if match:
                return self._lecture(method, match[1], match[2] or "", query)
            if method == "GET" and not path.startswith("/api/"):
                return self._static(path)
            raise APIError("没有找到这个接口。", 404)
        except KeyError:
            self._json({"error": "没有找到这个课次或条目。"}, 404)
        except APIError as exc:
            self.close_connection = True
            self._json({"error": str(exc)}, exc.status)
        except (StoreError, LocalSourceError) as exc:
            self._json({"error": str(exc)}, 400)
        except pipeline.PipelineError as exc:
            # Only this controlled error type is allowed through. Defense in
            # depth removes configured secrets, URLs and unusually long text.
            message = str(exc)
            try:
                secrets = self.server.store.private_settings()
                for name in ("llm", "asr"):
                    for field in ("api_key", "base_url"):
                        value = secrets[name].get(field)
                        if value:
                            message = message.replace(value, "[已隐藏]")
            except Exception:
                message = "处理未完成，请检查输入与接口配置。"
            if len(message) > 500 or "Traceback" in message:
                message = "处理未完成，请检查输入与接口配置。"
            self._json({"error": message}, 400)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            self.close_connection = True
            self._json({"error": "操作未完成。请检查本地文件、输入格式与接口配置后重试。"}, 500)

    def _lecture(self, method, identity, action, query):
        store = self.server.store
        item = store.get(identity)
        if method == "POST" and action == "sources/sync":
            body = self._body()
            return self._json(self._public(sync_sources(store, identity, body.get("confirm_replace_transcript") is True)))
        if method == "GET" and not action:
            return self._json(self._public(item))
        if method == "PUT" and not action:
            body = self._body()
            def update(lecture):
                if "asr_language" in body:
                    try:
                        lecture["asr_language"] = language(body["asr_language"])
                    except ValueError as exc:
                        raise APIError(str(exc)) from None
                for field, maximum in (("title", 200), ("date", 10)):
                    if field in body:
                        value = body[field]
                        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                            raise APIError("课次标题或日期格式无效。")
                        if field == "date":
                            from datetime import datetime
                            try:
                                datetime.strptime(value, "%Y-%m-%d")
                            except ValueError:
                                raise APIError("日期须使用 YYYY-MM-DD 格式。") from None
                        lecture[field] = value.strip()
                if "course_id" in body:
                    if body["course_id"] not in {course["id"] for course in store.courses()}:
                        raise APIError("课程不存在。")
                    lecture["course_id"] = body["course_id"]
            return self._json(self._public(store.mutate(identity, update)))
        if method == "POST" and action == "transcript":
            body = self._body()
            parsed = pipeline.parse_transcript(body.get("text"), body.get("format", "auto"))
            source = body.get("source", "manual")
            providers = {"manual": "手动导入", "tingwu": "通义听悟", "other": "其他外部转写"}
            if not isinstance(source, str) or source not in providers:
                raise APIError("转写来源无效。")
            filename = body.get("filename", "")
            if not isinstance(filename, str) or len(filename) > 200:
                raise APIError("文件名无效。")
            def import_text(lecture):
                task = lecture.get("external_transcription")
                if source == "tingwu" and task and task.get("status") == "prepared":
                    expected = lecture.get("external_transcription_private", {}).get("audio_fingerprint")
                    if expected:
                        try:
                            matches = fingerprint(store.audio_path(lecture)) == expected
                        except (LocalSourceError, StoreError, OSError):
                            matches = False
                        if not matches:
                            raise APIError("任务准备后原录音已变化，请同步来源并重新准备任务，避免稿音不符。", 409)
                install_transcript(lecture, parsed, body.get("text", ""), body.get("replace") is True)
                lecture["transcript_source"] = {"provider": source, "label": providers[source], "filename": Path(filename).name}
                if source == "tingwu" and task:
                    task.update(status="imported", imported_at=now())
            result = store.mutate(identity, import_text)
            return self._json(self._public(result))
        if method == "PUT" and action == "workflow":
            try:
                body = self._body()
                if isinstance(body, dict) and "output_language" not in body:
                    body = {**body, "output_language": item.get("workflow", {}).get("output_language", "zh")}
                config = workflow.normalize(body)
            except ValueError as exc:
                raise APIError(str(exc)) from None
            def save_workflow(lecture):
                previous = lecture.get("workflow")
                presets = lecture.setdefault("workflow_presets", {})
                if previous:
                    presets[previous["scene"]] = previous
                presets[config["scene"]] = config
                lecture["workflow"] = config
            return self._json(self._public(store.mutate(identity, save_workflow)))
        if method == "GET" and action == "local-asr":
            return self._json({"job": self.server.jobs.get(identity)})
        if method == "POST" and action == "local-asr":
            body = self._body()
            if body.get("confirm_local") is not True:
                raise APIError("请确认本次在本机运行模型。")
            try:
                with self.server.asr_lock:
                    if any(job["status"] == "running" for job in list(self.server.repair_jobs.jobs.values())):
                        raise ValueError("局部补转正在使用本地模型，请等待结束。")
                    config = {**store.private_settings()["local_asr"], "language": body.get("language", item.get("asr_language", store.private_settings()["local_asr"]["language"]))}
                    job = self.server.jobs.start(identity, config, body.get("replace") is True, resume=body.get("resume", True) is not False)
            except ValueError as exc:
                raise APIError(str(exc)) from None
            return self._json({"job": job}, 202)
        if method == "GET" and action == "local-repair":
            return self._json({"job": self.server.repair_jobs.get(identity)})
        if method == "POST" and action == "local-repair":
            body = self._body()
            if body.get("confirm_local") is not True:
                raise APIError("请确认仅在本机重新识别所选片段。")
            try:
                with self.server.asr_lock:
                    if any(job["status"] in {"queued", "running", "cancelling"} for job in list(self.server.jobs.jobs.values())):
                        raise APIError("全文转写正在使用本地模型，请等待或取消后再局部补转。")
                    config = {**store.private_settings()["local_asr"], "language": body.get("language", item.get("asr_language", store.private_settings()["local_asr"]["language"]))}
                    config["hint_text"]=body.get("hint_text","")
                    job = self.server.repair_jobs.start(identity, body.get("segment_ids"), config)
                return self._json({"job": job}, 202)
            except ValueError as exc:
                raise APIError(str(exc)) from None
        if method == "POST" and action == "local-repair/cancel":
            self._body()
            try:
                return self._json({"job":self.server.repair_jobs.cancel(identity)})
            except ValueError as exc:
                raise APIError(str(exc)) from None
        if method == "POST" and action == "local-repair/apply":
            body = self._body()
            try:
                return self._json(self._public(self.server.repair_jobs.apply(identity, body.get("job_id"), body.get("segment_ids"))))
            except ValueError as exc:
                raise APIError(str(exc)) from None
        if method == "GET" and action == "audio/denoise":
            return self._json({"job": self.server.denoise_jobs.get(identity)})
        if method == "POST" and action == "audio/denoise":
            body = self._body()
            if body.get("confirm_local") is not True:
                raise APIError("请确认仅在本机生成降噪听课版，原录音会保留。")
            return self._json({"job": self.server.denoise_jobs.start(identity, body.get("profile", "denoised"))}, 202)
        if method == "POST" and action == "local-asr/cancel":
            self._body()
            try:
                return self._json({"job": self.server.jobs.cancel(identity)})
            except ValueError as exc:
                raise APIError(str(exc)) from None
        if method == "POST" and action == "external-transcription/prepare":
            body = self._body()
            if body.get("acknowledge_privacy") is not True:
                raise APIError("操作说明含本地文件位置，请先确认仅交给可信的浏览器助手。")
            path = store.audio_path(item)
            source_hash = fingerprint(path)
            job_id = "external-" + uuid4().hex
            def prepare_task(lecture):
                if lecture["audio"] != item["audio"]:
                    raise APIError("录音已更换，请重试。", 409)
                lecture["external_transcription"] = {"id": job_id, "provider": "tingwu", "status": "prepared", "prepared_at": now()}
                lecture["external_transcription_private"] = {"audio_fingerprint": source_hash}
            result = store.mutate(identity, prepare_task)
            prompt = workflow.browser_handoff(item["title"], path, item["audio"]["name"], item.get("workflow"),
                                              "http://127.0.0.1:" + str(self.server.server_port), identity)
            return self._json({"lecture": self._public(result), "prompt": prompt, "url": "https://tingwu.aliyun.com/home"})
        if method == "GET" and action == "proofreading/jobs":
            return self._json({"job":self.server.correction_jobs.get(identity)})
        if method == "POST" and action == "proofreading/jobs":
            body=self._body()
            if body.get("allow_external") is not True:
                raise APIError("请明确同意将原文、背景及术语发送到模型做文字校对；不上传录音。")
            if any(source["kind"]=="transcript" and source["state"]!="available" for source in public_sources(item)):
                raise APIError("索引原稿已变化，请先同步或核对。",409)
            try:
                return self._json({"job":self.server.correction_jobs.start(item,store.private_settings(),body.get("context"),body.get("source_ids"))},202)
            except ValueError as exc:
                raise APIError(str(exc)) from None
        if method == "POST" and action == "proofreading/review":
            body=self._body()
            try:
                updated=store.mutate(identity,lambda row:redline.review(row,body,now()))
                return self._json(self._public(updated))
            except ValueError as exc:
                raise APIError(str(exc),409) from None
        if method == "GET" and action == "transcript/export":
            from core.proofread_export import export
            try:
                content,mime,extension=export(item,query.get("version",["clean"])[0],query.get("format",["docx"])[0],query.get("ui",["zh"])[0]=="en",layout=query.get("layout",["reading"])[0],timestamps=query.get("timestamps",["0"])[0]=="1")
            except ValueError as exc:
                raise APIError(str(exc)) from None
            self._headers(200,mime,len(content),Content_Disposition='attachment; filename="transcript.'+extension+'"')
            self.wfile.write(content)
            return
        if method == "POST" and action == "corrections/propose":
            body = self._body()
            if body.get("allow_external") is not True:
                raise APIError("请明确同意本次发送文字校对材料。")
            result = pipeline.propose_corrections(item["segments"], store.private_settings()["llm"],
                                                   store.private_settings()["glossary"], allow_external=True)
            def save_proposal(lecture):
                if lecture["segments"] != item["segments"]:
                    raise APIError("处理期间原稿已变化，未保存过期校对建议。", 409)
                lecture["correction_proposal"] = {**result, "id": uuid4().hex, "created_at": now()}
            return self._json(self._public(store.mutate(identity, save_proposal)))
        if method == "POST" and action == "corrections/apply":
            body = self._body()
            selected = body.get("source_ids")
            if not isinstance(selected, list) or not selected or any(not isinstance(sid, str) for sid in selected) or len(selected) != len(set(selected)):
                raise APIError("请选择要应用的校对建议，编号不可重复。")
            def apply_proposal(lecture):
                proposal = lecture.get("correction_proposal")
                if not proposal or body.get("proposal_id") != proposal["id"] or workflow.digest(lecture["segments"]) != proposal["source_hash"]:
                    raise APIError("原稿已变化或建议已过期，请重新生成校对建议。", 409)
                mapping = {row["source_id"]: row for row in proposal["corrections"]}
                if any(sid not in mapping for sid in selected):
                    raise APIError("校对建议编号不存在。")
                for segment in lecture["segments"]:
                    if segment["id"] in selected:
                        segment["text"] = mapping[segment["id"]]["after"]
                        segment["review_status"] = "needs_review"
                for note in lecture["notes"]:
                    if set(note["source_ids"]).intersection(selected):
                        note["review_status"] = "needs_review"
                lecture.setdefault("correction_history", []).append({"proposal_id": proposal["id"], "model": proposal["model"],
                    "applied_at": now(), "changes": [mapping[sid] for sid in selected]})
                # Retain the unselected proposals against the new exact source state.
                proposal["corrections"] = [row for row in proposal["corrections"] if row["source_id"] not in selected]
                proposal["source_hash"] = workflow.digest(lecture["segments"])
            return self._json(self._public(store.mutate(identity, apply_proposal)))
        if action == "audio":
            if method == "GET":
                versions = query.get("version", ["original"])
                if len(versions) != 1 or versions[0] not in {"original", "denoised", "keyboard"}:
                    raise APIError("不支持这个录音版本。")
                return self._audio(item, versions[0])
            if method == "POST":
                return self._upload_audio(item, query)
        if method == "PUT" and action == "segments":
            body = self._body()
            return self._json(self._public(store.mutate(identity, lambda lecture: edit_segments(lecture, body.get("edits"), require_snapshot=True))))
        if method == "PUT" and action.startswith("segments/"):
            segment_id = action.split("/", 1)[1]
            body = self._body()
            return self._json(self._public(store.mutate(identity, lambda lecture: edit_segments(lecture, [{**body, "id": segment_id}]))))
        if method == "GET" and action == "notes/estimate":
            try:
                return self._json(usage_estimate.estimate(item, store.private_settings(), query.get("scope", ["all"])[0], query.get("complexity", ["standard"])[0]))
            except ValueError as exc:
                raise APIError(str(exc)) from None
        if method == "GET" and action == "notion/preview":
            try:
                return self._json(notion_export.preview(self._public(item), store.private_settings()["notion"], query.get("ui", ["zh"])[0] == "en"))
            except ValueError as exc:
                raise APIError(str(exc)) from None
        if method == "POST" and action == "notion/export":
            try:
                return self._json(notion_export.export(store, identity, self._body()))
            except ValueError as exc:
                raise APIError(str(exc)) from None
        if method == "GET" and action == "notes/jobs":
            return self._json({"job": self.server.note_jobs.get(identity)})
        if method == "GET" and action == "notes/jobs/diagnostics":
            return self._json(self.server.note_jobs.diagnostics(identity))
        if method == "POST" and action == "notes/jobs":
            body = self._body()
            if body.get("allow_external") is not True:
                raise APIError("请明确同意本次发送转写与笔记、并进行全局综合后再调用模型。")
            if any(source["kind"] == "transcript" and source["state"] != "available" for source in public_sources(item)):
                raise APIError("原稿来源已变化，请先同步或核对。", 409)
            scope = body.get("scope", "all")
            if item["notes"] and scope == "all" and body.get("replace") is not True:
                raise APIError("已有笔记，请明确确认替换。", 409)
            return self._json({"job": self.server.note_jobs.start(item, store.private_settings(), scope)}, 202)
        if method == "POST" and action == "notes/generate":
            body = self._body()
            if any(source["kind"] == "transcript" and source["state"] != "available" for source in public_sources(item)):
                raise APIError("索引原稿已变化或丢失，请先检查并同步本地来源；现有缓存和笔记仍保留。", 409)
            if not item["segments"]:
                raise APIError("请先导入转写稿。")
            if item["notes"] and body.get("replace") is not True:
                raise APIError("已有笔记。请确认替换后再生成。", 409)
            settings = store.private_settings()
            mode = body.get("mode", "local")
            if mode == "local":
                generated = pipeline.extract_local_notes(item["segments"], settings["glossary"])
            elif mode == "llm":
                if body.get("allow_external") is not True:
                    raise APIError("请明确同意本次发送转写内容后再调用模型。")
                generated = pipeline.generate_llm_notes(item["segments"], settings["llm"], settings["glossary"], allow_external=True,
                                                        workflow_config=item.get("workflow"))
            else:
                raise APIError("未知的笔记生成方式。")
            notes = pipeline.validate_notes(generated["notes"], item["segments"])
            for note in notes:
                note["review_status"] = "unreviewed"
                note["user_edited"] = False
            def save_notes(lecture):
                if lecture["segments"] != item["segments"] or lecture["notes"] != item["notes"] or lecture.get("workflow") != item.get("workflow"):
                    raise APIError("处理期间资料已发生变化，请重新生成。", 409)
                if lecture["notes"] or lecture.get("overview"):
                    lecture.setdefault("note_history", []).append({**{key:deepcopy(lecture.get(key)) for key in ("notes","overview","generation")},"archived_at":now()})
                lecture["notes"] = notes
                lecture.pop("overview", None)
                lecture["warnings"].extend(warning for warning in generated.get("warnings", []) if warning not in lecture["warnings"])
                lecture["generation"] = {"mode": mode, "model": generated.get("model", ""), "created_at": now()}
                if mode == "llm":
                    lecture["generation"].update(workflow.metadata(item.get("workflow")))
            return self._json(self._public(store.mutate(identity, save_notes)))
        if method == "POST" and action == "transcribe":
            body = self._body()
            if body.get("allow_external") is not True:
                raise APIError("请明确同意本次发送录音后再转写。")
            if item["segments"] and body.get("replace") is not True:
                raise APIError("已有转写稿。替换会清除笔记，请确认后再操作。", 409)
            parsed = pipeline.transcribe_audio(store.audio_path(item), store.private_settings()["asr"], allow_external=True)
            original = parsed.get("original_transcript") or json.dumps({"segments": parsed["segments"]}, ensure_ascii=False)
            def save_transcript(lecture):
                if lecture["segments"] != item["segments"] or lecture["audio"] != item["audio"] or lecture["notes"] != item["notes"]:
                    raise APIError("处理期间录音、转写或笔记已变化，请重试。", 409)
                install_transcript(lecture, parsed, original, body.get("replace") is True)
            return self._json(self._public(store.mutate(identity, save_transcript)))
        if method == "POST" and action == "notes":
            body = self._body()
            body["id"] = "note-" + uuid4().hex
            body["user_edited"] = True
            body.setdefault("review_status", "unreviewed")
            def add_note(lecture):
                lecture["notes"].extend(pipeline.validate_notes([body], lecture["segments"]))
                lecture["notes"][-1]["user_edited"] = True
            return self._json(self._public(store.mutate(identity, add_note)))
        if method == "POST" and action == "notes/restore":
            body = self._body()
            note_id = body.get("note_id")
            if not isinstance(note_id, str):
                raise APIError("请提供要恢复的笔记编号。")
            def restore_note(lecture):
                archived = lecture.get("deleted_notes", [])
                index = next((i for i, note in enumerate(archived) if note["id"] == note_id), None)
                if index is None:
                    raise KeyError(note_id)
                if any(note["id"] == note_id for note in lecture["notes"]):
                    raise APIError("当前已存在同编号笔记，请先处理冲突后再恢复。", 409)
                restored = dict(archived[index])
                current_sources = {segment["id"]: {"text": segment["text"], "original_text": segment["original_text"]}
                                   for segment in lecture["segments"] if segment["id"] in restored["source_ids"]}
                if restored.get("source_snapshot") != current_sources or set(current_sources) != set(restored["source_ids"]):
                    raise APIError("引用原文已更换或修改，无法自动恢复旧笔记。归档仍保留，可导出 JSON 后核对原文并手动新建笔记。", 409)
                restored.pop("deleted_at", None)
                restored.pop("source_snapshot", None)
                restored["review_status"] = "needs_review"
                restored = pipeline.validate_notes([restored], lecture["segments"])[0]
                lecture["notes"].append(restored)
                archived.pop(index)
            return self._json(self._public(store.mutate(identity, restore_note)))
        if method == "DELETE" and action.startswith("notes/"):
            note_id = action.split("/", 1)[1]
            def archive_note(lecture):
                index = next((i for i, note in enumerate(lecture["notes"]) if note["id"] == note_id), None)
                if index is None:
                    raise KeyError(note_id)
                note = dict(lecture["notes"].pop(index))
                note["deleted_at"] = now()
                note["source_snapshot"] = {
                    segment["id"]: {"text": segment["text"], "original_text": segment["original_text"]}
                    for segment in lecture["segments"] if segment["id"] in note["source_ids"]
                }
                archived = lecture.setdefault("deleted_notes", [])
                # Re-archiving a previously restored item replaces that archive.
                archived[:] = [old for old in archived if old["id"] != note_id]
                archived.append(note)
            return self._json(self._public(store.mutate(identity, archive_note)))
        if method == "PUT" and action.startswith("notes/"):
            note_id = action.split("/", 1)[1]
            body = self._body()
            def edit_note(lecture):
                index = next((i for i, note in enumerate(lecture["notes"]) if note["id"] == note_id), None)
                if index is None:
                    raise KeyError(note_id)
                note = dict(lecture["notes"][index])
                changed = False
                for field in ("category", "title", "content", "source_ids"):
                    if field in body:
                        changed = changed or body[field] != note[field]
                        note[field] = body[field]
                if changed:
                    note["user_edited"] = True
                    note["review_status"] = "unreviewed"
                if "review_status" in body:
                    note["review_status"] = body["review_status"]
                lecture["notes"][index] = pipeline.validate_notes([note], lecture["segments"])[0]
                lecture["notes"][index]["user_edited"] = note["user_edited"]
            return self._json(self._public(store.mutate(identity, edit_note)))
        if method == "GET" and action == "export":
            return self._export(item, query)
        raise APIError("没有找到这个接口。", 404)

    def _upload_audio(self, item, query):
        if item["audio"] and query.get("replace") != ["1"]:
            raise APIError("已有录音，请明确确认替换。", 409)
        size = self._body_length(MAX_AUDIO)
        if size == 0:
            raise APIError("录音文件不能为空。")
        mime = self.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].strip().lower()
        if not (mime.startswith("audio/") or mime in {"application/octet-stream", "video/mp4", "video/webm", "video/quicktime", "application/x-quicktimeplayer"}):
            raise APIError("请选择音频文件。", 415)
        if not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", mime):
            raise APIError("音频类型无效。")
        name = Path(unquote(self.headers.get("X-Filename", "recording"))).name
        name = "".join(character for character in name if ord(character) >= 32)[:200] or "recording"
        suffix = Path(name).suffix.lower()
        if suffix not in {".mp3", ".wav", ".m4a", ".mp4", ".ogg", ".webm", ".aac", ".flac", ".opus", ".qta", ".qat", ".qt", ".mov"}:
            suffix = ".audio"
        # Voice Memos QTA is a QuickTime container, often with a regular AAC
        # track plus spatial tracks. Preserve its bytes/extension, but serve an
        # audio media type instead of the browser's video/quicktime or empty MIME.
        if suffix in {".qta", ".qat", ".qt", ".mov"}:
            mime = "audio/mp4"
        storage_name = uuid4().hex + suffix
        path = self.server.store.audio_dir / storage_name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                remaining = size
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise APIError("录音上传不完整。")
                    handle.write(chunk)
                    remaining -= len(chunk)
            if suffix in {".qta", ".qat"}:
                try:
                    audio_metadata(path)
                except (LocalSourceError, OSError, ValueError, OverflowError):
                    raise APIError("无法读取这个 QTA/QuickTime 文件。请在 iPhone 语音备忘录中用非“可编辑”的方式导出 M4A 后重试；仅修改后缀不能转换编码。", 415) from None
            audio = {"name": name, "mime": mime, "size": size,
                     "url": "/api/lectures/" + item["id"] + "/audio", "storage_name": storage_name}
            def save_audio(lecture):
                if lecture["audio"] != item["audio"]:
                    raise APIError("处理期间录音已变化，请重新上传。", 409)
                lecture["audio"] = audio
                lecture.pop("asr_report", None)
                lecture.pop("local_asr_state", None)
                if lecture.get("local_sources"):
                    lecture["local_sources"].pop("audio", None)
                if lecture["segments"]:
                    warning = "录音已更新；现有转写并未自动重新转写，请核对对应关系。"
                    if warning not in lecture["warnings"]:
                        lecture["warnings"].append(warning)
                    for segment in lecture["segments"]:
                        segment["review_status"] = "needs_review"
                    for note in lecture["notes"]:
                        note["review_status"] = "needs_review"
            result = self.server.store.mutate(item["id"], save_audio)
        except Exception:
            if path.exists():
                path.unlink()
            raise
        # Keep old local bytes recoverable; never delete an existing user file.
        return self._json(self._public(result))

    def _audio(self, item, version="original"):
        path = self.server.store.audio_path(item) if version == "original" else processed_path(self.server.store, item, version)
        total = path.stat().st_size
        start, end, status = 0, total - 1, 200
        extra = {"Accept_Ranges": "bytes"}
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            if not match or not any(match.groups()):
                self._headers(416, "application/octet-stream", 0, Content_Range="bytes */" + str(total))
                return
            left, right = match.groups()
            if left:
                start = int(left)
                end = min(int(right), total - 1) if right else total - 1
            else:
                start = max(0, total - int(right))
            if start > end or start >= total:
                self._headers(416, "application/octet-stream", 0, Content_Range="bytes */" + str(total))
                return
            status = 206
            extra["Content_Range"] = f"bytes {start}-{end}/{total}"
        length = end - start + 1
        self._headers(status, item["audio"]["mime"] if version == "original" else "audio/mp4", length, **extra)
        with path.open("rb") as handle:
            handle.seek(start)
            while length:
                chunk = handle.read(min(1024 * 1024, length))
                if not chunk:
                    break
                self.wfile.write(chunk)
                length -= len(chunk)

    def _export(self, item, query):
        kind = query.get("format", ["md"])[0]
        public = self._public(item)
        if kind == "pdf":
            course_name = next((course["name"] for course in self.server.store.courses() if course["id"] == item["course_id"]), "")
            try:
                content = export_pdf(public, course_name, query.get("ui", ["zh"])[0] == "en")
            except ValueError as exc:
                raise APIError(str(exc)) from None
            self._headers(200, "application/pdf", len(content), Content_Disposition='attachment; filename="lecture-notes.pdf"')
            self.wfile.write(content)
            return
        if kind == "docx":
            course_name = next((course["name"] for course in self.server.store.courses() if course["id"] == item["course_id"]), "")
            content = export_docx(public, course_name, query.get("ui", ["zh"])[0] == "en")
            self._headers(200, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", len(content), Content_Disposition='attachment; filename="lecture-notes.docx"')
            self.wfile.write(content)
            return
        if kind == "json":
            text = json.dumps(public, ensure_ascii=False, indent=2)
            mime = "application/json"
        elif kind == "md":
            course_name = next((course["name"] for course in self.server.store.courses() if course["id"] == item["course_id"]), "")
            text = pipeline.export_markdown(public, course_name)
            mime = "text/markdown"
        elif kind == "srt":
            text = pipeline.export_srt(item["segments"])
            mime = "application/x-subrip"
        elif kind == "txt":
            text = paragraphs.reading_text(item["segments"])
            mime = "text/plain"
        else:
            raise APIError("不支持的导出格式。")
        content = text.encode("utf-8")
        self._headers(200, mime + "; charset=utf-8", len(content), Content_Disposition='attachment; filename="lecture.' + kind + '"')
        self.wfile.write(content)

    def _static(self, requested):
        static = (ROOT / "static").resolve()
        relative = "index.html" if requested == "/" else requested.lstrip("/")
        if relative.startswith("static/"):
            relative = relative[len("static/"):]
        destination = (static / relative).resolve()
        if not destination.is_relative_to(static) or not destination.is_file() or destination.suffix not in {".html", ".css", ".js", ".svg", ".png", ".ico"}:
            raise APIError("没有找到这个页面。", 404)
        content = destination.read_bytes()
        mime = mimetypes.guess_type(destination.name)[0] or "application/octet-stream"
        self._headers(200, mime + ("; charset=utf-8" if destination.suffix in {".html", ".css", ".js", ".svg"} else ""), len(content))
        self.wfile.write(content)

    def _demo(self, ui="zh"):
        store = self.server.store
        # One demo per workspace, regardless of UI language. Existing demo edits
        # (including a legacy language-specific demo) must never be overwritten.
        previous = next((row for row in store.lectures() if row.get("is_demo") and row["id"].startswith("lecture-synthetic-demo")), None)
        if previous:
            return {"lecture_id": previous["id"], "courses": store.courses(), "lectures": store.lectures()}
        identity = "lecture-synthetic-demo"
        transcript = """1
00:00:00,000 --> 00:00:18,000
【虚构演示，非真实课堂】今天我们用一个虚构案例练习区分观察与解释：小林看到一只杯子的一面，但仍将它理解为一个完整的杯子。

2
00:00:18,000 --> 00:00:40,000
课堂问题：没有直接呈现的另一面，是怎样进入当前经验的？这里的问题只用于演示笔记结构，不代表任何老师的授课内容。

3
00:00:40,000 --> 00:01:05,000
虚构讲者提出一种解释：当前所见带有对其他可能视角的期待。我们先把这作为待讨论的解释，而不是已经证明的结论。

4
00:01:05,000 --> 00:01:30,000
反对意见：如果期待错误，例如杯子背后其实是破损的，我们的理解会不会改变？本段未解决这一问题，需要回到例子继续讨论。
"""
        if ui == "en":
            transcript = """1
00:00:00,000 --> 00:00:18,000
[FICTIONAL DEMO, NOT A REAL CLASS] Alex sees one side of a cup but experiences it as a whole object. This invented example helps us distinguish observation from interpretation.

2
00:00:18,000 --> 00:00:40,000
Question: how does the unseen side belong to the experience? This practice question is not a statement by a real teacher.

3
00:00:40,000 --> 00:01:05,000
One fictional speaker suggests that perception includes expectations of other possible views. This is a proposal for discussion, not an established conclusion.

4
00:01:05,000 --> 00:01:30,000
Objection: what if the hidden side is damaged and the expectation is wrong? The example leaves this unresolved. Return to the source before drawing a conclusion.
"""
        try:
            store.get(identity)
        except KeyError:
            title = "Fictional demo · Different views of a cup" if ui == "en" else "虚构演示 · 一只杯子的不同视角"
            store.create(store.ensure_sample_course(), title, "2026-10-15", identity=identity, is_demo=True)
            parsed = pipeline.parse_transcript(transcript, "srt")
            generated = pipeline.extract_local_notes(parsed["segments"])
            if ui == "en":
                for index, note in enumerate(generated["notes"], 1):
                    note["title"] = f"Source excerpt {index} · Review needed"
            def setup(item):
                # Only initialize an empty demo; subsequent calls preserve edits.
                if item["segments"]:
                    return
                install_transcript(item, parsed, transcript)
                item["notes"] = pipeline.validate_notes(generated["notes"], parsed["segments"])
                item["warnings"].insert(0, "Entirely fictional practice material, not a real class or a verified philosophical explanation." if ui == "en" else "完全虚构的演示材料，不是真实课堂，也不是经学术核验的哲学解释。")
                item["generation"] = {"mode": "local", "model": "", "created_at": now()}
            store.mutate(identity, setup)
        return {"lecture_id": identity, "courses": store.courses(), "lectures": store.lectures()}


def make_server(port=8767, data_dir=None):
    return LocalServer(("127.0.0.1", port), Store(data_dir or ROOT / ".runtime"))


def main():
    parser = argparse.ArgumentParser(description="听课之间 · 本地课程笔记工作台")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--data-dir", default=str(ROOT / ".runtime"))
    parser.add_argument("--open", action="store_true", help="启动后在默认浏览器打开本地页面")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port 须为 1—65535")
    try:
        server = make_server(args.port, args.data_dir)
    except OSError:
        parser.exit(1, "无法启动：端口可能被占用，或数据目录不可写。可尝试 --port 8768。\n")
    url = "http://127.0.0.1:" + str(server.server_port)
    print("听课之间已启动：" + url)
    print("Lecture Atelier is running at: " + url + "/?ui=en")
    print("录音和笔记保存在本地。按 Ctrl+C 停止。")
    print("Keep this Terminal running. Stop with Control+C, not Command+C (copy).")
    if args.open:
        import webbrowser
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
