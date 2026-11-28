"""LK-44 夜間爬蟲被中斷：上一次卡在「執行中」的紀錄收尾、crawl all 慢的來源排最後。"""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from crawling.ingest import INTERRUPTED_ERROR, ensure_sources, run_source
from crawling.management.commands.crawl import SLOW_LAST
from crawling.models import CrawlerSource, CrawlRun


class InterruptedRunTests(TestCase):
    def setUp(self):
        ensure_sources()
        self.src = CrawlerSource.objects.get(key="fia")
        self.other = CrawlerSource.objects.get(key="mohw")

    def test_next_run_closes_stuck_run_of_same_source_only(self):
        stuck = CrawlRun.objects.create(source=self.src)  # 被中斷、永遠停在執行中
        done = CrawlRun.objects.create(source=self.src, status=CrawlRun.Status.SUCCESS)
        other = CrawlRun.objects.create(source=self.other)  # 別的來源：不動
        run = run_source(self.src, items=[])

        stuck.refresh_from_db()
        self.assertEqual(stuck.status, CrawlRun.Status.FAILED)
        self.assertEqual(stuck.error, INTERRUPTED_ERROR)
        self.assertIsNotNone(stuck.finished_at)
        done.refresh_from_db()
        self.assertEqual(done.status, CrawlRun.Status.SUCCESS)
        other.refresh_from_db()
        self.assertEqual(other.status, CrawlRun.Status.RUNNING)
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)

    def test_no_stuck_run_changes_nothing(self):
        done = CrawlRun.objects.create(source=self.src, status=CrawlRun.Status.SUCCESS, error="")
        run_source(self.src, items=[])
        done.refresh_from_db()
        self.assertEqual(done.status, CrawlRun.Status.SUCCESS)
        self.assertEqual(done.error, "")


class CrawlAllOrderTests(TestCase):
    def test_slow_sources_run_last_in_order(self):
        ensure_sources()
        ran = []

        def fake_run(source, **kw):
            ran.append(source.key)
            run = CrawlRun.objects.create(source=source, status=CrawlRun.Status.SUCCESS, fetched=1)
            run.listed_cards = None
            return run

        with patch("crawling.management.commands.crawl.run_source", fake_run):
            call_command("crawl", "all", "--force", stdout=StringIO(), stderr=StringIO())

        slow = [k for k in SLOW_LAST if k in ran]
        self.assertEqual(ran[-len(slow):], slow)  # 慢的依序排在最後
        fast = ran[: -len(slow)]
        self.assertEqual(fast, sorted(fast))  # 快的照代號
        for key in ("wabay", "tpe_labor", "wda_grants"):  # 這次正式站整晚沒跑到的三個
            self.assertLess(ran.index(key), ran.index("orgsite"))
