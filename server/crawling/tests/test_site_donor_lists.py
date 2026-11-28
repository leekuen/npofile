"""官網的接受捐贈名單（LK-47）：審核後寫成捐款紀錄、跟衛福部清冊與其他官網名單去重。"""

from django.test import TestCase, override_settings
from npofile_crawler import donorlists, orgsite
from npofile_crawler.items import Item

from crawling import orgsite_targets
from crawling.ingest import apply_records, run_source
from crawling.models import CrawlerSource, CrawlRecord
from orgs import period
from orgs.models import Donation, Donor, Organization
from orgs.scoring import recompute

UBN = "01033182"
LIST = "https://npo.example.org/files/114donate.pdf"
LIST2 = "https://npo.example.org/files/114-1-10donate.pdf"
YEAR = period.today().year - 1  # 去年：落在近 5 年內
ROC = YEAR - 1911
D1, D2 = f"{YEAR}-01-03", f"{YEAR}-02-01"


def row(name, amount, on, kind="company"):
    return {"name": name, "kind": kind, "amount": amount, "donated_on": on}


def site_list(rows, url=LIST):
    return Item("site_donor_list", UBN, {
        "year": ROC, "title": f"{ROC}年捐款芳名錄", "url": url, "found_on": "https://npo.example.org/credit/",
        "method": "text", "rows": rows, "summary": {"total_rows": len(rows) + 10, "small_individual_count": 10},
    }, source_url=url, external_id=orgsite.url_id(url))


def mohw_list(rows, aid="9990001"):
    full = [{**r, "receipt_no": "", "purpose": ""} for r in rows]
    return Item("donor_list", UBN, {"project_name": "測試勸募活動", "rows": full, "summary": {"total_rows": len(rows)}},
                f"https://sasw.mohw.gov.tw/app39/fundactivity/{aid}", aid)


class SiteDonorListTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="orgsite")
        self.mohw = CrawlerSource.objects.get(key="mohw_activities")
        self.org = Organization.objects.create(ubn=UBN, name="財團法人天主教善牧社會福利基金會", website="https://npo.example.org/")

    def approve(self, *items):
        run_source(self.source, items=list(items))
        recs = list(CrawlRecord.objects.filter(source=self.source, status=CrawlRecord.Status.PENDING))
        ok, failed = apply_records(recs, CrawlRecord.Status.APPROVED)
        self.assertEqual(failed, 0)
        return ok

    def site_rows(self):
        return sorted(Donation.objects.filter(source_name=orgsite.SOURCE_NAME).values_list("donor_name", "amount"))

    def test_waits_for_review_then_writes_donations(self):
        run_source(self.source, items=[site_list([row("冠宇專利商標設計有限公司", 3000, D1)])])
        self.assertFalse(Donation.objects.exists())
        self.assertEqual(CrawlRecord.objects.get().kind, "site_donor_list")
        apply_records(list(CrawlRecord.objects.all()), CrawlRecord.Status.APPROVED)
        d = Donation.objects.get()
        self.assertEqual((d.donor_name, d.amount, d.donated_on.isoformat(), d.source_url), ("冠宇專利商標設計有限公司", 3000, D1, LIST))
        self.assertIsNone(d.project)
        self.assertEqual(d.donor.kind, Donor.Kind.COMPANY)

    def test_same_file_replaced_on_reread(self):
        self.approve(site_list([row("甲乙股份有限公司", 1000, D1)]))
        self.approve(site_list([row("甲乙股份有限公司", 2000, D1), row("丙丁企業社", 500, D2)]))
        self.assertEqual(self.site_rows(), [("丙丁企業社", 500), ("甲乙股份有限公司", 2000)])

    def test_mohw_first_then_site_duplicate_skipped(self):
        # C2：衛福部清冊已有同一筆（名稱＋金額＋日期），官網名單那一列不寫；台／臺寫法不同也算同一位
        run_source(self.mohw, items=[mohw_list([row("臺灣甲乙股份有限公司", 5000, D1)])])
        self.approve(site_list([row("台灣甲乙股份有限公司", 5000, D1), row("台灣甲乙股份有限公司", 5000, D2)]))
        self.assertEqual(Donation.objects.filter(source_name=orgsite.SOURCE_NAME).count(), 1)
        self.assertEqual(Donation.objects.filter(organization=self.org).count(), 2)

    def test_site_first_then_mohw_removes_site_duplicate(self):
        self.approve(site_list([row("甲乙股份有限公司", 5000, D1), row("甲乙股份有限公司", 5000, D1), row("丙丁企業社", 1, D1)]))
        run_source(self.mohw, items=[mohw_list([row("甲乙股份有限公司", 5000, D1)])])
        # 官網兩筆一模一樣的，衛福部只有一筆：只刪一筆
        self.assertEqual(self.site_rows(), [("丙丁企業社", 1), ("甲乙股份有限公司", 5000)])
        self.assertEqual(Donation.objects.filter(organization=self.org, donor_name="甲乙股份有限公司").count(), 2)

    def test_two_site_files_counted_once(self):
        # C3：「1-12 月」和「1-10 月」兩份都有的列只算一次；只在其中一份的照算
        self.approve(site_list([row("甲乙股份有限公司", 5000, D1), row("丙丁企業社", 800, D2)], url=LIST))
        self.approve(site_list([row("甲乙股份有限公司", 5000, D1), row("戊己有限公司", 300, D2)], url=LIST2))
        self.assertEqual(self.site_rows(), [("丙丁企業社", 800), ("戊己有限公司", 300), ("甲乙股份有限公司", 5000)])

    def test_api_and_has_data(self):
        self.approve(site_list([row("冠宇專利商標設計有限公司", 3000, D1), row("台北市測試協會", 120000, D2, kind="group")]))
        recompute(Organization.objects.filter(pk=self.org.pk))
        self.org.refresh_from_db()
        self.assertTrue(self.org.has_data)  # W5
        body = self.client.get(f"/api/orgs/{UBN}").json()  # W3
        got = {(d["donor_name"], d["donor_kind"], d["amount"], d["source_name"], d["source_url"]) for d in body["donations"]}
        self.assertEqual(got, {("冠宇專利商標設計有限公司", "company", 3000, "組織官網", LIST),
                               ("台北市測試協會", "group", 120000, "組織官網", LIST)})
        donor = Donor.objects.get(name="冠宇專利商標設計有限公司")
        detail = self.client.get(f"/api/donors/{donor.pk}").json()
        self.assertEqual(detail["total"], 3000)  # W4


class OptionsTests(TestCase):
    @override_settings(ANTHROPIC_API_KEY="", CLAUDE_CODE_OAUTH_TOKEN="", ORGSITE_DONOR_LIST_MAX_PER_RUN=7)
    def test_reader_works_without_claude(self):
        source = CrawlerSource.objects.get(key="orgsite")
        opts = orgsite_targets.options(source)
        self.assertEqual(opts["lists_per_run"], 7)
        self.assertIs(opts["list_reader"].func, donorlists.read)
        self.assertIsNone(opts["list_reader"].keywords["ai"])  # 沒設 Claude：掃描檔不讀，文字型照讀
        self.assertEqual(opts["seen_lists"], set())

    def test_seen_lists(self):
        source = CrawlerSource.objects.get(key="orgsite")
        Organization.objects.create(ubn=UBN, name="善牧")
        run_source(source, items=[site_list([row("甲乙股份有限公司", 1, D1)])])
        self.assertEqual(orgsite_targets.seen_lists(source), {LIST})
