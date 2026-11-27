from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from npofile_crawler.items import Item
from rest_framework.test import APIClient

from crawling.ingest import run_source
from crawling.models import CrawlerSource
from orgs.donor_merge import merge_donors
from orgs.models import Donation, Donor, Organization, Project


def raw_donor(name, **kw):
    """模擬合併前的舊資料：繞過 save()（舊資料沒有比對用名稱，名稱也沒整理過）。"""
    Donor.objects.bulk_create([Donor(name=name, name_key=f"old-{name}", kind=kw.pop("kind", "company"), **kw)])
    return Donor.objects.get(name=name)


class MergeTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(ubn="12345678", name="某某基金會")
        self.project = Project.objects.create(organization=self.org, name="計畫", external_id="1")

    def give(self, donor, amount, n=1):
        for _ in range(n):
            Donation.objects.create(organization=self.org, project=self.project, donor=donor, donor_name=donor.name, amount=amount)

    def test_variants_merge_into_one(self):
        a = raw_donor("台灣證券交易所股份有限公司")
        b = raw_donor("臺灣證券交易所股份有限公司")
        c = raw_donor("天​​行能源股份有限公司")
        self.give(a, 100)
        self.give(b, 200, n=2)
        self.give(c, 50)
        s = merge_donors(Donor, Donation)
        self.assertEqual(s["merged"], 1)
        self.assertEqual(Donor.objects.count(), 2)
        tse = Donor.objects.get(name="臺灣證券交易所股份有限公司")  # 捐款筆數多的那筆
        self.assertEqual(sum(tse.donations.values_list("amount", flat=True)), 500)
        self.assertTrue(Donor.objects.filter(name="天行能源股份有限公司").exists())
        self.assertEqual(merge_donors(Donor, Donation)["merged"], 0)  # 重跑不再動

    def test_keep_manual_hidden_and_registry(self):
        manual = raw_donor("翔喻企業(股)公司", kind_manual=True)
        other = raw_donor("翔喻企業股份有限公司", ubn="12345670", representative="王大明", hidden=True)
        self.give(other, 100, n=3)
        merge_donors(Donor, Donation)
        d = Donor.objects.get()
        self.assertEqual(d.pk, manual.pk)  # 管理員指定過類型的優先
        self.assertEqual((d.ubn, d.representative, d.hidden), ("12345670", "王大明", True))
        self.assertEqual(d.donations.count(), 3)

    def test_merged_away_donor_page_is_404(self):
        a = raw_donor("台中市慈林慈善關懷協會", kind="group")
        b = raw_donor("臺中市慈林慈善關懷協會", kind="group")
        self.give(a, 100)
        self.give(b, 100, n=2)
        merge_donors(Donor, Donation)
        api = APIClient()
        self.assertEqual(api.get(f"/api/donors/{a.pk}").status_code, 404)
        r = api.get(f"/api/donors/{b.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 300)  # 合併後的企業頁金額＝合併前相加

    def test_command(self):
        raw_donor("台東縣診所協會", kind="group")
        raw_donor("臺東縣診所協會", kind="group")
        call_command("merge_donors", stdout=__import__("io").StringIO())
        self.assertEqual(Donor.objects.count(), 1)


class SaveAndAdminTests(TestCase):
    def test_save_sets_key_and_cleans_name(self):
        d = Donor.objects.create(name="ＡＢＣ　股份有限公司 統編：12345678", kind="company")
        self.assertEqual(d.name, "ABC 股份有限公司")
        self.assertEqual(d.name_key, "abc股份有限公司")

    def test_admin_rename_to_same_donor_is_blocked(self):
        get_user_model().objects.create_superuser("admin", "admin@example.com", "pw-123456789")
        self.client.login(username="admin", password="pw-123456789")
        Donor.objects.create(name="臺灣證券交易所股份有限公司", kind="company")
        d = Donor.objects.create(name="某某公司", kind="company")
        r = self.client.post(f"/admin/orgs/donor/{d.pk}/change/", {
            "name": "台灣證券交易所股份有限公司", "kind": "company", "hidden": "", "ubn": "", "kind_manual": "",
        })
        self.assertEqual(r.status_code, 200)  # 留在表單頁、顯示錯誤
        self.assertContains(r, "是同一位")
        d.refresh_from_db()
        self.assertEqual(d.name, "某某公司")


class SearchTests(TestCase):
    def test_search_uses_same_rules(self):
        Donor.objects.create(name="臺灣證券交易所股份有限公司", kind="company")
        org = Organization.objects.create(ubn="12345678", name="某某基金會")
        Donation.objects.create(organization=org, donor=Donor.objects.get(), donor_name="x", amount=1)
        api = APIClient()
        for q in ("台灣證券交易所", "臺灣證券", "台灣 證券交易所"):
            self.assertEqual(api.get("/api/donors", {"q": q}).json()["count"], 1, q)
        self.assertEqual(api.get("/api/donors", {"q": "台積電"}).json()["count"], 0)


class ImportMatchesExistingTests(TestCase):
    def test_new_list_uses_existing_donor(self):
        org = Organization.objects.create(ubn="00570309", name="某某基金會")
        existing = Donor.objects.create(name="臺灣證券交易所股份有限公司", kind="company")
        source = CrawlerSource.objects.get(key="mohw_activities")
        rows = [
            {"receipt_no": "1", "donated_on": None, "name": "台灣證券交易所股份有限公司", "kind": "company", "amount": 100, "purpose": ""},
            {"receipt_no": "2", "donated_on": None, "name": "翔喻企業(股)公司", "kind": "company", "amount": 50, "purpose": ""},
            {"receipt_no": "3", "donated_on": None, "name": "翔喻企業股份有限公司", "kind": "company", "amount": 70, "purpose": ""},
        ]
        item = Item("donor_list", org.ubn, {"project_name": "計畫", "summary": {}, "rows": rows}, "https://example.com/a", "9")
        run_source(source, items=[item])
        self.assertEqual(existing.donations.get().amount, 100)
        self.assertEqual(Donor.objects.count(), 2)
        self.assertEqual(sorted(Donor.objects.get(name_key="翔喻企業股份有限公司").donations.values_list("amount", flat=True)), [50, 70])
        run_source(source, items=[item])  # 重抓不重複
        self.assertEqual((Donor.objects.count(), Donation.objects.count()), (2, 3))
