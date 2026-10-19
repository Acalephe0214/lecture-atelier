"""Generic new-workspace seed; never prune or reset a populated workspace."""
import json
import tempfile
import unittest

from store import Store
import test_server as server_helpers


class WorkspaceTests(unittest.TestCase):
    def test_fresh_workspace_has_one_generic_category_and_no_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            self.assertEqual(store.courses(), [{"id": "course-sample", "name": "示例课程", "color": "#70806d"}])
            self.assertEqual(store.lectures(), [])
            self.assertEqual(Store(folder).courses(), store.courses())

    def test_reopen_does_not_seed_new_categories_or_touch_existing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            with store.connection() as conn:
                # This is a temporary synthetic legacy workspace, not user data.
                conn.execute("DELETE FROM courses")
                conn.execute("INSERT INTO courses VALUES (?, ?, ?)", ("legacy-custom", "已有自定义课程", "#123456"))
            item = store.create("legacy-custom", "已有手工课次", "2026-10-18")
            item = store.mutate(item["id"], lambda row: row.update(notes=[{"content": "手工修改保留"}]))
            reopened = Store(folder)
            self.assertEqual(reopened.courses(), store.courses())
            self.assertEqual(reopened.get(item["id"]), item)
            self.assertNotIn("course-sample", {row["id"] for row in reopened.courses()})


class DemoTests(unittest.TestCase):
    setUp = server_helpers.ServerTests.setUp
    tearDown = server_helpers.ServerTests.tearDown
    call = server_helpers.ServerTests.call

    def test_language_switches_never_create_second_demo_or_overwrite_edits(self):
        _, first, _ = self.call("POST", "/api/demo", {"ui_language": "zh"})
        identity = first["lecture_id"]
        self.server.store.mutate(identity, lambda row: row.update(title="我的手工示例标题"))
        before = self.server.store.get(identity)
        for language in ("en", "zh", "en"):
            code, result, _ = self.call("POST", "/api/demo", {"ui_language": language})
            self.assertEqual(code, 200)
            self.assertEqual(result["lecture_id"], identity)
            self.assertEqual(len(result["lectures"]), 1)
            self.assertEqual(self.server.store.get(identity), before)

    def test_legacy_language_specific_demo_is_reused_not_deleted(self):
        store = self.server.store
        item = store.create("course-sample", "Existing English demo", "2026-10-18", identity="lecture-synthetic-demo-en", is_demo=True)
        code, result, _ = self.call("POST", "/api/demo", {"ui_language": "zh"})
        self.assertEqual(code, 200)
        self.assertEqual(result["lecture_id"], item["id"])
        self.assertEqual(store.get(item["id"]), item)
        self.assertEqual(len(store.lectures()), 1)
