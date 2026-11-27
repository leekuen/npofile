"""LK-29 勞動局違反勞基法處分：自動上架、對不上的進審核清單、管理員指定組織、重跑不重複、前台類別。"""

from pathlib import Path

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import TestCase
from django.urls import reverse
from npofile_crawler import labor
from npofile_crawler.grants import OrgMatcher, csv_table

from crawling.ingest import run_source
from crawling.models import CrawlerSource, CrawlRecord
from orgs.models import Organization, Penalty

FX = Path(__file__).resolve().parents[3] / "crawler" / "tests" / "fixtures"


def sample_items(orgs):
    rows = labor.rows_from_table(csv_table((FX / "labor_taipei_sample.csv").read_bytes()), labor.TAIPEI)
    return list(labor.to_items(labor.TAIPEI, rows, OrgMatcher(orgs)))


class LaborIngestTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="tpe_labor")
        self.maria = Organization.objects.create(ubn="05557110", name="財團法人瑪利亞社會福利基金會")
        self.yong = Organization.objects.create(ubn="33333333", name="詠馨長照社團法人")
        self.orgs = list(Organization.objects.values_list("ubn", "name"))

    def run_sample(self):
        return run_source(self.source, items=sample_items(self.orgs))

    def test_matched_auto_applied_unmatched_pending(self):
        run = self.run_sample()
        # 對得上的 2 筆上架；名稱像非營利組織但對不上的 2 筆（協會、興毅基金會）留在審核清單
        self.assertEqual((run.created, run.applied, run.pending, run.failed), (4, 2, 2, 0))
        p = Penalty.objects.get(organization=self.maria)
        self.assertEqual(p.authority, "臺北市政府勞動局")
        self.assertEqual(p.document_no, "北市勞動字第11560099999號")
        self.assertEqual(p.fine_text, "罰鍰新臺幣 20,000 元")
        self.assertEqual(p.source_name, labor.TAIPEI.source_name)
        pending = CrawlRecord.objects.filter(source=self.source, status=CrawlRecord.Status.PENDING)
        self.assertEqual(set(pending.values_list("ubn", flat=True)), {""})

    def test_rerun_no_duplicates_and_update_same_penalty(self):
        self.run_sample()
        items = sample_items(self.orgs)
        target = next(i for i in items if i.ubn == "05557110")
        target.data["fine_text"] = "罰鍰新臺幣 30,000 元"
        run = run_source(self.source, items=items)
        self.assertEqual(run.created, 1)
        self.assertEqual(Penalty.objects.count(), 2)
        self.assertEqual(Penalty.objects.get(organization=self.maria).fine_text, "罰鍰新臺幣 30,000 元")

    def test_no_responsible_person_name_stored(self):
        self.run_sample()
        stored = list(CrawlRecord.objects.values_list("payload", flat=True)) + list(
            Penalty.objects.values_list("content", "reason", "authority"))
        self.assertNotIn("王大明", str(stored))

    def test_admin_assigns_org_then_approves(self):
        self.run_sample()
        rec = CrawlRecord.objects.get(source=self.source, payload__org_name="財團法人興毅社會福利慈善事業基金會")
        org = Organization.objects.create(ubn="55555555", name="財團法人興毅社會福利慈善事業基金會")
        admin = get_user_model().objects.create_superuser("boss", "boss@example.invalid", "a-strong-pass-123")
        self.client.force_login(admin)
        url = reverse("admin:crawling_crawlrecord_change", args=[rec.pk])
        page = self.client.get(url)
        self.assertContains(page, "對不上組織")
        self.assertContains(page, 'name="organization"')
        self.client.post(url, {"organization": org.pk, "review_note": "", "_approve": "1"})
        rec.refresh_from_db()
        self.assertEqual((rec.status, rec.ubn, rec.organization_id), (CrawlRecord.Status.APPROVED, "55555555", org.pk))
        self.assertEqual(Penalty.objects.filter(organization=org).count(), 1)

    def test_approve_without_org_stays_pending(self):
        self.run_sample()
        rec = CrawlRecord.objects.filter(source=self.source, ubn="").first()
        admin = get_user_model().objects.create_superuser("boss", "boss@example.invalid", "a-strong-pass-123")
        self.client.force_login(admin)
        self.client.post(reverse("admin:crawling_crawlrecord_changelist"),
                         {"action": "approve", "_selected_action": [rec.pk]})
        rec.refresh_from_db()
        self.assertEqual(rec.status, CrawlRecord.Status.PENDING)
        self.assertIn("對不上組織", rec.review_note)
        unmatched = self.client.get(reverse("admin:crawling_crawlrecord_changelist") + "?match=unmatched")
        self.assertContains(unmatched, "財團法人興毅社會福利慈善事業基金會")

    def test_api_category_and_score_unchanged(self):
        before = Organization.objects.get(pk=self.maria.pk).disclosure_score
        Penalty.objects.create(organization=self.maria, content="勸募裁處", source_name="衛生福利部公益勸募管理系統",
                               external_id="1")
        self.run_sample()
        data = self.client.get("/api/orgs/05557110").json()
        self.assertEqual(sorted(p["category"] for p in data["penalties"]), ["fundraising", "labor"])
        self.assertEqual(Organization.objects.get(pk=self.maria.pk).disclosure_score, before)
        self.assertFalse(Penalty.objects.filter(Q(content__contains="王大明")).exists())
