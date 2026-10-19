"""All external writes mocked; estimates, PDF and friend installer regressions."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from core import usage_estimate as usage, overview, notion_export as notion
from core.pdf_export import export_pdf
from local_transcription import configuration, checked_config
from store import Store
from test_note_jobs import fixture
import test_server as server_helpers


def item():
    segments, notes, summary = fixture()
    return {"title":"合成会议 · 发布方案", "date":"2026-10-18", "segments":segments, "notes":notes,
        "workflow":{"scene":"meeting"}, "generation":{"mode":"llm","scene":"meeting"},
        "overview":overview.validate(summary, segments)}


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"llm":{"model":"deepseek-flash","base_url":"https://api.deepseek.com"},"glossary":[]}

    def test_known_model_has_uncached_usd_interval(self):
        result = usage.estimate(item(), self.settings)
        self.assertEqual(result["price"]["currency"], "USD")
        self.assertGreater(result["total_tokens"][1],result["total_tokens"][0])
        self.assertTrue(result["not_a_cap"])
        self.assertEqual(result["price"]["rates"]["as_of"],"2026-10-18")

    def test_unknown_model_or_reseller_never_inherits_price(self):
        for llm in ({"model":"deepseek-flash","base_url":"https://reseller.example/v1"},{"model":"unknown","base_url":"https://api.deepseek.com"}):
            self.assertIsNone(usage.estimate(item(),{"llm":llm})["price"])

    def test_complexity_increases_output_range(self):
        self.assertGreater(usage.estimate(item(),self.settings,complexity="deep")["output_tokens"][1], usage.estimate(item(),self.settings,complexity="light")["output_tokens"][1])

    def test_overview_only_does_not_count_detail_extraction(self):
        a, b = usage.estimate(item(),self.settings), usage.estimate(item(),self.settings,"overview")
        self.assertLess(b["requests"][0], a["requests"][0])

    def test_empty_and_mixed_text_ranges(self):
        self.assertEqual(usage.estimate({"segments":[]},self.settings)["total_tokens"],[0,0])
        a,b = usage.token_range("中文 English français tiếng Việt 😊")
        self.assertGreater(a,0); self.assertGreater(b,a)

    def test_manual_rate_is_tied_to_endpoint_and_model(self):
        self.settings["billing"] = usage.validate_billing({"enabled":True,"model":"deepseek-flash","base_url":"https://api.deepseek.com","currency":"CNY","input_low":1,"input_high":2,"output_low":3,"output_high":4})
        self.assertEqual(usage.rates(self.settings)["currency"],"CNY")
        self.settings["llm"]["model"]="other"
        self.assertIsNone(usage.rates(self.settings))

    def test_bad_options_and_rates(self):
        for args in (("bad","standard"),("all","unbounded")):
            with self.assertRaises(ValueError): usage.estimate(item(),self.settings,*args)
        with self.assertRaises(ValueError): usage.validate_billing({"currency":"USD","input_low":float('nan')})


class NotionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        row=self.store.create("course-sample","合成会议","2026-10-18");self.identity=row["id"]
        self.store.mutate(self.identity,lambda row:row.update(item()))
        self.parent="11111111-1111-1111-1111-111111111111"
        self.store.update_settings({"notion":{"parent_page_id":self.parent,"token":"SYNTHETIC-NOTION-KEY"}})
        self.body={"allow_external":True,"parent_page_id":self.parent}
    def tearDown(self): self.tmp.cleanup()

    def test_page_link_and_invalid_host(self):
        self.assertEqual(notion.page_id("https://www.notion.so/Some-title-"+self.parent.replace('-','')+"?p=1"),self.parent)
        for value in ("https://evil.example/"+self.parent,"bad",123):
            with self.assertRaises(ValueError): notion.page_id(value)

    def test_public_settings_never_return_connection_token(self):
        self.assertNotIn("SYNTHETIC-NOTION-KEY",json.dumps(self.store.public_settings()))
        self.store.update_settings({"notion":{"parent_page_id":self.parent,"token":""}})
        self.assertEqual(self.store.private_settings()["notion"]["token"],"SYNTHETIC-NOTION-KEY")

    def test_consent_and_changed_parent_block_all_requests(self):
        with patch("core.notion_export._request") as external:
            for body in ({"parent_page_id":self.parent},{**self.body,"parent_page_id":"other"}):
                with self.assertRaises(ValueError): notion.export(self.store,self.identity,body)
            external.assert_not_called()

    def test_preview_no_network_and_contains_no_audio_or_full_transcript(self):
        preview=notion.preview(item(),self.store.private_settings()["notion"])
        self.assertFalse(preview["contains_audio"]);self.assertFalse(preview["contains_full_transcript"])
        self.assertGreater(preview["blocks"],10)

    def test_new_child_page_and_citations(self):
        with patch("core.notion_export._request",side_effect=[{"id":"22222222-2222-2222-2222-222222222222"},{}]) as external:
            result=notion.export(self.store,self.identity,self.body)
        self.assertEqual(result["status"],"completed")
        calls=external.call_args_list
        self.assertEqual(calls[0].args[:2],("POST","/pages"))
        self.assertEqual(calls[0].args[2]["parent"]["page_id"],self.parent)
        self.assertIn("s0003",json.dumps(calls[1].args[2]))
        self.assertNotIn("SYNTHETIC-NOTION-KEY",json.dumps(result))

    def test_ambiguous_write_is_not_retried_and_needs_explicit_ack(self):
        with patch("core.notion_export._request",side_effect=ValueError("Notion 响应未确认")) as external:
            with self.assertRaises(ValueError): notion.export(self.store,self.identity,self.body)
            self.assertEqual(external.call_count,1)
        self.assertEqual(self.store.get(self.identity)["notion_export"]["status"],"unknown")
        with patch("core.notion_export._request") as external:
            with self.assertRaises(ValueError): notion.export(self.store,self.identity,self.body)
            external.assert_not_called()

    def test_partial_failure_preserves_url_and_block_progress(self):
        with patch("core.notion_export._request",side_effect=[{"id":"22222222-2222-2222-2222-222222222222"},ValueError("Notion timeout")]):
            with self.assertRaisesRegex(ValueError,"https://www.notion.so/"): notion.export(self.store,self.identity,self.body)
        self.assertIn("page_id",self.store.get(self.identity)["notion_export"])

    def test_large_blocks_are_batched_and_rich_text_bounded(self):
        source=item();source["notes"]*=35
        rows=notion.blocks(source);self.assertGreater(len(list(notion.batches(rows))),1)
        for batch in notion.batches(rows):
            self.assertLessEqual(len(batch),80)
            self.assertLess(len(json.dumps(batch,ensure_ascii=False).encode()),500000)


class PdfTests(unittest.TestCase):
    def test_real_pdf_has_chinese_title_decision_and_citations(self):
        try:
            import reportlab
            from pypdf import PdfReader
        except ImportError: self.skipTest("Optional QA PDF libraries not installed")
        pdf=export_pdf(item(),"合成课程")
        self.assertTrue(pdf.startswith(b'%PDF'))
        reader=PdfReader(BytesIO(pdf));content="\n".join(page.extract_text() for page in reader.pages)
        for text in ("合成会议", "最终决策", "方案 B", "s0003"):
            self.assertIn(text,content)
        self.assertNotIn("SYNTHETIC-NOTION-KEY",content)

    def test_long_body_and_literal_markup_render(self):
        try: import reportlab
        except ImportError: self.skipTest("ReportLab not installed")
        row=item();row["notes"][0]["content"]="<script>alert('not executed')</script>\n"+"讨论信息，需要核对。"*800
        self.assertTrue(export_pdf(row).startswith(b'%PDF'))


class PortableTests(unittest.TestCase):
    def test_backend_and_windows_executable_model_validation(self):
        self.assertEqual(configuration({"backend":"faster"})["backend"],"faster")
        with self.assertRaises(ValueError): configuration({"backend":"unknown"})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"config.json").write_text('{}');(root/"model.bin").write_bytes(b'synthetic')
            with self.assertRaisesRegex(ValueError,"tokenizer"):
                checked_config({"backend":"faster","model_path":tmp,"python_path":sys.executable})
            (root/"tokenizer.json").write_text('{}')
            result=checked_config({"backend":"faster","model_path":tmp,"python_path":sys.executable})
            self.assertEqual(result["backend"],"faster")

    def test_manifest_has_only_pinned_https_hashes(self):
        manifest=json.loads((Path(__file__).resolve().parents[1]/"portable_runtime.json").read_text())
        for key in ("mac-arm64","mac-x86_64","windows-x86_64"):
            self.assertTrue(manifest[key]["url"].startswith("https://github.com/astral-sh/python-build-standalone/releases/download/20261013/"))
            self.assertEqual(len(manifest[key]["sha256"]),64)


class DeliveryApiTests(unittest.TestCase):
    setUp = server_helpers.ServerTests.setUp
    tearDown = server_helpers.ServerTests.tearDown
    call = server_helpers.ServerTests.call
    lecture = server_helpers.ServerTests.lecture
    imported = server_helpers.ServerTests.imported
    def test_estimate_and_notion_consent_endpoints(self):
        row=self.imported();root=f"/api/lectures/{row['id']}"
        status,estimate,_=self.call("GET",root+"/notes/estimate")
        self.assertEqual(status,200);self.assertGreater(estimate["source_chars"],0)
        with patch("core.notion_export._request") as remote:
            self.assertEqual(self.call("POST",root+"/notion/export",{})[0],400)
            remote.assert_not_called()


if __name__=="__main__":unittest.main()
