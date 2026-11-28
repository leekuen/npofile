"""財團法人年度捐贈名單清冊（LK-48）：匯入、去重、個人門檻、近 5 年、前台顯示。"""

from datetime import date

from django.test import TestCase
from npofile_crawler import annual_donors
from npofile_crawler.items import Item
from rest_framework.test import APIClient

from crawling.ingest import apply_records, run_source
from crawling.models import CrawlerSource, CrawlRecord
from orgs import period
from orgs.models import AnnualDonorList, Donation, Donor, Organization, Project

GIVER = "00000011"  # 財團法人範例企業慈善基金會（支付清冊）
TAKER = "00000022"  # 財團法人範例兒童福利基金會（接受清冊）
OTHER = "00000033"


def this_year() -> int:
    return period.today().year - 1911


def lst(ubn, direction, year, rows, url=None):
    raw = [annual_donors.RawRow(n, a) for n, a in rows]
    result = annual_donors.summarize(direction, raw)
    url = url or f"https://npo{ubn}.example.org/{year}-{direction}.pdf"
    return Item("annual_list", ubn, {
        "year": year, "direction": direction, "title": f"{year}年{'支付' if direction == 'pay' else '接受'}捐贈名單清冊",
        "url": url, "found_on": f"https://npo{ubn}.example.org/disclosure", "format": "pdf", "scanned": False, **result,
    }, source_url=url, external_id=url[-20:])


class AnnualListTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="orgsite")
        self.giver = Organization.objects.create(ubn=GIVER, name="財團法人範例企業慈善基金會")
        self.taker = Organization.objects.create(ubn=TAKER, name="財團法人範例兒童福利基金會")
        self.other = Organization.objects.create(ubn=OTHER, name="社團法人範例關懷協會")
        self.api = APIClient()
        self.y = this_year() - 1

    def ingest(self, *items):
        run_source(self.source, items=list(items))
        apply_records(list(CrawlRecord.objects.filter(source=self.source, status=CrawlRecord.Status.PENDING)),
                      CrawlRecord.Status.APPROVED)

    def counted(self, **kw):
        return Donation.objects.filter(period.donation_q(), **kw)

    def test_receive_list_keeps_companies_groups_and_large_individuals_only(self):
        self.ingest(lst(TAKER, "receive", self.y, [
            ("範例科技股份有限公司", 500000), ("衛福部", 30000), ("王小明", 3000), ("陳大華", 60000), ("陳大華", 50000),
            ("善心人士", 1000),
        ]))
        names = sorted(self.counted(organization=self.taker).values_list("donor_name", flat=True))
        self.assertEqual(names, sorted(["範例科技股份有限公司", "衛福部", "陳大華", "陳大華"]))
        self.assertFalse(Donor.objects.filter(name="王小明").exists())  # 未達 10 萬的個人不存姓名
        listing = AnnualDonorList.objects.get()
        self.assertEqual((listing.small_individual_count, listing.anonymous_rows, listing.total_rows), (1, 1, 6))
        d = Donation.objects.filter(donor_name="範例科技股份有限公司").get()
        self.assertEqual((d.year, d.donated_on, d.source_name), (self.y, None, "財團法人年度清冊（接受）"))

    def test_pay_list_becomes_recipient_donation_and_unmatched_stays_in_admin(self):
        self.ingest(lst(GIVER, "pay", self.y, [
            ("財團法人範例兒童福利基金會", 500000), ("社團法人範例關懷協會附設日照中心", 80000),
            ("不在站上的協會", 10000), ("林〇儀喪葬補助費", 20000),
        ]))
        to_taker = self.counted(organization=self.taker).get()
        self.assertEqual((to_taker.donor.name, to_taker.amount, to_taker.source_name),
                         ("財團法人範例企業慈善基金會", 500000, "財團法人年度清冊（支付）"))
        self.assertEqual(self.counted(organization=self.other).get().amount, 80000)  # 「X附設Y」歸 X
        listing = AnnualDonorList.objects.get()
        self.assertEqual(listing.unmatched, [{"name": "不在站上的協會", "amount": 10000}])
        self.assertFalse(Donation.objects.filter(donor_name__contains="喪葬").exists())  # 個人受助者不留
        self.assertEqual(listing.small_individual_count, 1)

    def test_same_gift_in_pay_and_receive_lists_counts_once(self):
        self.ingest(
            lst(GIVER, "pay", self.y, [("財團法人範例兒童福利基金會", 500000)]),
            lst(TAKER, "receive", self.y, [("財團法人範例企業慈善基金會", 500000), ("財團法人範例企業慈善基金會", 500000)]),
        )
        rows = self.counted(organization=self.taker)
        # 接受清冊兩列都算（同一份清冊上的兩筆是兩次捐款），支付清冊那一筆已在接受清冊上，不算
        self.assertEqual(sorted(rows.values_list("source_name", flat=True)), ["財團法人年度清冊（接受）"] * 2)
        self.assertEqual(Donation.objects.filter(duplicate=True).count(), 1)
        # 不同金額不算重複
        self.ingest(lst(GIVER, "pay", self.y, [("財團法人範例兒童福利基金會", 300000)], url="https://x.example.org/pay2.pdf"))
        self.assertEqual(self.counted(organization=self.taker).count(), 3)

    def test_mohw_list_wins_over_annual_list(self):
        project = Project.objects.create(organization=self.taker, name="勸募活動", source_name="衛福部",
                                         start_date=date(self.y + 1911, 3, 1))
        donor = Donor.objects.create(name="範例科技股份有限公司", kind=Donor.Kind.COMPANY)
        Donation.objects.create(organization=self.taker, donor=donor, project=project, amount=200000,
                                donated_on=date(self.y + 1911, 5, 1), source_name="衛福部")
        self.ingest(lst(TAKER, "receive", self.y, [("範例科技股份有限公司", 200000), ("範例科技股份有限公司", 90000)]))
        self.assertEqual(sorted(self.counted(organization=self.taker).values_list("amount", flat=True)), [90000, 200000])
        self.assertTrue(Donation.objects.get(annual_list__isnull=False, amount=200000).duplicate)

    def test_relist_replaces_previous_rows(self):
        self.ingest(lst(TAKER, "receive", self.y, [("範例科技股份有限公司", 500000)]))
        self.ingest(lst(TAKER, "receive", self.y, [("範例科技股份有限公司", 400000), ("甲乙實業有限公司", 1000)]))
        self.assertEqual(sorted(self.counted(organization=self.taker).values_list("amount", flat=True)), [1000, 400000])
        self.assertEqual(AnnualDonorList.objects.count(), 1)

    def test_only_recent_five_years_count(self):
        old = period.since_roc_year() - 1
        self.ingest(lst(TAKER, "receive", old, [("範例科技股份有限公司", 500000)]))
        self.assertFalse(self.counted(organization=self.taker).exists())

    def test_org_page_shows_sources_and_lists(self):
        project = Project.objects.create(organization=self.taker, name="勸募活動", source_name="衛福部公益勸募",
                                         start_date=date(self.y + 1911, 3, 1))
        donor = Donor.objects.create(name="範例科技股份有限公司", kind=Donor.Kind.COMPANY)
        Donation.objects.create(organization=self.taker, donor=donor, project=project, amount=1000,
                                donated_on=date(self.y + 1911, 5, 1), source_name="衛福部公益勸募")
        self.ingest(lst(TAKER, "receive", self.y, [("範例科技股份有限公司", 500000)]))
        data = self.api.get(f"/api/orgs/{TAKER}").json()
        top = data["corporate_donors"][0]
        self.assertEqual((top["name"], top["total"]), ("範例科技股份有限公司", 501000))
        self.assertEqual(top["sources"], ["衛福部公益勸募", "財團法人年度清冊（接受）"])
        self.assertEqual([(x["year"], x["direction"]) for x in data["annual_donor_lists"]], [(self.y, "receive")])
        # 明細：同年度有日期的在前，年度清冊（沒有日期）排在同年度最後；PostgreSQL 的空值不會跑到最前面
        self.assertEqual([(d["donated_on"] is None, d["year"]) for d in data["donations"]], [(False, None), (True, self.y)])

    def test_company_page_counts_annual_years_and_home_skips_undated(self):
        self.ingest(lst(TAKER, "receive", self.y, [("範例科技股份有限公司", 500000)]))
        donor = Donor.objects.get(name="範例科技股份有限公司")
        data = self.api.get(f"/api/donors/{donor.pk}").json()
        self.assertEqual(data["overview"]["active_years"], [self.y])
        self.assertEqual(next(r for r in data["overview"]["yearly"] if r["year"] == self.y)["total"], 500000)
        self.assertEqual(data["organizations"][0]["years"], [self.y])
        gifts = self.api.get("/api/home/discover").json()["gifts"]
        self.assertEqual(gifts, [])  # 首頁「企業捐款」只放有日期的衛福部清冊捐款

    def test_hidden_donor_disappears(self):
        self.ingest(lst(TAKER, "receive", self.y, [("範例科技股份有限公司", 500000)]))
        Donor.objects.filter(name="範例科技股份有限公司").update(hidden=True)
        data = self.api.get(f"/api/orgs/{TAKER}").json()
        self.assertEqual(data["corporate_donors"], [])
        self.assertNotIn("範例科技股份有限公司", [d["donor_name"] for d in data["donations"]])

    def test_scores_unchanged_by_annual_lists(self):
        from orgs import scoring

        before = (self.taker.disclosure_level, self.taker.public_raised_5y)
        self.ingest(lst(TAKER, "receive", self.y, [("範例科技股份有限公司", 500000)]))
        self.taker.refresh_from_db()
        scoring.recompute(Organization.objects.filter(pk=self.taker.pk))
        self.taker.refresh_from_db()
        self.assertEqual((self.taker.disclosure_level, self.taker.public_raised_5y), before)
