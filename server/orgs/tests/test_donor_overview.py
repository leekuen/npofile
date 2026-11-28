"""捐款企業頁的捐款概況（LK-38）：同類排名、持續支持年度、年度趨勢、受捐組織的支持年度與裁罰筆數。"""

from datetime import date, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from orgs import period
from orgs.models import Donation, Donor, Organization, Penalty


def roc_now():
    return period.today().year - 1911


def on(roc, month=3, day=1):
    return date(roc + 1911, month, day)


class DonorOverviewTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.a = Organization.objects.create(ubn="11111111", name="甲協會")
        self.b = Organization.objects.create(ubn="22222222", name="乙基金會")
        Penalty.objects.create(organization=self.b, content="違反公益勸募條例", decided_on=date(2001, 1, 1))  # 很舊也算
        Penalty.objects.create(organization=self.b, content="未依限公開徵信")
        y = roc_now()
        self.big = self.donor("大公司", Donor.Kind.COMPANY)
        self.give(self.big, self.a, 300, on(y - 2))
        self.give(self.big, self.a, 200, on(y - 2, 6))
        self.give(self.big, self.b, 500, on(y))
        self.tie = self.donor("並列公司", Donor.Kind.COMPANY)
        self.give(self.tie, self.a, 1000, on(y - 1))
        self.small = self.donor("小公司", Donor.Kind.COMPANY)
        self.give(self.small, self.a, 10, on(y - 1))
        self.group = self.donor("某扶輪社", Donor.Kind.GROUP)
        self.give(self.group, self.a, 5, on(y - 1))
        hidden = self.donor("隱藏公司", Donor.Kind.COMPANY, hidden=True)
        self.give(hidden, self.a, 99999, on(y - 1))

    def donor(self, name, kind, **kw):
        return Donor.objects.create(name=name, kind=kind, **kw)

    def give(self, donor, org, amount, on_date):
        return Donation.objects.create(organization=org, donor=donor, donor_name=donor.name, amount=amount, donated_on=on_date)

    def detail(self, donor):
        r = self.api.get(f"/api/donors/{donor.pk}")
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_rank_within_same_kind_with_ties_and_hidden_excluded(self):
        big, tie, small = (self.detail(d)["overview"] for d in (self.big, self.tie, self.small))
        self.assertEqual((big["rank"], big["rank_of"]), (1, 3))  # 隱藏的不佔名次、團體不跟企業比
        self.assertEqual(tie["rank"], 1)  # 同額並列
        self.assertEqual(small["rank"], 3)
        g = self.detail(self.group)["overview"]
        self.assertEqual((g["rank"], g["rank_of"]), (1, 1))

    def test_yearly_fills_missing_years_with_zero(self):
        ov = self.detail(self.big)["overview"]
        y = roc_now()
        self.assertEqual([r["year"] for r in ov["yearly"]], list(range(y - 4, y + 1)))
        by_year = {r["year"]: r for r in ov["yearly"]}
        self.assertEqual(by_year[y - 2], {"year": y - 2, "total": 500, "org_count": 1, "count": 2})
        self.assertEqual(by_year[y - 1]["total"], 0)
        self.assertEqual(ov["active_years"], [y - 2, y])
        self.assertEqual(ov["max_donation"], 500)
        self.assertEqual(ov["first_donated_on"], on(y - 2).isoformat())

    def test_future_dates_count_in_total_but_not_in_trend_or_last(self):
        future = period.today() + timedelta(days=400)
        self.give(self.small, self.a, 7, future)
        d = self.detail(self.small)
        self.assertEqual(d["total"], 17)  # 總額照算
        ov = d["overview"]
        self.assertEqual(sum(r["total"] for r in ov["yearly"]), 10)
        self.assertEqual(ov["last_donated_on"], on(roc_now() - 1).isoformat())
        self.assertEqual(ov["active_years"], [roc_now() - 1])

    def test_organizations_have_years_and_penalty_count(self):
        orgs = {o["ubn"]: o for o in self.detail(self.big)["organizations"]}
        y = roc_now()
        self.assertEqual(orgs["11111111"]["years"], [y - 2])
        self.assertEqual(orgs["11111111"]["penalty_count"], 0)
        self.assertEqual(orgs["22222222"]["penalty_count"], 2)  # 裁罰不限年份

    def test_list_has_year_count_and_last_date_without_n_plus_1(self):
        with CaptureQueriesContext(connection) as ctx:
            rows = {r["name"]: r for r in self.api.get("/api/donors").json()["results"]}
        self.assertLessEqual(len(ctx.captured_queries), 3)
        self.assertEqual(rows["大公司"]["active_year_count"], 2)
        self.assertEqual(rows["大公司"]["last_donated_on"], on(roc_now()).isoformat())
        self.assertNotIn("隱藏公司", rows)
        # 總額跟改之前一樣（多一個 annotate 不能讓 join 重複算）
        self.assertEqual(rows["大公司"]["total"], 1000)
        self.assertEqual(rows["大公司"]["donation_count"], 3)
