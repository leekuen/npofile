"""組織官網成立宗旨（LK-54）：選哪一頁、頁裡取哪一段、一句話介紹。不連網。"""

import unittest
from types import SimpleNamespace

from npofile_crawler import mission

SITE = "https://npo.example.org/"

HOME = """<html><head><meta name="description" content="自閉症基金會：陪伴自閉症者與家庭走過每個人生階段。"></head><body>
<nav><a href="/news">最新消息</a><a href="/about">關於我們</a><a href="/about/mission">宗旨與使命</a>
<a href="/donate">我要捐款</a><a href="https://www.facebook.com/npo">臉書</a><a href="/files/about.pdf">簡介 PDF</a></nav>
<div class="menu"><a href="/a">認識我們</a> <a href="/b">組織架構</a> <a href="/c">服務據點</a> <a href="/d">財務公開</a> <a href="/e">聯絡我們</a></div>
<footer>版權所有 © 2026 地址：台北市</footer>
</body></html>"""

MISSION_PAGE = """<html><body>
<header><h1>網站名稱</h1></header>
<div class="content">
<h2>成立宗旨</h2>
<p>本會以協助自閉症者及其家庭為宗旨，提供早期療育、就業輔導與家庭支持。</p>
<p>我們相信每個自閉症者都能在社會中找到自己的位置。</p>
<h2>組織架構</h2>
<p>董事會下設執行長一人。</p>
</div>
<footer>地址：台北市 電話：02-1234-5678</footer>
</body></html>"""

INLINE_PAGE = """<html><body><div><p><strong>本會宗旨：</strong>推動偏鄉兒童閱讀，讓每個孩子都有書可讀、有人陪讀。</p></div></body></html>"""

SELF_PAGE = """<html><body>
<div class="sidebar"><a href="/x">最新消息</a> <a href="/y">活動花絮</a> <a href="/z">捐款徵信</a> <a href="/w">志工招募</a> <a href="/v">聯絡我們</a></div>
<div><p>歡迎光臨</p></div>
<div><p>本基金會成立於民國八十年，致力於照顧獨居長者，提供送餐、居家服務與關懷訪視，陪伴長輩在熟悉的社區安心老去。</p></div>
</body></html>"""

NOTHING_PAGE = """<html><body><div><p>歡迎光臨</p></div><div><p>電話：02-1234-5678 地址：台北市</p></div></body></html>"""


class FakeResponse:
    def __init__(self, url, text="", ctype="text/html"):
        self.url = url
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": ctype}


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        if url not in self.pages:
            raise RuntimeError(f"404 {url}")
        return FakeResponse(url, text=self.pages[url])


class AboutLinkTests(unittest.TestCase):
    def test_mission_page_before_about_page_and_skips_other_sites(self):
        links = mission.about_links(HOME, SITE)
        self.assertEqual(links[:2], [SITE + "about/mission", SITE + "about"])
        self.assertNotIn("https://www.facebook.com/npo", links)
        self.assertNotIn(SITE + "files/about.pdf", links)  # 檔案不是網頁
        self.assertNotIn(SITE + "news", links)
        self.assertIn(SITE + "a", links)  # 「認識我們」


class ExtractTests(unittest.TestCase):
    def test_text_under_mission_heading(self):
        text = mission.extract(MISSION_PAGE)
        self.assertTrue(text.startswith("本會以協助自閉症者及其家庭為宗旨"))
        self.assertIn("找到自己的位置", text)
        self.assertNotIn("董事會", text)  # 下一個標題就停
        self.assertNotIn("電話", text)

    def test_stops_at_button_or_pseudo_heading(self):
        page = """<html><body><h2>我們的使命</h2>
<p>我們的使命是促進可持續的交通改革，以人為中心，提升市民的生活質量。</p>
<div><span>立即參加</span></div><p>我們的核心價值</p><p>安全、友善、公平的道路環境，讓每個人都能放心走路。</p></body></html>"""
        self.assertEqual(mission.extract(page), "我們的使命是促進可持續的交通改革，以人為中心，提升市民的生活質量。")

    def test_heading_inside_paragraph(self):
        self.assertEqual(mission.extract(INLINE_PAGE), "推動偏鄉兒童閱讀，讓每個孩子都有書可讀、有人陪讀。")

    def test_self_introduction_paragraph_not_menu(self):
        self.assertTrue(mission.extract(SELF_PAGE).startswith("本基金會成立於民國八十年"))

    def test_meta_description_as_last_resort(self):
        self.assertEqual(mission.extract(HOME), "自閉症基金會：陪伴自閉症者與家庭走過每個人生階段。")

    def test_double_escaped_entity_decoded(self):
        page = "<html><body><p>本會宗旨：人心淨化、社會祥和、天下無災無難&amp;nbsp;，推動環保與助人。</p></body></html>"
        self.assertEqual(mission.extract(page), "人心淨化、社會祥和、天下無災無難 ，推動環保與助人。")

    def test_nothing_found(self):
        self.assertIsNone(mission.extract(NOTHING_PAGE))


class FirstSentenceTests(unittest.TestCase):
    def test_first_sentence(self):
        self.assertEqual(mission.first_sentence("本會以協助自閉症者為宗旨。另外也做倡議。"), "本會以協助自閉症者為宗旨")

    def test_label_removed_and_long_text_cut(self):
        out = mission.first_sentence("成立宗旨：" + "推" * 60)
        self.assertEqual(len(out), mission.SUMMARY_MAX)
        self.assertTrue(out.endswith("…"))
        self.assertTrue(out.startswith("推"))


class SummarizeTests(unittest.TestCase):
    def test_no_summarizer_uses_first_sentence(self):
        self.assertEqual(mission.summarize("某會", "照顧獨居長者。其他。", None), ("照顧獨居長者", "first_sentence"))

    def test_claude_result_used(self):
        client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text="「陪伴自閉症者與家庭」")])))
        s = mission.ClaudeSummarizer(client, model="m")
        self.assertEqual(mission.summarize("某會", "很長的原文。", s), ("陪伴自閉症者與家庭", "claude"))

    def test_claude_error_or_too_long_falls_back(self):
        def boom(**kw):
            raise RuntimeError("401")

        s = mission.ClaudeSummarizer(SimpleNamespace(messages=SimpleNamespace(create=boom)), model="m")
        self.assertEqual(mission.summarize("某會", "照顧長者。", s), ("照顧長者", "first_sentence"))
        long = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text="長" * 80)])))
        self.assertEqual(mission.summarize("某會", "照顧長者。", mission.ClaudeSummarizer(long, model="m"))[1],
                         "first_sentence")

    def test_max_calls(self):
        calls = []
        client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: calls.append(1) or SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text="一句話")])))
        s = mission.ClaudeSummarizer(client, model="m", max_calls=1)
        s("a", "x")
        self.assertIsNone(s("b", "y"))
        self.assertEqual(len(calls), 1)


class FetchTests(unittest.TestCase):
    def pages(self):
        return {SITE: HOME, SITE + "about/mission": MISSION_PAGE, SITE + "about": SELF_PAGE}

    def test_reads_mission_page_first(self):
        client = FakeClient(self.pages())
        items = list(mission.fetch(client, mission_targets=[("00968297", "某基金會", SITE)]))
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual((item.kind, item.ubn, item.external_id), ("mission", "00968297", "mission"))
        self.assertEqual(item.data["page_url"], SITE + "about/mission")
        self.assertEqual(item.data["summary_method"], "first_sentence")
        self.assertEqual(item.data["summary"], "本會以協助自閉症者及其家庭為宗旨，提供早期療育、就業輔導與家庭支持")
        self.assertNotIn(SITE + "about", client.requested)  # 第一個關於頁就找到了，不再往下讀

    def test_unchanged_text_not_sent_again(self):
        text = mission.extract(MISSION_PAGE)
        items = list(mission.fetch(FakeClient(self.pages()), mission_targets=[("00968297", "某", SITE)],
                                   mission_seen={"00968297": mission.text_hash(text)}))
        self.assertEqual(items, [])

    def test_unreachable_and_social_sites_skipped(self):
        targets = [("1", "a", "https://www.facebook.com/npo"), ("2", "b", "https://down.example.org/"), ("3", "c", SITE)]
        items = list(mission.fetch(FakeClient(self.pages()), mission_targets=targets, limit=2))
        self.assertEqual([i.ubn for i in items], ["3"])  # 臉書不算組織數；連不上的算一個


if __name__ == "__main__":
    unittest.main()
