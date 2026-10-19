import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch

from core.languages import language, catalog, check_model
from core.asr_guard import inspect_result
from local_repair import apply_candidates, segment_digest, resolve_issue, joined_text, RepairJobs
from audio_processing import fingerprint
from store import Store


class RepairTests(unittest.TestCase):
    def test_word_collapse_error_survives_repair_word_cropping(self):
        from local_repair import worker
        raw={'segments':[{'start':0,'end':10,'text':'Normal speech', 'words':[{'word':'Normal speech','start':0,'end':10}]},
                         {'start':21,'end':30,'text':'Hallucinated words', 'words':[{'word':'invented','start':21,'end':29.9}] + [{'word':'token','start':29.9,'end':29.9} for _ in range(8)]}]}
        out=io.StringIO()
        with patch('local_repair.media_duration',return_value=30), patch('core.local_engine.transcribe',return_value=raw), contextlib.redirect_stdout(out):
            worker({'path':'unused.wav','config':{'backend':'faster'},'row':{'start':0,'end':30},'strategy':0})
        result=json.loads(out.getvalue())
        self.assertTrue(any('塌缩' in err for err in result['errors']))

    def setUp(self):
        self.segment = {"id":"s2", "start":30, "end":60, "text":"【转写缺口，非录音原文】", "review_status":"needs_review", "asr_issue":True}
        self.item = {"segments":[{"id":"s1", "text":"人工改好的内容", "review_status":"verified"}, copy.deepcopy(self.segment)],
            "notes":[{"id":"n1", "source_ids":["s2"], "review_status":"verified"}], "warnings":[],
            "asr_report":{"issues":[{"start":30,"end":60,"reasons":["test"]}]}}
        self.result = {"segment_id":"s2", "snapshot":segment_digest(self.segment), "candidate":"仅用于测试的补写内容。", "segments":[]}
        self.job = {"id":"j", "status":"completed", "source":"one", "results":[self.result]}

    def test_selected_candidate_keeps_ids_other_edits_notes_and_history(self):
        before = copy.deepcopy(self.item["segments"][0])
        apply_candidates(self.item, self.job, ["s2"], "one")
        self.assertEqual(self.item["segments"][0], before)
        self.assertEqual(self.item["segments"][1]["id"], "s2")
        self.assertFalse(self.item["segments"][1]["asr_issue"])
        self.assertEqual(self.item["segments"][1]["review_status"], "unreviewed")
        self.assertEqual(self.item["notes"][0]["review_status"], "needs_review")
        self.assertTrue(self.item["asr_report"]["issues"][0]["resolved"])
        self.assertEqual(self.item["asr_repair_history"][0]["before"], self.segment)

    def test_ready_candidate_can_be_applied_before_queue_finishes_or_after_stop(self):
        for status in ('running','cancelled','failed','interrupted'):
            item=copy.deepcopy(self.item)
            apply_candidates(item,{**self.job,'status':status},['s2'],'one')
            self.assertEqual(item['segments'][1]['text'],self.result['candidate'])
            self.assertEqual(item['segments'][1]['review_status'],'unreviewed')
        for state in ('applied','unresolved'):
            with self.assertRaises(ValueError):
                apply_candidates(copy.deepcopy(self.item),{**self.job,'results':[{**self.result,'status':state}]},['s2'],'one')

    def test_stale_edit_or_changed_audio_rejects_without_partial_update(self):
        for source, edit in [("two",False),("one",True)]:
            item = copy.deepcopy(self.item)
            if edit: item["segments"][1]["text"] = "刚刚手工填写"
            before = copy.deepcopy(item)
            with self.assertRaises(ValueError): apply_candidates(item, self.job, ["s2"], source)
            self.assertEqual(item, before)

    def test_unresolved_or_duplicate_selection_does_not_overwrite(self):
        for ids in (["s2","s2"],["missing"],[],["s1"]):
            with self.assertRaises(ValueError): apply_candidates(self.item, self.job, ids, "one")
        self.result["candidate"] = ""
        with self.assertRaises(ValueError): apply_candidates(self.item, self.job, ["s2"], "one")

    def test_manual_filled_is_not_automatically_verified(self):
        segment = self.item["segments"][1]
        resolve_issue(self.item, segment, "manual")
        self.assertEqual(segment["review_status"], "needs_review")
        self.assertEqual(self.item["asr_report"]["issues"][0]["resolved_by"], "manual")

    def test_short_tail_padding_clipped_but_bad_times_rejected(self):
        rows, errors = inspect_result({"segments":[{"start":29.78,"end":30.18,"text":"字"}]}, 30)
        self.assertFalse(errors)
        self.assertEqual(rows[0]["end"], 30)
        for a,b in [(29,31),(30.1,30.2),(4,4),(-1,2)]:
            self.assertTrue(inspect_result({"segments":[{"start":a,"end":b,"text":"字"}]}, 30)[1])

    def test_word_join_keeps_english_and_vietnamese_spaces(self):
        self.assertEqual(joined_text([{"text":"hello"},{"text":"world"}]), "hello world")
        self.assertEqual(joined_text([{"text":"tôi"},{"text":"là"}]), "tôi là")
        self.assertEqual(joined_text([{"text":"中文"},{"text":"课文"}]), "中文课文")

    def test_common_languages_and_unsupported_no_cloud_fallback(self):
        for code in ("vi","ja","zh_en","fr","de","zh","en","auto"): self.assertEqual(language(code), code)
        with self.assertRaises(ValueError): language("xx")
        self.assertIn("vi", catalog()["codes"])
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "config.json").write_text(json.dumps({"n_vocab":51864}))
            with self.assertRaises(ValueError): check_model({"model_path":directory,"language":"vi"})
            check_model({"model_path":directory,"language":"en"})


class RepairJobTests(unittest.TestCase):
    def test_public_progress_uses_real_counts_and_hides_private_clocks(self):
        job={'status':'running','total':3,'source':'private','_started':10,'_strategy_started':18,
             'current':{'segment_id':'s2'},'results':[{'status':'applied','candidate':'ok'},{'status':'unresolved','candidate':''}]}
        with patch('local_repair.time.monotonic',return_value=25): public=RepairJobs.public(job)
        self.assertEqual(public['elapsed_seconds'],15)
        self.assertEqual(public['strategy_elapsed_seconds'],7)
        self.assertEqual((public['completed'],public['applied_count'],public['unresolved_count']),(2,1,1))
        self.assertEqual(public['progress'],66)
        self.assertFalse(any(key.startswith('_') for key in public))
        self.assertNotIn('source',public)
        public['results'].clear()
        self.assertEqual(len(job['results']),2)

    def test_progress_reports_strategy_and_apply_during_next_passage_keeps_queue(self):
        first=self.store.get(self.item['id'])['segments'][0]
        second={**copy.deepcopy(first),'id':'s2','start':60,'end':90}
        self.store.mutate(self.item['id'],lambda row:row['segments'].append(second))
        rows=self.rows+[{'segment_id':'s2','start':60,'end':90,'snapshot':segment_digest(second)}]
        p1,p2=self.process(self.good),self.process(self.good)
        def during_second(payload,timeout):
            job=self.jobs.get(self.item['id'])
            self.assertEqual(job['status'],'running')
            self.assertEqual(job['completed'],1)
            self.assertEqual(job['current']['index'],2)
            self.assertEqual(job['current']['strategy_index'],1)
            saved=self.jobs.apply(self.item['id'],'job',['s1'])
            self.assertEqual(saved['segments'][0]['text'],self.good['segments'][0]['text'])
            return json.dumps(self.good),None
        p2.communicate.side_effect=during_second
        with patch('local_repair.subprocess.Popen',side_effect=[p1,p2]):
            self.jobs._run(self.item['id'],self.audio,rows,{'python_path':'python3'})
        job=self.jobs.get(self.item['id'])
        self.assertEqual(job['status'],'completed')
        self.assertEqual([r['status'] for r in job['results']],['applied','candidate'])
        self.assertEqual(job['completed'],2)
        self.assertEqual(job['applied_count'],1)
        self.assertEqual(job['results'][1]['attempt_log'][0]['passed'],True)

    def test_restored_running_candidate_can_be_applied_without_ghost_worker(self):
        item=self.store.get(self.item['id'])
        candidate={'segment_id':'s1','snapshot':segment_digest(item['segments'][0]),'candidate':'Synthetic restored candidate','status':'candidate','errors':[]}
        saved={'id':'interrupted-job','status':'running','total':2,'results':[candidate]}
        self.store.mutate(item['id'],lambda row:row.update(local_repair_state=saved,local_repair_private={'source':fingerprint(self.audio)}))
        self.jobs.jobs.clear()
        self.assertEqual(self.jobs.get(item['id'])['status'],'interrupted')
        result=self.jobs.apply(item['id'],'interrupted-job',['s1'])
        self.assertEqual(result['segments'][0]['text'],'Synthetic restored candidate')
        self.assertEqual(self.jobs.get(item['id'])['status'],'interrupted')

    def test_fifty_gap_queue_is_supported_without_running_models(self):
        self.jobs.jobs.clear()
        segments=[{"id":f"s{i}","start":i*30,"end":(i+1)*30,"text":"Synthetic gap", "asr_issue":True} for i in range(50)]
        self.store.mutate(self.item['id'],lambda row:row.update(segments=segments))
        with patch('local_repair.checked_config',return_value={'python_path':'python3'}), patch('local_repair.threading.Thread.start') as start:
            result=self.jobs.start(self.item['id'],[row['id'] for row in segments],{})
        self.assertEqual(result['total'],50)
        start.assert_called_once()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lecture-repair-test-")
        self.store = Store(self.temp.name)
        self.item = self.store.create("course-sample", "合成补转", "2026-10-17")
        self.audio = self.store.audio_dir / "synthetic.wav"
        self.audio.write_bytes(b"synthetic-only")
        segment = {"id":"s1","start":30,"end":60,"text":"【转写缺口，非录音原文】","asr_issue":True,"review_status":"needs_review"}
        self.store.mutate(self.item["id"], lambda row: row.update(audio={"storage_name":self.audio.name,"name":self.audio.name,"mime":"audio/wav"}, segments=[segment]))
        self.jobs = RepairJobs(self.store)
        self.rows = [{"segment_id":"s1","start":30,"end":60,"snapshot":segment_digest(segment)}]
        self.jobs.jobs[self.item["id"]] = {"id":"job","status":"running","results":[],"total":1,"message":"test","source":fingerprint(self.audio)}
        self.good = {"segments":[{"start":0,"end":30,"text":"这只是一个用于回归测试的合成转写候选，不是课堂真实材料。"}],"errors":[]}
        self.bad = {"segments":[],"errors":["合成循环告警"]}

    def tearDown(self):
        self.jobs.close()
        self.temp.cleanup()

    def process(self, result):
        from unittest.mock import Mock
        process = Mock(returncode=0)
        process.poll.return_value = 0
        process.communicate.return_value = (json.dumps(result), None)
        return process

    def test_changes_strategy_and_stops_at_first_passing_candidate(self):
        processes = [self.process(row) for row in (self.bad,self.bad,self.good)]
        with patch("local_repair.subprocess.Popen", side_effect=processes) as start:
            self.jobs._run(self.item["id"], self.audio, self.rows, {"python_path":"python3"})
        job = self.jobs.get(self.item["id"])
        self.assertEqual(start.call_count,3)
        self.assertEqual(job["status"],"completed")
        self.assertEqual(job["results"][0]["attempts"],3)
        self.assertIn("去瞬态点击",job["results"][0]["strategy"])
        self.assertTrue(self.store.get(self.item["id"])["segments"][0]["asr_issue"])
        self.assertNotIn("source",job)

    def test_four_failed_strategies_leave_explicit_unresolved_gap(self):
        with patch("local_repair.subprocess.Popen", side_effect=[self.process(self.bad) for _ in range(4)]) as start:
            self.jobs._run(self.item["id"], self.audio, self.rows, {"python_path":"python3"})
        job = self.jobs.get(self.item["id"])
        self.assertEqual(start.call_count,4)
        self.assertEqual(job["results"][0]["status"],"unresolved")
        self.assertEqual(job["results"][0]["candidate"],"")
        self.assertTrue(self.store.get(self.item["id"])["segments"][0]["asr_issue"])

    def test_timeout_is_bounded_and_does_not_change_text(self):
        processes = [self.process(self.bad) for _ in range(4)]
        for process in processes:
            process.communicate.side_effect = [subprocess.TimeoutExpired("test",180),("",None)]
            process.poll.return_value = None
        with patch("local_repair.subprocess.Popen", side_effect=processes):
            self.jobs._run(self.item["id"], self.audio, self.rows, {"python_path":"python3"})
        for process in processes: process.kill.assert_called_once()
        self.assertEqual(self.jobs.get(self.item["id"])["results"][0]["attempts"],4)

    def test_cancel_before_loading_never_runs_worker(self):
        self.jobs.cancel(self.item["id"])
        with patch("local_repair.subprocess.Popen") as start:
            self.jobs._run(self.item["id"], self.audio, self.rows, {"python_path":"python3"})
            start.assert_not_called()
        self.assertEqual(self.jobs.get(self.item["id"])["status"],"cancelled")

    def test_persisted_candidate_can_be_applied_after_service_restart(self):
        with patch("local_repair.subprocess.Popen", return_value=self.process(self.good)):
            self.jobs._run(self.item["id"], self.audio, self.rows, {"python_path":"python3"})
        restarted = RepairJobs(self.store)
        item = restarted.apply(self.item["id"],"job",["s1"])
        self.assertEqual(item["segments"][0]["review_status"],"unreviewed")
        self.assertFalse(item["segments"][0]["asr_issue"])
        self.assertEqual(item["local_repair_state"]["results"][0]["status"],"applied")
        self.assertNotIn("local_repair_private",self.store.public_lecture(item))
        restarted.close()


if __name__ == "__main__": unittest.main()
