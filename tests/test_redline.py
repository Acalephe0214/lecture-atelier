"""Synthetic text only; no real API, recording or model used."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zipfile
from core import pipeline, redline
from core.proofread_export import export, data
from correction_jobs import CorrectionJobs
from store import Store
import test_server as server_helpers


def fixture():
    segments=pipeline.parse_transcript(json.dumps([
        {"text":"现在有三个选选选项，界面需要优花。","start":0,"end":20},
        {"text":"知决现象学讨论身体图试。","start":20,"end":40},
        {"text":"下周不发布，预算30元。","start":40,"end":60},
        {"text":"【转写缺口，非录音原文】","start":60,"end":75}]))["segments"]
    segments[-1]["asr_issue"]=True
    result={"model":"SYNTHETIC","corrections":[
        {"source_id":"s0001","before":segments[0]["text"],"after":"现在有三个选项，界面需要优化。","reason":"词内口吃和同音错字","certainty":"high","needs_audio":False},
        {"source_id":"s0002","before":segments[1]["text"],"after":"知觉现象学讨论身体图式。","reason":"根据术语猜测，需回听","certainty":"uncertain","needs_audio":True}],
        "flags":[{"source_id":"s0003","reason":"发布时间的语境可能矛盾，不能自行改否定词。","query_terms":"发布计划"},
                 {"source_id":"s0004","reason":"音频补转，不能凭背景补写缺口。","query_terms":""}]}
    item={"title":"合成校对课堂","date":"2026-10-18","segments":segments,"notes":[{"source_ids":["s0001"],"review_status":"verified"}]}
    session=redline.build(item,result,redline.context({"topic":"游戏优化与现象学词表示例","terms":"选项 优化 知觉现象学 身体图式"}),"2026-10-18T00:00:00Z")
    return item,result,session


class RedlineTests(unittest.TestCase):
    def setUp(self):
        self.item,self.result,self.session=fixture();redline.install(self.item,self.session)
    def edits(self,sid=None): return [edit for row in self.session["rows"] if sid is None or row["source_id"]==sid for edit in row["edits"]]
    def review(self,edit,action="accept"): redline.review(self.item,{"session_id":self.session["id"],"edit_ids":[edit["id"]],"action":action},"now")

    def test_auto_stutter_only_and_original_snapshot_intact(self):
        self.assertEqual(self.item["segments"][0]["text"],"现在有三个选项，界面需要优花。")
        self.assertIn("选选选项",redline.original_segments(self.item)[0]["text"])
        self.assertEqual(self.item["notes"][0]["review_status"],"needs_review")
        self.assertEqual(sum(edit.get("auto_applied",False) for edit in self.edits()),1)

    def test_character_edits_not_whole_paragraph_rewrites(self):
        nonauto=[e for e in self.edits("s0001") if not e["auto_applied"]]
        self.assertEqual([(e["before"],e["after"]) for e in nonauto],[("花","化")])

    def test_accept_and_reject_different_hunks_in_same_sentence(self):
        edits=self.edits("s0002");self.assertEqual(len(edits),2)
        self.review(edits[0]);self.review(edits[1],"reject")
        self.assertEqual(self.item["segments"][1]["text"],"知觉现象学讨论身体图试。")
        self.assertEqual(len(self.session["review_log"]),2)
        self.assertEqual(self.item["segments"][1]["review_status"],"needs_review")

    def test_automatic_cleanup_can_be_undone(self):
        auto=next(e for e in self.edits() if e["auto_applied"]);self.review(auto,"undo")
        self.assertIn("选选选项",self.item["segments"][0]["text"])

    def test_stale_one_sentence_does_not_block_other_sentence(self):
        self.item["segments"][1]["text"]="人工保留的文字"
        self.review(next(e for e in self.edits("s0001") if e["status"]=="pending"))
        self.assertIn("优化",self.item["segments"][0]["text"])
        with self.assertRaisesRegex(ValueError,"已被人工"):
            self.review(self.edits("s0002")[0])
        self.assertEqual(self.item["segments"][1]["text"],"人工保留的文字")

    def test_bad_ids_are_atomic_and_safe(self):
        before=deepcopy(self.item)
        for ids in ([],[{}],["missing"],[self.edits()[0]["id"]]*2):
            with self.assertRaises(ValueError): redline.review(self.item,{"session_id":self.session["id"],"edit_ids":ids,"action":"accept"},"now")
        self.assertEqual(self.item,before)

    def test_uncertain_and_pending_excluded_from_clean(self):
        clean=data(self.item,"clean");marked=data(self.item,"marked")
        self.assertIn("知决现象学",clean["rows"][1]["text"])
        self.assertTrue(any(run.get("uncertain") for run in marked["rows"][1]["runs"]))

    def test_marked_includes_automatic_history_but_ui_can_hide_it(self):
        self.assertTrue(any(r["kind"]=="delete" and "选" in r["text"] for r in redline.annotated_runs(self.item,"s0001",True)))
        self.assertFalse(any(r["kind"]=="delete" and "选" in r["text"] for r in redline.annotated_runs(self.item,"s0001")))

    def test_manual_edit_flags_session_as_stale(self):
        self.item["segments"][0]["text"]="人工版本"
        self.assertTrue(redline.public_session(self.item)["rows"][0]["stale"])

    def test_reject_stale_proposal_preserves_manual_text(self):
        self.item["segments"][1]["text"]="人工版本不被旧建议覆盖"
        self.review(self.edits("s0002")[0],"reject")
        self.assertEqual(self.item["segments"][1]["text"],"人工版本不被旧建议覆盖")

    def test_no_automatic_sentence_deduplication_or_negation_removal(self):
        for text in ("不不不，我没有同意。","哈哈哈哈。","先测试。先测试。先测试。"):
            self.assertEqual(redline.SAFE_STUTTERS.sub(lambda m:m.group()[0],text),text)

    def test_context_format_and_length_validation(self):
        for value in ([],{"topic":"文"*3001},{"terms":123}):
            with self.assertRaises(ValueError): redline.context(value)


class ProofreadModelTests(unittest.TestCase):
    def run_response(self,corrections,flags=None):
        item,_,_=fixture();settings={"base_url":"https://example.invalid","model":"synthetic"}
        body={"corrections":corrections,"flags":flags or []}
        with patch("core.pipeline._request_bytes",return_value=json.dumps({"choices":[{"message":{"content":json.dumps(body,ensure_ascii=False)}}]}).encode()) as req:
            result=pipeline.propose_corrections(item["segments"],settings,allow_external=True,correction_context={"topic":"现象学","terms":"身体图式"})
            payload=json.loads(req.call_args.args[1])
        return result,payload

    def test_context_and_minimal_guardrails_reach_model(self):
        _,payload=self.run_response([])
        self.assertEqual(json.loads(payload["messages"][1]["content"])["topic_context"]["topic"],"现象学")
        self.assertIn("不得声称已回听",payload["messages"][0]["content"])
        self.assertIn("最小修改",payload["messages"][0]["content"])

    def test_unknown_flags_and_duplicate_flags_rejected(self):
        for flags in ([{"source_id":"missing","reason":"x"}],[{"source_id":[],"reason":"x"}],[{"source_id":"s0001","reason":"x"}]*2):
            with self.assertRaises(pipeline.PipelineError): self.run_response([],flags)

    def test_gap_not_filled_from_topic(self):
        result,_=self.run_response([{"source_id":"s0004","text":"这句话是凭背景编造的","reason":"猜测","certainty":"high"}])
        self.assertEqual(result["corrections"],[]);self.assertTrue(result["flags"])

    def test_negation_and_numbers_are_flagged_not_replaced(self):
        for value in ("下周发布，预算30元。","下周不发布，预算300元。"):
            result,_=self.run_response([{"source_id":"s0003","text":value,"reason":"按语境猜测","certainty":"high"}])
            self.assertFalse(result["corrections"]);self.assertTrue(result["flags"])


class ProofreadExportTests(unittest.TestCase):
    def setUp(self): self.item,_,session=fixture();redline.install(self.item,session)
    def test_txt_three_editions_and_pending_not_accepted(self):
        original=export(self.item,"original","txt")[0].decode();marked=export(self.item,"marked","txt")[0].decode();clean=export(self.item,"clean","txt")[0].decode()
        self.assertIn("选选选项",original);self.assertIn("[-",marked);self.assertIn("[+",marked);self.assertIn("待回听",marked)
        self.assertIn("优花",clean);self.assertNotIn("优化",clean)
    def test_html_escapes_source_scripts(self):
        self.item["segments"][2]["text"]="<script>alert('unsafe')</script>"
        html=export(self.item,"clean","html")[0].decode()
        self.assertNotIn("<script>",html);self.assertIn("&lt;script&gt;",html)
    def test_word_real_ins_del_and_unique_ids(self):
        content=export(self.item,"marked","docx")[0]
        with zipfile.ZipFile(BytesIO(content)) as archive:
            document=ET.fromstring(archive.read("word/document.xml"));ns={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            ins=document.findall('.//w:ins',ns);dels=document.findall('.//w:del',ns)
            self.assertTrue(ins);self.assertTrue(dels)
            self.assertTrue(document.findall('.//w:delText',ns))
            ids=[node.attrib['{'+ns['w']+'}id'] for node in ins+dels];self.assertEqual(len(ids),len(set(ids)))
            self.assertIn(b'trackRevisions',archive.read("word/settings.xml"))
    def test_clean_word_has_no_tracked_changes(self):
        with zipfile.ZipFile(BytesIO(export(self.item,"clean","docx")[0])) as archive:
            self.assertNotIn(b'<w:ins ',archive.read("word/document.xml"));self.assertNotIn(b'<w:del ',archive.read("word/document.xml"))
    def test_srt_marked_refused_and_clean_timing_preserved(self):
        with self.assertRaises(ValueError): export(self.item,"marked","srt")
        self.assertIn(b'00:00:20,000',export(self.item,"clean","srt")[0])
    def test_json_marked_includes_unedited_issues(self):
        result=json.loads(export(self.item,"marked","json")[0]);self.assertTrue(result["rows"][2]["issues"])


class ProofreadJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name);self.item,self.result,_=fixture()
        row=self.store.create("course-sample",self.item["title"],"2026-10-18");self.identity=row["id"]
        self.store.mutate(self.identity,lambda row:row.update(self.item));self.jobs=CorrectionJobs(self.store)
        self.settings={"llm":{"base_url":"http://127.0.0.1:9999","model":"synthetic","api_key":"SYNTHETIC-SECRET"},"glossary":[]}
    def tearDown(self): self.jobs.close();self.tmp.cleanup()
    def wait(self):
        until=time.monotonic()+4
        while self.jobs.get(self.identity)["status"] in {"queued","running"} and time.monotonic()<until:time.sleep(.01)
        return self.jobs.get(self.identity)
    def test_background_saves_suggestions_and_keeps_key_private(self):
        def generated(*args,**kwargs):
            report=kwargs['on_progress'];report({"request_started":True});report({"usage":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120},"request_finished":True,"completed_units":1,"total_units":1});return self.result
        with patch("core.pipeline.propose_corrections",side_effect=generated):
            self.jobs.start(self.store.get(self.identity),self.settings,{"topic":"示例"});job=self.wait()
        self.assertEqual(job['status'],'completed',job);self.assertEqual(job['usage']['total_tokens'],120)
        saved=self.store.get(self.identity);self.assertIn('proofreading',saved);self.assertIn('优花',saved['segments'][0]['text'])
        self.assertNotIn('SYNTHETIC-SECRET',json.dumps(job))
    def test_failure_preserves_source_and_no_automatic_retry(self):
        original=self.store.get(self.identity)['segments']
        with patch("core.pipeline.propose_corrections",side_effect=pipeline.PipelineError('合成断线')) as req:
            self.jobs.start(self.store.get(self.identity),self.settings,{});job=self.wait();self.assertEqual(req.call_count,1)
        self.assertEqual(job['status'],'failed');self.assertEqual(self.store.get(self.identity)['segments'],original)
    def test_user_edit_during_generation_never_overwritten(self):
        def generated(*args,**kwargs):
            self.store.mutate(self.identity,lambda row:row['segments'][0].update(text='人工新版本'));return self.result
        with patch("core.pipeline.propose_corrections",side_effect=generated):
            self.jobs.start(self.store.get(self.identity),self.settings,{});job=self.wait()
        self.assertEqual(job['status'],'failed');self.assertEqual(self.store.get(self.identity)['segments'][0]['text'],'人工新版本')

    def test_targeted_recheck_keeps_other_pending_edits_and_history(self):
        item,result,session=fixture();self.store.mutate(self.identity,lambda row:redline.install(row,session))
        before=self.store.get(self.identity)
        old_ids={e['id'] for row in before['proofreading']['rows'] if row['source_id']=='s0001' for e in row['edits']}
        with patch('core.pipeline.propose_corrections',return_value={'corrections':[],'flags':[],'model':'synthetic'}):
            self.jobs.start(before,self.settings,{'topic':'只复核第二句'},['s0002']);job=self.wait()
        self.assertEqual(job['status'],'completed',job)
        saved=self.store.get(self.identity)
        new_ids={e['id'] for row in saved['proofreading']['rows'] if row['source_id']=='s0001' for e in row['edits']}
        self.assertEqual(new_ids,old_ids);self.assertEqual(len(saved['proofreading_history']),1)

    def test_restart_reports_interrupted_without_resubmitting(self):
        self.store.mutate(self.identity,lambda row:row.update(proofreading_job={'id':'old','status':'running'}))
        self.assertEqual(self.jobs.get(self.identity)['status'],'interrupted')

    def test_unresolved_full_pass_not_silently_replaced(self):
        _,_,session=fixture();self.store.mutate(self.identity,lambda row:redline.install(row,session))
        with self.assertRaises(pipeline.PipelineError): self.jobs.start(self.store.get(self.identity),self.settings,{})


class ProofreadApiTests(unittest.TestCase):
    setUp=server_helpers.ServerTests.setUp;tearDown=server_helpers.ServerTests.tearDown
    call=server_helpers.ServerTests.call;lecture=server_helpers.ServerTests.lecture;imported=server_helpers.ServerTests.imported
    def test_explicit_external_consent_required(self):
        row=self.imported();base=f"/api/lectures/{row['id']}"
        with patch('core.pipeline.propose_corrections') as req:
            self.assertEqual(self.call('POST',base+'/proofreading/jobs',{})[0],400);req.assert_not_called()
        self.assertEqual(self.call('GET',base+'/notes/estimate?scope=proofreading')[0],200)
    def test_review_and_three_export_routes(self):
        row=self.imported();item,_,session=fixture();self.server.store.mutate(row['id'],lambda value:value.update(item))
        self.server.store.mutate(row['id'],lambda value:redline.install(value,session));base=f"/api/lectures/{row['id']}"
        pending=next(edit for edit in session['rows'][0]['edits'] if edit['status']=='pending')
        status,value,_=self.call('POST',base+'/proofreading/review',{'session_id':session['id'],'action':'accept','edit_ids':[pending['id']]})
        self.assertEqual(status,200,value);self.assertIn('优化',value['segments'][0]['text'])
        for version in ('original','marked','clean'):
            self.assertEqual(self.call('GET',base+f'/transcript/export?version={version}&format=docx')[0],200)
    def test_replace_transcript_archives_revision_session(self):
        row=self.imported();item,_,session=fixture();self.server.store.mutate(row['id'],lambda value:value.update(item))
        self.server.store.mutate(row['id'],lambda value:redline.install(value,session))
        status,value,_=self.call('POST',f"/api/lectures/{row['id']}/transcript",{'text':'新的转写','replace':True,'format':'txt'})
        self.assertEqual(status,200);self.assertNotIn('proofreading',value);self.assertIn('proofreading',value['transcript_history'][-1])


if __name__=='__main__':unittest.main()
