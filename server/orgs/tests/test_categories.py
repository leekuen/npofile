from datetime import date

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from orgs import period, taxonomy
from orgs.categorize import categorize
from orgs.models import AnnualFundraising, Donation, Donor, OrgCategory, Organization, Penalty, Project


def codes(name, purposes="", projects=None):
    return set(taxonomy.classify(name, purposes, projects))


class RuleTests(SimpleTestCase):
    def test_official_purposes(self):
        result = taxonomy.classify("某某協會", "動物保護事業、教育事業、其他經主管機關認定之事業")
        self.assertEqual(result, {"animal": "official", "education": "official"})

    def test_two_level_and_targets(self):
        self.assertTrue({"culture", "culture.ethnic", "target.indigenous"} <= codes("南投縣泰雅族原住民文化發展協會"))
        self.assertTrue({"education", "target.indigenous"} <= codes("桃園市原住民社會教育發展協會"))
        self.assertTrue({"animal", "animal.stray"} <= codes("台南市苦心流浪動物協會"))
        self.assertTrue({"welfare", "welfare.longterm"} <= codes("屏東縣長期照顧關懷協會"))
        self.assertIn("other.religion", codes("樹林區樹德宮"))
        self.assertIn("other.sports", codes("彰化縣陳氏太極拳協會"))

    def test_sub_always_brings_parent(self):
        for name in ("宜蘭縣海洋保護協會", "台北市合唱團", "中華民國罕見疾病基金會"):
            got = codes(name)
            for c in got:
                if c in taxonomy.PARENT:
                    self.assertIn(taxonomy.PARENT[c], got, (name, c))

    def test_traps(self):
        self.assertNotIn("animal.shelter", codes("臺中市少年收容中心"))  # 收容不帶動物字樣 → 不是動物收容
        self.assertNotIn("welfare.emergency", codes("社團法人台灣動物救援協會"))  # 動物救援不是急難救助
        self.assertNotIn("other.sports", codes("高雄市地球公民協會"))  # 「地球」不是球類
        self.assertNotIn("rights.civic", codes("臺中市新田橋頭土地公民俗協會"))  # 土地公＋民俗，不是公民
        self.assertNotIn("rights.civic", codes("民主進步黨桃園縣八德市黨部"))
        self.assertNotIn("other.religion", codes("故宮之友協會"))
        self.assertNotIn("environment.ocean", codes("宜蘭縣潛水協會"))
        self.assertIn("other.trade", codes("瑋懋營造有限公司勞工退休準備金監督委員會"))

    def test_project_names_are_used(self):
        self.assertIn("target.children", codes("某某協會", projects=["115年偏鄉兒童課輔計畫"]))

    def test_unknown_name_gets_nothing(self):
        self.assertEqual(codes("中華民國擊劍協會") & {c for c in taxonomy.LABELS if not c.startswith("other")}, set())


class CategorizeTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(ubn="12345678", name="南投縣泰雅族原住民文化發展協會", purposes="文化事業")

    def test_sources_and_rerun(self):
        categorize()
        rows = dict(OrgCategory.objects.values_list("code", "source"))
        self.assertEqual(rows["culture"], "official")
        self.assertEqual(rows["culture.ethnic"], "inferred")
        self.assertEqual(rows["target.indigenous"], "inferred")
        n = OrgCategory.objects.count()
        categorize()
        self.assertEqual(OrgCategory.objects.count(), n)

    def test_admin_choices_survive(self):
        categorize()
        OrgCategory.objects.filter(code="target.indigenous").update(excluded=True, source="admin")
        OrgCategory.objects.create(organization=self.org, code="target.children", source="admin")
        call_command("classify_orgs")
        self.assertTrue(OrgCategory.objects.get(code="target.indigenous").excluded)
        self.assertTrue(OrgCategory.objects.filter(code="target.children").exists())

    def test_stale_auto_rows_removed(self):
        categorize()
        self.org.name = "南投縣某某協會"
        self.org.purposes = ""
        self.org.save()
        categorize()
        self.assertFalse(OrgCategory.objects.exists())

    def test_old_projects_not_used(self):
        org = Organization.objects.create(ubn="22222222", name="某某協會")
        Project.objects.create(organization=org, name="舊的兒童計畫", start_date=date(2015, 1, 1))
        categorize(Organization.objects.filter(pk=org.pk))
        self.assertFalse(org.categories.exists())


class CategoryApiTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.a = Organization.objects.create(ubn="11111111", name="南投縣泰雅族原住民文化發展協會", city="南投縣")
        self.b = Organization.objects.create(ubn="22222222", name="桃園市原住民社會教育發展協會", city="桃園市")
        self.c = Organization.objects.create(ubn="33333333", name="台南市苦心流浪動物協會", city="臺南市")
        categorize()
        since = period.since_roc_year()
        AnnualFundraising.objects.create(organization=self.a, year=since, raised=1000, target=2000)
        AnnualFundraising.objects.create(organization=self.a, year=since - 1, raised=99999, target=1)  # 近 5 年外
        Penalty.objects.create(organization=self.a, decided_on=date.today(), content="近期")
        self.company = Donor.objects.create(name="範例股份有限公司", kind=Donor.Kind.COMPANY)
        p = Project.objects.create(organization=self.a, name="文化計畫", start_date=date(since + 1911, 3, 1))
        Donation.objects.create(organization=self.a, project=p, donor=self.company, donor_name=self.company.name, amount=500)
        p2 = Project.objects.create(organization=self.c, name="救援計畫", start_date=date(since + 1911, 3, 1))
        Donation.objects.create(organization=self.c, project=p2, donor=self.company, donor_name=self.company.name, amount=200)

    def test_filters_combine(self):
        get = lambda q: [o["ubn"] for o in self.api.get(f"/api/orgs?{q}").json()["results"]]  # noqa: E731
        self.assertEqual(get("sub=culture.ethnic&target=target.indigenous"), ["11111111"])
        self.assertEqual(get("field=education&target=target.indigenous"), ["22222222"])
        self.assertEqual(sorted(get("target=target.indigenous")), ["11111111", "22222222"])
        self.assertEqual(get("field=animal&city=臺南市"), ["33333333"])
        self.assertEqual(len(get("field=nope")), 3)  # 不認得的代號忽略

    def test_list_and_detail_tags(self):
        row = next(o for o in self.api.get("/api/orgs").json()["results"] if o["ubn"] == "11111111")
        self.assertEqual([t["label"] for t in row["tags"]][:2], ["族群文化", "原住民"])
        cats = self.api.get("/api/orgs/11111111").json()["categories"]
        self.assertEqual(cats["fields"][0]["code"], "culture")
        self.assertEqual(cats["fields"][0]["subs"][0]["code"], "culture.ethnic")
        self.assertEqual(cats["targets"][0]["label"], "原住民")

    def test_excluded_hidden_everywhere(self):
        OrgCategory.objects.filter(organization=self.c, code="animal").update(excluded=True, source="admin")
        OrgCategory.objects.filter(organization=self.c, code="animal.stray").update(excluded=True, source="admin")
        self.assertEqual(self.api.get("/api/orgs?field=animal").json()["count"], 0)
        self.assertEqual(self.api.get("/api/orgs/33333333").json()["categories"]["fields"], [])
        tree = self.api.get("/api/taxonomy").json()
        self.assertEqual(next(f for f in tree["fields"] if f["code"] == "animal")["count"], 0)

    def test_taxonomy_counts(self):
        tree = self.api.get("/api/taxonomy").json()
        culture = next(f for f in tree["fields"] if f["code"] == "culture")
        self.assertEqual(culture["count"], 1)
        self.assertEqual(next(s for s in culture["subs"] if s["code"] == "culture.ethnic")["count"], 1)
        self.assertEqual(next(t for t in tree["targets"] if t["code"] == "target.indigenous")["count"], 2)

    def test_category_overview(self):
        r = self.api.get("/api/categories/culture.ethnic").json()
        self.assertEqual((r["label"], r["parent"]["code"], r["org_count"]), ("族群文化", "culture", 1))
        self.assertEqual(r["raised_5y"], 1000)  # 近 5 年外那筆不算
        self.assertEqual(r["penalized_5y"], 1)
        self.assertEqual(r["top_raised"][0]["ubn"], "11111111")
        self.assertEqual(r["top_donors"][0]["total"], 500)
        self.assertEqual(r["penalties"][0]["org_ubn"], "11111111")
        self.assertEqual(self.api.get("/api/categories/nope").status_code, 404)
        self.assertEqual(self.api.get("/api/categories/target.indigenous").json()["org_count"], 2)

    def test_donor_field_breakdown(self):
        r = self.api.get(f"/api/donors/{self.company.pk}").json()
        rows = {f["code"]: f["total"] for f in r["fields_breakdown"]}
        self.assertEqual(rows, {"culture": 500, "animal": 200})

    def test_admin_adds_sub_with_parent(self):
        get_user_model().objects.create_superuser("admin", "admin@example.com", "pw-123456789")
        client = self.client
        client.login(username="admin", password="pw-123456789")
        org = self.b
        existing = list(org.categories.order_by("code"))
        data = {
            "ubn": org.ubn, "name": org.name, "status": "active", "org_type": "", "representative": "",
            "registered_address": "", "contact_address": "", "phone": "", "website": "", "city": org.city,
            "purposes": "", "source_links": "[]", "locked_fields": "[]",
            "categories-TOTAL_FORMS": str(len(existing) + 1), "categories-INITIAL_FORMS": str(len(existing)),
        }
        for i, c in enumerate(existing):
            data.update({f"categories-{i}-id": str(c.pk), f"categories-{i}-organization": str(org.pk),
                         f"categories-{i}-code": c.code})
        data.update({f"categories-{len(existing)}-code": "environment.forest",
                     f"categories-{len(existing)}-organization": str(org.pk)})
        for prefix in ("annual_records", "donations", "projects", "penalties"):
            data.update({f"{prefix}-TOTAL_FORMS": "0", f"{prefix}-INITIAL_FORMS": "0"})
        r = client.post(f"/admin/orgs/organization/{org.pk}/change/", data)
        self.assertEqual(r.status_code, 302, r.content[:3000])
        rows = dict(org.categories.values_list("code", "source"))
        self.assertEqual(rows["environment.forest"], "admin")
        self.assertEqual(rows["environment"], "admin")
        call_command("classify_orgs")
        self.assertIn("environment.forest", set(org.categories.values_list("code", flat=True)))
