from datetime import date

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from orgs import period
from orgs.models import AnnualFundraising, Donation, Donor, DonorListSummary, Organization, Penalty, Project

SINCE = period.since_roc_year()
OLD = SINCE - 1  # 剛好在近 5 年外
NEW = SINCE  # 剛好在近 5 年內


def roc_date(roc_year: int, month: int = 6, day: int = 1) -> date:
    return date(roc_year + 1911, month, day)


class WindowRuleTests(SimpleTestCase):
    def test_window_is_calendar_year_four_years_back(self):
        self.assertEqual(period.since_roc_year(date(2026, 11, 27)), 111)
        self.assertEqual(period.window_start(date(2026, 11, 27)), date(2022, 1, 1))
        self.assertEqual(period.since_roc_year(date(2027, 1, 1)), 112)

    def test_unknown_year_counts_as_in_window(self):
        self.assertTrue(period.in_window(None))
        self.assertFalse(period.in_window(OLD))

    def test_project_period_year(self):
        self.assertEqual(Project(name="x", start_date=date(2023, 3, 1)).compute_period_year(), 112)
        self.assertEqual(Project(name="114年度行動音樂教室").compute_period_year(), 114)
        self.assertEqual(Project(name="沒寫年度", result_filed_on=date(2024, 1, 5)).compute_period_year(), 113)
        self.assertIsNone(Project(name="沒寫年度").compute_period_year())


class WindowApiTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.org = Organization.objects.create(ubn="12345678", name="甲協會", website="https://a.tw")
        AnnualFundraising.objects.create(organization=self.org, year=OLD, raised=100, target=100)
        AnnualFundraising.objects.create(organization=self.org, year=NEW, raised=200, target=400)
        self.old_p = Project.objects.create(organization=self.org, name="舊活動", start_date=roc_date(OLD), raised=10,
                                            result_filed_on=roc_date(OLD, 12))
        self.new_p = Project.objects.create(organization=self.org, name="新活動", start_date=roc_date(NEW), raised=10)
        self.company = Donor.objects.create(name="範例股份有限公司", kind=Donor.Kind.COMPANY)
        Donation.objects.create(organization=self.org, project=self.old_p, donor=self.company, donor_name=self.company.name, amount=1000)
        Donation.objects.create(organization=self.org, project=self.new_p, donor=self.company, donor_name=self.company.name, amount=300)
        DonorListSummary.objects.create(project=self.old_p, total_rows=10, anonymous_rows=5, anonymous_amount=50)
        DonorListSummary.objects.create(project=self.new_p, total_rows=3, anonymous_rows=1, anonymous_amount=7)
        Penalty.objects.create(organization=self.org, decided_on=date(2015, 1, 1), content="十年前的裁罰")
        Penalty.objects.create(organization=self.org, decided_on=roc_date(NEW), content="近期的裁罰")

    def test_org_detail_only_recent_but_all_penalties(self):
        r = self.api.get("/api/orgs/12345678").json()
        self.assertEqual([a["year"] for a in r["annual_records"]], [NEW])
        self.assertEqual([p["name"] for p in r["projects"]], ["新活動"])
        self.assertEqual(r["corporate_donors"][0]["total"], 300)
        self.assertEqual((r["donor_summary"]["total_rows"], r["donor_summary"]["anonymous_amount"]), (3, 7))
        self.assertEqual(len(r["penalties"]), 2)  # 裁罰不限年度
        self.assertEqual(r["penalty_count_5y"], 1)  # 醒目標示仍是近五年

    def test_level_ignores_old_projects(self):
        lv = self.api.get("/api/orgs/12345678").json()["levels"]
        # 舊專案不在近 5 年，不算進「到期的活動」；近 5 年的新活動算看得到的活動
        self.assertTrue(lv["layers"][1]["checks"][0]["met"])
        self.assertLessEqual(lv["results_due"], 1)

    def test_donor_totals_only_recent(self):
        row = self.api.get("/api/donors").json()["results"][0]
        self.assertEqual(row["total"], 300)
        detail = self.api.get(f"/api/donors/{self.company.pk}").json()
        self.assertEqual(len(detail["donations"]), 1)
        self.assertEqual(detail["organizations"][0]["total"], 300)

    def test_donor_with_only_old_donations_disappears(self):
        Donation.objects.filter(project=self.new_p).delete()
        self.assertEqual(self.api.get("/api/donors").json()["count"], 0)
        self.assertEqual(self.api.get(f"/api/donors/{self.company.pk}").status_code, 404)

    def test_stats_with_fundraising_is_recent(self):
        other = Organization.objects.create(ubn="87654321", name="乙協會")
        AnnualFundraising.objects.create(organization=other, year=OLD, raised=1, target=1)
        self.assertEqual(self.api.get("/api/stats").json()["with_fundraising"], 1)

    def test_prune_keeps_penalties(self):
        call_command("prune_old_records", "--dry-run")
        self.assertEqual(Project.objects.count(), 2)
        call_command("prune_old_records")
        self.assertEqual(list(Project.objects.values_list("name", flat=True)), ["新活動"])
        self.assertEqual(list(AnnualFundraising.objects.values_list("year", flat=True)), [NEW])
        self.assertEqual(Donation.objects.count(), 1)
        self.assertEqual(DonorListSummary.objects.count(), 1)
        self.assertEqual(Penalty.objects.count(), 2)
