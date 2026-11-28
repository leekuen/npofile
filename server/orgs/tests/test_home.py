from datetime import date, timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from orgs import home, period
from orgs.categorize import categorize
from orgs.models import AnnualFundraising, Donation, Donor, Organization, Penalty, Project


class PenaltyKindTests(SimpleTestCase):
    def kind(self, reason, content=""):
        return home.penalty_kind(Penalty(reason=reason, content=content))

    def test_kinds(self):
        self.assertEqual(self.kind("仍未就「勸募團體應於勸募活動期滿之翌日起三十日內…公開徵信」"), "沒有按時公開收支與成果")
        self.assertEqual(self.kind("確認該會於店家仍擺放募款箱持續募款"), "超過許可期間仍在募款")
        self.assertEqual(self.kind("勸募團體收受勸募所得財物，應開立收據。惟受處分人以募款箱募款未開立收據"), "沒有開立收據")
        self.assertEqual(self.kind("公開徵信內容之資料不實，顯為情節重大"), "公開的資料不實")
        self.assertEqual(self.kind("代表人涉嫌將大量善款轉入私人帳戶"), "")  # 歸不進去就不寫


class Base(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.since = period.since_roc_year()

    def org(self, ubn, name, purposes="", city="臺北市", level=2):
        return Organization.objects.create(ubn=ubn, name=name, purposes=purposes, city=city, disclosure_level=level)

    def live(self, org, name, days=5, **kw):
        return Project.objects.create(
            organization=org, name=name, external_id=kw.pop("external_id", f"{org.ubn}-{name}"),
            start_date=self.today - timedelta(days=30), end_date=self.today + timedelta(days=days), target=100_000, **kw)


class DiscoverTests(Base):
    def test_ending_campaigns(self):
        a = self.org("10000001", "甲協會", level=1)
        soon = self.live(a, "快截止", days=2)
        self.live(a, "今天截止", days=0)
        self.live(a, "還很久", days=30)
        self.live(a, "集資", days=1, channel=Project.Channel.CROWDFUNDING)
        Project.objects.create(organization=a, name="還沒開始", start_date=self.today + timedelta(days=1),
                               end_date=self.today + timedelta(days=3), target=1)
        Project.objects.create(organization=a, name="沒有預募", start_date=self.today, end_date=self.today + timedelta(days=3))
        rows = home.ending_campaigns()
        self.assertEqual([r["name"] for r in rows], ["今天截止", "快截止"])
        self.assertEqual(rows[1]["days_left"], 2)
        a.refresh_from_db()  # 揭露層級在存專案時會自動重算
        self.assertEqual((rows[1]["project_id"], rows[1]["org_level"]), (soon.external_id, a.disclosure_level))

    def test_latest_penalties(self):
        a = self.org("10000001", "甲協會")
        Penalty.objects.create(organization=a, decided_on=date(2024, 1, 1), reason="未開立收據", fine_text="罰鍰：4萬元")
        Penalty.objects.create(organization=a, decided_on=date(2026, 1, 1), reason="逾許可勸募活動期間", fine_text="罰鍰：2萬元")
        rows = home.latest_penalties()
        self.assertEqual([(r["decided_on"], r["kind"]) for r in rows],
                         [(date(2026, 1, 1), "超過許可期間仍在募款"), (date(2024, 1, 1), "沒有開立收據")])

    def test_company_gifts(self):
        a = self.org("10000001", "甲基金會")
        b = self.org("10000002", "乙基金會")
        p_a = self.live(a, "計畫甲")
        p_b = self.live(b, "計畫乙")
        recent = self.today - timedelta(days=10)

        def give(org, project, name, amount, days_ago=10, kind=Donor.Kind.COMPANY, hidden=False):
            donor = Donor.objects.create(name=name, kind=kind, hidden=hidden)
            Donation.objects.create(organization=org, project=project, donor=donor, donor_name=name, amount=amount,
                                    donated_on=self.today - timedelta(days=days_ago))

        give(a, p_a, "大公司股份有限公司", 500_000, days_ago=5)
        give(a, p_a, "第二家股份有限公司", 300_000, days_ago=4)  # 同一個受捐組織只列最近一筆
        give(b, p_b, "小公司股份有限公司", 99_999, days_ago=1)  # 未滿 10 萬
        give(b, p_b, "米O國際股份有限公司", 200_000, days_ago=2)  # 名字被遮
        give(b, p_b, "隱藏股份有限公司", 200_000, days_ago=3, hidden=True)
        give(b, p_b, "某某基金會", 900_000, days_ago=1, kind=Donor.Kind.GROUP)  # 不是企業
        give(b, p_b, "乙的金主股份有限公司", 150_000, days_ago=9)
        rows = home.recent_company_gifts()
        self.assertEqual([(r["donor_name"], r["org_name"]) for r in rows],
                         [("第二家股份有限公司", "甲基金會"), ("乙的金主股份有限公司", "乙基金會")])
        self.assertLess(recent, self.today)

    def test_api(self):
        r = APIClient().get("/api/home/discover").json()
        self.assertEqual(set(r), {"ending", "penalties", "gifts"})


class PickBase(Base):
    def setUp(self):
        super().setUp()
        AnnualFundraising.objects.all().delete()

    def raised(self, org, amount=1000):
        AnnualFundraising.objects.create(organization=org, year=self.since, raised=amount, target=1)

    def picks(self, **params):
        return home.field_picks(params)


class PicksTests(PickBase):
    def test_rules_and_order(self):
        by_name = self.org("10000001", "台南市流浪動物協會", level=2)  # 名稱看得出是動保
        official = self.org("10000002", "某某基金會", purposes="動物保護事業", level=2)  # 官方勸募用途
        penalized = self.org("10000003", "高雄市流浪貓協會", level=2)
        no_record = self.org("10000004", "台北市流浪狗協會", level=2)  # 近 5 年沒有公益勸募紀錄
        by_project = self.org("10000005", "某某協會", level=2)  # 只有活動名稱看得出動保
        for o in (by_name, official, penalized, by_project):
            self.raised(o)
        Project.objects.create(organization=by_project, name="流浪動物救援計畫", start_date=date(self.since + 1911, 2, 1))
        Penalty.objects.create(organization=penalized, decided_on=self.today - timedelta(days=30))
        categorize()
        r = self.picks(field="animal")
        self.assertEqual(r["label"], "動物保護")
        self.assertEqual([o["ubn"] for o in r["orgs"]], [by_name.ubn, official.ubn])
        self.assertNotIn(no_record.ubn, [o["ubn"] for o in r["orgs"]])

    def test_campaign_must_match_field(self):
        org = self.org("10000001", "台南市流浪動物協會")
        self.raised(org)
        self.live(org, "長者送餐計畫", days=3, category="社會福利事業/社會慈善事業")
        categorize()
        self.assertIsNone(self.picks(field="animal")["orgs"][0]["campaign"])
        p = self.live(org, "浪浪醫療計畫", days=20, category="動物保護事業")
        self.assertEqual(self.picks(field="animal")["orgs"][0]["campaign"]["project_id"], p.external_id)

    def test_other_filters_apply(self):
        tn = self.org("10000001", "台南市流浪動物協會", city="臺南市")
        tp = self.org("10000002", "台北市流浪動物協會", city="臺北市")
        self.raised(tn)
        self.raised(tp)
        categorize()
        self.assertEqual([o["ubn"] for o in self.picks(field="animal", city="臺南市")["orgs"]], [tn.ubn])

    def test_none_and_empty(self):
        self.assertIsNone(self.picks())
        self.assertIsNone(self.picks(field="other"))
        self.assertIsNone(self.picks(field="nope"))
        r = self.picks(target="target.elderly")
        self.assertEqual((r["label"], r["orgs"]), ("長者", []))

    def test_api(self):
        self.assertEqual(APIClient().get("/api/home/picks").json(), {"picks": None})
        self.assertEqual(APIClient().get("/api/home/picks", {"target": "target.elderly"}).json()["picks"]["orgs"], [])

    def test_project_anchor_in_org_detail(self):
        org = self.org("10000001", "甲協會")
        self.live(org, "計畫", external_id="555")
        projects = APIClient().get(f"/api/orgs/{org.ubn}").json()["projects"]
        self.assertEqual(projects[0]["external_id"], "555")


class PickCardTests(PickBase):
    """推薦卡的四行資料（LK-52）。"""

    def test_purpose_older_penalties_and_sources(self):
        org = self.org("10000001", "台南市流浪動物協會")
        self.raised(org, 5000)
        Project.objects.create(organization=org, name="舊的結紮計畫", external_id="old", start_date=date(2020, 1, 1))
        Project.objects.create(organization=org, name="最近的送養計畫", external_id="new", start_date=self.today - timedelta(days=400))
        Project.objects.create(organization=org, name="集資", external_id="cf", channel=Project.Channel.CROWDFUNDING,
                               start_date=self.today - timedelta(days=10))
        Penalty.objects.create(organization=org, decided_on=self.today - timedelta(days=365 * 7))
        Penalty.objects.create(organization=org, decided_on=None)
        categorize()
        r = self.picks(field="animal")
        card = r["orgs"][0]
        self.assertIsNone(card["campaign"])
        self.assertEqual((card["latest_project"]["project_id"], card["latest_project"]["name"]), ("new", "最近的送養計畫"))
        self.assertEqual(card["older_penalties"], 2)
        self.assertEqual(card["raised_5y"], 5000)
        self.assertEqual(r["penalty_sources"], ["衛福部", "環境部", "勞動部", "工程會"])

    def test_live_campaign_wins(self):
        org = self.org("10000001", "台南市流浪動物協會")
        self.raised(org)
        self.live(org, "浪浪醫療計畫", category="動物保護事業")
        categorize()
        card = self.picks(field="animal")["orgs"][0]
        self.assertEqual(card["campaign"]["name"], "浪浪醫療計畫")
        self.assertIsNone(card["latest_project"])
        self.assertEqual(card["older_penalties"], 0)

    def test_no_project_at_all(self):
        org = self.org("10000001", "某某基金會", purposes="動物保護事業")
        self.raised(org)
        categorize()
        card = self.picks(field="animal")["orgs"][0]
        self.assertIsNone(card["campaign"])
        self.assertIsNone(card["latest_project"])


class GuideTests(PickBase):
    """首頁引導模式（LK-51）：所有公益大類一次回，0 個的大類另列，結果快取。"""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()

    def test_fields_and_empty(self):
        animal = self.org("10000001", "台南市流浪動物協會")
        edu = self.org("10000002", "某某文教基金會")
        for o in (animal, edu):
            self.raised(o)
        for i in range(4):
            o = self.org(f"2000000{i}", f"第{i}流浪貓協會")
            self.raised(o)
        categorize()
        r = home.guide()
        codes = [f["code"] for f in r["fields"]]
        self.assertIn("animal", codes)
        self.assertIn("education", codes)
        self.assertNotIn("other", codes + [e["code"] for e in r["empty"]])
        animal_row = next(f for f in r["fields"] if f["code"] == "animal")
        self.assertEqual((animal_row["label"], len(animal_row["orgs"]), animal_row["count"]), ("動物保護", 3, 5))
        self.assertIn({"code": "international", "label": "國際援助"}, r["empty"])
        self.assertEqual(len(r["fields"]) + len(r["empty"]), 8)  # 非公益類不列

    def test_cached_until_data_changes(self):
        org = self.org("10000001", "台南市流浪動物協會", level=2)
        self.raised(org)
        categorize()
        home.guide()
        with self.assertNumQueries(3):  # 只剩算資料摘要那三支
            home.guide()
        Penalty.objects.create(organization=org, decided_on=self.today - timedelta(days=3))  # 新的裁罰 → 不再推薦
        self.assertNotIn("animal", [f["code"] for f in home.guide()["fields"]])

    def test_recompute_invalidates(self):
        a = self.org("10000001", "台南市流浪動物協會", level=1)
        b = self.org("10000002", "台北市流浪動物協會", level=1)
        for o in (a, b):
            self.raised(o)
        categorize()
        Organization.objects.filter(pk=b.pk).update(disclosure_level=3)  # 像 recompute_scores 用 bulk_update 改層級
        first = [o["ubn"] for o in next(f for f in home.guide()["fields"] if f["code"] == "animal")["orgs"]]
        self.assertEqual(first[0], b.ubn)
        Organization.objects.filter(pk=a.pk).update(disclosure_level=4)
        again = [o["ubn"] for o in next(f for f in home.guide()["fields"] if f["code"] == "animal")["orgs"]]
        self.assertEqual(again[0], a.ubn)

    def test_api(self):
        r = APIClient().get("/api/home/guide").json()
        self.assertEqual(set(r), {"penalty_sources", "fields", "empty"})
