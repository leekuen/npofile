"""企業依法公開的捐贈（LK-49）：重大訊息、保險業捐贈情形表 → 捐款紀錄；去重、對不到組織、範圍金額、前台。"""

from datetime import date, timedelta

from django.test import TestCase
from npofile_crawler import corporate_gifts
from npofile_crawler.items import Item
from rest_framework.test import APIClient

from crawling.ingest import apply_records, run_source
from crawling.models import CrawlerSource, CrawlRecord
from orgs import period
from orgs.models import CompanyESG, Donation, Donor, Organization

ORG = "00000041"  # 財團法人範例企業基金會
INSURER_UBN = "03374707"


def recent(days=30) -> date:
    return period.today() - timedelta(days=days)


def mops(ubn, recipient="財團法人範例企業基金會", amount=30_000_000, amount_text="", on=None, code="2327", short="範例",
         subsidiary="", ext="m1"):
    return Item("gift", ubn, {
        "recipient": recipient, "party": False, "donor_name": subsidiary or short, "company_code": code,
        "company_short": short, "subsidiary": subsidiary, "donor_ubn": "", "donated_on": on or recent(),
        "amount": amount, "amount_text": amount_text, "purpose": "推動公益", "relation": "關係人", "subject": "公告捐贈",
        "category": "", "note": "",
    }, source_url=corporate_gifts.MOPS_PAGE, external_id=ext)


def insurer(ubn, recipient="財團法人範例企業基金會", amount=30_000_000, on=None, party=False, ext="i1"):
    return Item("gift", ubn, {
        "recipient": recipient, "party": party, "donor_name": "範例人壽保險股份有限公司", "company_code": "",
        "company_short": "", "subsidiary": "", "donor_ubn": INSURER_UBN, "donated_on": on or recent(), "amount": amount,
        "amount_text": "", "purpose": "", "relation": "", "subject": "", "category": "公益團體", "note": "",
    }, source_url=corporate_gifts.INS_PAGE.format(uid=INSURER_UBN), external_id=ext)


class CorporateGiftTests(TestCase):
    def setUp(self):
        self.mops = CrawlerSource.objects.get(key="mops_donations")
        self.ins = CrawlerSource.objects.get(key="insurer_donations")
        self.org = Organization.objects.create(ubn=ORG, name="財團法人範例企業基金會")
        CompanyESG.objects.create(market="listed", code="2327", name="範例電子股份有限公司", short_name="範例",
                                  ubn="12345678", report_year=113)
        self.api = APIClient()

    def counted(self):
        return Donation.objects.filter(period.donation_q(), organization=self.org)

    def test_matched_announcement_becomes_company_donation(self):
        run = run_source(self.mops, items=[mops(ORG)])
        self.assertEqual(run.applied, 1)
        d = self.counted().get()
        self.assertEqual((d.amount, d.donor.name, d.donor.ubn, d.donor.kind), (30_000_000, "範例電子股份有限公司", "12345678", "company"))
        self.assertEqual(d.source_name, corporate_gifts.MOPS_SOURCE_NAME)
        donor = self.api.get(f"/api/donors/{d.donor_id}").json()
        self.assertEqual(donor["donations"][0]["org_ubn"], ORG)

    def test_republished_announcement_counts_once(self):
        run_source(self.mops, items=[mops(ORG, ext="m1"), mops(ORG, ext="m1")])
        run_source(self.mops, items=[mops(ORG, ext="m1")])
        self.assertEqual(self.counted().count(), 1)

    def test_same_gift_in_insurer_table_and_mops_counts_once(self):
        # 金控代子公司（保險公司）發重大訊息，保險業捐贈情形表也列同一筆
        on = recent()
        run_source(self.mops, items=[mops(ORG, on=on, subsidiary="範例人壽保險股份有限公司", code="2888")])
        run_source(self.ins, items=[insurer(ORG, on=on)])
        self.assertEqual(self.counted().count(), 1)
        rec = CrawlRecord.objects.get(source=self.ins)
        self.assertIn("已經從", rec.review_note)
        self.assertEqual(Donor.objects.get(name="範例人壽保險股份有限公司").ubn, INSURER_UBN)

    def test_range_amount_shows_text_and_is_not_summed(self):
        run_source(self.mops, items=[mops(ORG, amount=None, amount_text="新台幣20-30萬元(以實際名冊為準)")])
        d = self.counted().get()
        self.assertEqual((d.amount, d.amount_note), (0, "新台幣20-30萬元(以實際名冊為準)"))
        donor = self.api.get(f"/api/donors/{d.donor_id}").json()
        self.assertEqual(donor["donations"][0]["amount_note"], "新台幣20-30萬元(以實際名冊為準)")

    def test_unmatched_and_party_stay_in_review_queue(self):
        run = run_source(self.ins, items=[insurer("", recipient="某某球隊", ext="i2"),
                                          insurer("", recipient="某某黨", party=True, ext="i3")])
        self.assertEqual((run.applied, run.pending), (0, 2))
        self.assertFalse(Donation.objects.exists())
        # 管理員指定組織後核准：前台出現
        rec = CrawlRecord.objects.get(source=self.ins, external_id="i2")
        rec.organization = self.org
        rec.save()
        apply_records([rec], CrawlRecord.Status.APPROVED)
        self.assertEqual(self.counted().count(), 1)

    def test_old_gift_outside_window_not_counted(self):
        run_source(self.ins, items=[insurer(ORG, on=date(period.since_roc_year() + 1911 - 2, 6, 1))])
        self.assertEqual(Donation.objects.count(), 1)
        self.assertEqual(self.counted().count(), 0)
