"""LK-15 挖貝群眾集資專案：只收收錄的組織、先審核、核准後更新直接上架、不影響揭露指數、回頭看結束不久的專案。"""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from npofile_crawler import wabay

from crawling.ingest import revisit_ids, run_source
from crawling.models import CrawlerSource, CrawlRecord, CrawlRun
from orgs.models import Organization, Project

FX = Path(__file__).resolve().parents[3] / "crawler" / "tests" / "fixtures"


def project(name: str, slug: str) -> wabay.Project:
    return wabay.parse_project((FX / name).read_text(encoding="utf-8"), slug)


def items(*projects):
    return [wabay.to_item(p) for p in projects]


class WabayIngestTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="wabay")
        self.org = Organization.objects.create(ubn="88114366", name="社團法人台灣生命之窗慈善協會")
        self.monthly = project("wabay_project_monthly.html", "twsma")
        self.company = project("wabay_project_company.html", "newsveg-tw2027")
        User = get_user_model()
        User.objects.create_superuser("admin", "admin@example.com", "pw-123456789")
        self.client.login(username="admin", password="pw-123456789")

    def approve_all(self):
        ids = [str(i) for i in CrawlRecord.objects.filter(status="pending").values_list("pk", flat=True)]
        self.client.post("/admin/crawling/crawlrecord/", {"action": "approve", "_selected_action": ids})

    def test_source_defaults_to_review_and_enabled(self):
        self.assertFalse(self.source.auto_approve)
        self.assertTrue(self.source.enabled)

    def test_unknown_proposer_is_skipped_not_queued(self):
        run = run_source(self.source, items=items(self.monthly, self.company))
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)
        self.assertEqual((run.fetched, run.created, run.pending), (2, 1, 1))
        self.assertIn("跳過 1 筆", run.note)
        self.assertFalse(CrawlRecord.objects.filter(ubn="52962610").exists())
        self.assertFalse(Project.objects.exists())  # 先審核

    def test_approved_project_shows_as_crowdfunding_and_score_unchanged(self):
        before = Organization.objects.get(pk=self.org.pk).disclosure_score
        run_source(self.source, items=items(self.monthly))
        self.approve_all()
        p = Project.objects.get(organization=self.org)
        self.assertEqual(p.channel, Project.Channel.CROWDFUNDING)
        self.assertEqual((p.raised, p.monthly_raised, p.backers, p.target), (4831060, 280449, 2328, None))
        self.assertEqual(p.external_id, "twsma")
        self.assertEqual(p.source_name, wabay.SOURCE_NAME)
        self.assertEqual(Organization.objects.get(pk=self.org.pk).disclosure_score, before)

        data = self.client.get("/api/orgs/88114366").json()
        card = data["projects"][0]
        self.assertEqual(card["channel"], "crowdfunding")
        self.assertEqual(card["monthly_raised"], 280449)
        self.assertEqual(card["backers"], 2328)
        self.assertEqual(data["score"]["project"], 0)

    def test_update_after_approval_goes_live_without_review(self):
        run_source(self.source, items=items(self.monthly))
        self.approve_all()
        bumped = replace(self.monthly, raised=5000000, backers=2400)
        run = run_source(self.source, items=items(bumped))
        self.assertEqual((run.created, run.applied, run.pending), (1, 1, 0))
        p = Project.objects.get(organization=self.org)
        self.assertEqual((p.raised, p.backers), (5000000, 2400))
        self.assertEqual(Project.objects.count(), 1)

    def test_unapproved_project_update_stays_pending(self):
        run_source(self.source, items=items(self.monthly))
        run = run_source(self.source, items=items(replace(self.monthly, raised=5000000)))
        self.assertEqual((run.applied, run.pending), (0, 1))

    def test_same_numbers_do_not_create_new_records(self):
        run_source(self.source, items=items(self.monthly))
        run = run_source(self.source, items=items(self.monthly))
        self.assertEqual(run.created, 0)

    def test_revisit_long_term_and_recently_ended_only(self):
        today = timezone.localdate()
        common = {"organization": self.org, "source_name": wabay.SOURCE_NAME, "channel": Project.Channel.CROWDFUNDING}
        Project.objects.create(name="長期", external_id="long", end_date=None, **common)
        Project.objects.create(name="剛結束", external_id="recent", end_date=today - timedelta(days=14), **common)
        Project.objects.create(name="早結束", external_id="old", end_date=today - timedelta(days=15), **common)
        Project.objects.create(name="勸募活動", external_id="permit", organization=self.org)
        self.assertEqual(sorted(revisit_ids(self.source)), ["long", "recent"])
