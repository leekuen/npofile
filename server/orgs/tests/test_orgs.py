import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

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


class ScoringTests(TestCase):
    def test_empty_org_only_gets_ubn_points(self):
        org = make_org()
        self.assertEqual(scoring.breakdown(org)["total"], 5)
        org.refresh_from_db()
        self.assertEqual(org.disclosure_score, 5)

    def test_full_score(self):
        org = make_org(
            org_type="財團法人", registered_address="臺北市", phone="02", website="https://a.tw", purposes="教育事業"
        )
        year = scoring.today().year - 1911
        AnnualFundraising.objects.create(organization=org, year=year - 1, raised=100, target=200)
        Project.objects.create(organization=org, name="a", raised=10, result_filed_on=date(2025, 1, 1))
        Project.objects.create(organization=org, name="b", raised=0)
        b = scoring.breakdown(org)
        self.assertEqual((b["basic"], b["fundraising"], b["project"], b["result"]), (30, 25, 20, 25))
        org.refresh_from_db()
        self.assertEqual(org.disclosure_score, 100)

    def test_result_ratio_and_old_fundraising(self):
        org = make_org()
        AnnualFundraising.objects.create(organization=org, year=scoring.today().year - 1911 - 6, raised=100, target=100)
        Project.objects.create(organization=org, name="a", raised=10, result_filed_on=date(2025, 1, 1))
        Project.objects.create(organization=org, name="b", raised=10)
        b = scoring.breakdown(org)
        self.assertEqual(b["fundraising"], 0)  # 六年前的不算
        self.assertEqual(b["result"], 12)  # 1/2 × 25 四捨五入（銀行家捨入 12.5→12）
        self.assertEqual(b["total"], 5 + 0 + 20 + 12)

    def test_donation_counts_as_fundraising_disclosure(self):
        org = make_org()
        Donation.objects.create(organization=org, donor_name="甲", amount=100)
        self.assertEqual(scoring.breakdown(org)["fundraising"], 25)

    def test_penalty_does_not_change_score(self):
        org = make_org()
        before = Organization.objects.get(pk=org.pk).disclosure_score
        Penalty.objects.create(organization=org, decided_on=date.today(), content="罰")
        self.assertEqual(Organization.objects.get(pk=org.pk).disclosure_score, before)


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
            r, {"organizations": 3, "with_fundraising": 1, "penalized_5y": 1, "since_roc_year": period.since_roc_year()}
        )

    def test_list_default_order_and_penalty_count(self):
        r = self.client.get("/api/orgs").json()
        self.assertEqual(r["count"], 3)
        first = r["results"][0]
        self.assertEqual(first["ubn"], "11111111")  # 有官網、有捐款 → 分數最高
        self.assertEqual(first["penalty_count_5y"], 1)
        scores = [o["disclosure_score"] for o in r["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

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
        self.assertEqual(r["score"]["total"], r["disclosure_score"])

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
        for prefix in ("annual_records", "donations", "projects", "penalties"):
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
