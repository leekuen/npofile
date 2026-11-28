"""LK-25 組織財報寫進 LK-17 的年度財務：官方決算自動上架、同年度整列取代、來源優先順序、已收過的不再下載。"""

from django.test import TestCase
from npofile_crawler import swft
from npofile_crawler.items import Item

from crawling.ingest import run_source
from crawling.models import CrawlerSource, CrawlRecord, CrawlRun
from orgs import period
from orgs.models import FinancialYear, Organization

UBN = "31006107"


def ministry(year: int, contributions=1000, total=5000, no="A0003") -> Item:
    return Item(
        kind="financial", ubn=UBN, external_id=f"{no}-{year}", source_url=swft.SITE_URL,
        data={"year": year, "contributions": contributions, "total_revenue": total, "net_assets": 7000,
              "document_url": swft.SITE_URL, "document_title": f"財團法人測試基金會 {year} 年度決算總表",
              "method": "official", "notes": "", "filer_name": "財團法人測試基金會", "filer_no": no},
    )


def alliance(year: int, contributions=1234, method="ocr") -> Item:
    return Item(
        kind="financial", ubn=UBN, external_id=f"F0999-{year}", source_url="https://drive.google.com/file/d/X/view",
        data={"year": year, "contributions": contributions, "total_revenue": None,
              "document_url": "https://drive.google.com/file/d/X/view", "document_title": "財務報告（自律聯盟）",
              "method": method, "notes": "", "filer_name": "財團法人測試基金會", "filer_no": "F0999"},
    )


class MinistrySettlementTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="swft")
        self.org = Organization.objects.create(ubn=UBN, name="財團法人測試基金會")
        self.year = period.since_roc_year() + 3

    def test_official_source_auto_applies(self):
        self.assertTrue(self.source.auto_approve)
        run = run_source(self.source, items=[ministry(self.year), ministry(self.year - 1)])
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)
        self.assertEqual((run.created, run.applied, run.pending), (2, 2, 0))
        fy = FinancialYear.objects.get(year=self.year)
        self.assertEqual((fy.organization, fy.contributions, fy.total_revenue, fy.net_assets), (self.org, 1000, 5000, 7000))
        self.assertEqual(fy.method, FinancialYear.Method.OFFICIAL)
        self.assertIsNone(fy.total_expenses)  # 報告沒列的留空，不當 0

    def test_same_year_replaced(self):
        run_source(self.source, items=[ministry(self.year)])
        run_source(self.source, items=[ministry(self.year, contributions=2000)])
        self.assertEqual(FinancialYear.objects.get().contributions, 2000)

    def test_api_shows_method(self):
        run_source(self.source, items=[ministry(self.year)])
        rows = self.client.get(f"/api/orgs/{UBN}").json()["financials"]
        self.assertEqual([(r["year"], r["contributions"], r["method"]) for r in rows], [(self.year, 1000, "official")])

    def test_known_reports_are_passed_to_crawler(self):
        run_source(self.source, items=[ministry(self.year)])
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
        self.assertIn((UBN, "財團法人測試基金會"), seen["orgs"])


class SourcePriorityTests(TestCase):
    """自律聯盟會員財報先進審核清單；同一年有衛福部決算時，可信度低的不蓋過高的。"""

    def setUp(self):
        self.swft = CrawlerSource.objects.get(key="swft")
        self.twnpos = CrawlerSource.objects.get(key="twnpos")
        self.org = Organization.objects.create(ubn=UBN, name="財團法人測試基金會")
        self.year = period.since_roc_year() + 3

    def test_alliance_goes_to_review(self):
        self.assertFalse(self.twnpos.auto_approve)
        run = run_source(self.twnpos, items=[alliance(self.year)])
        self.assertEqual((run.created, run.pending), (1, 1))
        self.assertFalse(FinancialYear.objects.exists())

    def approve_alliance(self, *items):
        self.twnpos.auto_approve = True
        self.twnpos.save()
        run_source(self.twnpos, items=list(items))

    def test_ministry_overrides_alliance_but_not_the_other_way(self):
        self.approve_alliance(alliance(self.year), alliance(self.year - 1, contributions=999))
        run_source(self.swft, items=[ministry(self.year, contributions=5000)])
        self.assertEqual(FinancialYear.objects.get(year=self.year).contributions, 5000)
        # 聯盟那份之後再進來（例：重新核准）也不蓋掉衛福部的
        self.approve_alliance(alliance(self.year, contributions=1))
        fy = FinancialYear.objects.get(year=self.year)
        self.assertEqual((fy.contributions, fy.method), (5000, "official"))
        rec = CrawlRecord.objects.filter(source=self.twnpos, external_id=f"F0999-{self.year}").latest("id")
        self.assertIn("沒有覆蓋", rec.review_note)
        # 衛福部沒有的那一年照用聯盟的
        self.assertEqual(FinancialYear.objects.get(year=self.year - 1).method, "ocr")

    def test_link_only_row_can_be_filled_by_lower_rank(self):
        run_source(self.swft, items=[ministry(self.year, contributions=None, total=None)])
        FinancialYear.objects.filter(year=self.year).update(net_assets=None)
        self.approve_alliance(alliance(self.year, contributions=42))
        self.assertEqual(FinancialYear.objects.get(year=self.year).contributions, 42)

    def test_locked_year_untouched(self):
        FinancialYear.objects.create(organization=self.org, year=self.year, contributions=7, locked=True)
        run_source(self.swft, items=[ministry(self.year)])
        self.assertEqual(FinancialYear.objects.get().contributions, 7)
