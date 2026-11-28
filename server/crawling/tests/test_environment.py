"""LK-36 裁罰分類存欄位＋環境部列管事業污染源裁處：回填、匯入、API 類別、沒金鑰略過、只抓新的。"""

import importlib
import json
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.apps import apps as global_apps
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from npofile_crawler import environment, labor

from crawling.ingest import READ_ALL_NOTE, ensure_sources, penalty_category, run_source, since_last_success
from crawling.models import CrawlerSource, CrawlRecord, CrawlRun
from orgs.models import Organization, Penalty

FX = Path(__file__).resolve().parents[3] / "crawler" / "tests" / "fixtures"
SAMPLE = json.loads((FX / "moenv_penalties_sample.json").read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, body):
        self.text = json.dumps(body, ensure_ascii=False)


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(params)
        idx = params["offset"] // environment.PAGE_SIZE
        return FakeResponse(self.pages[idx] if idx < len(self.pages) else [])

    def close(self):
        pass


class BackfillTests(TestCase):
    """0015 回填：名稱含「勞動」的來源 → labor，其他維持 fundraising。"""

    def test_backfill_by_source_name(self):
        org = Organization.objects.create(ubn="05557110", name="財團法人瑪利亞社會福利基金會")
        labor_p = Penalty.objects.create(organization=org, content="勞基法", source_name=labor.TAIPEI.source_name,
                                         category="fundraising")
        mol_p = Penalty.objects.create(organization=org, content="勞動部", category="fundraising",
                                       source_name="勞動部 違反勞動法令事業單位（雇主）查詢系統")  # LK-37 會用的那類名稱
        fund_p = Penalty.objects.create(organization=org, content="勸募", source_name="衛生福利部公益勸募管理系統")
        migration = importlib.import_module("orgs.migrations.0015_penalty_category")
        migration.backfill(global_apps, None)
        cats = dict(Penalty.objects.values_list("pk", "category"))
        self.assertEqual(cats[labor_p.pk], "labor")
        self.assertEqual(cats[mol_p.pk], "labor")
        self.assertEqual(cats[fund_p.pk], "fundraising")

    def test_category_from_item_or_source_name(self):
        self.assertEqual(penalty_category("任何來源", {"category": "environment"}), "environment")
        self.assertEqual(penalty_category(labor.TAIPEI.source_name, {}), "labor")
        self.assertEqual(penalty_category("衛生福利部公益勸募管理系統", {"category": "亂寫"}), "fundraising")


@override_settings(MOENV_API_KEY="test-key")
class EnvironmentIngestTests(TestCase):
    def setUp(self):
        ensure_sources()
        self.source = CrawlerSource.objects.get(key="moenv_penalties")
        self.cju = Organization.objects.create(ubn="06479492", name="財團法人私立長榮大學")
        self.env = Organization.objects.create(ubn="12345678", name="財團法人台灣環境測試基金會")

    def run_sample(self, pages=None):
        return run_source(self.source, client=FakeClient(pages or [SAMPLE]), min_interval=0)

    def test_applied_only_known_orgs(self):
        run = self.run_sample()
        self.assertEqual((run.fetched, run.created, run.applied, run.pending), (2, 2, 2, 0))
        self.assertEqual(run.note, READ_ALL_NOTE)
        p = Penalty.objects.get(organization=self.cju)
        self.assertEqual(p.category, "environment")
        self.assertEqual(p.law, "廢棄物清理法第27條第11款")
        self.assertEqual(p.authority, "臺南市政府環境保護局")
        self.assertEqual(p.decided_on, date(2026, 9, 11))
        self.assertEqual(p.source_name, environment.SOURCE_NAME)
        # 公司那筆（統編不在名冊）不存、不進審核清單
        self.assertEqual(CrawlRecord.objects.filter(source=self.source).count(), 2)

    def test_rerun_no_duplicates(self):
        self.run_sample()
        run = self.run_sample()
        self.assertEqual(run.created, 0)
        self.assertEqual(Penalty.objects.count(), 2)

    def test_no_personal_name_or_address(self):
        self.run_sample()
        stored = str(list(CrawlRecord.objects.values_list("payload", flat=True))) + str(
            list(Penalty.objects.values_list("content", "reason", "authority", "law")))
        self.assertNotIn("王大明", stored)
        self.assertNotIn("某路", stored)

    def test_api_category(self):
        Penalty.objects.create(organization=self.cju, content="勸募裁處", source_name="衛生福利部公益勸募管理系統",
                               external_id="1")
        self.run_sample()
        data = self.client.get("/api/orgs/06479492").json()
        cats = sorted((p["category"], p["law"]) for p in data["penalties"])
        self.assertEqual(cats, [("environment", "廢棄物清理法第27條第11款"), ("fundraising", "")])

    def test_since_last_success(self):
        self.assertIsNone(since_last_success(self.source))  # 從沒跑完：全部回補
        self.run_sample()
        self.assertEqual(since_last_success(self.source), timezone.localdate() - timedelta(days=120))

    def test_limited_run_does_not_count_as_read_all(self):
        run_source(self.source, limit=1, client=FakeClient([SAMPLE]), min_interval=0)
        self.assertIsNone(since_last_success(self.source))

    def test_incremental_run_stops_early(self):
        self.run_sample()
        old = [dict(SAMPLE[1], document_no=f"D{i}", penalty_date="2015-01-01") for i in range(environment.PAGE_SIZE)]
        client = FakeClient([old, old, old])
        run_source(self.source, client=client, min_interval=0)
        self.assertEqual(len(client.calls), 1)


class CrawlAllWithoutKeyTests(TestCase):
    @override_settings(MOENV_API_KEY="")
    def test_named_run_fails_with_reason(self):
        out, err = StringIO(), StringIO()
        with self.assertRaises(Exception):
            call_command("crawl", "moenv_penalties", stdout=out, stderr=err)
        self.assertIn("MOENV_API_KEY", out.getvalue())
        self.assertEqual(CrawlRun.objects.get().status, CrawlRun.Status.FAILED)

    @override_settings(MOENV_API_KEY="")
    def test_crawl_all_skips_without_key(self):
        ran = []

        def fake_run(source, **kw):
            ran.append(source.key)
            run = CrawlRun.objects.create(source=source, status=CrawlRun.Status.SUCCESS, fetched=1)
            run.listed_cards = None
            return run

        out = StringIO()
        with patch("crawling.management.commands.crawl.run_source", fake_run):
            call_command("crawl", "all", stdout=out, stderr=StringIO())
        self.assertNotIn("moenv_penalties", ran)
        self.assertIn("略過（沒有設定 MOENV_API_KEY）", out.getvalue())
