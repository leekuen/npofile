"""LK-41 工程會拒絕往來廠商：只收站上組織、類別 procurement、重跑不重複、個資不存、到期消失不刪、API 看得到停權期間。"""

import json
from datetime import date
from pathlib import Path

from django.test import TestCase
from npofile_crawler import procurement

from crawling.ingest import ensure_sources, run_source
from crawling.models import CrawlerSource, CrawlRecord
from orgs.models import Organization, Penalty

FX = Path(__file__).resolve().parents[3] / "crawler" / "tests" / "fixtures"
PAYLOAD = json.loads((FX / "pcc_debarment_sample.json").read_text(encoding="utf-8"))
ROWS = PAYLOAD["Rvlmd_List"]["Rvlmd"]


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, body):
        self.body = body

    def get(self, url, **kwargs):
        return FakeResponse(self.body)

    def close(self):
        pass


def payload(rows):
    return {"Rvlmd_List": {"Rvlmd": rows}}


class ProcurementIngestTests(TestCase):
    def setUp(self):
        ensure_sources()
        self.source = CrawlerSource.objects.get(key="pcc_debarment")
        self.org = Organization.objects.create(ubn="30147375", name="社團法人中華美容技藝促進協會附設職業訓練中心")
        self.org2 = Organization.objects.create(ubn="39952863", name="社團法人中華髮學苑交流協會")

    def run_with(self, body=PAYLOAD):
        return run_source(self.source, client=FakeClient(body), min_interval=0)

    def test_applied_only_known_orgs(self):
        run = self.run_with()
        self.assertEqual((run.fetched, run.created, run.applied, run.pending), (2, 2, 2, 0))
        p = Penalty.objects.get(organization=self.org)
        self.assertEqual(p.category, "procurement")
        self.assertEqual(p.law, "政府採購法第101條第1項第4款")
        self.assertEqual(p.decided_on, date(2026, 4, 9))
        self.assertEqual(p.source_name, procurement.SOURCE_NAME)
        self.assertIn("115/04/09～118/04/08", p.content)
        # 公司行號、個人（統編不在名冊）不存、不進審核清單
        self.assertEqual(CrawlRecord.objects.filter(source=self.source).count(), 2)

    def test_rerun_no_duplicates(self):
        self.run_with()
        run = self.run_with()
        self.assertEqual(run.created, 0)
        self.assertEqual(Penalty.objects.count(), 2)

    def test_expired_entry_kept(self):
        self.run_with()
        self.run_with(payload(ROWS[1:]))  # 第一筆到期、從名單消失
        self.assertTrue(Penalty.objects.filter(organization=self.org).exists())

    def test_no_personal_data(self):
        self.run_with()
        stored = str(list(CrawlRecord.objects.values_list("payload", flat=True))) + str(
            list(Penalty.objects.values_list("content", "reason", "authority", "law", "document_no")))
        for secret in ("王大明", "A1234", "李聯絡", "1234-5678", "某路"):
            self.assertNotIn(secret, stored)

    def test_api_shows_category_and_period(self):
        self.run_with()
        data = self.client.get("/api/orgs/30147375").json()
        [p] = data["penalties"]
        self.assertEqual(p["category"], "procurement")
        self.assertIn("停權 3年（115/04/09～118/04/08）", p["content"])
