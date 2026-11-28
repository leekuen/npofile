import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from orgs import period, scoring
from orgs.models import AnnualFundraising, Donation, Organization, Penalty, Project


def make_org(ubn="12345678", **kw):
    kw.setdefault("name", f"測試協會{ubn}")
    return Organization.objects.create(ubn=ubn, **kw)


class OrganizationModelTests(TestCase):
    def test_ubn_must_be_8_digits(self):
        org = Organization(ubn="1234", name="x")
        with self.assertRaises(ValidationError):
            org.full_clean()

    def test_anonymous_donor_name_is_hidden(self):
        org = make_org()
        self.assertEqual(Donation(organization=org, donor_name="王小明", is_anonymous=True, amount=1).public_donor_name, "匿名")
        self.assertEqual(Donation(organization=org, donor_name="  ", amount=1).public_donor_name, "匿名")
        self.assertEqual(Donation(organization=org, donor_name="王小明", amount=1).public_donor_name, "王小明")


def full_identity(ubn="12345678", **kw):
    """第 1 層的條件全部有。"""
    base = dict(org_type="財團法人", registered_address="臺北市", phone="02", purposes="教育事業")
    base.update(kw)
    return make_org(ubn, **base)


def roc_now():
    return scoring.today().year - 1911


def on_year(roc):
    """專案的年度依開始日期算（Project.compute_period_year）。"""
    return date(roc + 1911, 3, 1)


class LevelTests(TestCase):
    """LK-35 揭露層級：四層依序達成，每一層的條件全部達到才算。"""

    def fin(self, org, year, **kw):
        from orgs.models import FinancialYear
        kw.setdefault("total_revenue", 100)
        kw.setdefault("total_expenses", 90)
        return FinancialYear.objects.create(organization=org, year=year, **kw)

    def doc(self, org, year, kind="annual"):
        from orgs.models import OrgDocument
        return OrgDocument.objects.create(organization=org, year=year, kind=kind, title="年報", url="https://a.tw/r.pdf")

    def level(self, org):
        org.refresh_from_db()
        return org.disclosure_level

    def test_empty_org_has_no_level(self):
        org = make_org()
        lv = scoring.levels(org)
        self.assertEqual((lv["level"], lv["medal"], lv["name"]), (0, "未分級", "資料不足"))
        self.assertEqual([l["medal"] for l in lv["layers"]], ["銅", "銀", "金", "鑽石"])
        self.assertEqual(self.level(org), 0)
        missing = [c["key"] for c in lv["layers"][0]["checks"] if not c["met"]]
        self.assertEqual(missing, ["org_type", "address", "purpose", "contact"])

    def test_layer1_needs_every_identity_check(self):
        org = full_identity()
        self.assertEqual(self.level(org), 1)
        for i, field in enumerate(("org_type", "registered_address", "phone", "purposes")):
            other = full_identity(f"2000000{i}", **{field: ""})
            self.assertEqual(self.level(other), 0, field)

    def test_website_or_contact_address_also_count(self):
        org = full_identity(phone="", website="https://a.tw", registered_address="", contact_address="新北市")
        self.assertEqual(self.level(org), 1)

    def test_registry_purpose_counts_as_purpose(self):
        from orgs.models import RegistryEntry
        org = full_identity(purposes="")
        self.assertEqual(self.level(org), 0)
        RegistryEntry.objects.create(organization=org, external_id="1", authority="教育部", registry_name=org.name,
                                     purpose="推廣教育")
        self.assertEqual(self.level(org), 1)

    def test_not_active_is_level_0(self):
        org = full_identity(status=Organization.Status.CANCELLED)
        lv = scoring.levels(org)
        self.assertEqual(lv["level"], 0)
        self.assertFalse(lv["active"])

    def test_layer2_activity_and_due_results(self):
        org = full_identity()
        p = Project.objects.create(organization=org, name="a", raised=10, start_date=on_year(roc_now() - 1))
        lv = scoring.levels(org)
        self.assertEqual(lv["level"], 1)  # 去年募到款的活動還沒成果備查
        self.assertEqual((lv["results_due"], lv["results_filed"]), (1, 0))
        p.result_filed_on = date(2026, 1, 1)
        p.save()
        self.assertEqual(self.level(org), 2)

    def test_activity_page_filing_counts_as_filed(self):
        """LK-43：團體頁列表只列最近幾筆，舊活動的備查狀態從活動頁讀（逾期補交也算交了）。"""
        org = full_identity()
        p = Project.objects.create(organization=org, name="a", raised=10, start_date=on_year(roc_now() - 1))
        self.assertEqual(self.level(org), 1)
        p.result_done, p.result_late = True, True
        p.save()
        self.assertEqual(self.level(org), 2)

    def test_due_follows_legal_deadline(self):
        """LK-43：到期看活動頁的法定期限（期滿後 30 日），不是活動年度。"""
        today = scoring.today()
        org = full_identity()
        # 去年開始、下個月才結束的活動：還沒到期
        Project.objects.create(organization=org, name="跨年", raised=10, start_date=on_year(roc_now() - 1),
                               end_date=today + timedelta(days=30), result_due_on=today + timedelta(days=60),
                               result_done=False)
        lv = scoring.levels(org)
        self.assertEqual((lv["level"], lv["results_due"]), (2, 0))
        # 今年開始、上個月期限已過、沒備查：到期了
        Project.objects.create(organization=org, name="今年逾期", raised=10, start_date=on_year(roc_now()),
                               result_due_on=today - timedelta(days=1), result_done=False, result_late=True)
        lv = scoring.levels(org)
        self.assertEqual((lv["level"], lv["results_due"], lv["results_filed"]), (1, 1, 0))

    def test_end_date_plus_30_days_when_no_deadline(self):
        today = scoring.today()
        org = full_identity()
        Project.objects.create(organization=org, name="期滿未滿 30 日", raised=10, start_date=on_year(roc_now() - 1),
                               end_date=today - timedelta(days=29))
        self.assertEqual(scoring.levels(org)["results_due"], 0)
        Project.objects.create(organization=org, name="期滿 31 日", raised=10, start_date=on_year(roc_now()),
                               end_date=today - timedelta(days=31))
        self.assertEqual(scoring.levels(org)["results_due"], 1)

    def test_this_year_and_unknown_year_are_not_due(self):
        org = full_identity()
        Project.objects.create(organization=org, name="今年", raised=10, start_date=on_year(roc_now()))
        Project.objects.create(organization=org, name="年度不明", raised=10, )
        lv = scoring.levels(org)
        self.assertEqual((lv["level"], lv["results_due"]), (2, 0))

    def test_unfunded_and_old_projects_are_not_due(self):
        org = full_identity()
        Project.objects.create(organization=org, name="沒募到", raised=0, start_date=on_year(roc_now() - 1))
        Project.objects.create(organization=org, name="很久以前", raised=10, start_date=on_year(roc_now() - 6))
        lv = scoring.levels(org)
        self.assertEqual((lv["level"], lv["results_due"]), (2, 0))

    def test_crowdfunding_is_not_an_activity(self):
        org = full_identity()
        Project.objects.create(organization=org, name="集資", raised=10, channel=Project.Channel.CROWDFUNDING,
                               start_date=on_year(roc_now() - 1))
        self.assertEqual(self.level(org), 1)

    def test_grant_or_registry_business_counts_as_activity(self):
        from orgs.models import Grant, RegistryEntry
        org = full_identity()
        Grant.objects.create(organization=org, external_id="g1", year=roc_now() - 1, agency="衛福部",
                             recipient=org.name, purpose="補助", amount=100)
        self.assertEqual(self.level(org), 2)
        other = full_identity("87654321")
        RegistryEntry.objects.create(organization=other, external_id="2", authority="教育部",
                                     registry_name=other.name, main_business="辦理講座")
        self.assertEqual(self.level(other), 2)

    def layer2_org(self, ubn="12345678"):
        org = full_identity(ubn)
        Project.objects.create(organization=org, name="今年", raised=10, start_date=on_year(roc_now()))
        return org

    def test_layer3_needs_recent_financials_with_numbers(self):
        org = self.layer2_org()
        self.fin(org, roc_now() - 3)
        self.assertEqual(self.level(org), 2)  # 太舊
        f = self.fin(org, roc_now() - 2, total_expenses=None)
        self.assertEqual(self.level(org), 2)  # 沒有總支出
        f.total_expenses = 90
        f.save()
        self.assertEqual(self.level(org), 3)

    def test_layer4_consecutive_and_report(self):
        org = self.layer2_org()
        y = roc_now() - 1
        self.fin(org, y)
        self.fin(org, y - 1)
        self.assertEqual(self.level(org), 3)
        self.fin(org, y - 3)  # 跳過一年，不連續
        self.doc(org, y, kind="work")
        self.assertEqual(self.level(org), 3)
        self.fin(org, y - 2)
        self.assertEqual(self.level(org), 4)

    def test_layer4_does_not_require_audit(self):
        # LK-45：衛福部決算不寫有沒有查核（audited=None），沒查核也一樣能到鑽石
        org = self.layer2_org()
        y = roc_now() - 1
        self.fin(org, y, audited=False)
        self.fin(org, y - 1, audited=None)
        self.fin(org, y - 2, audited=None)
        self.doc(org, y)
        lv = scoring.levels(org)
        self.assertEqual(lv["level"], 4)
        self.assertEqual([c["key"] for c in lv["layers"][3]["checks"]], ["financial_consecutive", "report"])

    def test_layers_must_be_reached_in_order(self):
        org = make_org()  # 第 1 層沒過
        y = roc_now() - 1
        for i in range(3):
            self.fin(org, y - i, audited=True)
        self.doc(org, y)
        lv = scoring.levels(org)
        self.assertEqual(lv["level"], 0)
        self.assertTrue(lv["layers"][3]["met"])  # 第 4 層的條件達到了，但前面沒過就不算

    def test_penalty_does_not_change_level(self):
        org = full_identity()
        before = self.level(org)
        Penalty.objects.create(organization=org, decided_on=date.today(), content="罰")
        self.assertEqual(self.level(org), before)


class ApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        today = scoring.today()
        self.a = make_org("11111111", name="甲公益協會", city="臺北市", website="https://a.tw")
        self.b = make_org("22222222", name="乙基金會", city="臺中市", status=Organization.Status.CANCELLED)
        self.c = make_org("33333333", name="丙協會", city="臺北市")
        Penalty.objects.create(organization=self.a, decided_on=today - timedelta(days=30), content="近期")
        Penalty.objects.create(organization=self.a, decided_on=today - timedelta(days=365 * 6), content="很久以前")
        Penalty.objects.create(organization=self.c, decided_on=today - timedelta(days=365 * 7), content="很久以前")
        AnnualFundraising.objects.create(organization=self.b, year=period.since_roc_year(), raised=0, target=0)
        Donation.objects.create(organization=self.a, donor_name="王大明", amount=500)
        Donation.objects.create(organization=self.a, donor_name="王大明", amount=700)
        Donation.objects.create(organization=self.a, donor_name="陳小華", amount=1000)
        Donation.objects.create(organization=self.a, donor_name="秘密捐款人", is_anonymous=True, amount=99999)

    def test_stats(self):
        r = self.client.get("/api/stats").json()
        self.assertEqual(
            r, {"organizations": 3, "with_fundraising": 1, "penalized_5y": 1, "since_roc_year": period.since_roc_year(),
                "donor_individual_threshold": settings.DONOR_INDIVIDUAL_THRESHOLD}
        )

    def test_list_default_order_and_penalty_count(self):
        r = self.client.get("/api/orgs").json()
        self.assertEqual(r["count"], 3)
        a = next(o for o in r["results"] if o["ubn"] == "11111111")
        self.assertEqual(a["penalty_count_5y"], 1)
        levels = [o["disclosure_level"] for o in r["results"]]
        self.assertEqual(levels, sorted(levels, reverse=True))

    def test_search_and_filters(self):
        self.assertEqual([o["ubn"] for o in self.client.get("/api/orgs?q=22222222").json()["results"]], ["22222222"])
        self.assertEqual(self.client.get("/api/orgs?q=協會").json()["count"], 2)
        self.assertEqual(self.client.get("/api/orgs?city=臺北市").json()["count"], 2)
        self.assertEqual(self.client.get("/api/orgs?status=cancelled").json()["count"], 1)
        names = [o["name"] for o in self.client.get("/api/orgs?ordering=name").json()["results"]]
        self.assertEqual(names, sorted(names))

    def test_detail_hides_anonymous_donor(self):
        r = self.client.get("/api/orgs/11111111").json()
        self.assertEqual(r["penalty_count_5y"], 1)
        self.assertEqual(len(r["penalties"]), 2)
        self.assertEqual(
            [(d["name"], d["total"]) for d in r["individual_donors"]], [("王大明", 1200), ("陳小華", 1000)]
        )
        self.assertEqual(r["corporate_donors"], [])
        self.assertIsNone(r["donor_summary"])
        names = {d["donor_name"] for d in r["donations"]}
        self.assertIn("匿名", names)
        self.assertNotIn("秘密捐款人", str(r))
        self.assertEqual(r["levels"]["level"], r["disclosure_level"])
        self.assertEqual(len(r["levels"]["layers"]), 4)

    def test_detail_404(self):
        self.assertEqual(self.client.get("/api/orgs/99999999").status_code, 404)

    def test_achievement_rate(self):
        AnnualFundraising.objects.create(organization=self.c, year=period.since_roc_year() + 1, raised=66358, target=1500000)
        rows = self.client.get("/api/orgs/33333333").json()["annual_records"]
        self.assertEqual(rows[0]["achievement_rate"], 4.4)
        self.assertIsNone(self.client.get("/api/orgs/22222222").json()["annual_records"][0]["achievement_rate"])

    def test_filters(self):
        r = self.client.get("/api/filters").json()
        self.assertEqual(r["cities"], ["臺中市", "臺北市"])
        self.assertEqual(r["statuses"][0], {"value": "active", "label": "營運中"})


class AdminAccessTests(TestCase):
    def test_admin_requires_staff(self):
        User = get_user_model()
        self.assertEqual(self.client.get("/admin/orgs/organization/").status_code, 302)
        User.objects.create_user("donor@example.com", "donor@example.com", "pw-123456789")
        self.client.login(username="donor@example.com", password="pw-123456789")
        r = self.client.get("/admin/orgs/organization/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])

    def test_admin_edit_locks_changed_field(self):
        User = get_user_model()
        User.objects.create_superuser("admin", "admin@example.com", "pw-123456789")
        self.client.login(username="admin", password="pw-123456789")
        org = make_org(name="原名")
        r = self.client.get(f"/admin/orgs/organization/{org.pk}/change/")
        self.assertEqual(r.status_code, 200)
        data = {
            "ubn": org.ubn, "name": "新名", "status": "active", "org_type": "", "representative": "",
            "registered_address": "", "contact_address": "", "phone": "", "website": "", "city": "", "purposes": "",
            "source_links": "[]", "locked_fields": "[]",
        }
        for prefix in ("categories", "annual_records", "financials", "documents", "donations", "projects", "penalties"):
            data.update({f"{prefix}-TOTAL_FORMS": "0", f"{prefix}-INITIAL_FORMS": "0"})
        # locked_fields 欄位原值也是 []，沒被改動 → 由 save_model 自動補上被改的欄位
        r = self.client.post(f"/admin/orgs/organization/{org.pk}/change/", data)
        self.assertEqual(r.status_code, 302, r.content[:2000])
        org.refresh_from_db()
        self.assertEqual(org.name, "新名")
        self.assertEqual(org.locked_fields, ["name"])


class SettingsTests(SimpleTestCase):
    def test_database_url_switches_to_postgres(self):
        code = (
            "import importlib, json, npofile.settings as s;"
            "print(json.dumps([s.DATABASES['default']['ENGINE'], s.DATABASES['default']['NAME']]))"
        )
        env = {**os.environ, "DATABASE_URL": "postgres://u:p@db.example.com:5432/npofile",
               "DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY": "x", "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, encoding="utf-8",
                             cwd=Path(__file__).resolve().parents[2], check=True).stdout
        self.assertEqual(json.loads(out), ["django.db.backends.postgresql", "npofile"])

    def test_production_requires_secret_key(self):
        env = {k: v for k, v in os.environ.items() if k != "DJANGO_SECRET_KEY"}
        env.update({"DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY": "", "PYTHONIOENCODING": "utf-8"})
        r = subprocess.run([sys.executable, "-c", "import npofile.settings"], env=env, capture_output=True,
                           encoding="utf-8", errors="replace", cwd=Path(__file__).resolve().parents[2])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", r.stderr)


class OrgListRaisedOrderingTests(TestCase):
    """LK-20：首頁預設依近 5 年公開募款排序（勸募申報＋群眾集資，同一年度不重複）；沒有的依揭露指數、名稱。"""

    def setUp(self):
        self.this_year = period.since_roc_year() + period.YEARS - 1
        y = self.this_year
        self.big = make_org("10000001", name="甲")
        self.small = make_org("10000002", name="乙")
        self.old_only = make_org("10000003", name="丙")
        self.none_high = make_org("10000004", name="丁", website="https://d.tw")
        self.crowd = make_org("10000005", name="戊")
        AnnualFundraising.objects.create(organization=self.big, year=y, raised=500)
        AnnualFundraising.objects.create(organization=self.big, year=y - 1, raised=300)
        AnnualFundraising.objects.create(organization=self.small, year=y, raised=100)
        # 早於近 5 年的不算
        AnnualFundraising.objects.create(organization=self.old_only, year=period.since_roc_year() - 1, raised=9999)
        # 有裁罰也不能讓金額被放大
        Penalty.objects.create(organization=self.big, decided_on=date.today(), content="a")
        Penalty.objects.create(organization=self.big, decided_on=date.today(), content="b")
        # 群眾集資：今年勸募還沒申報（0）→ 用集資補上；去年勸募已申報 → 去年的集資不重複算
        AnnualFundraising.objects.create(organization=self.crowd, year=y, raised=0)
        AnnualFundraising.objects.create(organization=self.crowd, year=y - 1, raised=40)
        Project.objects.create(organization=self.crowd, name="今年集資", channel="crowdfunding", raised=600, start_date=date(y + 1911, 3, 1))
        Project.objects.create(organization=self.crowd, name="去年集資", channel="crowdfunding", raised=70, start_date=date(y + 1910, 3, 1))
        Project.objects.create(organization=self.crowd, name="定期定額", channel="crowdfunding", raised=None, monthly_raised=999, start_date=date(y + 1911, 5, 1))
        scoring.recompute()

    def test_public_raised_rule(self):
        b = scoring.public_raised(list(self.crowd.annual_records.all()), list(self.crowd.projects.all()))
        self.assertEqual(b, {"total": 640, "permit": 40, "crowdfunding": 670, "crowdfunding_counted": 600})

    def test_default_ordering_is_public_raised_5y(self):
        r = self.client.get("/api/orgs").json()["results"]
        self.assertEqual([o["ubn"] for o in r[:3]], ["10000001", "10000005", "10000002"])
        self.assertEqual([o["public_raised_5y"] for o in r[:3]], [800, 640, 100])
        rest = r[3:]
        self.assertTrue(all(o["public_raised_5y"] == 0 for o in rest))
        levels = [o["disclosure_level"] for o in rest]
        self.assertEqual(levels, sorted(levels, reverse=True))

    def test_detail_has_breakdown(self):
        d = self.client.get("/api/orgs/10000005").json()
        self.assertEqual(d["public_raised"]["total"], 640)

    def test_stored_total_follows_new_data(self):
        AnnualFundraising.objects.filter(organization=self.crowd, year=self.this_year).update(raised=900)
        scoring.recompute(Organization.objects.filter(pk=self.crowd.pk))
        self.crowd.refresh_from_db()
        self.assertEqual(self.crowd.public_raised_5y, 940)  # 今年勸募申報後，今年的集資就不再加

    def test_score_ordering_still_available(self):
        for ordering in ("level", "score"):  # score 是舊網址
            r = self.client.get(f"/api/orgs?ordering={ordering}").json()["results"]
            levels = [o["disclosure_level"] for o in r]
            self.assertEqual(levels, sorted(levels, reverse=True))


class DonationTrendTests(TestCase):
    """LK-33：組織頁近 5 年受捐款趨勢——勸募、集資、補助各自逐年加總，不相加。"""

    def setUp(self):
        from orgs.models import Grant

        self.since = period.since_roc_year()
        self.this_year = self.since + period.YEARS - 1
        y = self.this_year
        self.org = make_org("10000011", name="趨勢協會")
        AnnualFundraising.objects.create(organization=self.org, year=y - 1, raised=300)
        AnnualFundraising.objects.create(organization=self.org, year=y - 3, raised=100)
        AnnualFundraising.objects.create(organization=self.org, year=self.since - 1, raised=9999)  # 早於近 5 年
        Project.objects.create(organization=self.org, name="去年集資", channel="crowdfunding", raised=70,
                               start_date=date(y + 1910, 3, 1))
        Project.objects.create(organization=self.org, name="定期定額", channel="crowdfunding", raised=None,
                               monthly_raised=999, start_date=date(y + 1910, 5, 1))
        Project.objects.create(organization=self.org, name="勸募活動", channel="permit", raised=5000,
                               start_date=date(y + 1910, 1, 1))
        common = dict(organization=self.org, year=y - 1, agency="衛福部", recipient="趨勢協會", purpose="服務",
                      approved_on=date(y + 1910, 6, 1), amount=200)
        Grant.objects.create(source_name="甲表", external_id="g1", **common)
        Grant.objects.create(source_name="乙表", external_id="g1", **common)  # 別的部會表重複列 → 只算一次
        Grant.objects.create(source_name="甲表", external_id="g2", **{**common, "year": y - 2, "amount": 50})

    def trend(self):
        return self.client.get("/api/orgs/10000011").json()["donation_trend"]

    def test_yearly_sums_by_kind(self):
        rows = {r["year"]: r for r in self.trend()}
        y = self.this_year
        self.assertEqual(rows[y - 1], {"year": y - 1, "permit": 300, "crowdfunding": 70, "grants": 200})
        self.assertEqual(rows[y - 2], {"year": y - 2, "permit": 0, "crowdfunding": 0, "grants": 50})
        self.assertEqual(rows[y - 3]["permit"], 100)
        self.assertEqual(rows[self.since], {"year": self.since, "permit": 0, "crowdfunding": 0, "grants": 0})

    def test_empty_current_year_is_dropped(self):
        years = [r["year"] for r in self.trend()]
        self.assertEqual(years, list(range(self.since, self.this_year)))

    def test_current_year_kept_when_it_has_money(self):
        AnnualFundraising.objects.create(organization=self.org, year=self.this_year, raised=1)
        self.assertEqual(self.trend()[-1]["year"], self.this_year)

    def test_totals_match_public_raised(self):
        d = self.client.get("/api/orgs/10000011").json()
        t = d["donation_trend"]
        self.assertEqual(sum(r["permit"] for r in t), d["public_raised"]["permit"])
        self.assertEqual(sum(r["crowdfunding"] for r in t), d["public_raised"]["crowdfunding"])
        self.assertEqual(sum(r["grants"] for r in t), sum(g["amount"] for g in d["grants"]))
