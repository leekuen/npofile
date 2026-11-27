"""LK-19 政府補助：官方來源自動上架、跨季累計金額更新同一筆、近 5 年、清舊資料、API。"""

from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from npofile_crawler import grants

from crawling.ingest import run_source
from crawling.models import CrawlerSource, CrawlRun
from orgs import period
from orgs.models import Grant, Organization

FX = Path(__file__).resolve().parents[3] / "crawler" / "tests" / "fixtures"


def sample_items(year: int, orgs):
    f = grants.GrantFile(year, 4, "CSV", "x")
    rows = grants.rows_from_table(grants.csv_table((FX / "grants_sample.csv").read_bytes()))
    return list(grants.to_items(f, rows, grants.OrgMatcher(orgs)))


class GrantIngestTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="mohw_grants")
        self.maria = Organization.objects.create(ubn="05557110", name="財團法人瑪利亞社會福利基金會")
        self.garden = Organization.objects.create(ubn="01234567", name="財團法人勵馨社會福利事業基金會")
        self.orgs = list(Organization.objects.values_list("ubn", "name"))
        self.year = period.since_roc_year() + 3

    def test_official_source_auto_applies(self):
        self.assertTrue(self.source.auto_approve)
        run = run_source(self.source, items=sample_items(self.year, self.orgs))
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)
        self.assertEqual((run.created, run.applied, run.pending), (5, 5, 0))
        self.assertEqual(Grant.objects.filter(organization=self.maria).count(), 3)
        attached = Grant.objects.get(organization=self.garden, facility="台北市私立少女中途之家")
        self.assertEqual(attached.amount, 350000)
        self.assertEqual(attached.agency, "社會及家庭署")

    def test_next_quarter_updates_same_grant(self):
        run_source(self.source, items=sample_items(self.year, self.orgs))
        items = sample_items(self.year, self.orgs)
        items[0].data["amount"] = 1_500_000
        items[0].data["quarter"] = 4
        run = run_source(self.source, items=items)
        self.assertEqual(run.created, 1)  # 只有金額變了的那筆是新紀錄
        self.assertEqual(Grant.objects.count(), 5)
        self.assertEqual(Grant.objects.get(external_id=items[0].external_id).amount, 1_500_000)

    def test_api_lists_window_only_and_score_unchanged(self):
        before = Organization.objects.get(pk=self.maria.pk).disclosure_score
        run_source(self.source, items=sample_items(self.year, self.orgs) + sample_items(period.since_roc_year() - 1, self.orgs))
        data = self.client.get("/api/orgs/05557110").json()
        self.assertEqual({g["year"] for g in data["grants"]}, {self.year})
        self.assertEqual(len(data["grants"]), 3)
        self.assertEqual(data["grants"][0]["amount"], 2_400_000)  # 金額大的在前
        self.assertEqual(Organization.objects.get(pk=self.maria.pk).disclosure_score, before)

    def test_prune_removes_old_grants(self):
        run_source(self.source, items=sample_items(self.year, self.orgs) + sample_items(period.since_roc_year() - 1, self.orgs))
        self.assertEqual(Grant.objects.count(), 10)
        call_command("prune_old_records")
        self.assertEqual(Grant.objects.count(), 5)
        self.assertFalse(Grant.objects.filter(year__lt=period.since_roc_year()).exists())
