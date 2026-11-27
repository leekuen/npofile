import unittest
from datetime import date
from pathlib import Path

from npofile_crawler import donors, gcis, mohw

FX = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


class ClassifyTests(unittest.TestCase):
    def test_kinds(self):
        cases = {
            "台灣積體電路製造股份有限公司": donors.COMPANY,
            "滙豐(台灣)商業銀行股份有限公司": donors.COMPANY,
            "古實室內裝修有限公司": donors.COMPANY,
            "財團法人富邦慈善基金會": donors.GROUP,
            "台北清溪扶輪社": donors.GROUP,
            "中國醫藥大學附設醫院": donors.GROUP,
            "HSBC Holdings plc": donors.COMPANY,
            "BRIGHT FUNDS": donors.GROUP,
            "Great Commission Church International": donors.GROUP,
            "外交部": donors.GROUP,
            "台北真理堂": donors.GROUP,
            "基督教台灣貴格會合一堂": donors.GROUP,
            "財團法人基督教中華聖潔會新屋活水泉教會": donors.GROUP,
            "捐款人聲明捐款資訊不公開": donors.ANONYMOUS,
            "MOMO捐款有心人": donors.ANONYMOUS,
            "鼎鼎聯合行銷股份有限公司 有心人捐款": donors.ANONYMOUS,  # 金流平台彙總，不是企業
            "Line Pay 有心人": donors.ANONYMOUS,
            "MOMO": donors.ANONYMOUS,
            "OK超商門市捐款(助學活動)": donors.ANONYMOUS,
            "新北市私立育才國民小學": donors.GROUP,
            "World Vision Korea": donors.GROUP,
            "": donors.ANONYMOUS,
            "王小明": donors.INDIVIDUAL,
            "林國民": donors.INDIVIDUAL,  # 姓名裡有「國民」不能被當成學校
            "李健行": donors.INDIVIDUAL,  # 「行」結尾的姓名不能被當成商行
            "Stephanie": donors.INDIVIDUAL,
            "SHANG-CHI CHEN": donors.INDIVIDUAL,
            "Lala Chang": donors.INDIVIDUAL,
            "陳亮嘉 余品嫺": donors.INDIVIDUAL,
            "品言國際美學館": donors.INDIVIDUAL,  # 認不出的一律先當個人
            "星巴克": donors.INDIVIDUAL,  # 只有品牌名的認不出來，由管理員改類型
        }
        for name, kind in cases.items():
            with self.subTest(name=name):
                self.assertEqual(donors.classify(name), kind)

    def test_normalize_strips_internal_note(self):
        self.assertEqual(donors.normalize("洪正哲(同001772220)"), "洪正哲")
        self.assertEqual(donors.normalize("李素菁 （同 001179057）"), "李素菁")


class OdsTests(unittest.TestCase):
    def setUp(self):
        self.rows = list(donors.parse_ods((FX / "donors_sample.ods").read_bytes()))

    def test_parse_rows(self):
        self.assertEqual(len(self.rows), 13)  # 標題列與最後的空白列略過
        first = self.rows[0]
        self.assertEqual(
            (first.receipt_no, first.donated_on, first.name, first.amount),
            ("A001", "2025-08-06", "範例科技股份有限公司", 1500000),
        )

    def test_summarize_keeps_companies_and_large_individuals_only(self):
        result = donors.summarize(iter(self.rows))
        names = {(r["name"], r["kind"]) for r in result["rows"]}
        self.assertIn(("範例科技股份有限公司", "company"), names)
        self.assertIn(("財團法人範例文教基金會", "group"), names)
        self.assertIn(("甲大明", "individual"), names)  # 60,000 + 50,000（附註編號合併）≥ 10 萬
        kept = {n for n, _ in names}
        for hidden in ("乙小華", "Sample Lee", "範例美學館", "MOMO捐款有心人", "捐款人聲明捐款資訊不公開"):
            self.assertNotIn(hidden, kept)
        s = result["summary"]
        self.assertEqual((s["total_rows"], s["total_amount"]), (13, 3973600))
        self.assertEqual((s["small_individual_count"], s["small_individual_amount"]), (3, 3600))
        self.assertEqual((s["anonymous_rows"], s["anonymous_amount"]), (3, 60000))

    def test_threshold_is_configurable(self):
        result = donors.summarize(iter(self.rows), threshold=500)
        kept = {r["name"] for r in result["rows"]}
        self.assertIn("乙小華", kept)  # 600 ≥ 500
        self.assertNotIn("範例美學館", {r["name"] for r in donors.summarize(iter(self.rows), threshold=2000)["rows"]})


class ActivityTests(unittest.TestCase):
    def test_index(self):
        ids = mohw.parse_activity_index(read("activity_index.html"))
        self.assertEqual(len(ids), 6)
        self.assertIn("2362529", ids)

    def test_activity_with_donor_file(self):
        url = mohw.ACTIVITY_URL.format(aid="6380987")
        item, donors_url = mohw.parse_activity(read("activity_with_donors.html"), url, "00570309")
        self.assertEqual(item.external_id, "6380987")
        self.assertEqual(item.data["start_date"], date(2025, 2, 13))
        self.assertEqual(item.data["end_date"], date(2026, 1, 31))
        self.assertEqual(item.data["permit_no"], "衛部救字第1141360537號")
        self.assertEqual(item.data["region"], "全國")
        self.assertEqual(item.data["category"], "社會福利事業/社會慈善事業")
        self.assertEqual(donors_url, "https://sasw.mohw.gov.tw/app39/fundactivity/downloadDonors?refid=27285123")

    def test_activity_without_donor_file(self):
        item, donors_url = mohw.parse_activity(
            read("activity_no_donors.html"), mohw.ACTIVITY_URL.format(aid="2362529"), "10374724"
        )
        self.assertEqual(item.data["raised"], 343815)
        self.assertIsNone(donors_url)


class GcisTests(unittest.TestCase):
    def test_exact_match(self):
        hit = gcis.pick_exact("台灣積體電路製造股份有限公司", read("gcis_tsmc.json"))
        self.assertEqual(hit["ubn"], "22099131")
        self.assertEqual(hit["representative"], "魏哲家")
        self.assertGreater(hit["capital"], 0)

    def test_partial_name_is_not_linked(self):
        self.assertIsNone(gcis.pick_exact("星巴克", read("gcis_starbucks_partial.json")))

    def test_empty_or_bad_body(self):
        self.assertIsNone(gcis.pick_exact("x", ""))
        self.assertIsNone(gcis.pick_exact("x", "<html>"))

    def test_query_url_uses_percent_20(self):
        url = gcis.query_url("台灣積體電路製造股份有限公司")
        self.assertIn("%20like%20", url)
        self.assertNotIn("+", url)


if __name__ == "__main__":
    unittest.main()


class FetchActivitiesTests(unittest.TestCase):
    """用存下來的頁面模擬整條抓取；清冊下載逾時要跳過那一份、其他照常。"""

    class FakeResp:
        def __init__(self, text="", content=b""):
            self.text, self.content = text, content

    def make_client(self, donors_error=None):
        test = self

        class FakeClient:
            def get(self, url, **kw):
                if "fundgroupDetails" in url:
                    return test.FakeResp(read("group_clean.html"))
                if "fundactivityIndex" in url:
                    # 第二頁起沒有卡片＝列表結束；每個活動頁都回同一份存下來的頁面
                    return test.FakeResp(read("activity_index.html") if "offset=0" in url else "")
                if "fundactivityDetails" in url:
                    return test.FakeResp(read("activity_with_donors.html"))
                if "downloadDonors" in url:
                    if donors_error:
                        raise donors_error
                    return test.FakeResp(content=(FX / "donors_sample.ods").read_bytes())
                raise AssertionError(url)

        return FakeClient()

    def test_full_flow(self):
        items = list(mohw.fetch_activities_for(self.make_client(), ["10057"]))
        kinds = [i.kind for i in items]
        self.assertIn("org", kinds)
        self.assertIn("annual", kinds)
        self.assertEqual(kinds.count("donor_list"), 6)  # 列表上 6 個活動，每個都有清冊

    def test_timeout_skips_only_that_list(self):
        import httpx

        items = list(mohw.fetch_activities_for(self.make_client(httpx.ReadTimeout("slow")), ["10057"]))
        kinds = [i.kind for i in items]
        self.assertEqual(kinds.count("donor_list"), 0)
        self.assertGreater(kinds.count("project"), 6)  # 團體頁的專案＋6 個活動頁都還在


ORG = "社團法人台灣收容動物關懷協會"  # activity_index.html 六張卡片的申請單位


def search_html(*gids, name=ORG):
    return "".join(f'<a class="card-style card-sg" href="/app39/fundgroup/fundgroupDetails/{g}" title="{name}">x</a>' for g in gids)


class ActivityCardTests(unittest.TestCase):
    def test_cards(self):
        cards = mohw.parse_activity_cards(read("activity_index.html"), 114)
        self.assertEqual(len(cards), 6)
        self.assertEqual({c.org_name for c in cards}, {ORG})
        self.assertEqual(cards[0].raised, 47244)
        self.assertEqual(cards[0].year, 114)
        self.assertTrue(cards[0].name)

    def test_exact_group_ids(self):
        self.assertEqual(mohw.exact_group_ids(search_html("1", "2"), ORG), ["1", "2"])
        self.assertEqual(mohw.exact_group_ids(search_html("1", name="社團法人台灣收容動物關懷協會分會"), ORG), [])


class FetchByYearTests(unittest.TestCase):
    """依年度列活動 → plan 挑 → 活動頁＋清冊；第一次遇到的申請單位查一次團體。"""

    FakeResp = FetchActivitiesTests.FakeResp

    def make_client(self, search=None, log=None):
        test = self
        search = search if search is not None else search_html("10057")

        class FakeClient:
            def get(self, url, **kw):
                (log if log is not None else []).append(url)
                if "qdisplayName" in url:
                    return test.FakeResp(search)
                if "fundgroupDetails" in url:
                    return test.FakeResp(read("group_clean.html"))
                if "fundactivityIndex" in url:
                    return test.FakeResp(read("activity_index.html") if "qyyy=114" in url and "offset=0&" in url else "")
                if "fundactivityDetails" in url:
                    return test.FakeResp(read("activity_with_donors.html"))
                if "downloadDonors" in url:
                    return test.FakeResp(content=(FX / "donors_sample.ods").read_bytes())
                raise AssertionError(url)

        return FakeClient()

    def test_lists_years_and_fetches_every_card(self):
        log = []
        items = list(mohw.fetch_activities(self.make_client(log=log), since_roc=113, this_roc=115))
        years = sorted({u.split("qyyy=")[1].split("&")[0] for u in log if "qyyy=" in u})
        self.assertEqual(years, ["113", "114", "115", "116"])  # 起始年度到明年
        kinds = [i.kind for i in items]
        self.assertEqual(kinds.count("donor_list"), 6)
        self.assertEqual(kinds.count("org"), 1)
        self.assertEqual(sum("qdisplayName" in u for u in log), 1)  # 同一個申請單位只查一次

    def test_limit_counts_activities(self):
        items = list(mohw.fetch_activities(self.make_client(), limit=2, since_roc=114, this_roc=114))
        self.assertEqual([i.kind for i in items].count("donor_list"), 2)

    def test_unmatched_names_are_reported_and_skipped(self):
        class Plan(mohw.ActivityPlan):
            def __init__(self):
                self.unmatched_reasons = []

            def unmatched(self, card, reason):
                self.unmatched_reasons.append(reason)

        for search, reason in ((search_html(), "團體列表查無此名稱"), (search_html("1", "2"), "同名團體不只一個")):
            plan = Plan()
            items = list(mohw.fetch_activities(self.make_client(search=search), since_roc=114, this_roc=114, plan=plan))
            self.assertEqual(items, [])
            self.assertEqual(plan.unmatched_reasons, [reason] * 6)

    def test_plan_controls_order_ubn_and_downloads(self):
        log = []

        class Plan(mohw.ActivityPlan):
            done_calls = []

            def select(self, cards, listed=True):
                return cards[:2]

            def ubn_for(self, name):
                return "12345678"

            def need_donors(self, card):
                return False

            def done(self, card, ubn, **kw):
                self.done_calls.append((card.aid, ubn, kw["donors_fetched"]))

        plan = Plan()
        items = list(mohw.fetch_activities(self.make_client(log=log), since_roc=114, this_roc=114, plan=plan))
        self.assertEqual([i.kind for i in items], ["project", "project"])
        self.assertFalse(any("qdisplayName" in u or "downloadDonors" in u for u in log))
        self.assertEqual([(ubn, fetched) for _, ubn, fetched in plan.done_calls], [("12345678", False)] * 2)


class FetchActivitiesSinceTests(unittest.TestCase):
    FakeResp = FetchActivitiesTests.FakeResp
    make_client = FetchActivitiesTests.make_client

    def test_old_activities_are_skipped_without_download(self):
        downloads = []
        client = self.make_client()
        original = client.get

        def counting_get(url, **kw):
            if "downloadDonors" in url:
                downloads.append(url)
            return original(url, **kw)

        client.get = counting_get
        # 存下來的活動頁是民國 114 年開始：since=115 → 全部略過、一份清冊都不下載
        items = list(mohw.fetch_activities_for(client, ["10057"], since_roc=115))
        self.assertEqual([i for i in items if i.kind == "donor_list"], [])
        self.assertEqual(downloads, [])
