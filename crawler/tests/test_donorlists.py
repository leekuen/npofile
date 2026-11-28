import json
import unittest
from unittest import mock

from npofile_crawler import donorlists, financials, orgsite
from npofile_crawler.donors import DonorRow

from test_orgsite import SITE, FakeClient


def seg(y, x, text, width=40):
    """測試用的字串片段：（y 中心, x 左, x 右, 字）。"""
    return (y, x, x + width, text)


# 善牧那種：日期｜捐款人｜金額，表頭只在第一頁
PAGE1 = [
    seg(800, 200, "財團法人測試社會福利基金會 112年1月至112年12月份捐款芳名錄", 300),
    seg(770, 50, "日期"), seg(770, 200, "愛心捐贈人名稱"), seg(770, 400, "金額"),
    seg(750, 50, "112/01/03"), seg(750, 200, "冠宇專利商標設計有限公司"), seg(750, 400, "3,000"),
    seg(730, 50, "112/01/03"), seg(730, 200, "王小明"), seg(730, 400, "500"),
    seg(710, 50, "112/01/04"), seg(710, 200, "善心人士"), seg(710, 400, "600"),
]
PAGE2 = [
    seg(750, 50, "112/02/01"), seg(750, 200, "台北市測試協會"), seg(750, 400, "120,000"),
    seg(730, 50, "112/02/02"), seg(730, 200, "華○工業有限公司"), seg(730, 400, "100"),
    seg(20, 300, "第 2 頁"),
]
# 衡山那種：同一份檔後面接支付名單（受贈單位）
PAYOUT = [
    seg(770, 50, "日期"), seg(770, 200, "受贈單位"), seg(770, 400, "金額"),
    seg(750, 50, "112/12/01"), seg(750, 200, "某某國小"), seg(750, 400, "50,000"),
]
# 萬海那種：官網連結寫「補助及捐贈清冊」，檔案裡的標題才寫支付，表頭是一般的「單位名稱｜補助額度」
TITLED_PAYOUT = [
    seg(800, 200, "113年度 萬海航運慈善基金會支付獎助、捐贈名單清冊", 300),
    seg(770, 50, "單位名稱"), seg(770, 300, "補助額度"),
    seg(750, 50, "社團法人測試協會"), seg(750, 300, "8,000"),
]
TITLED_INCOMING = [
    seg(800, 200, "113年度接受捐贈名單", 300),
    seg(770, 50, "捐贈者名稱"), seg(770, 300, "金額"),
    seg(750, 50, "甲乙股份有限公司"), seg(750, 300, "1,000"),
]
# 芳名錄常見的並排兩組：捐款人｜金額｜捐款人｜金額，沒有日期
SIDE_BY_SIDE = [
    seg(770, 50, "捐款人"), seg(770, 150, "金額"), seg(770, 300, "捐款人"), seg(770, 400, "金額"),
    seg(750, 50, "甲乙股份有限公司"), seg(750, 150, "10,000"), seg(750, 300, "丙丁企業社"), seg(750, 400, "2,000"),
]


class TitleTests(unittest.TestCase):
    def test_incoming_lists(self):
        for t in ("114年度接受補助、捐贈名單清冊", "113 年捐款及捐物芳名錄", "115年1-10月晨曦發展中心捐款名單清冊",
                  "114年度接收及支付捐贈名單", "113捐款徵信名單.pdf", "第18屆玉山黃金種子計畫捐款人清冊", "115年度1月捐款明細"):
            self.assertTrue(donorlists.is_list_title(t), t)

    def test_not_incoming(self):
        for t in ("113年創世支付獎助捐贈名單清冊", "114年度支付捐贈清冊", "115年1-3月捐物芳名錄", "113年度財務報告",
                  "115年度工作計畫及經費預算", "115 1-6月實物捐贈芳名錄"):
            self.assertFalse(donorlists.is_list_title(t), t)

    def test_masked(self):
        for n in ("華○工業有限公司", "陳Ｏ朝", "林*源", "王O明"):
            self.assertTrue(donorlists.is_masked(n), n)
        for n in ("冠宇專利商標設計有限公司", "OBI 股份有限公司", "Coca-Cola"):
            self.assertFalse(donorlists.is_masked(n), n)

    def test_dates(self):
        self.assertEqual(donorlists.parse_date("114/1/3"), "2025-01-03")
        self.assertEqual(donorlists.parse_date("2025-01-03"), "2025-01-03")
        self.assertEqual(donorlists.parse_date("114年1月3日"), "2025-01-03")
        self.assertIsNone(donorlists.parse_date("113/13/40"))
        self.assertIsNone(donorlists.parse_date("HS20250101000001"))


class TableTests(unittest.TestCase):
    def test_header_carries_to_next_page(self):
        rows = donorlists.table_rows([PAGE1, PAGE2])
        self.assertEqual([(r.name, r.amount, r.donated_on) for r in rows], [
            ("冠宇專利商標設計有限公司", 3000, "2023-01-03"),
            ("王小明", 500, "2023-01-03"),
            ("善心人士", 600, "2023-01-04"),
            ("台北市測試協會", 120000, "2023-02-01"),
            ("華○工業有限公司", 100, "2023-02-02"),
        ])

    def test_payout_section_skipped(self):
        rows = donorlists.table_rows([PAGE1, PAYOUT])
        self.assertNotIn("某某國小", [r.name for r in rows])
        self.assertEqual(len(rows), 3)

    def test_payout_by_section_title(self):
        self.assertEqual(donorlists.table_rows([TITLED_PAYOUT]), [])
        rows = donorlists.table_rows([TITLED_PAYOUT, TITLED_INCOMING])  # 後面接受段照讀
        self.assertEqual([(r.name, r.amount) for r in rows], [("甲乙股份有限公司", 1000)])

    def test_side_by_side_blocks(self):
        rows = donorlists.table_rows([SIDE_BY_SIDE])
        self.assertEqual([(r.name, r.amount, r.donated_on) for r in rows],
                         [("甲乙股份有限公司", 10000, None), ("丙丁企業社", 2000, None)])

    def test_no_header_no_rows(self):
        self.assertEqual(donorlists.table_rows([[seg(750, 50, "王小明"), seg(750, 200, "500")]]), [])


class ReadTests(unittest.TestCase):
    def read(self, rows, **kw):
        with mock.patch.object(donorlists, "text_rows", return_value=iter(rows)):
            return donorlists.read(b"%PDF", 112, "112年捐款芳名錄", **kw)

    def test_keeps_companies_groups_and_big_individuals_only(self):
        got = self.read(donorlists.table_rows([PAGE1, PAGE2]))
        self.assertEqual(got["method"], "text")
        self.assertEqual([(r["name"], r["kind"]) for r in got["rows"]],
                         [("冠宇專利商標設計有限公司", "company"), ("台北市測試協會", "group")])
        s = got["summary"]
        self.assertEqual((s["total_rows"], s["total_amount"]), (5, 124200))
        self.assertEqual((s["small_individual_count"], s["small_individual_amount"]), (1, 500))
        self.assertEqual((s["anonymous_rows"], s["masked_rows"], s["masked_amount"]), (2, 1, 100))
        self.assertNotIn("王小明", json.dumps(got, ensure_ascii=False))  # 小額個人不往下游傳姓名
        self.assertNotIn("華○", json.dumps(got, ensure_ascii=False))

    def test_year_end_when_no_date(self):
        got = self.read([DonorRow("", None, "甲乙股份有限公司", 1000, "")])
        self.assertEqual(got["rows"][0]["donated_on"], "2023-12-31")

    def test_trailing_ubn_removed(self):
        got = self.read([DonorRow("", "2023-01-03", "力天防災科技有限公司 24887062", 1000, "")])
        self.assertEqual(got["rows"][0]["name"], "力天防災科技有限公司")

    def test_empty_list_is_none(self):
        self.assertIsNone(self.read([]))

    def test_scanned_without_ai_is_none(self):
        with mock.patch.object(donorlists, "text_rows", return_value=None):
            self.assertIsNone(donorlists.read(b"%PDF", 112, "t"))

    def test_scanned_with_ai(self):
        ai = mock.Mock(return_value={"rows": [{"name": "甲乙股份有限公司", "amount": 5000, "date": None}], "method": "ai"})
        with mock.patch.object(donorlists, "text_rows", return_value=None), \
                mock.patch.object(donorlists, "page_count", return_value=3):
            got = donorlists.read(b"%PDF", 112, "t", ai=ai)
        self.assertEqual(got["method"], "ai")
        self.assertEqual(got["rows"][0]["name"], "甲乙股份有限公司")

    def test_scanned_too_long_not_sent_to_ai(self):
        ai = mock.Mock()
        with mock.patch.object(donorlists, "text_rows", return_value=None), \
                mock.patch.object(donorlists, "page_count", return_value=donorlists.MAX_AI_PAGES + 1):
            self.assertIsNone(donorlists.read(b"%PDF", 112, "t", ai=ai))
        ai.assert_not_called()

    def test_broken_pdf_is_none(self):
        self.assertIsNone(donorlists.read(b"not a pdf", 112, "t"))


class AiTaskTests(unittest.TestCase):
    def test_clean(self):
        raw = {"is_incoming_list": True, "notes": "第 1-3 頁", "rows": [
            {"name": "甲乙股份有限公司", "amount": 5000, "date": "2025-01-03"},
            {"name": "", "amount": 1, "date": None},
            {"name": "丙丁企業社", "amount": None, "date": None},
        ]}
        got = donorlists.DONOR_LIST_TASK.clean(raw, 114)
        self.assertEqual(got["rows"], [{"name": "甲乙股份有限公司", "amount": 5000, "date": "2025-01-03"}])
        self.assertIsNone(donorlists.DONOR_LIST_TASK.clean({"is_incoming_list": False, "rows": [], "notes": ""}, 114))

    def test_extractors_take_the_task(self):
        sent = {}

        class Fake:
            class beta:
                class messages:
                    @staticmethod
                    def create(**kw):
                        sent.update(kw)
                        text = json.dumps({"is_incoming_list": True, "notes": "", "rows": [
                            {"name": "甲乙股份有限公司", "amount": 5000, "date": None}]})
                        block = mock.Mock(type="text", text=text)
                        return mock.Mock(stop_reason="end_turn", content=[block], model="m")

        got = financials.ClaudeExtractor(Fake, task=donorlists.DONOR_LIST_TASK)(b"%PDF", 114, "t")
        self.assertEqual(got["rows"][0]["name"], "甲乙股份有限公司")
        self.assertEqual(sent["output_config"]["format"]["schema"], donorlists.AI_SCHEMA)
        self.assertIn("捐款名單", sent["messages"][0]["content"][1]["text"])
        cli = financials.ClaudeCodeExtractor(task=donorlists.DONOR_LIST_TASK)
        self.assertEqual(json.loads(cli.args()[cli.args().index("--json-schema") + 1]), donorlists.AI_SCHEMA)
        # 財報讀法沒變
        self.assertEqual(financials.ClaudeExtractor(Fake).task.schema, financials.SCHEMA)


DISCLOSURE = """<html><body>
<a href="/files/113fin.pdf">113年度財務報告</a>
<a href="/files/113donate.pdf">113年度接受捐贈名單清冊</a>
<a href="/download/downloadfile/103/1">Download 112年捐贈芳名錄</a>
<a href="/files/113pay.pdf">113年度支付獎助捐贈名單清冊</a>
<a href="/files/113goods.pdf">113年捐物芳名錄</a>
<a href="/credit/">捐款徵信</a>
</body></html>"""


class OrgsiteTests(unittest.TestCase):
    def client(self):
        return FakeClient({
            SITE: DISCLOSURE, SITE + "credit/": "<html></html>",
            SITE + "files/113fin.pdf": b"%PDF fin", SITE + "files/113donate.pdf": b"%PDF list113",
            SITE + "download/downloadfile/103/1": b"%PDF list112",
        })

    def test_parse_links(self):
        docs, nav = orgsite.parse_links(DISCLOSURE, SITE)
        got = {(d.year, d.doc_kind, d.url.replace(SITE, "")) for d in docs}
        self.assertEqual(got, {(113, "financial", "files/113fin.pdf"), (113, "donor_list", "files/113donate.pdf"),
                               (112, "donor_list", "download/downloadfile/103/1")})
        self.assertEqual(nav, [SITE + "credit/"])  # 徵信網頁照樣往下走，去找裡面的名單檔

    def test_fetch_reads_lists_skips_seen_and_caps(self):
        calls = []

        def reader(pdf, year, title):
            calls.append((year, pdf))
            return {"method": "text", "rows": [{"name": "甲乙股份有限公司", "kind": "company", "amount": 1, "donated_on": None}],
                    "summary": {"total_rows": 1}}

        items = list(orgsite.fetch(self.client(), targets=[("12345678", SITE)], since_roc=111, list_reader=reader))
        lists = [i for i in items if i.kind == "site_donor_list"]
        self.assertEqual([c[0] for c in calls], [113, 112])
        self.assertEqual(lists[0].data["url"], SITE + "files/113donate.pdf")
        self.assertEqual(lists[0].data["rows"][0]["name"], "甲乙股份有限公司")
        self.assertEqual(lists[0].external_id, orgsite.url_id(SITE + "files/113donate.pdf"))
        self.assertNotIn("donor_list", {i.data.get("doc_kind") for i in items if i.kind == "document"})

        calls.clear()
        list(orgsite.fetch(self.client(), targets=[("12345678", SITE)], since_roc=111, list_reader=reader,
                           seen_lists={SITE + "files/113donate.pdf"}, lists_per_run=5))
        self.assertEqual([c[0] for c in calls], [112])
        calls.clear()
        list(orgsite.fetch(self.client(), targets=[("12345678", SITE)], since_roc=111, list_reader=reader, lists_per_run=1))
        self.assertEqual(len(calls), 1)

    def test_fetch_without_reader_skips_lists(self):
        items = list(orgsite.fetch(self.client(), targets=[("12345678", SITE)], since_roc=111))
        self.assertEqual({i.kind for i in items}, {"document"})


if __name__ == "__main__":
    unittest.main()
