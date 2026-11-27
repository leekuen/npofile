"""LK-05：司法院裁判書來源（判決比對組織、進待審核、撤下要刪）。"""

import json
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from npofile_crawler import judicial

from crawling import ingest
from crawling.ingest import run_source
from crawling.models import CrawlerSource, CrawlRecord, CrawlRun
from orgs.models import Organization, Penalty

FX = Path(__file__).resolve().parents[3] / "crawler" / "tests" / "fixtures" / "judicial"
JID = "TCDM,115,訴,999,20261020,1"


def load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def staff_items():
    index = judicial.NameIndex(ingest.org_names())
    return judicial.match(judicial.parse_doc(load("synthetic_staff_embezzle.json")), index)


class JudicialSourceTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="judicial")
        Organization.objects.create(ubn="22222222", name="財團法人測試兒童福利基金會")
        Organization.objects.create(ubn="72856004", name="財團法人基督教更生團契桃園市私立少年之家")
        User = get_user_model()
        User.objects.create_superuser("admin", "admin@example.com", "pw-123456789")
        self.client.login(username="admin", password="pw-123456789")

    def test_seeded_disabled_and_needs_review(self):
        self.assertFalse(self.source.enabled)
        self.assertFalse(self.source.auto_approve)

    def test_org_names_come_from_database(self):
        self.assertEqual(ingest.org_names()["財團法人測試兒童福利基金會"], "22222222")

    def test_match_goes_to_review_then_becomes_penalty(self):
        run = run_source(self.source, items=staff_items())
        self.assertEqual((run.created, run.pending, run.applied), (1, 1, 0))
        self.assertFalse(Penalty.objects.exists())

        rec = CrawlRecord.objects.get()
        self.client.post("/admin/crawling/crawlrecord/", {"action": "approve", "_selected_action": [str(rec.pk)]})
        p = Penalty.objects.get()
        self.assertEqual(p.organization.ubn, "22222222")
        self.assertEqual(p.source_name, "司法院裁判書")
        self.assertEqual(p.authority, "臺灣臺中地方法院")
        self.assertEqual(p.document_no, "115年度訴字第999號")
        self.assertEqual(p.content, "刑事判決：業務侵占（組織人員涉案）")
        self.assertEqual(str(p.decided_on), "2026-10-20")

        data = self.client.get("/api/orgs/22222222").json()
        self.assertIn("刑事判決：業務侵占（組織人員涉案）", json.dumps(data, ensure_ascii=False))

    def test_withdrawn_judgment_is_deleted_everywhere(self):
        run_source(self.source, items=staff_items())
        rec = CrawlRecord.objects.get()
        self.client.post("/admin/crawling/crawlrecord/", {"action": "approve", "_selected_action": [str(rec.pk)]})
        self.assertTrue(Penalty.objects.exists())

        run = run_source(self.source, items=[judicial.deleted_item(JID)])
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)
        self.assertFalse(Penalty.objects.exists())
        self.assertFalse(CrawlRecord.objects.exists())

    def test_withdrawn_does_not_touch_other_sources(self):
        other = Organization.objects.get(ubn="22222222")
        Penalty.objects.create(organization=other, source_name="衛生福利部公益勸募管理系統", external_id=JID, content="x")
        run_source(self.source, items=[judicial.deleted_item(JID)])
        self.assertEqual(Penalty.objects.count(), 1)

    def test_fetch_gets_names_and_credentials(self):
        seen = {}

        def fake_fetch(client, limit, org_names, judicial_credentials):
            seen.update(names=org_names, cred=judicial_credentials)
            return iter([])

        with self.settings(JUDICIAL_API_USER="u", JUDICIAL_API_PASSWORD="p"), \
                mock.patch.dict(ingest.SOURCES, {"judicial": replace(ingest.SOURCES["judicial"], fetch=fake_fetch)}):
            run_source(self.source)
        self.assertEqual(seen["cred"], ("u", "p"))
        self.assertIn("財團法人測試兒童福利基金會", seen["names"])


class JudicialCommandTests(TestCase):
    def setUp(self):
        Organization.objects.create(ubn="22222222", name="財團法人測試兒童福利基金會")

    def test_crawl_all_skips_judicial(self):
        CrawlerSource.objects.exclude(key="judicial").update(enabled=False)
        CrawlerSource.objects.filter(key="judicial").update(enabled=True)
        call_command("crawl", "all", stdout=StringIO())
        self.assertFalse(CrawlRun.objects.exists())

    def test_empty_night_is_not_a_failure(self):
        """多數晚上沒有一則判決牽涉到組織：不能讓 LK-12 的「0 筆算失敗」每天誤報。"""
        CrawlerSource.objects.filter(key="judicial").update(enabled=True)
        fake = replace(ingest.SOURCES["judicial"], fetch=lambda client, limit, **kw: iter([]))
        with mock.patch.dict(ingest.SOURCES, {"judicial": fake}):
            call_command("crawl", "judicial", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(CrawlRun.objects.get().status, CrawlRun.Status.SUCCESS)

    def test_archive_import(self):
        doc = load("synthetic_staff_embezzle.json")
        doc["JFULL"] = doc.pop("JFULLX")["JFULLCONTENT"]
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "a.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            call_command("crawl", "judicial", "--archive", tmp, "--force", stdout=StringIO())
        run = CrawlRun.objects.get()
        self.assertEqual((run.fetched, run.pending), (1, 1))
        self.assertEqual(CrawlRecord.objects.get().ubn, "22222222")

    def test_archive_only_for_judicial(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("crawl", "fia", "--archive", "x", stdout=StringIO())
