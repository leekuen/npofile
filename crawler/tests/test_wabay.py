import unittest
from datetime import date
from pathlib import Path

import httpx

from npofile_crawler import wabay

FX = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


class ParseProjectTests(unittest.TestCase):
    def test_monthly_project_records_one_time_amount_separately(self):
        p = wabay.parse_project(read("wabay_project_monthly.html"), "twsma")
        self.assertEqual(p.name, "第二扇窗｜SMA 病友全方位支持計畫")
        self.assertEqual(p.proposer, "社團法人台灣生命之窗慈善協會")
        self.assertEqual(p.ubn, "88114366")
        self.assertEqual(p.raised, 4831060)      # 單次贊助，不是「已募集 683,037／月」
        self.assertEqual(p.monthly, 280449)
        self.assertIsNone(p.target)              # 目標是每月的，不記成預募金額
        self.assertEqual(p.backers, 2328)
        self.assertEqual(p.start_date, date(2026, 9, 24))
        self.assertEqual(p.end_date, date(2026, 12, 25))
        self.assertFalse(p.long_term)
        self.assertEqual(p.tags, ["公益"])

    def test_one_time_long_term_project(self):
        p = wabay.parse_project(read("wabay_project_longterm.html"), "read")
        self.assertEqual(p.ubn, "93463379")
        self.assertEqual(p.target, 500000)
        self.assertEqual(p.raised, 156046)
        self.assertIsNone(p.monthly)
        self.assertEqual(p.backers, 48)
        self.assertTrue(p.long_term)
        self.assertIsNone(p.end_date)
        self.assertEqual(p.start_date, date(2025, 8, 8))
        self.assertEqual(p.tags, ["公益", "出版", "文化"])

    def test_monthly_long_term_uses_legal_proposer_name(self):
        p = wabay.parse_project(read("wabay_project_monthly_longterm.html"), "fluffylove")
        self.assertEqual(p.proposer, "解脫協會")  # 團隊顯示名稱是「毛孩樂土」，提案者名稱才是登記的
        self.assertEqual(p.ubn, "42521621")
        self.assertEqual(p.raised, 9155108)
        self.assertEqual(p.monthly, 618435)
        self.assertEqual(p.backers, 10240)
        self.assertTrue(p.long_term)

    def test_company_project_still_parses(self):
        p = wabay.parse_project(read("wabay_project_company.html"), "newsveg-tw2027")
        self.assertEqual(p.ubn, "52962610")
        self.assertEqual(p.raised, 1197897)
        self.assertEqual(p.end_date, date(2026, 12, 4))

    def test_unrecognised_page_returns_none(self):
        self.assertIsNone(wabay.parse_project("<html><body>維護中</body></html>", "x"))

    def test_item_has_own_description_not_site_copy(self):
        p = wabay.parse_project(read("wabay_project_monthly.html"), "twsma")
        item = wabay.to_item(p)
        self.assertEqual(item.kind, "project")
        self.assertEqual(item.external_id, "twsma")
        self.assertEqual(item.source_url, "https://wabay.tw/projects/twsma")
        self.assertEqual(item.data["channel"], "crowdfunding")
        self.assertEqual(
            item.data["description"],
            "挖貝群眾集資：定期定額每月 280,449 元、單次贊助 4,831,060 元，2,328 人參與（挖貝頁面顯示的即時金額）",
        )


class ListingTests(unittest.TestCase):
    def test_index_lists_project_slugs_only(self):
        slugs = wabay.list_slugs(read("wabay_index.html"))
        self.assertGreaterEqual(len(slugs), 10)
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertTrue(all("?" not in s and "/" not in s for s in slugs))

    def test_empty_page(self):
        self.assertEqual(wabay.list_slugs(read("wabay_index_empty.html")), [])


class FakeClient:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.urls: list[str] = []

    def get(self, url: str):
        self.urls.append(url)
        if url not in self.pages:
            req = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))
        return httpx.Response(200, text=self.pages[url], request=httpx.Request("GET", url))


def page(slugs: list[str]) -> str:
    return "".join(f'<a href="/projects/{s}?context=projects_index&amp;locale=zh-TW">x</a>' for s in slugs)


class FetchTests(unittest.TestCase):
    def setUp(self):
        idx = wabay.INDEX_URL
        proj = wabay.PROJECT_URL + "?locale=zh-TW"
        self.client = FakeClient({
            idx.format(page=1): page(["twsma", "newsveg-tw2027"]),
            idx.format(page=2): page(["read", "twsma"]),
            idx.format(page=3): page([]),
            proj.format(slug="twsma"): read("wabay_project_monthly.html"),
            proj.format(slug="newsveg-tw2027"): read("wabay_project_company.html"),
            proj.format(slug="read"): read("wabay_project_longterm.html"),
            proj.format(slug="fluffylove"): read("wabay_project_monthly_longterm.html"),
        })

    def test_walks_pages_until_empty_then_revisits(self):
        items = list(wabay.fetch(self.client, revisit=["fluffylove", "read", "gone"]))
        self.assertEqual([i.external_id for i in items], ["twsma", "newsveg-tw2027", "read", "fluffylove"])
        # 下架的專案（404）跳過，不讓整個來源失敗
        self.assertIn(wabay.PROJECT_URL.format(slug="gone") + "?locale=zh-TW", self.client.urls)

    def test_limit_counts_projects(self):
        items = list(wabay.fetch(self.client, limit=1))
        self.assertEqual([i.external_id for i in items], ["twsma"])


if __name__ == "__main__":
    unittest.main()
