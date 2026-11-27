from datetime import date, timedelta
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from npofile_crawler import mohw

from crawling import progress
from crawling.ingest import run_source
from crawling.models import ActivityProgress, CrawlerSource, CrawlRun
from orgs import period
from orgs.models import Donation, DonorListSummary, Organization, Project

from .test_ingest import FX, read

ORG = "社團法人台灣收容動物關懷協會"  # activity_index.html 六張卡片的申請單位


class Resp:
    def __init__(self, text="", content=b""):
        self.text, self.content = text, content


class FakeMohw:
    """存下來的頁面：民國 114 年有 6 個活動（都有清冊）、申請單位查得到一個團體。"""

    def __init__(self, search_gids=("10057",), fail_on_detail=None):
        self.log: list[str] = []
        self.search_gids = search_gids
        self.fail_on_detail = fail_on_detail
        self.details = 0

    def get(self, url, **kw):
        self.log.append(url)
        if "qdisplayName" in url:
            return Resp("".join(f'<a class="card-sg" href="/app39/fundgroup/fundgroupDetails/{g}" title="{ORG}">x</a>'
                                for g in self.search_gids))
        if "fundgroupDetails" in url:
            return Resp(read("group_clean.html"))
        if "fundactivityIndex" in url:
            return Resp(read("activity_index.html") if "qyyy=114" in url and "offset=0&" in url else "")
        if "fundactivityDetails" in url:
            self.details += 1
            if self.fail_on_detail and self.details == self.fail_on_detail:
                raise RuntimeError("網站暫時連不上")
            return Resp(read("activity_with_donors.html"))
        if "downloadDonors" in url:
            return Resp(content=(FX / "donors_sample.ods").read_bytes())
        raise AssertionError(url)

    def close(self):
        pass

    def count(self, part):
        return sum(part in u for u in self.log)


class PriorityTests(SimpleTestCase):
    now = timezone.now()
    today = date(2026, 11, 27)

    def row(self, **kw):
        base = {"checked_at": self.now - timedelta(days=8), "checked_raised": 100, "has_donor_list": True,
                "end_date": self.today - timedelta(days=30)}
        return ActivityProgress(activity_id="1", org_name="x", roc_year=114, **{**base, **kw})

    def p(self, row, raised=100):
        return progress.priority(row, raised, self.now, self.today)

    def test_rules(self):
        self.assertEqual(self.p(self.row(checked_at=None)), 0)  # 沒抓過
        self.assertEqual(self.p(self.row(), raised=200), 1)  # 金額變了
        self.assertIsNone(self.p(self.row()))  # 有清冊、金額沒變
        self.assertEqual(self.p(self.row(has_donor_list=False)), 2)  # 沒清冊、結束未滿 12 個月、隔 7 天
        self.assertIsNone(self.p(self.row(has_donor_list=False, checked_at=self.now - timedelta(days=3))))  # 未滿 7 天
        old = self.today - timedelta(days=400)
        self.assertIsNone(self.p(self.row(has_donor_list=False, end_date=old)))  # 結束超過 12 個月：不再看
        self.assertEqual(self.p(self.row(has_donor_list=False, end_date=old, has_donor_link=True)), 2)  # 上次下載失敗
        self.assertEqual(self.p(self.row(has_donor_list=False, end_date=None)), 2)  # 還沒結束
        self.assertIsNone(self.p(self.row(unmatched_reason="查無", checked_at=self.now - timedelta(days=10))))
        self.assertEqual(self.p(self.row(unmatched_reason="查無", checked_at=self.now - timedelta(days=31))), 3)


class RunTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="mohw_activities")

    def run_once(self, client, **kw):
        return run_source(self.source, client=client, **kw)

    def test_default_time_limit(self):
        self.assertEqual(self.source.max_minutes, 120)
        self.assertEqual(CrawlerSource.objects.get(key="fia").max_minutes, 0)

    def test_first_run_then_only_changes(self):
        c1 = FakeMohw()
        run = self.run_once(c1)
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)
        self.assertEqual(c1.count("downloadDonors"), 6)
        self.assertEqual(DonorListSummary.objects.count(), 6)
        self.assertTrue(Organization.objects.filter(ubn__in=ActivityProgress.objects.values("ubn")).exists())
        self.assertEqual(progress.summary(), {"total": 6, "done": 6, "with_list": 6, "pending": 0, "unmatched": 0})
        self.assertIn("近 5 年活動 6 個，已抓 6 個", run.note)

        c2 = FakeMohw()
        self.run_once(c2)
        self.assertEqual((c2.count("fundactivityDetails"), c2.count("downloadDonors"), c2.count("qdisplayName")), (0, 0, 0))
        # 過去的年度（114）7 天內不重翻列表；今年、明年照翻
        self.assertEqual((c2.count("qyyy=114"), c2.count("qyyy=115") > 0, c2.count("qyyy=116") > 0), (0, True, True))

        row = ActivityProgress.objects.first()
        ActivityProgress.objects.filter(pk=row.pk).update(checked_raised=1, donors_raised=1)  # 列表上的金額跟上次不同
        c3 = FakeMohw()
        self.run_once(c3)
        self.assertEqual((c3.count("fundactivityDetails"), c3.count("downloadDonors")), (1, 1))
        self.assertEqual(DonorListSummary.objects.count(), 6)  # 重抓不重複
        row.refresh_from_db()
        self.assertEqual(row.checked_raised, row.listed_raised)

    def test_past_year_relisted_after_a_week(self):
        self.run_once(FakeMohw())
        ActivityProgress.objects.update(listed_at=timezone.now() - timedelta(days=8))
        c = FakeMohw()
        self.run_once(c)
        self.assertGreater(c.count("qyyy=114"), 0)
        self.assertEqual(c.count("fundactivityDetails"), 0)  # 金額沒變：只翻列表，不開活動頁

    def test_short_time_limit_still_fetches_first_year(self):
        # 列完一年就先抓那一年：上限很短，也不會整段時間都花在翻列表。
        # 假網站：列表一頁 25 秒、其他 1 秒；上限 60 秒。先翻完 6 個年度（7 頁＝175 秒）再抓的話一個都抓不到。
        self.source.max_minutes = 1
        self.source.save()
        site = FakeMohw()
        site.clock = 0
        original = site.get

        def timed_get(url, **kw):
            site.clock += 25 if "fundactivityIndex" in url else 1
            return original(url, **kw)

        site.get = timed_get
        with mock.patch("crawling.ingest.time.monotonic", side_effect=lambda: site.clock):
            run = self.run_once(site)
        self.assertIn("上限先停", run.note)
        self.assertTrue(0 < progress.summary()["done"] < 6)

    def test_killed_midway_keeps_progress_saved_each_minute(self):
        """程式中途被關掉（電腦重開）：至少每分鐘存過一次的進度要留著，下次不必從頭抓。"""
        site = FakeMohw()
        site.clock = 0
        original = site.get

        def get(url, **kw):
            site.clock += 40  # 每個請求 40 秒：每兩個請求就超過一分鐘
            if "fundactivityDetails" in url and site.details == 4:
                raise KeyboardInterrupt  # 模擬被強制關掉（不是一般錯誤，不會走到最後的存檔）
            return original(url, **kw)

        site.get = get
        with mock.patch("crawling.ingest.time.monotonic", side_effect=lambda: site.clock):
            with self.assertRaises(KeyboardInterrupt):
                self.run_once(site)
        self.assertGreater(progress.summary()["done"], 0)

    def test_known_group_name_needs_no_search(self):
        mohw_source = CrawlerSource.objects.get(key="mohw")
        items = mohw.parse_group(read("group_clean.html"), mohw.GROUP_URL.format(gid="10057"))
        for i in items:
            if i.kind == "org":
                i.data["name"] = ORG  # 團體頁抓過這個名稱
        run_source(mohw_source, items=items)
        c = FakeMohw()
        self.run_once(c)
        self.assertEqual(c.count("qdisplayName"), 0)
        self.assertEqual(c.count("downloadDonors"), 6)

    def test_time_limit_stops_and_next_run_continues(self):
        self.source.max_minutes = 1
        self.source.save()
        clock = iter(range(0, 10_000, 10))  # 每呼叫一次過 10 秒：開始後第 7 筆左右到 60 秒
        with mock.patch("crawling.ingest.time.monotonic", side_effect=lambda: next(clock)):
            run = self.run_once(FakeMohw())
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)
        self.assertIn("上限先停", run.note)
        done = progress.summary()["done"]
        self.assertLess(done, 6)
        self.source.max_minutes = 0
        self.source.save()
        c = FakeMohw()
        self.run_once(c)
        self.assertEqual(c.count("fundactivityDetails"), 6 - done)  # 只抓剩下的
        self.assertEqual(progress.summary()["done"], 6)

    def test_failure_keeps_what_was_saved(self):
        run = self.run_once(FakeMohw(fail_on_detail=4))
        self.assertEqual(run.status, CrawlRun.Status.FAILED)
        self.assertEqual(progress.summary()["done"], 3)
        self.assertEqual(DonorListSummary.objects.count(), 3)
        c = FakeMohw()
        self.run_once(c)
        self.assertEqual(c.count("fundactivityDetails"), 3)
        self.assertEqual(DonorListSummary.objects.count(), 6)

    def test_unmatched_recorded_and_not_retried_soon(self):
        self.run_once(FakeMohw(search_gids=()))
        s = progress.summary()
        self.assertEqual((s["unmatched"], s["done"], s["total"]), (6, 0, 6))
        self.assertEqual(set(ActivityProgress.objects.values_list("unmatched_reason", flat=True)), {"團體列表查無此名稱"})
        c = FakeMohw()
        self.run_once(c)
        self.assertEqual(c.count("qdisplayName"), 0)
        ActivityProgress.objects.update(checked_at=timezone.now() - timedelta(days=31))
        c = FakeMohw()
        self.run_once(c)
        self.assertEqual(c.count("qdisplayName"), 1)
        self.assertEqual(progress.summary()["done"], 6)

    def test_limit_counts_activities(self):
        c = FakeMohw()
        self.run_once(c, limit=2)
        self.assertEqual(c.count("fundactivityDetails"), 2)
        self.assertEqual(progress.summary()["pending"], 4)

    def test_crawl_command_nothing_new_is_not_a_failure(self):
        """LK-12 把「一筆都沒抓到」當成來源網站改版；勸募活動補齊後沒有新的是正常的，改看列表有沒有讀到卡片。"""
        from io import StringIO

        from django.core.management.base import CommandError

        def crawl(site):
            with mock.patch("crawling.ingest.PoliteClient", return_value=site):
                call_command("crawl", "mohw_activities", stdout=StringIO(), stderr=StringIO())

        this_roc = timezone.localdate().year - 1911

        class ThisYear(FakeMohw):
            """真實網站今年一定有活動（今年的列表每晚都翻）：把存下來的列表當成今年的。"""

            def get(self, url, **kw):
                if "fundactivityIndex" in url:
                    hit = f"qyyy={this_roc}&" in url and "offset=0&" in url
                    return Resp(read("activity_index.html") if hit else "")
                return super().get(url, **kw)

        crawl(ThisYear())
        crawl(ThisYear())  # 第二次什麼都不用抓：不算失敗
        self.assertEqual(CrawlRun.objects.filter(source=self.source).first().fetched, 0)

        class Broken(FakeMohw):
            def get(self, url, **kw):
                return Resp("") if "fundactivityIndex" in url else super().get(url, **kw)

        with self.assertRaises(CommandError):
            crawl(Broken())  # 列表一張卡片都讀不到：多半是網站改版

    def test_prune_removes_old_progress(self):
        since = period.since_roc_year()
        ActivityProgress.objects.create(activity_id="old", org_name="x", roc_year=since - 1)
        ActivityProgress.objects.create(activity_id="new", org_name="x", roc_year=since)
        call_command("prune_old_records")
        self.assertEqual(list(ActivityProgress.objects.values_list("activity_id", flat=True)), ["new"])

    def test_donations_written(self):
        self.run_once(FakeMohw())
        self.assertEqual(Project.objects.filter(external_id__in=ActivityProgress.objects.values("activity_id")).count(), 6)
        self.assertTrue(Donation.objects.exists())
