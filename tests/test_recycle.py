"""Synthetic removal/recovery checks; user media never enters this suite."""
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch

from recycle import RecycleBin, RemovalConflict
from store import Store
import test_server as helpers


class RecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.bin = RecycleBin(self.store)
        self.course = self.store.add_course("Synthetic course")
        self.item = self.store.create(self.course["id"], "Synthetic session", "2026-10-19")
        self.media = self.store.audio_dir / "synthetic.wav"
        self.media.write_bytes(b"synthetic original bytes")
        self.item = self.store.mutate(self.item["id"], lambda x: x.update(
            audio={"name":"synthetic.wav","storage_name":"synthetic.wav","url":"/synthetic","mime":"audio/wav"},
            segments=[{"id":"s1","text":"manual correction","review_status":"verified"}],
            notes=[{"id":"n1","content":"manual note"}]))

    def tearDown(self):
        self.temp.cleanup()

    def remove(self, kind, identity):
        return self.bin.remove(kind, identity, self.bin.preview(kind, identity)["revision"])

    def test_course_removal_and_restore_keep_all_material_and_media(self):
        before = deepcopy(self.item)
        removed = self.remove("course", self.course["id"])
        self.assertNotIn(self.course, self.store.courses())
        with self.assertRaises(KeyError): self.store.get(self.item["id"])
        self.assertEqual(self.media.read_bytes(), b"synthetic original bytes")
        self.assertEqual(set(self.bin.entries()[0]), {"id","kind","name","removed_at","lecture_count"})
        self.assertNotIn("manual correction", str(self.bin.entries()))
        self.bin.restore(removed["recycle_id"])
        self.assertEqual(self.store.get(self.item["id"]), before)
        self.assertIn(self.course, self.store.courses())
        self.assertEqual(self.bin.entries(), [])

    def test_audio_detach_and_restore_preserve_subsequent_text_edits(self):
        removed = self.remove("audio", self.item["id"])
        detached = self.store.get(self.item["id"])
        self.assertIsNone(detached["audio"])
        self.assertEqual(detached["segments"], self.item["segments"])
        self.assertEqual(detached["notes"], self.item["notes"])
        self.assertTrue(self.media.exists())
        self.store.mutate(self.item["id"], lambda x: x["segments"][0].update(text="later manual edit"))
        self.bin.restore(removed["recycle_id"])
        restored = self.store.get(self.item["id"])
        self.assertEqual(restored["audio"], self.item["audio"])
        self.assertEqual(restored["segments"][0]["text"], "later manual edit")

    def test_stale_preview_rejected_without_partial_removal(self):
        preview = self.bin.preview("course", self.course["id"])
        self.store.mutate(self.item["id"], lambda x: x.update(title="changed title"))
        with self.assertRaises(RemovalConflict): self.bin.remove("course", self.course["id"], preview["revision"])
        self.assertEqual(self.bin.entries(), [])
        self.assertEqual(self.store.get(self.item["id"])["title"], "changed title")

    def test_new_audio_prevents_overwriting_and_keeps_recovery_entry(self):
        removed = self.remove("audio", self.item["id"])
        self.store.mutate(self.item["id"], lambda x: x.update(audio={"name":"new recording"}))
        with self.assertRaises(RemovalConflict): self.bin.restore(removed["recycle_id"])
        self.assertEqual(self.store.get(self.item["id"])["audio"]["name"], "new recording")
        self.assertEqual(len(self.bin.entries()), 1)

    def test_indexed_audio_detaches_link_without_touching_original(self):
        original = self.store.root / "external-original.wav"
        original.write_bytes(b"external original")
        self.store.mutate(self.item["id"], lambda x: x.update(
            audio={"name":"external-original.wav","storage_kind":"local_index"},
            local_sources={"audio":{"path":str(original)},"transcript":{"path":"synthetic-transcript"}}))
        removed = self.remove("audio", self.item["id"])
        self.assertEqual(original.read_bytes(), b"external original")
        self.assertNotIn("audio", self.store.get(self.item["id"])["local_sources"])
        self.bin.restore(removed["recycle_id"])
        self.assertEqual(self.store.get(self.item["id"])["local_sources"]["audio"]["path"], str(original))

    def test_session_restore_waits_for_course_and_rolls_back(self):
        session = self.remove("lecture", self.item["id"])
        course = self.remove("course", self.course["id"])
        with self.assertRaises(RemovalConflict): self.bin.restore(session["recycle_id"])
        self.assertEqual(len(self.bin.entries()), 2)
        self.bin.restore(course["recycle_id"])
        self.bin.restore(session["recycle_id"])
        self.assertEqual(self.store.get(self.item["id"])["segments"], self.item["segments"])

    def test_restore_collision_is_atomic(self):
        removed = self.remove("course", self.course["id"])
        other = self.store.add_course("Other course")
        self.store.create(other["id"], "new item", "2026-10-19", identity=self.item["id"])
        with self.assertRaises(RemovalConflict): self.bin.restore(removed["recycle_id"])
        self.assertNotIn(self.course, self.store.courses())
        self.assertEqual(self.store.get(self.item["id"])["title"], "new item")

    def test_removing_all_courses_stays_empty_after_restart(self):
        self.remove("course", self.course["id"])
        self.remove("course", "course-sample")
        self.assertEqual(Store(self.temp.name).courses(), [])
        self.store.ensure_sample_course()
        self.assertEqual(len(self.store.courses()), 1)


class RecycleApiTests(unittest.TestCase):
    setUp = helpers.ServerTests.setUp
    tearDown = helpers.ServerTests.tearDown
    call = helpers.ServerTests.call
    lecture = helpers.ServerTests.lecture

    def test_confirmation_stale_preview_and_restore(self):
        item = self.lecture()
        base = "/api/lectures/"+item["id"]
        preview = self.call("GET", "/api/removal-preview?kind=lecture&id="+item["id"])[1]
        self.assertEqual(self.call("DELETE", base, {"revision":preview["revision"]})[0], 400)
        self.call("PUT", base, {"title":"updated"})
        self.assertEqual(self.call("DELETE", base, {"confirm":True,"revision":preview["revision"]})[0], 409)
        preview = self.call("GET", "/api/removal-preview?kind=lecture&id="+item["id"])[1]
        code, removed, _ = self.call("DELETE", base, {"confirm":True,"revision":preview["revision"]})
        self.assertEqual(code, 200)
        self.assertEqual(self.call("GET", base)[0], 404)
        endpoint = "/api/recycle/"+removed["recycle_id"]+"/restore"
        self.assertEqual(self.call("POST", endpoint, {})[0], 400)
        self.assertEqual(self.call("POST", endpoint, {"confirm":True})[0], 200)
        self.assertEqual(self.call("GET", base)[1]["title"], "updated")
        self.assertEqual(self.call("GET", "/api/recycle")[1]["entries"], [])

    def test_active_job_prevents_course_removal(self):
        self.lecture()
        preview = self.call("GET", "/api/removal-preview?kind=course&id=course-sample")[1]
        for manager in (self.server.jobs,self.server.repair_jobs,self.server.denoise_jobs,self.server.note_jobs,self.server.correction_jobs):
            with patch.object(manager,"get",return_value={"status":"running"}):
                self.assertEqual(self.call("DELETE", "/api/courses/course-sample", {"confirm":True,"revision":preview["revision"]})[0],409)
        self.assertEqual(len(self.server.store.courses()),1)

    def test_origin_guard_applies_to_removal(self):
        item=self.lecture()
        self.assertEqual(self.call("DELETE","/api/lectures/"+item["id"],{"confirm":True},headers={"Origin":"https://untrusted.example"})[0],403)
        self.assertEqual(self.call("GET","/api/lectures/"+item["id"])[0],200)


if __name__ == "__main__": unittest.main()
