import unittest
from datetime import date
from pathlib import Path

from npofile_crawler import mohw, violations

FX = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


class ViolationParseTests(unittest.TestCase):
    def test_index(self):
        ids = violations.parse_index(read("violation_index.html"))
        self.assertEqual(len(ids), 9)
        self.assertEqual(ids[0], "51669145")

    def test_detail(self):
        d = violations.parse_detail(read("violation_detail.html"), violations.DETAIL_URL.format(vid="51669145"))
        self.assertEqual(d["id"], "51669145")
        self.assertEqual(d["group_name"], "社團法人台灣愛克特動物重生救援協會")
        self.assertEqual(d["decided_on"], date(2026, 10, 8))
        self.assertEqual(d["authority"], "新北市政府")
        self.assertEqual(d["document_no"], "新北市政府新北府社團字第1151950240號")
        self.assertIn("四萬元罰鍰及廢止勸募許可", d["content"])
        self.assertNotIn("罰鍰金額", d["content"])  # 紅框的罰鍰另外取
        self.assertEqual(d["fine_text"], "罰鍰金額：處新臺幣 4萬元")
        self.assertIn("違反公益勸募條例第18、19及20條", d["reason"])
        self.assertNotIn("負責人", str({k: v for k, v in d.items() if k != "reason"}))

    def test_find_group_exact_name_only(self):
        html = read("group_search.html")
        self.assertEqual(violations.find_group_id(html, "社團法人台灣愛克特動物重生救援協會"), "8697")
        self.assertIsNone(violations.find_group_id(html, "台灣愛克特"))


class SinceFilterTests(unittest.TestCase):
    def test_group_page_drops_old_years_but_keeps_penalties(self):
        url = mohw.GROUP_URL.format(gid="7688")
        all_items = mohw.parse_group(read("group_penalty.html"), url)
        recent = mohw.parse_group(read("group_penalty.html"), url, since_roc=111)
        years = [i.data["year"] for i in recent if i.kind == "annual"]
        self.assertTrue(years and min(years) >= 111)
        self.assertLess(len(recent), len(all_items))
        names = [i.data["name"] for i in recent if i.kind == "project"]
        self.assertNotIn("110年收容動物傷病救援醫治暨送養", names)
        self.assertIn("112年收容動物傷病救援醫治暨送養", names)
        self.assertEqual(
            [i.external_id for i in recent if i.kind == "penalty"], [i.external_id for i in all_items if i.kind == "penalty"]
        )

    def test_name_year(self):
        self.assertEqual(mohw.name_roc_year("114年度《行動音樂教室》"), 114)
        self.assertEqual(mohw.name_roc_year(" 98年 春節"), 98)
        self.assertIsNone(mohw.name_roc_year("行動音樂教室"))
