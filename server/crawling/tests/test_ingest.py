from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from npofile_crawler import fia, mohw

from crawling.ingest import run_source
from crawling.models import CrawlerSource, CrawlRecord, CrawlRun
from orgs.models import Organization, Penalty, Project

FX = Path(__file__).resolve().parents[3] / "crawler" / "tests" / "fixtures"


def read(name):
    return (FX / name).read_text(encoding="utf-8")


def mohw_items():
    return mohw.parse_group(read("group_clean.html"), mohw.GROUP_URL.format(gid="10057")) + mohw.parse_group(
        read("group_penalty.html"), mohw.GROUP_URL.format(gid="7688")
    )


class SourceSeedTests(TestCase):
    def test_sources_seeded_after_migrate(self):
        self.assertEqual(
            dict(CrawlerSource.objects.values_list("key", "auto_approve")),
            {"fia": True, "mohw": True, "mohw_activities": True, "mohw_violations": True, "wabay": False,
             "mohw_grants": True, "esf_grants": True, "k12ea_grants": True, "wda_grants": True, "nidf_grants": True,
             "oac_grants": True, "tpe_labor": True, "mol_labor": True, "orgsite": False, "judicial": True, "moe_registry": True,
             "einvoice_codes": True, "swft": True, "twnpos": False},
        )


class AutoApproveTests(TestCase):
    def setUp(self):
        self.mohw = CrawlerSource.objects.get(key="mohw")
        self.fia = CrawlerSource.objects.get(key="fia")

    def test_fia_import(self):
        run = run_source(self.fia, items=fia.parse_csv(read("fia_sample.csv")))
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)
        self.assertEqual((run.fetched, run.created, run.applied, run.pending), (7, 7, 7, 0))
        self.assertEqual(Organization.objects.count(), 7)
        self.assertEqual(Organization.objects.get(ubn="00510209").status, "cancelled")
        self.assertEqual(Organization.objects.get(ubn="00099678").disclosure_level, 0)  # 財政部名冊只有名稱、縣市：資料不足

    def test_mohw_import_writes_all_kinds(self):
        run = run_source(self.mohw, items=mohw_items())
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)
        self.assertEqual(run.failed, 0)
        org = Organization.objects.get(ubn="00570309")
        self.assertEqual(org.name, "社團法人賦格行動音樂關懷協會")
        self.assertEqual(org.annual_records.get(year=114).raised, 66358)
        self.assertGreaterEqual(org.projects.count(), 2)
        self.assertEqual(org.source_links[0]["name"], "衛生福利部公益勸募管理系統")
        self.assertGreater(org.disclosure_level, 0)  # 財政部名冊只有名稱、縣市：資料不足
        penalty = Penalty.objects.get()
        self.assertEqual(penalty.external_id, "3319306")
        self.assertTrue(penalty.source_url.endswith("/violationDetails/3319306"))

    def test_rerun_does_not_duplicate(self):
        run_source(self.mohw, items=mohw_items())
        counts = (CrawlRecord.objects.count(), Project.objects.count(), Penalty.objects.count())
        run = run_source(self.mohw, items=mohw_items())
        self.assertEqual(run.created, 0)
        self.assertEqual((CrawlRecord.objects.count(), Project.objects.count(), Penalty.objects.count()), counts)

    def test_fia_then_mohw_merges_by_ubn(self):
        Organization.objects.create(ubn="00570309", name="舊名", city="")
        run_source(self.mohw, items=mohw_items())
        self.assertEqual(Organization.objects.filter(ubn="00570309").count(), 1)
        self.assertEqual(Organization.objects.get(ubn="00570309").city, "臺北市")

    def test_locked_field_not_overwritten(self):
        Organization.objects.create(ubn="00570309", name="管理員改的名字", locked_fields=["name"])
        run_source(self.mohw, items=mohw_items())
        org = Organization.objects.get(ubn="00570309")
        self.assertEqual(org.name, "管理員改的名字")
        self.assertEqual(org.org_type, "公益性社團法人")

    def test_large_import_recomputes_in_chunks(self):
        from npofile_crawler.items import Item

        items = (Item("org", f"{i:08d}", {"name": f"組織{i}", "city": "臺北市", "status": "active"}) for i in range(1200))
        run = run_source(self.fia, items=items)
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS, run.error)
        self.assertEqual(Organization.objects.filter(disclosure_level=0).count(), 1200)

    def test_failure_is_recorded(self):
        def boom():
            yield from fia.parse_csv(read("fia_sample.csv"), limit=2)
            raise RuntimeError("連線中斷")

        run = run_source(self.fia, items=boom())
        self.assertEqual(run.status, CrawlRun.Status.FAILED)
        self.assertIn("連線中斷", run.error)
        self.assertEqual(Organization.objects.count(), 2)  # 已抓到的保留


class ManualReviewTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="mohw")
        self.source.auto_approve = False
        self.source.save()
        User = get_user_model()
        User.objects.create_superuser("admin", "admin@example.com", "pw-123456789")
        self.client.login(username="admin", password="pw-123456789")

    def _action(self, action, ids):
        return self.client.post(
            "/admin/crawling/crawlrecord/", {"action": action, "_selected_action": [str(i) for i in ids]}
        )

    def test_pending_until_approved(self):
        run = run_source(self.source, items=mohw_items())
        self.assertEqual(run.applied, 0)
        self.assertEqual(run.pending, run.created)
        self.assertFalse(Organization.objects.exists())
        self.assertEqual(self.client.get("/api/orgs/00570309").status_code, 404)

        listing = self.client.get("/admin/crawling/crawlrecord/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.context["cl"].result_count, run.created)  # 預設只列待審核

        org_ids = list(CrawlRecord.objects.filter(ubn="00570309").values_list("pk", flat=True))
        self._action("approve", org_ids)
        self.assertEqual(self.client.get("/api/orgs/00570309").status_code, 200)
        self.assertTrue(CrawlRecord.objects.filter(ubn="00570309", status="approved").exists())
        self.assertGreater(Organization.objects.get(ubn="00570309").disclosure_level, 0)  # 財政部名冊只有名稱、縣市：資料不足

        other = list(CrawlRecord.objects.filter(status="pending").values_list("pk", flat=True))
        self._action("reject", other)
        self.assertEqual(Organization.objects.count(), 1)
        self.assertEqual(CrawlRecord.objects.filter(status="rejected").count(), len(other))

    def test_child_without_org_fails_softly(self):
        run_source(self.source, items=mohw_items())
        child = CrawlRecord.objects.filter(kind="annual").first()
        self._action("approve", [child.pk])
        child.refresh_from_db()
        self.assertEqual(child.status, "pending")
        self.assertIn("找不到", child.review_note)


class CommandTests(TestCase):
    def test_unknown_source(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("crawl", "nope")

    def test_disabled_source_skipped(self):
        CrawlerSource.objects.filter(key="fia").update(enabled=False)
        call_command("crawl", "fia")
        self.assertFalse(CrawlRun.objects.exists())

    def _crawl_with(self, items):
        from dataclasses import replace
        from io import StringIO
        from unittest import mock

        from crawling import ingest

        fake = replace(ingest.SOURCES["fia"], fetch=lambda client, limit: iter(items))
        with mock.patch.dict(ingest.SOURCES, {"fia": fake}):
            call_command("crawl", "fia", stdout=StringIO(), stderr=StringIO())

    def test_zero_items_counts_as_failure(self):
        """LK-12：成功卻一筆都沒抓到＝來源網站多半改版了，結束碼要是失敗，排程才會通知。"""
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self._crawl_with([])
        self.assertEqual(CrawlRun.objects.get().status, CrawlRun.Status.SUCCESS)

    def test_items_found_is_success(self):
        items = list(fia.parse_csv(read("fia_sample.csv")))
        self._crawl_with(items)
        self.assertEqual(CrawlRun.objects.get().fetched, len(items))
