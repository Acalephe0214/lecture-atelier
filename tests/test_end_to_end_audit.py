"""Whole local HTTP workflow against a loopback SSE provider; never paid APIs."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import threading
import time
import unittest
from unittest.mock import patch
import wave
import zipfile

import test_server as helpers
from app import EDIT_SNAPSHOT_FIELDS


def fixture():
    statements=["This is an optmization review.","Proposal: launch on Friday.",
        "Do not launch on Friday; that proposal is rejected.","Final decision: run a small pilot.",
        "Mina will report the pilot results on Tuesday.","The wider launch date remains undecided."]
    return [{"id":f"s{i}","text":text,"start":i*5,"end":i*5+5,"speaker":"Speaker"} for i,text in enumerate(statements)]


class MockModel(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        material=json.loads(payload["messages"][1]["content"])
        prompt=payload["messages"][0]["content"]
        if '"corrections"' in prompt:
            kind="proofreading";source=material["segments"][0]
            result={"corrections":[{"source_id":source["id"],"text":source["text"].replace("optmization","optimization"),"reason":"Synthetic typo correction","certainty":"high","needs_audio":False}],"flags":[]}
        elif '"notes"' in prompt:
            kind="details";ids=[row["id"] for row in material["segments"]]
            result={"notes":[{"title":"Pilot discussion","content":"The Friday launch proposal was rejected. A small pilot was decided; Mina reports on Tuesday. The wider launch is undecided.","category":"argument","source_ids":ids}]}
        else:
            kind="overview";ids=[row["id"] for row in material["sources"]]
            row=lambda title,content,ids: {"title":title,"content":content,"source_ids":ids}
            result={"summary":row("Pilot before launch","A small pilot replaces the rejected Friday launch proposal.",ids),
                "key_points":[row("Rejected proposal","Friday launch is not an agreed action.",["s1","s2"])],
                "decisions":[{**row("Small pilot","Run a small pilot.",["s3"]),"evidence_quote":"Final decision: run a small pilot."}],
                "actions":[row("Report pilot results","Owner: Mina; deadline: Tuesday, relative date as spoken.",["s4"])],
                "open_questions":[row("Wider launch","No date was agreed.",["s5"])]}
        self.server.kinds.append(kind)
        fail=kind=="overview" and self.server.fail_next
        if fail:self.server.fail_next=False
        content='{"summary":' if fail else '```json\n'+json.dumps(result)+'\n```'
        frames=[{"choices":[{"delta":{"content":content[i:i+90]},"finish_reason":None}]} for i in range(0,len(content),90)]
        frames += [{"choices":[{"delta":{},"finish_reason":"length" if fail else "stop"}]},
                   {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120}}]
        raw=b"".join(b"data: "+json.dumps(frame).encode()+b"\n\n" for frame in frames)+b"data: [DONE]\n\n"
        self.send_response(200);self.send_header("Content-Type","text/event-stream");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)


class EndToEndAuditTests(unittest.TestCase):
    call=helpers.ServerTests.call
    lecture=helpers.ServerTests.lecture
    def setUp(self):
        helpers.ServerTests.setUp(self)
        self.provider=ThreadingHTTPServer(("127.0.0.1",0),MockModel)
        self.provider.kinds=[];self.provider.fail_next=False
        self.provider_thread=threading.Thread(target=self.provider.serve_forever,daemon=True);self.provider_thread.start()
        code,_,_=self.call("PUT","/api/settings",{"llm":{"base_url":f"http://127.0.0.1:{self.provider.server_port}/v1","model":"synthetic-audit","api_key":"SYNTHETIC-PRIVATE-KEY"}})
        self.assertEqual(code,200)
    def tearDown(self):
        self.provider.shutdown();self.provider.server_close();self.provider_thread.join(3)
        helpers.ServerTests.tearDown(self)
    def wait(self,base,route):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            code,value,_=self.call("GET",base+route);self.assertEqual(code,200,value)
            job=value["job"]
            if job and job["status"] not in {"queued","running"}:return job
            time.sleep(.01)
        self.fail("Synthetic job did not finish")
    def read(self,base):return self.call("GET",base)[1]

    def test_complete_recording_to_review_notes_failure_recovery_exports_and_notion(self):
        item=self.lecture();base=f"/api/lectures/{item['id']}"
        audio=BytesIO()
        with wave.open(audio,"wb") as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000);out.writeframes(b"\0\0"*8000*30)
        raw=audio.getvalue()
        self.assertEqual(self.call("POST",base+"/audio",headers={"Content-Type":"audio/wav","X-Filename":"synthetic.wav"},raw=raw)[0],200)
        self.assertEqual(self.call("GET",base+"/audio",headers={"Range":"bytes=0-19"})[1],raw[:20])
        self.assertEqual(self.call("PUT",base+"/workflow",{"scene":"meeting","output_language":"en"})[0],200)
        self.assertEqual(self.call("PUT",base,{"asr_language":"mix:fr,vi"})[0],200)
        code,item,_=self.call("POST",base+"/transcript",{"format":"json","text":json.dumps(fixture())})
        self.assertEqual(code,200,item)
        self.call("POST",base+"/notes/generate",{"mode":"local"})
        before=self.read(base)
        self.assertEqual(len(before["notes"]),6)
        for scope in ("all","overview"):
            code,estimate,_=self.call("GET",base+"/notes/estimate?scope="+scope)
            self.assertEqual(code,200);self.assertTrue(estimate["can_run"])
            self.assertLessEqual(*estimate["requests"])
            self.assertEqual(estimate["overview_plan"]["source_copy_cards"],6)
        self.assertGreaterEqual(self.call("POST",base+"/notes/jobs",{"scope":"all"})[0],400)
        self.assertEqual(self.provider.kinds,[])
        code,_,_=self.call("POST",base+"/proofreading/jobs",{"allow_external":True,"context":{"topic":"Application optimization review","terms":"optimization pilot"}})
        self.assertEqual(code,202)
        self.assertEqual(self.wait(base,"/proofreading/jobs")["status"],"completed")
        item=self.read(base);session=item["proofreading"]
        pending=[edit["id"] for row in session["rows"] for edit in row["edits"] if edit["status"]=="pending"]
        self.assertTrue(pending)
        self.assertEqual(self.call("POST",base+"/proofreading/review",{"session_id":session["id"],"edit_ids":pending,"action":"accept"})[0],200)
        item=self.read(base);self.assertIn("optimization",item["segments"][0]["text"])
        row=item["segments"][1]
        self.assertEqual(self.call("PUT",base+"/segments",{"edits":[{"id":row["id"],"text":"Initial proposal: launch on Friday.","expected":{key:row.get(key) for key in EDIT_SNAPSHOT_FIELDS}}]})[0],200)
        # Real SSE transport and actual pipeline, validation, persistence and accounting.
        code,_,_=self.call("POST",base+"/notes/jobs",{"scope":"all","allow_external":True,"replace":True})
        self.assertEqual(code,202)
        job=self.wait(base,"/notes/jobs");self.assertEqual(job["status"],"completed",job)
        self.assertEqual(job["usage"]["total_tokens"],240)
        self.assertEqual(self.provider.kinds,["proofreading","details","overview"])
        item=self.read(base)
        self.assertEqual(item["overview"]["decisions"][0]["evidence_quote"],fixture()[3]["text"])
        self.assertNotIn("Friday",item["overview"]["actions"][0]["content"])
        self.assertFalse(item["overview"]["stale"])
        note=item["notes"][0]
        self.assertEqual(self.call("PUT",base+"/notes/"+note["id"],{"content":note["content"]+" User annotation."})[0],200)
        item=self.read(base);self.assertTrue(item["overview"]["stale"])
        notes=deepcopy(item["notes"]);old_overview=deepcopy(item["overview"])
        self.provider.fail_next=True
        code,_,_=self.call("POST",base+"/notes/jobs",{"scope":"overview","allow_external":True})
        self.assertEqual(code,202)
        job=self.wait(base,"/notes/jobs");self.assertEqual(job["status"],"failed")
        self.assertEqual(self.provider.kinds.count("details"),1)
        self.assertEqual(self.read(base)["notes"],notes)
        self.assertEqual(self.read(base)["overview"],old_overview)
        self.assertTrue(job["diagnostics_available"])
        diagnostic=self.call("GET",base+"/notes/jobs/diagnostics")[1]
        self.assertEqual(diagnostic["error_code"],"output_limit")
        self.assertNotIn("SYNTHETIC-PRIVATE-KEY",json.dumps(diagnostic))
        calls=len(self.provider.kinds);time.sleep(.05);self.assertEqual(len(self.provider.kinds),calls)
        self.call("POST",base+"/notes/jobs",{"scope":"overview","allow_external":True})
        self.assertEqual(self.wait(base,"/notes/jobs")["status"],"completed")
        self.assertEqual(self.read(base)["notes"],notes)
        self.assertEqual(self.provider.kinds.count("details"),1)
        for version in ("original","marked","clean"):
            for fmt in ("txt","md","html","json","docx"):
                code,body,_=self.call("GET",base+f"/transcript/export?version={version}&format={fmt}&ui=en")
                self.assertEqual(code,200,(version,fmt,body))
                if fmt=="docx":self.assertIn("word/document.xml",zipfile.ZipFile(BytesIO(body)).namelist())
                if fmt=="txt":self.assertNotIn(b"s0 00:",body)
        for fmt in ("md","json","srt","txt","docx","pdf"):
            code,body,_=self.call("GET",base+f"/export?format={fmt}&ui=en")
            self.assertEqual(code,200,(fmt,body))
            if fmt=="srt":self.assertEqual(body.count(b" --> "),6)
            if fmt=="docx":
                xml=zipfile.ZipFile(BytesIO(body)).read("word/document.xml").decode()
                self.assertIn("Final decisions",xml);self.assertIn("Detailed notes",xml)
                self.assertNotIn("最终决策",xml)
            self.assertNotIn("SYNTHETIC-PRIVATE-KEY",json.dumps(body) if isinstance(body,dict) else str(body))
        parent="11111111-1111-1111-1111-111111111111"
        self.call("PUT","/api/settings",{"notion":{"parent_page_id":parent,"token":"SYNTHETIC-NOTION-SECRET"}})
        self.assertEqual(self.call("GET",base+"/notion/preview?ui=en")[0],200)
        with patch("core.notion_export._request",side_effect=[{"id":"22222222-2222-2222-2222-222222222222"},{}]) as notion:
            self.assertEqual(self.call("POST",base+"/notion/export",{})[0],400);notion.assert_not_called()
            self.assertEqual(self.call("POST",base+"/notion/export",{"allow_external":True,"parent_page_id":parent,"ui":"en"})[0],200)
            self.assertEqual(notion.call_count,2)
        exported=self.call("GET",base+"/export?format=json")[1]
        self.assertNotIn("SYNTHETIC-NOTION-SECRET",json.dumps(exported))

    def test_replacing_notes_by_local_copies_keeps_previous_versions(self):
        item=self.lecture();base=f"/api/lectures/{item['id']}"
        self.call("POST",base+"/transcript",{"format":"json","text":json.dumps(fixture())})
        self.call("POST",base+"/notes/generate",{"mode":"local"})
        before=self.read(base)
        self.call("PUT",base+"/notes/"+before["notes"][0]["id"],{"content":"Keep my manual note."})
        before=self.read(base)
        code,after,_=self.call("POST",base+"/notes/generate",{"mode":"local","replace":True})
        self.assertEqual(code,200)
        self.assertEqual(after["note_history"][-1]["notes"],before["notes"])
        self.assertEqual(self.provider.kinds,[])
