"""上市櫃公司 ESG（LK-39）：寫入、對捐款人（統編優先、全名比對）、解除對應不接回、API 只給最新年度。"""

import json
from io import StringIO
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient
from npofile_crawler import esg

from orgs import company_esg
from orgs.admin import CompanyESGAdmin
from orgs.models import CompanyESG, Donation, Donor, Organization

FX = json.loads(
    (Path(esg.__file__).resolve().parents[1] / "tests" / "fixtures" / "esg_sample.json").read_text(encoding="utf-8")
)


def records(market=esg.LISTED):
    suffix = "L" if market is esg.LISTED else "O"
    base = FX["t187ap03_L"] if market is esg.LISTED else FX["mopsfin_t187ap03_O"]
    return esg.parse_market(market, base, {n: FX[f"t187ap46_{suffix}_{n}"] for n in esg.TOPICS})


class CompanyEsgTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.org = Organization.objects.create(ubn="11111111", name="甲協會")
        # 華碩：有統編 → 用統編對（名稱寫法不同也對得到）
        self.asus = self.donor("華碩電腦股份有限公司台北分公司", ubn="23638777")
        # 台泥：沒有統編 → 全名比對寫法相同才對（台／臺、(股) 不同也算）
        self.tcc = self.donor("台灣水泥(股)公司")
        # 有統編但統編不同：不准再用名稱對
        self.otc = self.donor("茂生農經股份有限公司", ubn="99999999")
        # 簡稱不對
        self.short = self.donor("華碩")

    def donor(self, name, ubn="", kind=Donor.Kind.COMPANY):
        d = Donor.objects.create(name=name, kind=kind, ubn=ubn)
        Donation.objects.create(organization=self.org, donor=d, amount=100, donated_on=date.today())
        return d

    def sync(self):
        company_esg.store(records(esg.LISTED))
        company_esg.store(records(esg.OTC))
        return company_esg.link_donors()

    def test_store_is_idempotent(self):
        self.assertEqual(company_esg.store(records()), (2, 0))
        self.assertEqual(company_esg.store(records()), (0, 2))
        self.assertEqual(CompanyESG.objects.count(), 2)
        tcc = CompanyESG.objects.get(code="1101")
        self.assertEqual(tcc.scope1, Decimal("41020073.6100"))
        self.assertEqual(tcc.transition_plan, "")

    def test_matching_rules(self):
        self.assertEqual(self.sync(), 2)
        self.assertEqual(CompanyESG.objects.get(code="2357").donor, self.asus)
        self.assertEqual(CompanyESG.objects.get(code="1101").donor, self.tcc)
        self.assertIsNone(CompanyESG.objects.get(code="1240").donor)  # 統編不同，名稱相同也不對
        self.assertFalse(self.short.esg_reports.exists())

    def test_unlink_survives_resync_and_new_year(self):
        self.sync()
        company_esg.unlink(CompanyESG.objects.filter(code="2357"))
        self.sync()
        self.assertIsNone(CompanyESG.objects.get(code="2357").donor)
        newer = [dict(r, report_year=115) for r in records() if r["code"] == "2357"]
        company_esg.store(newer)
        company_esg.link_donors()
        self.assertFalse(CompanyESG.objects.filter(code="2357", donor__isnull=False).exists())
        self.assertIsNone(self.api.get(f"/api/donors/{self.asus.pk}").json()["esg"])

    def test_api_latest_year_only(self):
        self.sync()
        old = CompanyESG.objects.get(code="1101")
        CompanyESG.objects.create(
            market="listed", code="1101", name=old.name, report_year=113, donor=self.tcc, climate_targets="舊年度目標"
        )
        body = self.api.get(f"/api/donors/{self.tcc.pk}").json()["esg"]
        self.assertEqual(body["report_year"], 114)
        self.assertEqual(body["market_label"], "上市")
        self.assertEqual(body["scope3_verified"], "否")
        self.assertEqual(body["renewable_ratio"], 6.59)
        self.assertEqual(body["salary_median"], 895)
        self.assertNotIn("張安平", json.dumps(body, ensure_ascii=False))

    def test_api_none_for_unmatched_and_groups(self):
        self.sync()
        self.assertIsNone(self.api.get(f"/api/donors/{self.otc.pk}").json()["esg"])
        group = self.donor("台灣水泥扶輪社", kind=Donor.Kind.GROUP)
        self.assertIsNone(self.api.get(f"/api/donors/{group.pk}").json()["esg"])

    def test_link_only_command_links_new_donors(self):
        company_esg.store(records())
        CompanyESG.objects.update(donor=None)
        call_command("sync_esg", "--link-only", stdout=StringIO())
        self.assertEqual(CompanyESG.objects.get(code="2357").donor, self.asus)

    def test_admin_is_read_only(self):
        admin = CompanyESGAdmin(CompanyESG, AdminSite())
        self.assertFalse(admin.has_add_permission(None))
        self.assertFalse(admin.has_change_permission(None))
