"""LK-26：後台「排入完整爬取」與排程的 run_crawl_requests。"""

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from crawling.ingest import ensure_sources
from crawling.models import CrawlerSource, CrawlRequest

RUNNER = "crawling.management.commands.run_crawl_requests.call_command"


def queue(*keys, **fields):
    req = CrawlRequest.objects.create(**fields)
    req.sources.set(CrawlerSource.objects.filter(key__in=keys))
    return req


class RunCrawlRequestsTests(TestCase):
    def setUp(self):
        ensure_sources()

    def test_nothing_queued_does_nothing(self):
        with mock.patch(RUNNER) as cc:
            call_command("run_crawl_requests")
        cc.assert_not_called()

    def test_runs_crawl_then_prune_and_scores(self):
        req = queue("fia", "mohw")
        with mock.patch(RUNNER) as cc:
            call_command("run_crawl_requests")
        names = [c.args[0] for c in cc.call_args_list]
        self.assertEqual(names, ["crawl", "prune_old_records", "recompute_scores"])
        self.assertEqual(sorted(cc.call_args_list[0].args[1:]), ["fia", "mohw"])
        req.refresh_from_db()
        self.assertEqual(req.status, CrawlRequest.Status.DONE)
        self.assertIsNotNone(req.started_at)
        self.assertIsNotNone(req.finished_at)
        self.assertIn("==> crawl", req.output)

    def test_crawl_failure_marks_failed_but_still_recomputes(self):
        req = queue("fia")

        def fake(name, *args, **kwargs):
            if name == "crawl":
                raise CommandError("有來源執行失敗")

        with mock.patch(RUNNER, side_effect=fake) as cc:
            call_command("run_crawl_requests")
        self.assertEqual([c.args[0] for c in cc.call_args_list], ["crawl", "prune_old_records", "recompute_scores"])
        req.refresh_from_db()
        self.assertEqual(req.status, CrawlRequest.Status.FAILED)
        self.assertIn("有來源執行失敗", req.output)

    def test_unexpected_error_is_recorded(self):
        req = queue("fia")
        with mock.patch(RUNNER, side_effect=RuntimeError("boom")):
            call_command("run_crawl_requests")
        req.refresh_from_db()
        self.assertEqual(req.status, CrawlRequest.Status.FAILED)
        self.assertIn("RuntimeError: boom", req.output)

    def test_only_one_at_a_time(self):
        queue("fia", status=CrawlRequest.Status.RUNNING, started_at=timezone.now())
        waiting = queue("mohw")
        with mock.patch(RUNNER) as cc:
            call_command("run_crawl_requests")
        cc.assert_not_called()
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, CrawlRequest.Status.QUEUED)

    def test_oldest_queued_first_and_one_per_call(self):
        first = queue("fia")
        second = queue("mohw")
        with mock.patch(RUNNER):
            call_command("run_crawl_requests")
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, CrawlRequest.Status.DONE)
        self.assertEqual(second.status, CrawlRequest.Status.QUEUED)

    def test_stale_running_is_failed_and_next_one_starts(self):
        stale = queue("fia", status=CrawlRequest.Status.RUNNING, started_at=timezone.now() - timedelta(hours=13))
        waiting = queue("mohw")
        with mock.patch(RUNNER):
            call_command("run_crawl_requests")
        stale.refresh_from_db()
        waiting.refresh_from_db()
        self.assertEqual(stale.status, CrawlRequest.Status.FAILED)
        self.assertIn("中斷", stale.output)
        self.assertEqual(waiting.status, CrawlRequest.Status.DONE)

    def test_output_is_truncated(self):
        req = queue("fia")

        def noisy(name, *args, stdout=None, **kwargs):
            stdout.write("x" * 30000)

        with mock.patch(RUNNER, side_effect=noisy):
            call_command("run_crawl_requests")
        req.refresh_from_db()
        self.assertLessEqual(len(req.output), 20000)


class QueueFullCrawlAdminTests(TestCase):
    def setUp(self):
        ensure_sources()
        self.admin = get_user_model().objects.create_superuser("boss", "boss@example.invalid", "a-strong-pass-123")
        self.client.force_login(self.admin)
        self.url = reverse("admin:crawling_crawlersource_changelist")

    def post(self, keys):
        ids = CrawlerSource.objects.filter(key__in=keys).values_list("pk", flat=True)
        return self.client.post(self.url, {"action": "queue_full_crawl", "_selected_action": list(ids)}, follow=True)

    def test_queues_selected_enabled_sources(self):
        resp = self.post(["fia", "mohw"])
        req = CrawlRequest.objects.get()
        self.assertEqual(req.status, CrawlRequest.Status.QUEUED)
        self.assertEqual(req.requested_by, self.admin)
        self.assertEqual(sorted(req.sources.values_list("key", flat=True)), ["fia", "mohw"])
        self.assertContains(resp, f"已排入完整爬取 #{req.pk}")

    def test_skips_disabled_sources(self):
        CrawlerSource.objects.filter(key="mohw").update(enabled=False)
        resp = self.post(["fia", "mohw"])
        req = CrawlRequest.objects.get()
        self.assertEqual(list(req.sources.values_list("key", flat=True)), ["fia"])
        self.assertContains(resp, "略過停用的來源")

    def test_all_disabled_queues_nothing(self):
        CrawlerSource.objects.filter(key="fia").update(enabled=False)
        resp = self.post(["fia"])
        self.assertFalse(CrawlRequest.objects.exists())
        self.assertContains(resp, "都是停用的")

    def test_refuses_while_another_is_active(self):
        queue("fia", status=CrawlRequest.Status.RUNNING, started_at=timezone.now())
        resp = self.post(["mohw"])
        self.assertEqual(CrawlRequest.objects.count(), 1)
        self.assertContains(resp, "還沒跑完的完整爬取")

    def test_cancel_only_affects_queued(self):
        queued = queue("fia")
        running = queue("mohw", status=CrawlRequest.Status.RUNNING, started_at=timezone.now())
        self.client.post(
            reverse("admin:crawling_crawlrequest_changelist"),
            {"action": "cancel", "_selected_action": [queued.pk, running.pk]},
            follow=True,
        )
        queued.refresh_from_db()
        running.refresh_from_db()
        self.assertEqual(queued.status, CrawlRequest.Status.CANCELED)
        self.assertEqual(running.status, CrawlRequest.Status.RUNNING)

    def test_request_pages_render(self):
        req = queue("fia")
        self.assertEqual(self.client.get(reverse("admin:crawling_crawlrequest_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:crawling_crawlrequest_change", args=[req.pk])).status_code, 200)
