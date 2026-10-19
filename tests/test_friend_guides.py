"""Offline friend-manual coverage and link checks; no installs or external API."""
from html.parser import HTMLParser
import unittest
from urllib.parse import unquote, urlsplit

from package_for_friends import FILES, ROOT


class GuideParser(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids, self.links, self.remote_resources = [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"script", "img", "iframe", "link"}:
            self.remote_resources.append(attrs.get("src") or attrs.get("href"))


class FriendGuideTests(unittest.TestCase):
    def test_both_languages_have_the_complete_twelve_sections(self):
        expected = {"prepare", "install", "daily", "first", "review", "api", "ai", "export", "data", "trouble", "codex", "checklist"}
        for name in ("FRIEND-GUIDE.html", "FRIEND-GUIDE-EN.html"):
            text = (ROOT / name).read_text()
            parsed = GuideParser(text)
            self.assertEqual(set(parsed.ids), expected, name)
            self.assertEqual(len(parsed.ids), len(set(parsed.ids)), name)

    def test_relative_links_and_toc_anchors_exist_in_the_package(self):
        for name in ("START-HERE.html", "FRIEND-GUIDE.html", "FRIEND-GUIDE-EN.html"):
            parsed = GuideParser((ROOT / name).read_text())
            for href in parsed.links:
                url = urlsplit(href)
                if url.scheme or url.netloc:
                    continue
                if url.path:
                    self.assertIn(unquote(url.path), FILES, (name, href))
                    self.assertTrue((ROOT / unquote(url.path)).is_file())
                elif url.fragment:
                    self.assertIn(unquote(url.fragment), parsed.ids, (name, href))

    def test_guides_work_offline_without_external_assets(self):
        for name in ("START-HERE.html", "FRIEND-GUIDE.html", "FRIEND-GUIDE-EN.html"):
            self.assertEqual(GuideParser((ROOT / name).read_text()).remote_resources, [])

    def test_no_obsolete_platform_or_no_download_claims(self):
        obsolete = ("本版未接入这些平台的本地 Whisper", "本版未接入本地 Whisper", "Currently Apple Silicon Mac only", "This does not install packages or models.", "不会自动安装模型。")
        for name in ("START-HERE.html", "FRIEND-GUIDE.html", "FRIEND-GUIDE-EN.html", "FRIEND-README.txt"):
            text = (ROOT / name).read_text()
            for phrase in obsolete:
                self.assertNotIn(phrase, text, (name, phrase))

    def test_setup_launch_and_optional_cost_boundaries_are_documented(self):
        for name in ("FRIEND-GUIDE.html", "FRIEND-GUIDE-EN.html"):
            text = (ROOT / name).read_text()
            for phrase in ("setup-mac.command", "setup-windows.bat", "launch.command", "launch-windows.bat", "Control", "Command", "Chat Completions", "API key", "Notion", "Windows ARM64", ".runtime", "CODEX_SETUP.md", "AGENTS.md"):
                self.assertIn(phrase, text, (name, phrase))

    def test_copyable_codex_instructions_are_in_entry_page(self):
        text = (ROOT / "START-HERE.html").read_text()
        self.assertIn('aria-label="Message to copy into Codex"', text)
        self.assertIn('aria-label="给 Codex 的中文说明"', text)
        for phrase in ("read-only", "ask before", "Preserve", "保留", "不调用付费 API", "127.0.0.1"):
            self.assertIn(phrase.lower(), text.lower())


if __name__ == "__main__":
    unittest.main()
