"""LK-25 組織財報：官方來源自動上架、同年度更新同一筆、近 5 年、清舊資料、API、已收過的不再下載。"""

import io
from django.core.management import call_command
from django.test import TestCase
from npofile_crawler import swft
from npofile_crawler.items import Item

from crawling.ingest import run_source
from crawling.models import CrawlerSource, CrawlRun
from orgs import period
from orgs.models import FinancialReport, Organization


def report(ubn: str, no: str, year: int, donation=1000, total=5000) -> Item:
    return Item(
        kind="financial", ubn=ubn, external_id=f"{no}-{year}", source_url=swft.SITE_URL,
        data={"year": year, "donation": donation, "income_total": total, "statement": "決算總表",
              "filer_name": "財團法人測試基金會", "filer_no": no},
    )


class FinancialIngestTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="swft")
        self.org = Organization.objects.create(ubn="31006107", name="財團法人測試基金會")
        self.year = period.since_roc_year() + 3

    def test_official_source_auto_applies(self):
        self.assertTrue(self.source.auto_approve)
        run = run_source(self.source, items=[report("31006107", "A0003", self.year), report("31006107", "A0003", self.year - 1)])
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)
        self.assertEqual((run.created, run.applied, run.pending), (2, 2, 0))
        r = FinancialReport.objects.get(external_id=f"A0003-{self.year}")
        self.assertEqual((r.organization, r.donation_income, r.income_total), (self.org, 1000, 5000))

    def test_same_year_updates_same_row(self):
        run_source(self.source, items=[report("31006107", "A0003", self.year)])
        run_source(self.source, items=[report("31006107", "A0003", self.year, donation=2000)])
        self.assertEqual(FinancialReport.objects.count(), 1)
        self.assertEqual(FinancialReport.objects.get().donation_income, 2000)

    def test_unreadable_numbers_stay_empty(self):
        run_source(self.source, items=[report("31006107", "A0003", self.year, donation=None, total=None)])
        r = FinancialReport.objects.get()
        self.assertIsNone(r.donation_income)
        self.assertIsNone(r.income_total)

    def test_api_lists_window_only_and_score_unchanged(self):
        before = Organization.objects.get(pk=self.org.pk).disclosure_score
        run_source(self.source, items=[report("31006107", "A0003", self.year), report("31006107", "A0003", period.since_roc_year() - 1)])
        data = self.client.get("/api/orgs/31006107").json()
        self.assertEqual([r["year"] for r in data["financial_reports"]], [self.year])
        self.assertEqual(data["financial_reports"][0]["donation_income"], 1000)
        self.assertEqual(data["public_raised"]["total"], 0)  # 財報不加進公開募款
        self.assertEqual(Organization.objects.get(pk=self.org.pk).disclosure_score, before)

    def test_prune_removes_old_reports(self):
        run_source(self.source, items=[report("31006107", "A0003", self.year), report("31006107", "A0003", period.since_roc_year() - 1)])
        call_command("prune_old_records", stdout=io.StringIO())
        self.assertEqual(list(FinancialReport.objects.values_list("year", flat=True)), [self.year])

    def test_known_reports_are_passed_to_crawler(self):
        run_source(self.source, items=[report("31006107", "A0003", self.year)])
        seen = {}

        def fake_fetch(client, limit=None, since_roc=None, orgs=(), have=()):
            seen["have"] = set(have)
            seen["orgs"] = list(orgs)
            return iter(())

        from npofile_crawler import sources
        real = sources.SOURCES["swft"]
        sources.SOURCES["swft"] = real.__class__(**{**real.__dict__, "fetch": fake_fetch})
        try:
            run_source(self.source, client=object())
        finally:
            sources.SOURCES["swft"] = real
        self.assertEqual(seen["have"], {f"A0003-{self.year}"})
        self.assertIn(("31006107", "財團法人測試基金會"), seen["orgs"])


class AlliancePriorityTests(TestCase):
    """自律聯盟會員財務報告：先進審核清單；同一年衛福部也有時，API 只給衛福部那份。"""

    def setUp(self):
        self.swft = CrawlerSource.objects.get(key="swft")
        self.twnpos = CrawlerSource.objects.get(key="twnpos")
        self.org = Organization.objects.create(ubn="31006107", name="財團法人測試基金會")
        self.year = period.since_roc_year() + 3

    def alliance(self, year, donation, method="影像辨識"):
        return Item(kind="financial", ubn="31006107", external_id=f"F0999-{year}",
                    source_url="https://drive.google.com/file/d/X/view",
                    data={"year": year, "donation": donation, "income_total": None, "statement": "自律聯盟會員財務報告",
                          "method": method, "filer_name": "財團法人測試基金會", "filer_no": "F0999"})

    def test_alliance_goes_to_review(self):
        self.assertFalse(self.twnpos.auto_approve)
        run = run_source(self.twnpos, items=[self.alliance(self.year, 1234)])
        self.assertEqual((run.created, run.pending), (1, 1))
        self.assertEqual(FinancialReport.objects.count(), 0)

    def test_ministry_wins_same_year(self):
        self.twnpos.auto_approve = True
        self.twnpos.save()
        run_source(self.twnpos, items=[self.alliance(self.year, 1234), self.alliance(self.year - 1, 999)])
        run_source(self.swft, items=[report("31006107", "A0003", self.year, donation=5000, total=9000)])
        rows = self.client.get("/api/orgs/31006107").json()["financial_reports"]
        self.assertEqual([(r["year"], r["donation_income"], r["parse_method"]) for r in rows],
                         [(self.year, 5000, ""), (self.year - 1, 999, "影像辨識")])
