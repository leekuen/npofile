from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from npofile_crawler.items import Item

from crawling import orgsite_targets
from crawling.ingest import apply_records, run_source
from crawling.models import CrawlerSource, CrawlRecord, OrgSiteCheck
from orgs import period
from orgs.models import FinancialYear, OrgDocument, Organization

UBN = "00968297"
PDF = "https://npo.example.org/files/113fin.pdf"


def doc(year, kind="financial", url=PDF):
    return Item("document", UBN, {"year": year, "doc_kind": kind, "title": f"{year}年度財務報告", "url": url,
                                  "found_on": "https://npo.example.org/disclosure"},
                source_url="https://npo.example.org/disclosure", external_id=url[-20:])


def fin(year, revenue=36914991, url=PDF):
    return Item("financial", UBN, {
        "year": year, "audited": True, "total_revenue": revenue, "contributions": 15157996, "government_grants": None,
        "program_service_revenue": None, "investment_income": None, "other_revenue": None,
        "total_expenses": 34405607, "program_expenses": 30087354, "admin_expenses": 4289453,
        "fundraising_expenses": None, "surplus": 2509384, "total_assets": 40616848, "total_liabilities": 2268192,
        "net_assets": 38348656, "notes": "", "method": "ai", "document_url": url, "document_title": f"{year}年度財務報告",
    }, source_url=url, external_id=str(year))


class OrgSiteIngestTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="orgsite")
        self.org = Organization.objects.create(ubn=UBN, name="財團法人中華民國自閉症基金會", website="https://npo.example.org/")

    def test_source_seeded_as_needing_review(self):
        self.assertFalse(self.source.auto_approve)

    def test_records_wait_for_review_then_apply(self):
        run = run_source(self.source, items=[doc(113), fin(113)])
        self.assertEqual((run.created, run.pending, run.applied), (2, 2, 0))
        self.assertFalse(OrgDocument.objects.exists())
        self.assertFalse(FinancialYear.objects.exists())

        ok, failed = apply_records(list(CrawlRecord.objects.filter(source=self.source)), CrawlRecord.Status.APPROVED)
        self.assertEqual((ok, failed), (2, 0))
        d = OrgDocument.objects.get()
        self.assertEqual((d.year, d.kind, d.url), (113, "financial", PDF))
        f = FinancialYear.objects.get()
        self.assertEqual((f.year, f.total_revenue, f.method, f.locked), (113, 36914991, "ai", False))
        self.assertIsNone(f.government_grants)
        self.assertEqual(f.program_expense_ratio, 87)

    def test_locked_year_not_overwritten(self):
        FinancialYear.objects.create(organization=self.org, year=113, total_revenue=1, locked=True)
        run_source(self.source, items=[fin(113, revenue=999)])
        rec = CrawlRecord.objects.get()
        apply_records([rec], CrawlRecord.Status.APPROVED)
        self.assertEqual(FinancialYear.objects.get().total_revenue, 1)
        rec.refresh_from_db()
        self.assertIn("管理員改過", rec.review_note)

    def test_api_shows_only_recent_years(self):
        old = period.since_roc_year() - 1
        new = period.since_roc_year()
        run_source(self.source, items=[doc(old, url=PDF + "?old"), doc(new), fin(old, url=PDF + "?old"), fin(new)])
        apply_records(list(CrawlRecord.objects.all()), CrawlRecord.Status.APPROVED)
        body = self.client.get(f"/api/orgs/{UBN}").json()
        self.assertEqual([f["year"] for f in body["financials"]], [new])
        self.assertEqual([d["year"] for d in body["documents"]], [new])
        self.assertEqual(body["financials"][0]["program_expense_ratio"], 87)
        self.assertEqual(body["documents"][0]["kind_label"], "財務報告")

    def test_existing_tabs_api_unchanged(self):
        body = self.client.get(f"/api/orgs/{UBN}").json()
        for key in ("annual_records", "projects", "penalties", "donations"):
            self.assertIn(key, body)


class TargetsTests(TestCase):
    def test_order_never_checked_first_and_skip_social(self):
        Organization.objects.create(ubn="11111111", name="甲", website="https://a.example.org/")
        Organization.objects.create(ubn="22222222", name="乙", website="https://b.example.org/")
        Organization.objects.create(ubn="33333333", name="丙", website="https://www.facebook.com/c")
        Organization.objects.create(ubn="44444444", name="丁", website="")
        OrgSiteCheck.objects.create(ubn="11111111", website="https://a.example.org/", checked_at="2026-01-01T00:00Z")
        got = [ubn for ubn, _ in orgsite_targets.targets()]
        self.assertEqual(got, ["22222222", "11111111"])
        self.assertEqual(OrgSiteCheck.objects.count(), 2)

    @override_settings(ANTHROPIC_API_KEY="")
    def test_no_key_no_extractor(self):
        self.assertIsNone(orgsite_targets.extractor())

    @override_settings(ANTHROPIC_API_KEY="test-key", FINANCIAL_EXTRACT_MODEL="claude-opus-5-5")
    def test_key_builds_extractor_without_calling_api(self):
        # 用假的 anthropic 模組：沒裝這個套件的環境也能跑，也確定不會真的打 API
        fake = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"anthropic": fake}):
            ex = orgsite_targets.extractor()
        client = fake.Anthropic
        self.assertEqual(ex.model, "claude-opus-5-5")
        client.assert_called_once_with(api_key="test-key")

    def test_seen_docs(self):
        source = CrawlerSource.objects.get(key="orgsite")
        Organization.objects.create(ubn=UBN, name="自閉症基金會")
        run_source(source, items=[fin(113)])
        self.assertEqual(orgsite_targets.seen_docs(source), {PDF})


class AdminLockTests(TestCase):
    def test_admin_edit_locks_year(self):
        user = get_user_model().objects.create_superuser("admin", "a@example.org", "pw-for-test-only")
        self.client.force_login(user)
        org = Organization.objects.create(ubn=UBN, name="自閉症基金會")
        f = FinancialYear.objects.create(organization=org, year=113, total_revenue=5, method="ai")
        resp = self.client.post(f"/admin/orgs/financialyear/{f.pk}/change/", {
            "organization": org.pk, "year": 113, "total_revenue": 6, "audited": "unknown", "document_title": "",
            "document_url": "", "notes": "",
        })
        self.assertEqual(resp.status_code, 302, resp.content[:500])
        f.refresh_from_db()
        self.assertEqual((f.total_revenue, f.locked, f.method), (6, True, "manual"))


class PruneTests(TestCase):
    def test_prune_drops_old_financials_and_documents(self):
        from io import StringIO

        from django.core.management import call_command

        org = Organization.objects.create(ubn=UBN, name="自閉症基金會")
        old, new = period.since_roc_year() - 1, period.since_roc_year()
        for y in (old, new):
            FinancialYear.objects.create(organization=org, year=y, total_revenue=1)
            OrgDocument.objects.create(organization=org, year=y, kind="financial", title="t", url=f"{PDF}?{y}")
        out = StringIO()
        call_command("prune_old_records", stdout=out)
        self.assertEqual(list(FinancialYear.objects.values_list("year", flat=True)), [new])
        self.assertEqual(list(OrgDocument.objects.values_list("year", flat=True)), [new])
        self.assertIn("年度財務 1 筆、官網報告 1 筆", out.getvalue())


class ListAndReviewPageTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(ubn=UBN, name="自閉症基金會")
        self.source = CrawlerSource.objects.get(key="orgsite")

    def test_list_shows_latest_revenue_in_window(self):
        new = period.since_roc_year() + 2
        FinancialYear.objects.create(organization=self.org, year=new - 1, total_revenue=100)
        FinancialYear.objects.create(organization=self.org, year=new, total_revenue=None)  # 沒有總收入的年度跳過
        FinancialYear.objects.create(organization=self.org, year=period.since_roc_year() - 1, total_revenue=999)
        Organization.objects.create(ubn="22222222", name="沒有財報")
        rows = {o["ubn"]: o["latest_revenue"] for o in self.client.get("/api/orgs").json()["results"]}
        self.assertEqual(rows[UBN], {"year": new - 1, "total_revenue": 100})
        self.assertIsNone(rows["22222222"])

    def test_review_page_shows_table_and_report_link(self):
        user = get_user_model().objects.create_superuser("admin", "a@example.org", "pw-for-test-only")
        self.client.force_login(user)
        run_source(self.source, items=[fin(113), doc(113)])
        fin_rec = CrawlRecord.objects.get(kind="financial")
        page = self.client.get(f"/admin/crawling/crawlrecord/{fin_rec.pk}/change/").content.decode()
        self.assertIn("36,914,991 元", page)
        self.assertIn("總收入", page)
        self.assertIn("—（報告沒列）", page)
        self.assertIn(PDF, page)
        self.assertIn("自閉症基金會", page)
        doc_rec = CrawlRecord.objects.get(kind="document")
        page = self.client.get(f"/admin/crawling/crawlrecord/{doc_rec.pk}/change/").content.decode()
        self.assertIn("打開原始報告", page)
        listing = self.client.get("/admin/crawling/crawlrecord/").content.decode()
        self.assertIn("113 年 財務報告：113年度財務報告", listing)

        apply_records([fin_rec], CrawlRecord.Status.APPROVED)
        page = self.client.get(f"/admin/crawling/crawlrecord/{fin_rec.pk}/change/").content.decode()
        self.assertIn("到這一年的年度財務修改", page)


class ReviewButtonsTests(TestCase):
    def setUp(self):
        Organization.objects.create(ubn=UBN, name="自閉症基金會")
        user = get_user_model().objects.create_superuser("admin", "a@example.org", "pw-for-test-only")
        self.client.force_login(user)
        run_source(CrawlerSource.objects.get(key="orgsite"), items=[fin(113), doc(113)])

    def post(self, rec, button):
        return self.client.post(f"/admin/crawling/crawlrecord/{rec.pk}/change/", {"review_note": "對過原檔", button: "1"})

    def test_approve_button(self):
        rec = CrawlRecord.objects.get(kind="financial")
        self.assertIn("核准並上架", self.client.get(f"/admin/crawling/crawlrecord/{rec.pk}/change/").content.decode())
        resp = self.post(rec, "_approve")
        self.assertEqual(resp.status_code, 302)
        rec.refresh_from_db()
        self.assertEqual((rec.status, rec.review_note), ("approved", "對過原檔"))
        self.assertEqual(FinancialYear.objects.get().total_revenue, 36914991)

    def test_reject_button(self):
        rec = CrawlRecord.objects.get(kind="document")
        self.post(rec, "_reject")
        rec.refresh_from_db()
        self.assertEqual(rec.status, "rejected")
        self.assertFalse(OrgDocument.objects.exists())
