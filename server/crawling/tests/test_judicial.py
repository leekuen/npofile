"""LK-31 司法院法人登記公告：存檔、同一筆不重複、對不到也存、管理員指定不被蓋、組織頁、解散標示、營運狀態不動。"""

import io
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from npofile_crawler import fia, judicial

from crawling.ingest import court_registration_options, run_source
from crawling.models import CrawlerSource, CrawlRecord, CrawlRun
from orgs.court_match import rematch
from orgs.models import CourtRegistration, Organization

FX = Path(__file__).resolve().parents[3] / "crawler" / "tests" / "fixtures"


def read(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


def rows():
    return judicial.parse_list(read("judicial_list.html"))[0]


def items(orgs, overrides=None):
    """樣本列表 → Item；對到組織的配上變更登記樣本的內頁。overrides：{列號: {欄位: 值}}"""
    m = judicial.CourtMatcher(orgs)
    out = []
    for i, r in enumerate(rows()):
        r = {**r, **(overrides or {}).get(i, {})}
        ubn = m.match(r["name"], r["court"])
        detail = judicial.parse_detail(read("judicial_change.html"), r["case_type"]) if ubn else None
        out.append(judicial.to_item(r, ubn, detail))
    return out


class CourtRegistrationIngestTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="judicial")
        r = rows()
        self.first = r[0]
        self.dissolved_row = next(x for x in r if x["case_type"] == "dissolution")
        self.org = Organization.objects.create(ubn="11111111", name=self.first["name"], city="彰化縣")
        self.gone = Organization.objects.create(ubn="22222222", name=self.dissolved_row["name"], city="桃園市")
        self.orgs = list(Organization.objects.values_list("ubn", "name", "city"))

    def test_official_auto_apply_unmatched_kept_without_org(self):
        self.assertTrue(self.source.auto_approve)
        run = run_source(self.source, items=items(self.orgs))
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS, run.error)
        self.assertEqual((run.created, run.applied, run.failed), (20, 20, 0))
        self.assertEqual(CourtRegistration.objects.count(), 20)
        self.assertEqual(CourtRegistration.objects.filter(organization__isnull=True).count(), 18)
        reg = CourtRegistration.objects.get(organization=self.org)
        self.assertEqual(reg.case_type, "change")
        self.assertEqual(reg.change_items, ["董監事"])
        self.assertTrue(reg.detail_fetched)

    def test_rerun_same_case_no_does_not_duplicate(self):
        run_source(self.source, items=items(self.orgs))
        # 同一個登記案號、內容有變（例：補讀了內頁）：更新同一筆，不會變兩筆
        again = items(self.orgs, {1: {"reg_no": "999"}})
        run = run_source(self.source, items=again)
        self.assertEqual(run.created, 1)
        self.assertEqual(CourtRegistration.objects.count(), 20)
        self.assertEqual(CourtRegistration.objects.get(court=rows()[1]["court"], case_no=rows()[1]["case_no"]).reg_no, "999")

    def test_admin_assignment_survives_recrawl_and_rematch(self):
        run_source(self.source, items=items(self.orgs))
        other = Organization.objects.create(ubn="33333333", name="財團法人另一個基金會")
        reg = CourtRegistration.objects.get(organization=self.org)
        reg.organization, reg.org_manual = other, True
        reg.save()
        run_source(self.source, items=items(self.orgs, {0: {"reg_no": "1"}}))
        self.assertEqual(rematch(), 0)
        reg.refresh_from_db()
        self.assertEqual(reg.organization, other)

    def test_rematch_links_after_new_org_appears(self):
        run_source(self.source, items=items(self.orgs))
        late = Organization.objects.create(ubn="44444444", name=rows()[2]["name"])
        self.assertEqual(rematch(), 1)
        self.assertEqual(CourtRegistration.objects.get(organization=late).case_no, rows()[2]["case_no"])

    def test_options_seen_and_floor(self):
        run_source(self.source, items=items(self.orgs))
        opts = court_registration_options()
        self.assertEqual(len(opts["seen_regs"]), 20)
        self.assertIn(judicial.registration_id(self.first["court"], self.first["case_no"]), opts["seen_regs"])
        self.assertFalse(opts["floor_reached"])

    def test_no_board_member_names_stored(self):
        run_source(self.source, items=items(self.orgs))
        dump = str(list(CrawlRecord.objects.filter(source=self.source).values_list("payload", flat=True)))
        dump += str(list(CourtRegistration.objects.values()))
        for name in ("王大明", "李小華", "張三", "某某某"):
            self.assertNotIn(name, dump)


class OrgPageTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="judicial")
        r = rows()
        self.dissolved_row = next(x for x in r if x["case_type"] == "dissolution")
        self.changed_row = r[0]

    def test_change_listed_and_status_kept(self):
        org = Organization.objects.create(ubn="11111111", name=self.changed_row["name"], city="彰化縣")
        run_source(self.source, items=items(list(Organization.objects.values_list("ubn", "name", "city"))))
        data = self.client.get("/api/orgs/11111111").json()
        self.assertEqual(len(data["court_registrations"]), 1)
        reg = data["court_registrations"][0]
        self.assertEqual(reg["case_label"], "變更登記")
        self.assertEqual(reg["court"], "臺灣彰化地方法院")
        self.assertTrue(reg["source_url"].startswith("https://www.judicial.gov.tw/"))
        self.assertIsNone(data["court_dissolution"])
        self.assertEqual(data["status"], org.status)

    def test_dissolved_banner_but_fia_status_unchanged(self):
        # W1／W3：財政部名冊說「營運中」，法院已解散 → 頁首標示解散，營運狀態欄位照財政部原值
        Organization.objects.create(ubn="22222222", name=self.dissolved_row["name"], city="桃園市", status="active")
        run_source(self.source, items=items(list(Organization.objects.values_list("ubn", "name", "city"))))
        data = self.client.get("/api/orgs/22222222").json()
        self.assertEqual(data["status"], "active")
        self.assertEqual(data["court_dissolution"]["court"], self.dissolved_row["court"])
        self.assertEqual(data["court_dissolution"]["case_label"], "解散登記")
        self.assertEqual(data["court_dissolution"]["posted_on"], self.dissolved_row["posted_on"].isoformat())

    def test_later_change_clears_banner(self):
        org = Organization.objects.create(ubn="22222222", name=self.dissolved_row["name"], city="桃園市")
        CourtRegistration.objects.create(organization=org, court="臺灣桃園地方法院", case_no="A", name=org.name,
                                         case_type="dissolution", posted_on="2024-01-01")
        CourtRegistration.objects.create(organization=org, court="臺灣桃園地方法院", case_no="B", name=org.name,
                                         case_type="liquidation_end", posted_on="2024-06-01")
        self.assertEqual(self.client.get("/api/orgs/22222222").json()["court_dissolution"]["case_type"], "liquidation_end")
        CourtRegistration.objects.create(organization=org, court="臺灣桃園地方法院", case_no="C", name=org.name,
                                         case_type="change", posted_on="2025-01-01")
        self.assertIsNone(self.client.get("/api/orgs/22222222").json()["court_dissolution"])

    def test_fia_rerun_and_list_filter_unaffected(self):
        # W2／W3：法院公告進來前後，財政部名冊重跑的營運狀態與列表狀態篩選結果都一樣
        fia_source = CrawlerSource.objects.get(key="fia")
        run_source(fia_source, items=fia.parse_csv(read("fia_sample.csv")))
        before_status = dict(Organization.objects.values_list("ubn", "status"))
        before_list = self.client.get("/api/orgs?status=cancelled").json()
        cancelled = Organization.objects.get(ubn="00510209")
        CourtRegistration.objects.create(organization=cancelled, court="臺灣基隆地方法院", case_no="X", name=cancelled.name,
                                         case_type="setup", posted_on="2024-01-01")
        active = Organization.objects.get(ubn="00099678")
        CourtRegistration.objects.create(organization=active, court="臺灣臺北地方法院", case_no="Y", name=active.name,
                                         case_type="dissolution", posted_on="2024-01-01")
        run_source(fia_source, items=fia.parse_csv(read("fia_sample.csv")))
        self.assertEqual(dict(Organization.objects.values_list("ubn", "status")), before_status)
        self.assertEqual(self.client.get("/api/orgs?status=cancelled").json(), before_list)


class AdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@example.com", "pw")
        self.client.force_login(self.admin)
        run_source(CrawlerSource.objects.get(key="judicial"), items=items([]))

    def test_changelist_filters(self):
        url = "/admin/orgs/courtregistration/"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url + "?matched=no").status_code, 200)
        self.assertEqual(self.client.get(url + "?case_type__exact=dissolution").status_code, 200)
        self.assertEqual(self.client.get(url + "?court=臺灣彰化地方法院").status_code, 200)

    def test_manual_assign_sets_flag(self):
        org = Organization.objects.create(ubn="55555555", name="財團法人手動指定基金會")
        reg = CourtRegistration.objects.first()
        url = f"/admin/orgs/courtregistration/{reg.pk}/change/"
        self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.client.post(url, {"organization": org.pk})
        self.assertEqual(resp.status_code, 302, resp.content[:2000])
        reg.refresh_from_db()
        self.assertEqual(reg.organization, org)
        self.assertTrue(reg.org_manual)

    def test_match_command_without_details(self):
        out = io.StringIO()
        call_command("match_court_registrations", "--details", "0", stdout=out)
        self.assertIn("重新比對：0 筆", out.getvalue())
