import base64
import json
import os
import subprocess
import unittest
from types import SimpleNamespace

from npofile_crawler import financials, orgsite

SITE = "https://npo.example.org/"

HOME = """<html><body>
<nav><a href="/about">關於我們</a><a href="/disclosure">資訊公開</a><a href="/news">最新消息</a>
<a href="https://www.facebook.com/npo">臉書</a></nav>
</body></html>"""

DISCLOSURE = """<html><body>
<h2>財務報告</h2>
<table>
<tr><td>113年度財務報告</td><td><a href="/files/113fin.pdf">PDF</a></td></tr>
<tr><td>112年度財務報告</td><td><a href="/files/112fin.pdf">PDF</a></td></tr>
<tr><td>115年度工作計畫及經費預算</td><td><a href="/files/115plan.pdf">PDF</a></td></tr>
</table>
<a href="/files/113年度工作報告.pdf">113年度工作報告</a>
<a href="/files/2019年報.pdf">2019 年報</a>
<a href="/files/113捐款徵信名單.pdf">113 年徵信</a>
<div><p>財務報表</p><p><span><a href="https://drive.google.com/file/d/abc123/view">2022</a></span></p></div>
<a href="/files/113勸募收支彙總表.pdf">113勸募收支彙總表</a>
</body></html>"""


class FakeResponse:
    def __init__(self, url, text="", content=b"", ctype="text/html"):
        self.url = url
        self.text = text
        self.content = content
        self.headers = {"content-type": ctype}


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        if url not in self.pages:
            raise RuntimeError(f"404 {url}")
        value = self.pages[url]
        if isinstance(value, bytes):
            return FakeResponse(url, content=value, ctype="application/pdf")
        return FakeResponse(url, text=value)


class ClassifyTests(unittest.TestCase):
    def test_year(self):
        self.assertEqual(orgsite.find_year("113年度財務報告"), 113)
        self.assertEqual(orgsite.find_year("2024 Annual Report"), 113)
        self.assertEqual(orgsite.find_year("民國111年報 uploaded 2025"), 111)
        self.assertIsNone(orgsite.find_year("財務報告"))

    def test_kind(self):
        self.assertEqual(orgsite.classify("113年創世財務報表暨會計師查核報告"), "financial")
        self.assertEqual(orgsite.classify("2023年芒草心年報"), "annual")
        self.assertEqual(orgsite.classify("113年度工作報告"), "work")
        self.assertEqual(orgsite.classify("113勸募收支彙總表"), "work")  # 單一勸募活動，不是整個組織的財報
        for text in ("115年度工作計畫及經費預算", "113年度捐款徵信", "11301-12捐贈人資料"):
            self.assertIsNone(orgsite.classify(text), text)

    def test_social_sites_skipped(self):
        self.assertTrue(orgsite.is_crawlable_site("https://www.genesis.org.tw/"))
        for url in ("https://www.facebook.com/npo", "http://service@twfms.org", "https://forms.gle/x", ""):
            self.assertFalse(orgsite.is_crawlable_site(url), url)


class ParseLinksTests(unittest.TestCase):
    def test_documents_and_nav(self):
        docs, nav = orgsite.parse_links(DISCLOSURE, SITE + "disclosure")
        got = {(d.year, d.doc_kind, d.url.rsplit("/", 1)[-1]) for d in docs}
        self.assertIn((113, "financial", "113fin.pdf"), got)  # 連結字只有「PDF」，年度與種類從表格列補
        self.assertIn((112, "financial", "112fin.pdf"), got)
        self.assertIn((113, "work", "113年度工作報告.pdf"), got)
        self.assertIn((108, "annual", "2019年報.pdf"), got)
        self.assertIn((111, "financial", "view"), got)  # 雲端檔：連結字只有西元年，種類看外層標題
        self.assertIn((113, "work", "113勸募收支彙總表.pdf"), got)
        names = {d.url.rsplit("/", 1)[-1] for d in docs}
        self.assertNotIn("115plan.pdf", names)
        self.assertNotIn("113捐款徵信名單.pdf", names)
        drive = next(d for d in docs if "drive" in d.url)
        self.assertEqual(drive.title, "111 年度財務報告")
        self.assertEqual(nav, [])

    def test_nav_same_site_only(self):
        _, nav = orgsite.parse_links(HOME, SITE)
        self.assertEqual(nav, [SITE + "about", SITE + "disclosure"])


class DiscoverAndFetchTests(unittest.TestCase):
    def client(self):
        return FakeClient({
            SITE: HOME, SITE + "about": "<html></html>", SITE + "disclosure": DISCLOSURE,
            SITE + "files/113fin.pdf": b"%PDF-1.4 fake 113", SITE + "files/112fin.pdf": b"%PDF-1.4 fake 112",
        })

    def test_discover_keeps_recent_years_only(self):
        docs = orgsite.discover(self.client(), SITE, since_roc=111)
        self.assertTrue(docs)
        self.assertTrue(all(d.year >= 111 for d in docs))
        self.assertEqual(docs[0].year, 113)

    def test_robots_disallow(self):
        client = self.client()
        client.pages[SITE + "robots.txt"] = "User-agent: *\nDisallow: /disclosure"
        docs = orgsite.discover(client, SITE, since_roc=111)
        self.assertEqual(docs, [])
        self.assertNotIn(SITE + "disclosure", client.requested)

    def test_fetch_without_extractor_yields_documents_only(self):
        items = list(orgsite.fetch(self.client(), targets=[("12345678", SITE)], since_roc=111))
        self.assertTrue(items)
        self.assertEqual({i.kind for i in items}, {"document"})
        self.assertEqual(items[0].ubn, "12345678")

    def test_fetch_with_extractor_reads_one_doc_per_year_and_skips_seen(self):
        calls = []

        def extractor(pdf, year, title):
            calls.append((year, pdf))
            return {"year": year, "total_revenue": 1000 * year, "method": "ai"}

        seen = {SITE + "files/112fin.pdf"}
        items = list(orgsite.fetch(self.client(), targets=[("12345678", SITE)], since_roc=111,
                                   extractor=extractor, seen_docs=seen))
        fin = [i for i in items if i.kind == "financial"]
        # 113 讀本機的 PDF；112 已讀過不再讀；111 的雲端檔下載失敗就略過
        self.assertEqual([c[0] for c in calls], [113])
        self.assertEqual(len(fin), 1)
        self.assertEqual(fin[0].data["document_url"], SITE + "files/113fin.pdf")
        self.assertEqual(fin[0].external_id, "113")

    def test_limit_counts_organizations(self):
        items = list(orgsite.fetch(self.client(), limit=0, targets=[("12345678", SITE)]))
        self.assertEqual(items, [])

    def test_drive_download_url(self):
        self.assertEqual(orgsite.download_url("https://drive.google.com/file/d/abc-1/view?usp=sharing"),
                         "https://drive.google.com/uc?export=download&id=abc-1")


RAW = {
    "has_statement": True, "fiscal_year_roc": 113, "audited": True,
    "total_revenue": 36914991, "contributions": 15157996, "government_grants": 19717610,
    "program_service_revenue": 1496709, "investment_income": 518076, "other_revenue": 24600,
    "total_expenses": 34405607, "program_expenses": 30087354, "admin_expenses": 4289453,
    "fundraising_expenses": None, "surplus": 2509384, "total_assets": 40616848,
    "total_liabilities": 2268192, "net_assets": None, "notes": "第 3、4 頁",
}


class CleanTests(unittest.TestCase):
    def test_clean_fills_net_assets_and_keeps_nulls(self):
        d = financials.clean(dict(RAW), 113)
        self.assertEqual(d["year"], 113)
        self.assertEqual(d["net_assets"], 40616848 - 2268192)
        self.assertIsNone(d["fundraising_expenses"])
        self.assertEqual(d["method"], "ai")

    def test_no_statement_or_bad_values(self):
        self.assertIsNone(financials.clean({**RAW, "has_statement": False}, 113))
        d = financials.clean({**RAW, "total_revenue": -5, "fiscal_year_roc": 2024}, 112)
        self.assertIsNone(d["total_revenue"])  # 收入不會是負的
        self.assertEqual(d["year"], 112)  # 模型給了西元年：用網站標示的年度


class FakeAnthropic:
    def __init__(self, text, stop_reason="end_turn"):
        self.sent = None
        msg = SimpleNamespace(stop_reason=stop_reason, model="claude-opus-5-5",
                              content=[SimpleNamespace(type="text", text=text)])

        def create(**kwargs):
            self.sent = kwargs
            return msg

        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


class ExtractorTests(unittest.TestCase):
    def test_sends_pdf_and_parses_json(self):
        fake = FakeAnthropic(json.dumps(RAW))
        d = financials.ClaudeExtractor(fake)(b"%PDF-1.4 x", 113, "113年度財務報告")
        self.assertEqual(d["total_revenue"], 36914991)
        self.assertEqual(d["model"], "claude-opus-5-5")
        doc = fake.sent["messages"][0]["content"][0]
        self.assertEqual(doc["type"], "document")
        self.assertEqual(base64.b64decode(doc["source"]["data"]), b"%PDF-1.4 x")
        self.assertEqual(fake.sent["output_config"]["format"]["schema"], financials.SCHEMA)

    def test_refusal_and_errors_return_none(self):
        self.assertIsNone(financials.ClaudeExtractor(FakeAnthropic("{}", "refusal"))(b"%PDF", 113, "t"))

        class Boom:
            beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: (_ for _ in ()).throw(RuntimeError("x"))))

        self.assertIsNone(financials.ClaudeExtractor(Boom())(b"%PDF", 113, "t"))


class FakeRun:
    """假的 subprocess.run：記下指令，確認 PDF 有放進暫存資料夾，回傳 claude -p 的 JSON 輸出。"""

    def __init__(self, out=None, returncode=0, stdout=None):
        self.out, self.returncode, self.stdout = out, returncode, stdout
        self.calls = []

    def __call__(self, args, cwd, input, **kwargs):
        with open(os.path.join(cwd, "report.pdf"), "rb") as f:
            self.calls.append({"args": args, "input": input, "pdf": f.read(), "files": os.listdir(cwd)})
        stdout = self.stdout if self.stdout is not None else json.dumps(self.out)
        return SimpleNamespace(returncode=self.returncode, stdout=stdout, stderr="")


class ClaudeCodeExtractorTests(unittest.TestCase):
    def test_runs_cli_with_only_read_tool_and_parses_structured_output(self):
        run = FakeRun({"type": "result", "is_error": False, "result": "", "structured_output": RAW})
        d = financials.ClaudeCodeExtractor("claude", run=run)(b"%PDF-1.4 x", 113, "113年度財務報告")
        self.assertEqual(d["total_revenue"], 36914991)
        self.assertEqual(d["model"], financials.DEFAULT_MODEL)
        call = run.calls[0]
        self.assertEqual(call["pdf"], b"%PDF-1.4 x")
        self.assertEqual(call["files"], ["report.pdf"])  # 暫存資料夾裡只有這份 PDF
        args = call["args"]
        self.assertEqual(args[args.index("--tools") + 1], "Read")
        self.assertIn("--strict-mcp-config", args)
        self.assertEqual(json.loads(args[args.index("--json-schema") + 1]), financials.SCHEMA)
        self.assertIn("113年度財務報告", call["input"])

    def test_falls_back_to_result_text(self):
        run = FakeRun({"is_error": False, "result": json.dumps(RAW)})
        self.assertEqual(financials.ClaudeCodeExtractor(run=run)(b"%PDF", 113, "t")["total_expenses"], 34405607)

    def test_errors_return_none(self):
        self.assertIsNone(financials.ClaudeCodeExtractor(run=FakeRun({"is_error": True, "result": "usage limit"}))(b"%PDF", 113, "t"))
        self.assertIsNone(financials.ClaudeCodeExtractor(run=FakeRun(stdout="not json", returncode=1))(b"%PDF", 113, "t"))

        def boom(*a, **k):
            raise subprocess.TimeoutExpired("claude", 1)

        self.assertIsNone(financials.ClaudeCodeExtractor(run=boom)(b"%PDF", 113, "t"))

    def test_max_calls_per_run(self):
        run = FakeRun({"is_error": False, "structured_output": RAW})
        ex = financials.ClaudeCodeExtractor(run=run, max_calls=2)
        results = [ex(b"%PDF", 113, "t") for _ in range(3)]
        self.assertIsNotNone(results[1])
        self.assertIsNone(results[2])
        self.assertEqual(len(run.calls), 2)


if __name__ == "__main__":
    unittest.main()
