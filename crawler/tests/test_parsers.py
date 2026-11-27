import unittest
from datetime import date
from pathlib import Path

from npofile_crawler import fia, mohw
from npofile_crawler.items import Item, money, roc_date

FX = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


def by_kind(items: list[Item], kind: str) -> list[Item]:
    return [i for i in items if i.kind == kind]


class HelperTests(unittest.TestCase):
    def test_roc_date(self):
        self.assertEqual(roc_date("113/05/31"), date(2024, 5, 31))
        self.assertEqual(roc_date("0910222"), date(2002, 2, 22))
        self.assertEqual(roc_date("1150624"), date(2026, 6, 24))
        self.assertIsNone(roc_date(""))
        self.assertIsNone(roc_date("113/13/40"))

    def test_money(self):
        self.assertEqual(money(" 1,500,000"), 1500000)
        self.assertEqual(money("23,118 元"), 23118)
        self.assertIsNone(money(""))

    def test_content_hash_stable_and_source_scoped(self):
        a = Item("org", "00570309", {"name": "甲"})
        b = Item("org", "00570309", {"name": "甲"})
        self.assertEqual(a.content_hash("mohw"), b.content_hash("mohw"))
        self.assertNotEqual(a.content_hash("mohw"), a.content_hash("fia"))


class FiaTests(unittest.TestCase):
    def test_parse_sample(self):
        items = list(fia.parse_csv(read("fia_sample.csv")))
        ubns = [i.ubn for i in items]
        # 第二列是日期列、最後一列統編只有 5 碼，兩列都要略過
        self.assertEqual(len(items), 7)
        self.assertNotIn("12345", ubns)
        self.assertEqual(items[0].data, {"name": "中華民國擊劍協會", "city": "臺北市", "status": "active"})
        status = {i.ubn: i.data["status"] for i in items}
        self.assertEqual(status["00510209"], "cancelled")
        self.assertEqual(status["00831856"], "closed")

    def test_limit(self):
        self.assertEqual(len(list(fia.parse_csv(read("fia_sample.csv"), limit=3))), 3)


class MohwTests(unittest.TestCase):
    def test_index_lists_group_ids(self):
        ids = mohw.parse_index(read("group_index.html"))
        self.assertEqual(len(ids), 10)
        self.assertIn("10447", ids)

    def test_clean_group(self):
        url = mohw.GROUP_URL.format(gid="10057")
        items = mohw.parse_group(read("group_clean.html"), url)
        org = by_kind(items, "org")[0]
        self.assertEqual(org.ubn, "00570309")
        self.assertEqual(org.data["name"], "社團法人賦格行動音樂關懷協會")
        self.assertEqual(org.data["org_type"], "公益性社團法人")
        self.assertEqual(org.data["website"], "https://fuguemusic.tw/association")
        self.assertEqual(org.data["city"], "臺北市")
        self.assertEqual(org.data["purposes"], "社會福利事業/社會慈善事業、教育事業、文化事業")
        self.assertEqual(by_kind(items, "penalty"), [])

        annual = {i.data["year"]: i.data for i in by_kind(items, "annual")}
        self.assertEqual(annual[114], {"year": 114, "raised": 66358, "target": 1500000})
        self.assertEqual(annual[98]["raised"], 0)

        projects = by_kind(items, "project")
        self.assertGreaterEqual(len(projects), 2)
        done = next(p for p in projects if p.data["name"].startswith("114年度"))
        self.assertEqual(done.data["raised"], 66358)
        self.assertEqual(done.data["result_filed_on"], date(2026, 2, 25))
        self.assertEqual(done.data["closed_filed_on"], date(2026, 4, 21))
        self.assertTrue(done.source_url.startswith("https://sasw.mohw.gov.tw/app39/fundactivity/fundactivityDetails/"))

    def test_group_with_penalty(self):
        items = mohw.parse_group(read("group_penalty.html"), mohw.GROUP_URL.format(gid="7688"))
        penalties = by_kind(items, "penalty")
        self.assertEqual(len(penalties), 1)
        p = penalties[0]
        self.assertEqual(p.external_id, "3319306")
        self.assertEqual(p.data["decided_on"], date(2024, 5, 31))
        self.assertIn("新臺幣4萬元罰鍰", p.data["content"])
        self.assertTrue(p.data["fine_text"].startswith("罰鍰"))
        self.assertEqual(len(by_kind(items, "project")), 6)

    def test_page_without_ubn_yields_nothing(self):
        self.assertEqual(mohw.parse_group("<html><title> | 公益勸募管理系統</title></html>", "x"), [])


if __name__ == "__main__":
    unittest.main()
