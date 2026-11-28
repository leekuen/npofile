"""LK-31 司法院法人登記公告：列表與內頁解析、對組織、只抓 www.judicial.gov.tw、不留人名。"""

import json
import re
import unittest
from datetime import date
from pathlib import Path

from npofile_crawler import judicial

FX = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


# 樣本內頁上出現的人名（樣本已換成假名）：解析結果裡一個都不能有
FAKE_NAMES = ("王大明", "林六", "黃七", "某甲乙", "某某某", "李小華", "張三")


class ListParseTests(unittest.TestCase):
    def test_rows_and_last_page(self):
        rows, last = judicial.parse_list(read("judicial_list.html"))
        self.assertEqual(len(rows), 20)
        self.assertEqual(last, 2712)
        r = rows[0]
        self.assertEqual(r["court"], "臺灣彰化地方法院")
        self.assertEqual(r["case_no"], "115年度法登他字第000160號")
        self.assertEqual(r["reg_no"], "120")
        self.assertEqual(r["category"], "foundation")
        self.assertEqual(r["case_type"], "change")
        self.assertEqual(r["posted_on"], date(2026, 11, 25))
        self.assertTrue(r["url"].startswith("https://www.judicial.gov.tw/tw/cp-144-"))

    def test_case_types(self):
        rows, _ = judicial.parse_list(read("judicial_list.html"))
        types = {r["case_label"]: r["case_type"] for r in rows}
        self.assertEqual(types.get("解散登記"), "dissolution")
        self.assertEqual(types.get("設立登記"), "setup")
        self.assertTrue(all(r["case_type"] for r in rows))


class DetailParseTests(unittest.TestCase):
    def test_change(self):
        d = judicial.parse_detail(read("judicial_change.html"), "change")
        self.assertEqual(d["registered_on"], date(2026, 11, 26))
        self.assertEqual(d["change_items"], ["董監事"])
        self.assertIsNone(d["property_total"])

    def test_setup_property_total(self):
        d = judicial.parse_detail(read("judicial_setup.html"), "setup")
        self.assertEqual(d["registered_on"], date(2026, 11, 27))
        self.assertEqual(d["property_total"], 0)
        self.assertEqual(d["change_items"], [])

    def test_dissolution_ignores_minimum_property_rule(self):
        # 解散原因裡的「最低捐助財產總額新台幣3,000萬元」是法規門檻，不是這個組織的財產
        d = judicial.parse_detail(read("judicial_dissolution.html"), "dissolution")
        self.assertEqual(d["registered_on"], date(2026, 11, 25))
        self.assertIsNone(d["property_total"])

    def test_liquidation_end(self):
        d = judicial.parse_detail(read("judicial_liquidation_end.html"), "liquidation_end")
        self.assertEqual(d["registered_on"], date(2026, 11, 23))

    def test_no_person_names_in_output(self):
        for f, t in (("change", "change"), ("setup", "setup"), ("dissolution", "dissolution"),
                     ("liquidation_end", "liquidation_end")):
            out = json.dumps(judicial.parse_detail(read(f"judicial_{f}.html"), t), ensure_ascii=False, default=str)
            for name in FAKE_NAMES:
                self.assertNotIn(name, out, f)

    def test_change_kinds(self):
        lines = [
            "一、主事務所變更為臺北市信義區松仁路277號十三樓。",
            "二、捐助章程第4條經董事會決議通過變更，報經主管機關予以許可。",
            "三、財產總額變更為新臺幣3,000萬元。",
            "四、第12屆董事王大明辭任，由李小華繼任。",
            "五、新任董事印鑑。",
        ]
        self.assertEqual(judicial.change_kinds(lines), ["主事務所", "財產總額", "章程", "董監事"])

    def test_single_unnumbered_change(self):
        html = ('<section class="cp"><div>主旨：公告王大明等聲請辦理財團法人甲基金會變更登記，業經本院登記處於中華民國115年11月20日'
                '登記於法人登記簿。</div><div>貳、變更登記事項：</div><div>第4屆監察人姓名及住所如下：</div>'
                '<div>監察人  王大明</div></section>')
        d = judicial.parse_detail(html, "change")
        self.assertEqual(d["change_items"], ["董監事"])
        self.assertNotIn("王大明", json.dumps(d, ensure_ascii=False, default=str))

    def test_property_in_wan(self):
        html = '<section class="cp"><div>財產總額：新臺幣3,000萬元整。</div></section>'
        self.assertEqual(judicial.parse_detail(html, "setup")["property_total"], 30_000_000)


class MatcherTests(unittest.TestCase):
    def test_unique_exact_name(self):
        m = judicial.CourtMatcher([("11111111", "財團法人台灣甲基金會", "臺北市")])
        self.assertEqual(m.match("財團法人臺灣甲基金會", "臺灣臺北地方法院"), "11111111")
        self.assertIsNone(m.match("財團法人臺灣甲", "臺灣臺北地方法院"))

    def test_same_name_resolved_by_court_county(self):
        m = judicial.CourtMatcher([
            ("11111111", "社團法人關懷協會", "高雄市"),
            ("22222222", "社團法人關懷協會", "臺中市"),
        ])
        self.assertEqual(m.match("社團法人關懷協會", "臺灣橋頭地方法院"), "11111111")
        self.assertEqual(m.match("社團法人關懷協會", "臺灣臺中地方法院"), "22222222")
        self.assertIsNone(m.match("社團法人關懷協會", "臺灣花蓮地方法院"))

    def test_same_name_same_county_not_matched(self):
        m = judicial.CourtMatcher([
            ("11111111", "社團法人關懷協會", "高雄市"),
            ("22222222", "社團法人關懷協會", "高雄市"),
        ])
        self.assertIsNone(m.match("社團法人關懷協會", "臺灣高雄地方法院"))


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeClient:
    """列表第 1 頁＝樣本；其他頁空白；內頁一律回變更登記樣本。記下所有請求的網址。"""

    def __init__(self, pages=None):
        self.urls = []
        self.pages = pages or {1: read("judicial_list.html")}

    def get(self, url, **kw):
        self.urls.append(url)
        if m := re.search(r"lp-144-1-(\d+)-\d+\.html", url):
            return FakeResponse(self.pages.get(int(m.group(1)), "<html></html>"))
        return FakeResponse(read("judicial_change.html"))


class FetchTests(unittest.TestCase):
    def setUp(self):
        rows, _ = judicial.parse_list(read("judicial_list.html"))
        self.rows = rows
        self.orgs = [("11111111", rows[0]["name"], "彰化縣")]

    def test_only_matched_rows_fetch_detail_and_only_judicial_host(self):
        client = FakeClient()
        listed = [0]
        items = list(judicial.fetch(client, orgs_city=self.orgs, listed=listed))
        self.assertEqual(len(items), 20)
        self.assertEqual(listed[0], 20)
        matched = [i for i in items if i.ubn]
        self.assertEqual([i.ubn for i in matched], ["11111111"])
        self.assertTrue(matched[0].data["detail_fetched"])
        self.assertFalse(any(i.data["detail_fetched"] for i in items if not i.ubn))
        detail_urls = [u for u in client.urls if "/cp-144-" in u]
        self.assertEqual(len(detail_urls), 1)
        for u in client.urls:
            self.assertTrue(u.startswith("https://www.judicial.gov.tw/"), u)
            self.assertNotIn("aomp109", u)
        self.assertEqual(matched[0].external_id, f"{self.rows[0]['court']}|{self.rows[0]['case_no']}")

    def test_refuses_other_hosts(self):
        with self.assertRaises(ValueError):
            judicial.fetch_details(FakeClient(), "https://aomp109.judicial.gov.tw/judbp/wkw/WHD9HN01/V2.htm", "change")

    def test_stops_at_known_page_after_backfill(self):
        seen = [judicial.registration_id(r["court"], r["case_no"]) for r in self.rows]
        client = FakeClient({1: read("judicial_list.html"), 2: read("judicial_list.html")})
        items = list(judicial.fetch(client, seen_regs=seen, floor_reached=True))
        self.assertEqual(items, [])
        self.assertEqual(len(client.urls), 1)

    def test_backfill_jumps_past_stored_pages(self):
        # 還沒補齊：第 1 頁都存過 → 跳到「已存筆數 ÷ 每頁筆數」那頁接著抓
        seen = [judicial.registration_id(r["court"], r["case_no"]) for r in self.rows] + [f"x|{i}" for i in range(580)]
        client = FakeClient({1: read("judicial_list.html")})
        list(judicial.fetch(client, seen_regs=seen, floor_reached=False))
        self.assertEqual(len(client.urls), 2)
        self.assertIn("lp-144-1-10-60.html", client.urls[1])

    def test_limit(self):
        self.assertEqual(len(list(judicial.fetch(FakeClient(), limit=3))), 3)

    def test_backfill_done(self):
        self.assertFalse(judicial.backfill_done(None))
        self.assertFalse(judicial.backfill_done(date(2020, 3, 1)))
        self.assertTrue(judicial.backfill_done(date(2019, 12, 10)))


if __name__ == "__main__":
    unittest.main()
