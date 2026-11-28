from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from npofile_crawler import donors, mohw
from npofile_crawler.items import Item
from rest_framework.test import APIClient

from crawling.ingest import run_source
from crawling.models import CrawlerSource, CrawlRun
from orgs.models import Donation, Donor, DonorListSummary, Organization, Project

FX = Path(__file__).resolve().parents[3] / "crawler" / "tests" / "fixtures"
UBN = "00570309"
AID = "6380987"


def read(name):
    return (FX / name).read_text(encoding="utf-8")


def activity_items():
    """跟 mohw.fetch_activities 產生的一樣：組織、活動頁補的專案、清冊。"""
    url = mohw.ACTIVITY_URL.format(aid=AID)
    org = next(i for i in mohw.parse_group(read("group_clean.html"), mohw.GROUP_URL.format(gid="10057")) if i.kind == "org")
    project, _ = mohw.parse_activity(read("activity_with_donors.html"), url, UBN)
    result = donors.summarize(donors.parse_ods((FX / "donors_sample.ods").read_bytes()))
    donor_list = Item("donor_list", UBN, {"project_name": project.data["name"], **result}, url, AID)
    return [org, project, donor_list]


class DonorListImportTests(TestCase):
    def setUp(self):
        self.group_source = CrawlerSource.objects.get(key="mohw")
        self.source = CrawlerSource.objects.get(key="mohw_activities")
        self.api = APIClient()

    def import_all(self):
        run_source(self.group_source, items=mohw.parse_group(read("group_clean.html"), mohw.GROUP_URL.format(gid="10057")))
        return run_source(self.source, items=activity_items())

    def test_activity_enriches_existing_project_without_duplicate(self):
        run = self.import_all()
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS, run.error)
        projects = Project.objects.filter(organization__ubn=UBN, external_id=AID)
        self.assertEqual(projects.count(), 1)
        p = projects.get()
        self.assertEqual(p.permit_no, "衛部救字第1141360537號")
        self.assertEqual(p.region, "全國")
        self.assertIsNotNone(p.result_filed_on)  # 團體頁抓到的成果備查日期沒被活動頁的空值蓋掉

    def test_only_companies_groups_and_large_individuals_are_stored(self):
        self.import_all()
        names = set(Donation.objects.filter(project__external_id=AID).values_list("donor_name", flat=True))
        self.assertEqual(names, {"範例科技股份有限公司", "財團法人範例文教基金會", "台北範例扶輪社", "甲大明"})
        self.assertFalse(Donor.objects.filter(name__in=["乙小華", "Sample Lee", "MOMO捐款有心人"]).exists())
        s = DonorListSummary.objects.get(project__external_id=AID)
        self.assertEqual((s.small_individual_count, s.anonymous_rows, s.total_rows), (3, 3, 13))

    def test_rerun_does_not_duplicate(self):
        self.import_all()
        counts = (Donation.objects.count(), Donor.objects.count(), DonorListSummary.objects.count(), Project.objects.count())
        run_source(self.source, items=activity_items())
        self.source.records.all().delete()  # 讓同內容也重新套用一次（模擬清冊內容更新）
        run_source(self.source, items=activity_items())
        self.assertEqual(
            (Donation.objects.count(), Donor.objects.count(), DonorListSummary.objects.count(), Project.objects.count()),
            counts,
        )

    def test_org_api_donor_sections(self):
        self.import_all()
        r = self.api.get(f"/api/orgs/{UBN}").json()
        corp = {(d["name"], d["kind"], d["total"]) for d in r["corporate_donors"]}
        self.assertEqual(
            corp,
            {("範例科技股份有限公司", "company", 2000000), ("財團法人範例文教基金會", "group", 1000000), ("台北範例扶輪社", "group", 800000)},
        )
        self.assertEqual([(d["name"], d["total"]) for d in r["individual_donors"]], [("甲大明", 110000)])
        summary = r["donor_summary"]
        self.assertEqual((summary["small_individual_count"], summary["small_individual_amount"]), (3, 3600))
        self.assertEqual((summary["anonymous_rows"], summary["anonymous_amount"]), (3, 60000))
        self.assertNotIn("receipt_no", str(r))
        self.assertNotIn("A001", str(r))
        self.assertEqual(Organization.objects.get(ubn=UBN).disclosure_level, 2)  # 身分＋勸募活動都齊，沒有財報

    def test_donor_ranking_excludes_individuals(self):
        self.import_all()
        names = [d["name"] for d in self.api.get("/api/donors").json()["results"]]
        self.assertEqual(names, ["範例科技股份有限公司", "財團法人範例文教基金會", "台北範例扶輪社"])
        self.assertEqual(self.api.get("/api/donors?q=甲大明").json()["count"], 0)
        person = Donor.objects.get(name="甲大明")
        self.assertEqual(self.api.get(f"/api/donors/{person.pk}").status_code, 404)
        self.assertEqual(self.api.get("/api/donors?kind=group").json()["count"], 2)

    def test_donor_detail(self):
        self.import_all()
        donor = Donor.objects.get(name="範例科技股份有限公司")
        r = self.api.get(f"/api/donors/{donor.pk}").json()
        self.assertEqual(r["total"], 2000000)
        orgs = [{k: o[k] for k in ("ubn", "name", "total", "count", "penalty_count")} for o in r["organizations"]]
        self.assertEqual(orgs, [{"ubn": UBN, "name": "社團法人賦格行動音樂關懷協會", "total": 2000000, "count": 2, "penalty_count": 0}])
        self.assertEqual(len(r["donations"]), 2)
        self.assertNotIn("receipt_no", r["donations"][0])

    def test_hidden_donor_disappears_everywhere(self):
        self.import_all()
        donor = Donor.objects.get(name="範例科技股份有限公司")
        donor.hidden = True
        donor.save()
        r = self.api.get(f"/api/orgs/{UBN}").json()
        self.assertNotIn("範例科技股份有限公司", str(r))
        self.assertEqual(r["donor_summary"]["anonymous_amount"], 60000 + 2000000)
        self.assertEqual(r["donor_summary"]["anonymous_rows"], 3 + 2)
        self.assertNotIn("範例科技", str(self.api.get("/api/donors").json()))
        self.assertEqual(self.api.get(f"/api/donors/{donor.pk}").status_code, 404)

    def test_hidden_individual_also_hidden(self):
        self.import_all()
        Donor.objects.filter(name="甲大明").update(hidden=True)
        r = self.api.get(f"/api/orgs/{UBN}").json()
        self.assertEqual(r["individual_donors"], [])
        self.assertNotIn("甲大明", str(r))


class MatchCompaniesTests(TestCase):
    def test_exact_name_links_ubn_once(self):
        exact = Donor.objects.create(name="台灣積體電路製造股份有限公司", kind=Donor.Kind.COMPANY)
        brand = Donor.objects.create(name="星巴克股份有限公司範例", kind=Donor.Kind.COMPANY)
        Donor.objects.create(name="財團法人範例基金會", kind=Donor.Kind.GROUP)
        bodies = {exact.name: read("gcis_tsmc.json"), brand.name: read("gcis_starbucks_partial.json")}

        class FakeResp:
            def __init__(self, text):
                self.text = text

        def fake_get(self, url, **kw):
            name = next(n for n in bodies if __import__("urllib.parse").parse.quote(n) in url)
            return FakeResp(bodies[name])

        with mock.patch("npofile_crawler.http.PoliteClient.get", fake_get):
            call_command("match_companies")
            call_command("match_companies")  # 查過的不重查（fake_get 找不到名稱會出錯）
        exact.refresh_from_db()
        brand.refresh_from_db()
        self.assertEqual((exact.ubn, exact.representative), ("22099131", "魏哲家"))
        self.assertEqual(brand.ubn, "")
        self.assertIsNotNone(brand.registry_checked_at)


class ReclassifyTests(TestCase):
    def test_reclassify_respects_admin_choice(self):
        auto = Donor.objects.create(name="HSBC Holdings plc", kind=Donor.Kind.INDIVIDUAL)
        manual = Donor.objects.create(name="星巴克", kind=Donor.Kind.COMPANY, kind_manual=True)
        church = Donor.objects.create(name="Great Commission Church International", kind=Donor.Kind.INDIVIDUAL,
                                      kind_manual=True)
        platform = Donor.objects.create(name="MOMO", kind=Donor.Kind.INDIVIDUAL)
        call_command("reclassify_donors")
        platform.refresh_from_db()
        self.assertTrue(platform.hidden)  # 平台彙總：隱藏，金額併入匿名
        auto.refresh_from_db()
        manual.refresh_from_db()
        church.refresh_from_db()
        self.assertEqual(auto.kind, Donor.Kind.COMPANY)
        self.assertEqual(manual.kind, Donor.Kind.COMPANY)  # 新規則會判成個人，但管理員指定過
        self.assertEqual(church.kind, Donor.Kind.INDIVIDUAL)

    def test_admin_kind_change_marks_manual(self):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_superuser("admin", "admin@example.com", "pw-123456789")
        self.client.login(username="admin", password="pw-123456789")
        d = Donor.objects.create(name="星巴克", kind=Donor.Kind.INDIVIDUAL)
        r = self.client.post(f"/admin/orgs/donor/{d.pk}/change/", {
            "name": "星巴克", "kind": "company", "hidden": "", "ubn": "", "kind_manual": "",
        })
        self.assertEqual(r.status_code, 302, r.content[:1500])
        d.refresh_from_db()
        self.assertEqual((d.kind, d.kind_manual), ("company", True))
