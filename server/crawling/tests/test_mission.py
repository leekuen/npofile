"""組織理念（LK-54）：官網成立宗旨要審核、名冊優先、管理員改過不覆蓋、只每週跑。"""

from io import StringIO
from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from npofile_crawler.items import Item

from crawling import mission_targets
from crawling.ingest import apply_records, run_source
from crawling.models import CrawlerSource, CrawlRecord, OrgMissionCheck
from orgs import mission as org_mission
from orgs.admin import OrgMissionAdmin
from orgs.models import Organization, OrgMission, RegistryEntry

UBN = "00968297"
TEXT = "本會以協助自閉症者及其家庭為宗旨，提供早期療育與家庭支持。我們相信每個人都有位置。"


def item(text=TEXT, summary="陪伴自閉症者與家庭", method="claude", ubn=UBN):
    return Item("mission", ubn, {"text": text, "summary": summary, "summary_method": method,
                                 "page_url": "https://npo.example.org/about"},
                source_url="https://npo.example.org/about", external_id="mission")


class MissionIngestTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="orgsite_mission")
        self.org = Organization.objects.create(ubn=UBN, name="財團法人自閉症基金會", website="https://npo.example.org/")

    def approve_all(self):
        return apply_records(list(CrawlRecord.objects.filter(status=CrawlRecord.Status.PENDING)), CrawlRecord.Status.APPROVED)

    def test_waits_for_review_then_shown(self):
        self.assertFalse(self.source.auto_approve)
        run = run_source(self.source, items=[item()])
        self.assertEqual((run.created, run.pending, run.applied), (1, 1, 0))
        self.assertIsNone(self.client.get(f"/api/orgs/{UBN}").json()["mission"])

        self.assertEqual(self.approve_all(), (1, 0))
        m = self.client.get(f"/api/orgs/{UBN}").json()["mission"]
        self.assertEqual(m["summary"], "陪伴自閉症者與家庭")
        self.assertEqual(m["text"], TEXT)
        self.assertEqual((m["origin"], m["origin_label"], m["summary_method"]), ("website", "組織官網", "claude"))
        self.assertTrue(m["summarized_by_site"])
        self.assertEqual(m["source_url"], "https://npo.example.org/about")
        self.assertIsNotNone(m["fetched_on"])

    def test_registry_purpose_wins_over_website(self):
        run_source(self.source, items=[item()])
        self.approve_all()
        RegistryEntry.objects.create(organization=self.org, source_name="教育部", external_id="1", authority="教育部",
                                     registry_name=self.org.name, purpose="推動特殊教育。辦理研習。")
        m = self.client.get(f"/api/orgs/{UBN}").json()["mission"]
        self.assertEqual((m["origin"], m["summary"], m["text"]), ("registry", "推動特殊教育", "推動特殊教育。辦理研習。"))
        self.assertEqual(m["origin_label"], "教育部名冊")

    def test_admin_edit_locks_and_is_not_overwritten(self):
        run_source(self.source, items=[item()])
        self.approve_all()
        m = OrgMission.objects.get()
        m.summary = "管理員改的一句話"
        admin = OrgMissionAdmin(OrgMission, AdminSite())
        form = mock.Mock(changed_data=["summary"])
        admin.save_model(RequestFactory().post("/"), m, form, True)
        m.refresh_from_db()
        self.assertEqual((m.locked, m.summary_method), (True, OrgMission.Method.MANUAL))

        run_source(self.source, items=[item(text="完全不一樣的新宗旨，照顧獨居長者。", summary="新的")])
        rec = CrawlRecord.objects.get(status=CrawlRecord.Status.PENDING)
        self.approve_all()
        rec.refresh_from_db()
        self.assertIn("管理員改過", rec.review_note)
        self.assertEqual(OrgMission.objects.get().summary, "管理員改的一句話")
        # 管理員改的也蓋過名冊
        RegistryEntry.objects.create(organization=self.org, source_name="教育部", external_id="1", authority="教育部",
                                     registry_name=self.org.name, purpose="推動特殊教育。")
        api = self.client.get(f"/api/orgs/{UBN}").json()["mission"]
        self.assertEqual((api["summary"], api["origin"], api["summarized_by_site"]), ("管理員改的一句話", "manual", False))

    def test_new_text_replaces_old_after_review(self):
        run_source(self.source, items=[item()])
        self.approve_all()
        run_source(self.source, items=[item(text="新宗旨：照顧獨居長者。", summary="照顧獨居長者", method="first_sentence")])
        self.approve_all()
        m = OrgMission.objects.get()
        self.assertEqual((m.summary, m.summary_method), ("照顧獨居長者", "first_sentence"))

    def test_bulk_summaries_for_cards(self):
        other = Organization.objects.create(ubn="12345678", name="某協會")
        none = Organization.objects.create(ubn="87654321", name="沒有理念的協會")
        run_source(self.source, items=[item()])
        self.approve_all()
        RegistryEntry.objects.create(organization=other, source_name="教育部", external_id="2", authority="教育部",
                                     registry_name="某協會", purpose="推廣閱讀。")
        with self.assertNumQueries(2):
            out = org_mission.summaries([self.org.id, other.id, none.id])
        self.assertEqual(out[self.org.id]["summary"], "陪伴自閉症者與家庭")
        self.assertEqual(out[other.id]["summary"], "推廣閱讀")
        self.assertNotIn(none.id, out)


class MissionTargetTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="orgsite_mission")

    def test_only_orgs_without_registry_purpose_or_admin_edit(self):
        plain = Organization.objects.create(ubn="11111111", name="甲", website="https://a.example.org/")
        reg = Organization.objects.create(ubn="22222222", name="乙", website="https://b.example.org/")
        RegistryEntry.objects.create(organization=reg, source_name="教育部", external_id="1", authority="教育部",
                                     registry_name="乙", purpose="推動教育。")
        empty_reg = Organization.objects.create(ubn="33333333", name="丙", website="https://c.example.org/")
        RegistryEntry.objects.create(organization=empty_reg, source_name="教育部", external_id="2", authority="教育部",
                                     registry_name="丙", purpose="")
        locked = Organization.objects.create(ubn="44444444", name="丁", website="https://d.example.org/")
        OrgMission.objects.create(organization=locked, text="x", summary="x", locked=True)
        Organization.objects.create(ubn="55555555", name="戊", website="https://www.facebook.com/x")
        Organization.objects.create(ubn="66666666", name="己")
        got = [t[0] for t in mission_targets.targets()]
        self.assertEqual(sorted(got), ["11111111", "33333333"])
        self.assertEqual(set(OrgMissionCheck.objects.values_list("ubn", flat=True)), {"11111111", "33333333"})
        self.assertEqual(next(mission_targets.targets())[:2], ("11111111", plain.name))

    def test_least_recently_checked_first(self):
        Organization.objects.create(ubn="11111111", name="甲", website="https://a.example.org/")
        Organization.objects.create(ubn="22222222", name="乙", website="https://b.example.org/")
        first = next(mission_targets.targets())[0]
        second = next(mission_targets.targets())[0]
        self.assertNotEqual(first, second)

    @override_settings(ANTHROPIC_API_KEY="")
    def test_no_key_no_summarizer(self):
        self.assertIsNone(mission_targets.summarizer())

    def test_seen_hashes_latest_text(self):
        run_source(self.source, items=[item()])
        from npofile_crawler import mission

        self.assertEqual(mission_targets.seen(self.source), {UBN: mission.text_hash(TEXT)})


class MissionScheduleTests(TestCase):
    def test_crawl_all_skips_weekly_source(self):
        CrawlerSource.objects.exclude(key="orgsite_mission").update(enabled=False)
        out = StringIO()
        with mock.patch("crawling.management.commands.crawl.run_source") as run:
            call_command("crawl", "all", stdout=out)
        run.assert_not_called()
        self.assertIn("另外排程", out.getvalue())

    def test_named_run_works(self):
        with mock.patch("crawling.management.commands.crawl.run_source") as run:
            run.return_value = mock.Mock(status="success", Status=mock.Mock(SUCCESS="success"), fetched=1, note="",
                                         error="", listed_cards=None, get_status_display=lambda: "完成",
                                         created=0, applied=0, pending=0, failed=0)
            call_command("crawl", "orgsite_mission", stdout=StringIO())
        run.assert_called_once()
