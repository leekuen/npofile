"""集團歸戶（LK-23）：法人董事連結、共用法人、排除政府基金、不用同名個人、管理員指定、前台合計。"""

from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from orgs import groups
from orgs.groups import Company, build_clusters
from orgs.models import CompanyGroup, Donation, Donor, Organization, Project

FUBON = "富邦金融控股股份有限公司"


def J(name, seats=1, shares=0):
    return {"name": name, "seats": seats, "shares": shares}


class RuleTests(TestCase):
    def test_same_parent_makes_one_group(self):
        clusters = build_clusters([
            Company(1, ("富邦人壽保險股份有限公司", ""), (J(FUBON, 9),)),
            Company(2, ("台北富邦商業銀行股份有限公司", ""), (J(FUBON, 9),)),
            Company(3, ("富邦綜合證券股份有限公司", ""), (J(FUBON, 7), J("富邦人壽保險股份有限公司", 1))),
            Company(4, ("富邦產物保險股份有限公司", ""), (J(FUBON, 8),)),
            Company(5, ("無關的公司股份有限公司", ""), ()),
        ])
        self.assertEqual([(c.anchor, c.members) for c in clusters], [(FUBON, [1, 2, 3, 4])])

    def test_joint_venture_does_not_chain_groups(self):
        # 2026-11-27 本機實測：合資公司的董事來自好幾家，不能把各集團串成一群
        clusters = build_clusters([
            Company(1, ("富邦人壽保險股份有限公司", ""), (J(FUBON, 9),)),
            Company(2, ("台北富邦商業銀行股份有限公司", ""), (J(FUBON, 9),)),
            Company(3, ("悠遊卡股份有限公司", ""), (J("悠遊卡投資控股股份有限公司", 5), J("台北富邦商業銀行股份有限公司", 1))),
            Company(4, ("台北金融大樓股份有限公司", ""), (J("臺灣證券交易所股份有限公司", 3), J("中華電信股份有限公司", 2))),
            Company(5, ("中華電信股份有限公司", ""), ()),
            Company(6, ("臺灣證券交易所股份有限公司", ""), ()),
        ])
        self.assertIn((FUBON, [1, 2]), [(c.anchor, c.members) for c in clusters])
        self.assertIn(("臺灣證券交易所股份有限公司", [4, 6]), [(c.anchor, c.members) for c in clusters])
        self.assertFalse(any(5 in c.members or 3 in c.members for c in clusters))

    def test_chain_goes_up_to_the_top(self):
        # 國泰世華的上層是國泰金控（也是捐款公司）；台灣名稱寫法不同也認得
        clusters = build_clusters([
            Company(1, ("國泰世華商業銀行股份有限公司", ""), (J("國泰金融控股股份有限公司", 9),)),
            Company(2, ("國泰金融控股股份有限公司", ""), ()),
            Company(3, ("某某保險經紀人股份有限公司", ""), (J("國泰世華商業銀行股份有限公司", 3),)),
        ])
        self.assertEqual([(c.anchor, c.members) for c in clusters], [("國泰金融控股股份有限公司", [1, 2, 3])])

    def test_tie_is_not_linked_and_cycle_stops(self):
        tie = (J("甲投資股份有限公司", 2, 100), J("乙投資股份有限公司", 2, 100))
        self.assertEqual(build_clusters([Company(1, ("丙股份有限公司", ""), tie), Company(2, ("丁股份有限公司", ""), tie)]), [])
        more_shares = (J("甲投資股份有限公司", 2, 100), J("乙投資股份有限公司", 2, 900))
        clusters = build_clusters([Company(1, ("丙股份有限公司", ""), more_shares), Company(2, ("丁股份有限公司", ""), more_shares)])
        self.assertEqual(clusters[0].anchor, "乙投資股份有限公司")
        # 互相持股：甲的上層是乙、乙的上層是甲，不會無限迴圈
        loop = build_clusters([
            Company(1, ("甲股份有限公司", ""), (J("乙股份有限公司"),)),
            Company(2, ("乙股份有限公司", ""), (J("甲股份有限公司"),)),
        ])
        self.assertEqual([c.members for c in loop], [[1, 2]])

    def test_government_funds_and_trusts_do_not_link(self):
        for juristic in (
            "行政院國家發展基金管理會",
            "中華郵政股份有限公司",
            "兆豐國際商業銀行股份有限公司受託信託財產專戶",
            "財團法人某某基金會",
            "某某市政府",
        ):
            with self.subTest(juristic=juristic):
                self.assertFalse(groups.eligible(juristic))
                clusters = build_clusters([Company(1, ("甲股份有限公司", ""), (J(juristic, 5),)), Company(2, ("乙股份有限公司", ""), (J(juristic, 5),))])
                self.assertEqual(clusters, [])

    def test_single_company_with_parent_is_not_a_group(self):
        self.assertEqual(build_clusters([Company(1, ("甲股份有限公司", ""), (J("母公司股份有限公司"),))]), [])

    def test_short_name_and_label(self):
        self.assertEqual(groups.group_label(FUBON, 4), "富邦金融控股 等 4 家")
        self.assertEqual(groups.short_name("某某有限公司"), "某某")


def company(name, juristic=(), **kw):
    return Donor.objects.create(
        name=name, kind="company", ubn=kw.pop("ubn", ""), juristic_directors=[J(j, 5) for j in juristic],
        directors_checked_at=timezone.now(), **kw,
    )


class RecomputeTests(TestCase):
    def test_stable_ids_manual_overrides_and_dissolve(self):
        a = company("富邦人壽保險股份有限公司", [FUBON])
        b = company("台北富邦商業銀行股份有限公司", [FUBON])
        c = company("富邦產物保險股份有限公司", [FUBON])
        groups.recompute()
        g = CompanyGroup.objects.get(anchor=FUBON)
        self.assertEqual(set(g.members.values_list("pk", flat=True)), {a.pk, b.pk, c.pk})

        # 管理員把 c 移出集團：重算不會加回去；集團編號不變
        c.group, c.group_manual = None, True
        c.save()
        groups.recompute()
        self.assertEqual(CompanyGroup.objects.get(anchor=FUBON).pk, g.pk)
        c.refresh_from_db()
        self.assertIsNone(c.group)

        # 管理員自己建的集團，重算不動
        mg = CompanyGroup.objects.create(name="手動集團", manual=True)
        x = company("關係企業甲股份有限公司", group=mg, group_manual=True)
        groups.recompute()
        x.refresh_from_db()
        self.assertEqual(x.group, mg)

        # 法人董事換掉 → 只剩一家 → 集團拿掉
        b.juristic_directors = []
        b.save()
        stats = groups.recompute()
        self.assertFalse(CompanyGroup.objects.filter(anchor=FUBON).exists())
        self.assertEqual(stats["removed_groups"], 1)
        self.assertTrue(CompanyGroup.objects.filter(pk=mg.pk).exists())

    def test_registry_timeout_skips_company_and_still_regroups(self):
        import httpx

        a = Donor.objects.create(name="富邦人壽保險股份有限公司", kind="company", ubn="11111111")
        company("台北富邦商業銀行股份有限公司", [FUBON])
        company("富邦產物保險股份有限公司", [FUBON])
        boom = httpx.HTTPStatusError("server error 504", request=None, response=None)
        with mock.patch("orgs.management.commands.group_companies.gcis.juristic_directors", side_effect=boom):
            call_command("group_companies", stdout=mock.MagicMock(), stderr=mock.MagicMock())
        a.refresh_from_db()
        self.assertIsNone(a.directors_checked_at)  # 下次再查
        self.assertEqual(CompanyGroup.objects.get(anchor=FUBON).members.count(), 2)

    def test_old_string_format_still_works(self):
        self.assertEqual(groups.parent_of([FUBON]), FUBON)

    def test_same_representative_alone_does_not_link(self):
        company("甲股份有限公司", representative="王大明")
        company("乙股份有限公司", representative="王大明")
        self.assertEqual(groups.recompute()["groups"], 0)

    def test_command_fetches_only_due_companies_and_keeps_no_personal_names(self):
        due = Donor.objects.create(name="富邦人壽保險股份有限公司", kind="company", ubn="11111111")
        Donor.objects.create(name="沒有統編股份有限公司", kind="company")
        fresh = company("台北富邦商業銀行股份有限公司", [FUBON], ubn="22222222")
        with mock.patch("orgs.management.commands.group_companies.gcis.juristic_directors", return_value=[J(FUBON, 5)]) as fetch:
            call_command("group_companies", stdout=mock.MagicMock())
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[1], "11111111")
        due.refresh_from_db()
        self.assertEqual(due.juristic_directors, [J(FUBON, 5)])
        self.assertEqual(due.group_id, Donor.objects.get(pk=fresh.pk).group_id)


class ApiTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        org = Organization.objects.create(ubn="12345678", name="某某基金會")
        project = Project.objects.create(organization=org, name="計畫", external_id="1")
        self.members = []
        for name, amount in (("富邦人壽保險股份有限公司", 300), ("台北富邦商業銀行股份有限公司", 200), ("富邦產物保險股份有限公司", 100)):
            d = company(name, [FUBON])
            Donation.objects.create(organization=org, project=project, donor=d, donor_name=name, amount=amount)
            self.members.append(d)
        groups.recompute()
        self.group = CompanyGroup.objects.get(anchor=FUBON)

    def test_group_total_equals_member_totals(self):
        rows = self.api.get("/api/donor-groups").json()["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total"], 600)
        self.assertEqual(rows[0]["label"], "富邦金融控股 等 3 家")
        detail = self.api.get(f"/api/donor-groups/{self.group.pk}").json()
        self.assertEqual(sum(m["total"] for m in detail["members"]), detail["total"])
        self.assertEqual(detail["organizations"][0]["total"], 600)
        self.assertEqual(detail["fields_breakdown"][0]["total"], 600)

    def test_hidden_member_not_counted_and_group_needs_two_public(self):
        self.members[0].hidden = True
        self.members[0].save()
        rows = self.api.get("/api/donor-groups").json()["results"]
        self.assertEqual(rows[0]["total"], 300)
        self.members[1].hidden = True
        self.members[1].save()
        self.assertEqual(self.api.get("/api/donor-groups").json()["count"], 0)
        self.assertEqual(self.api.get(f"/api/donor-groups/{self.group.pk}").status_code, 404)

    def test_search_by_member_name_and_donor_page_shows_group(self):
        self.assertEqual(self.api.get("/api/donor-groups", {"q": "產物"}).json()["count"], 1)
        self.assertEqual(self.api.get("/api/donor-groups", {"q": "國泰"}).json()["count"], 0)
        donor = self.api.get(f"/api/donors/{self.members[2].pk}").json()
        self.assertEqual(donor["group"]["label"], "富邦金融控股 等 3 家")
        self.assertNotIn("juristic_directors", donor)

    def test_company_ranking_unchanged(self):
        rows = self.api.get("/api/donors").json()["results"]
        self.assertEqual([r["total"] for r in rows], [300, 200, 100])
