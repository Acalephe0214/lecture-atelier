"""Regression cases from the workflow audit. Synthetic materials only."""
from copy import deepcopy
import json
import tempfile
import unittest
from unittest.mock import patch

from core import overview, pipeline, usage_estimate
from note_jobs import NoteJobs
from store import Store


def material(count=2664):
    rows=[{"id":f"s{i:04d}","text":f"Synthetic source {i}. Keep the complete statement, not a duplicated excerpt.",
           "speaker":"Speaker", "start":i*2,"end":i*2+2,"review_status":"unreviewed"} for i in range(count)]
    return {"segments":rows,"notes":pipeline.extract_local_notes(rows)["notes"],"workflow":{"scene":"meeting"},"title":"Synthetic audit"}


class WorkflowAuditTests(unittest.TestCase):
    def test_2664_source_cards_compact_without_mutation_or_missing_sources(self):
        item=material();before=deepcopy(item)
        planned=overview.plan(item["notes"],item["segments"])
        self.assertTrue(planned["fits_call_limit"])
        self.assertEqual(planned["source_copy_cards"],2664)
        self.assertLess(len(planned["groups"]),20)
        seen={row["id"] for group in planned["groups"] for row in group["sources"]}
        self.assertEqual(seen,{row["id"] for row in item["segments"]})
        self.assertEqual(item,before)
        for group in planned["groups"]:
            self.assertTrue(all("Synthetic source" not in row["content"] for row in group["entries"]))

    def test_human_and_verified_copies_stay_verbatim_and_uncited_audio_is_included(self):
        item=material(5)
        for field,value in (("user_edited",True),("review_status","verified")):
            notes=deepcopy(item["notes"][:1]);notes[0][field]=value
            planned=overview.plan(notes,item["segments"])
            self.assertEqual(planned["entries"][0]["content"],notes[0]["content"])
            self.assertNotIn("input_kind",planned["entries"][0])
            self.assertEqual(planned["added_source_passages"],4)
            self.assertEqual({s["id"] for g in planned["groups"] for s in g["sources"]},{s["id"] for s in item["segments"]})

    def test_all_ranges_ordered_and_stages_add_up_for_every_mode(self):
        item=material(70)
        for scene in ("class","lecture","meeting","discussion","custom"):
            item["workflow"]["scene"]=scene
            item["workflow"]["instructions"]="Summarize statements and preserve explicit decisions."
            for complexity in ("light","standard","deep"):
                for scope in ("all","overview","proofreading"):
                    result=usage_estimate.estimate(item,{},scope,complexity)
                    self.assertTrue(result["can_run"],result)
                    for key in ("input_tokens","output_tokens","total_tokens","requests"):
                        self.assertLessEqual(result[key][0],result[key][1])
                    for index in (0,1):
                        self.assertEqual(result["total_tokens"][index],sum(stage["input_tokens"][index]+stage["output_tokens"][index] for stage in result["stages"]))
                    if scope=="overview":self.assertLessEqual(result["requests"][1],overview.MAX_CALLS)

    def test_overview_reference_component_identical_not_artificially_clamped(self):
        item=material(2664)
        only=usage_estimate.estimate(item,{},"overview")
        full=usage_estimate.estimate(item,{},"all")
        self.assertEqual(only["stages"][0],full["stages"][-1])
        for index in (0,1):
            self.assertEqual(full["total_tokens"][index]-only["total_tokens"][index],full["stages"][0]["input_tokens"][index]+full["stages"][0]["output_tokens"][index])
        self.assertEqual(only["overview_plan"]["first_pass_groups"],len(overview.plan(item["notes"],item["segments"])["groups"]))

    def test_impossible_overview_blocked_before_any_call_or_job(self):
        item=material(1)
        item["notes"]=[{**item["notes"][0],"id":f"n{i}","content":"x"*19500,"user_edited":True} for i in range(140)]
        result=usage_estimate.estimate(item,{},"overview")
        self.assertFalse(result["can_run"])
        self.assertEqual(result["requests"],[0,0])
        self.assertIsNone(result["price"])
        # Full generation replaces these notes, so it can use source planning.
        self.assertTrue(usage_estimate.estimate(item,{},"all")["can_run"])
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);stored=store.create("course-sample","Synthetic","2026-10-18")
            stored=store.mutate(stored["id"],lambda row:row.update(item))
            jobs=NoteJobs(store)
            with patch("core.chat_stream.chat") as remote:
                with self.assertRaisesRegex(pipeline.PipelineError,"尚未调用"):
                    jobs.start(stored,{"llm":{"base_url":"http://127.0.0.1:9999","model":"synthetic"}},"overview")
                remote.assert_not_called()
            self.assertNotIn("generation_job",store.get(stored["id"]))
            jobs.close()

    def test_missing_notes_overview_and_invalid_references_are_not_cost_quotes(self):
        item=material(2);item["notes"]=[]
        self.assertFalse(usage_estimate.estimate(item,{},"overview")["can_run"])
        self.assertTrue(usage_estimate.estimate(item,{},"all")["can_run"])
        item=material(2);item["notes"][0]["source_ids"]=["missing"]
        self.assertFalse(usage_estimate.estimate(item,{},"overview")["can_run"])

    def test_json_wrappers_are_accepted_but_truncation_or_prose_are_not_repaired(self):
        for text in ('{"notes":[]}', '```json\n{"notes":[]}\n```'):
            self.assertEqual(pipeline.complete_json(text),{"notes":[]})
        for text in ('{"notes":', '```json\n{"notes":[]}', 'The answer is {"notes":[]}',None):
            with self.assertRaises(ValueError):pipeline.complete_json(text)

    def test_uncovered_fallback_copies_in_all_output_languages_are_indexed(self):
        from core import output_language
        for code in output_language.LANGUAGES:
            item=material(2)
            for row in item["notes"]:row["title"]=output_language.uncovered_title(code)
            self.assertEqual(overview.plan(item["notes"],item["segments"])["source_copy_cards"],2)

    def test_reference_index_hierarchy_can_converge_even_when_summary_text_is_longer(self):
        item=material(4)
        seen=[]
        def response(url,payload,headers,report):
            group=json.loads(payload["messages"][1]["content"]);seen.append(group)
            ids=[row["id"] for row in group["sources"]]
            value={"summary":{"title":"Synthetic summary","content":"A faithful, longer summary of all referenced statements. "*4,"source_ids":ids},"key_points":[],"decisions":[],"actions":[],"open_questions":[]}
            return {"choices":[{"finish_reason":"stop","message":{"content":json.dumps(value)}}]}
        # First pass splits indexes; later passes can fit the combined result.
        with patch("core.overview.REFERENCE_LIMIT",1),patch("core.overview.ENTRY_LIMIT",2),patch("core.chat_stream.chat",side_effect=response):
            result=overview.synthesize(item["notes"],item["segments"],{"base_url":"http://127.0.0.1:9999","model":"synthetic"},{},True,lambda _:None)
        self.assertEqual(len(seen),3)
        self.assertEqual(set(result["summary"]["source_ids"]),{row["id"] for row in item["segments"]})
