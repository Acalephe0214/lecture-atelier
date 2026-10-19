"""Synthetic paragraph exports and manual edits; no model or external service."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zipfile

from app import edit_segments, EDIT_SNAPSHOT_FIELDS, APIError
from core import paragraphs, redline
from core.proofread_export import data, export
import test_server as server_helpers
from test_redline import fixture


def sources():
    return [{"id":f"s{i:04d}", "text":f"Sentence {i} ends here.", "start":i*3, "end":i*3+3,
             "review_status":"verified"} for i in range(30)]


def snapshot(row):
    return {key:row.get(key) for key in EDIT_SNAPSHOT_FIELDS}


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.item={"title":"Fictional transcript", "segments":sources(), "date":"2026-10-18"}

    def test_grouping_preserves_every_source_and_does_not_mutate(self):
        before=deepcopy(self.item)
        result=data(self.item,"clean")
        self.assertLess(len(result["blocks"]),len(result["rows"])/2)
        self.assertEqual([sid for block in result["blocks"] for sid in block["source_ids"]], [s["id"] for s in sources()])
        self.assertEqual(self.item,before)
        self.assertEqual(result["blocks"][0]["text"]," ".join(s["text"] for s in result["rows"][:len(result["blocks"][0]["source_ids"])]))

    def test_boundaries_gaps_speakers_pauses_and_untimed_sources(self):
        rows=sources()[:5]
        rows[1]["asr_issue"]=True
        rows[3]["speaker"]="Speaker B"
        rows[4].update(start=70,end=73)
        self.assertEqual([len(group) for group in paragraphs.group(rows)],[1,1,1,1,1])
        untimed=[dict(row,start=None,end=None) for row in sources()]
        self.assertLess(len(paragraphs.group(untimed)),len(untimed))
        self.assertEqual(paragraphs.separator("Xin chào.","Thế giới")," ")
        self.assertEqual(paragraphs.separator('He said “yes.”','“Next” follows.')," ")
        self.assertEqual(paragraphs.separator('Il dit « oui. »','Puis')," ")
        self.assertEqual(paragraphs.separator('Already spaced. ','Next'),"")
        self.assertEqual(paragraphs.separator("你好。","世界"),"")

    def test_python_matches_browser_grouping(self):
        root=Path(__file__).resolve().parents[1]
        node=shutil.which("node") or str(Path.home()/".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
        if not Path(node).is_file():self.skipTest("Node unavailable")
        rows=sources()*3
        rows=deepcopy(rows)
        for i,row in enumerate(rows):
            row["id"]=str(i);row["start"]=i*3;row["end"]=i*3+3
            row["text"]=["这是合成示例。","Français et tiếng Việt.","Emoji 🙂. "][i%3]*4
        rows[8]["asr_issue"]=True;rows[30]["speaker"]="B";rows[50].update(start=None,end=None)
        js="const p=require('./static/paragraphs.js');let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(p.group(JSON.parse(s)).map(g=>g.map(x=>x.id)))));"
        result=json.loads(subprocess.check_output([node,"-e",js],input=json.dumps(rows),text=True,cwd=root))
        self.assertEqual(result,[[row["id"] for row in group] for group in paragraphs.group(rows)])

    def test_reading_text_md_html_default_and_timeline_opt_in(self):
        for fmt in ("txt","md","html"):
            reading=export(self.item,"clean",fmt)[0].decode()
            timeline=export(self.item,"clean",fmt,layout="timeline")[0].decode()
            self.assertNotIn("s0000",reading);self.assertIn("s0000",timeline)
            self.assertIn("Sentence 0 ends here. Sentence 1 ends here.",reading)
            self.assertNotIn("00:00",reading)
            self.assertIn("00:00",export(self.item,"clean",fmt,timestamps=True)[0].decode())

    def test_json_mapping_and_srt_exact_timing(self):
        result=json.loads(export(self.item,"clean","json")[0])
        self.assertEqual(len(result["rows"]),30)
        self.assertEqual(result["blocks"][0]["start"],0)
        self.assertEqual(result["blocks"][0]["end"],result["rows"][len(result["blocks"][0]["source_ids"])-1]["end"])
        self.assertEqual(export(self.item,"clean","srt")[0],export(self.item,"clean","srt",layout="timeline")[0])
        self.assertEqual(export(self.item,"clean","srt")[0].count(b" --> "),30)

    def test_word_has_one_body_paragraph_per_block_not_per_sentence(self):
        with zipfile.ZipFile(BytesIO(export(self.item,"clean","docx")[0])) as archive:
            xml=ET.fromstring(archive.read("word/document.xml"))
        ns={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        body=xml.find("w:body",ns)
        self.assertEqual(len(body.findall("w:p",ns)),3+len(data(self.item,"clean")["blocks"]))
        self.assertNotIn("s0000",ET.tostring(xml).decode())

    def test_marked_runs_remain_marked_across_merged_paragraph(self):
        item,_,session=fixture();redline.install(item,session)
        result=data(item,"marked")
        self.assertGreater(len(result["blocks"][0]["source_ids"]),1)
        self.assertTrue(any(run["kind"]=="delete" for run in result["blocks"][0]["runs"]))
        with zipfile.ZipFile(BytesIO(export(item,"marked","docx")[0])) as archive:
            text=archive.read("word/document.xml")
            self.assertIn(b"<w:del ",text);self.assertIn(b"<w:ins ",text)
        self.assertNotIn("[+",export(item,"clean","txt")[0].decode())

    def test_pdf_receives_reading_blocks_and_optional_time_labels(self):
        with patch("core.pdf_export.export_pdf",return_value=b"%PDF-synthetic") as pdf:
            export(self.item,"clean","pdf")
            sections=pdf.call_args.kwargs["rich_sections"]
            self.assertEqual(sum(style=="body" for style,_ in sections),len(data(self.item,"clean")["blocks"]))
            self.assertFalse(any(style=="source" for style,_ in sections))
            export(self.item,"clean","pdf",timestamps=True)
            self.assertTrue(any(style=="source" for style,_ in pdf.call_args.kwargs["rich_sections"]))


class ManualEditingTests(unittest.TestCase):
    def setUp(self):
        self.item={"segments":sources(),"notes":[{"source_ids":["s0000"],"review_status":"verified"}],"warnings":[]}

    def edit(self,index,text):
        row=self.item["segments"][index]
        return {"id":row["id"],"text":text,"expected":snapshot(row)}

    def test_normal_passages_editable_history_status_and_timing(self):
        before=deepcopy(self.item)
        edit_segments(self.item,[self.edit(0,"Manually corrected."),self.edit(1,"Another correction.")],True)
        for index in (0,1):
            row=self.item["segments"][index]
            self.assertEqual((row["id"],row["start"],row["end"]),(before["segments"][index]["id"],index*3,index*3+3))
            self.assertEqual(row["original_text"],before["segments"][index]["text"])
            self.assertEqual(row["review_status"],"unreviewed")
            self.assertTrue(row["user_edited"])
        self.assertEqual(self.item["segments"][2:],before["segments"][2:])
        self.assertEqual(self.item["notes"][0]["review_status"],"needs_review")
        self.assertEqual(len(self.item["transcript_edit_history"]),2)
        edit_segments(self.item,[self.edit(0,"Corrected again.")],True)
        self.assertEqual(self.item["segments"][0]["original_text"],before["segments"][0]["text"])
        self.assertEqual(self.item["transcript_edit_history"][-1]["before"]["text"],"Manually corrected.")

    def test_invalid_and_stale_batches_do_not_partially_apply(self):
        for bad in ({"text":""},{"expected":{}},{"id":"missing"},{"review_status":"unknown"}):
            before=deepcopy(self.item)
            edits=[self.edit(0,"Valid change"),{**self.edit(1,"Other change"),**bad}]
            with self.assertRaises(APIError):edit_segments(self.item,edits,True)
            self.assertEqual(self.item,before)
        edit=self.edit(0,"Old editor")
        for key,value in (("text","Newer retry"),("start",4),("review_status","unreviewed"),("asr_issue",True)):
            before=deepcopy(self.item)
            self.item["segments"][0][key]=value
            current=deepcopy(self.item)
            with self.assertRaises(APIError) as error:edit_segments(self.item,[edit],True)
            self.assertEqual(error.exception.status,409)
            self.assertEqual(self.item,current)
            self.item=before

    def test_duplicate_noop_and_overlength(self):
        edit=self.edit(0,"New text")
        for edits in ([],[edit,edit],[self.edit(0,"x"*16001)]):
            with self.assertRaises(APIError):edit_segments(self.item,edits,True)
        edit_segments(self.item,[self.edit(0,self.item["segments"][0]["text"])],True)
        self.assertNotIn("transcript_edit_history",self.item)


class ReadingServerTests(unittest.TestCase):
    setUp=server_helpers.ServerTests.setUp
    tearDown=server_helpers.ServerTests.tearDown
    call=server_helpers.ServerTests.call
    lecture=server_helpers.ServerTests.lecture

    def test_batch_endpoint_roundtrip_and_plain_txt_export(self):
        item=self.lecture();base=f"/api/lectures/{item['id']}"
        code,item,_=self.call("POST",base+"/transcript",{"text":json.dumps(sources()),"format":"json"})
        self.assertEqual(code,200,item)
        first,second=item["segments"][:2]
        edits=[{"id":row["id"],"text":row["text"]+" Changed.","expected":snapshot(row)} for row in (first,second)]
        code,item,_=self.call("PUT",base+"/segments",{"edits":edits})
        self.assertEqual(code,200,item)
        self.assertEqual(len(item["transcript_edit_history"]),2)
        self.assertEqual(self.call("PUT",base+"/segments",{"edits":edits})[0],409)
        code,text,_=self.call("GET",base+"/export?format=txt")
        self.assertEqual(code,200)
        self.assertIn(b"Sentence 0 ends here. Changed. Sentence 1 ends here. Changed.",text)
        code,doc,_=self.call("GET",base+"/transcript/export?version=clean&format=txt&layout=reading")
        self.assertEqual(code,200);self.assertNotIn(b"s0001",doc)
        code,doc,_=self.call("GET",base+"/transcript/export?version=clean&format=txt&layout=timeline")
        self.assertEqual(code,200);self.assertIn(b"s0001",doc)
        self.assertEqual(self.call("GET",base+"/transcript/export?layout=invalid")[0],400)
