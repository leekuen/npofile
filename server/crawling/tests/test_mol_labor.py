"""LK-37 勞動部全國違反勞動法令名單：自動上架、對不上的進審核清單、前台類別、跟臺北市總表用處分字號去重、每月一次。"""

import io
import zipfile
from datetime import timedelta
from pathlib import Path

import httpx
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from npofile_crawler import labor
from npofile_crawler.grants import OrgMatcher, csv_table

from crawling.ingest import labor_docs, run_source
from crawling.models import CrawlerSource, CrawlRecord, CrawlRun
from orgs.models import Organization, Penalty

FX = Path(__file__).resolve().parents[3] / "crawler" / "tests" / "fixtures"
FAKE_OWNERS = ("王大明", "陳小華", "林一二", "李四五", "張三", "趙六", "周七")
PAGE = '<form id="searchForm"><input type="hidden" name="_csrf_token" value="tok"></form>'


def mol_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in sorted((FX / "mol_labor").glob("*.csv")):
            zf.writestr(f.name, f.read_bytes())
    return buf.getvalue()


class FakeMol:
    """假的勞動部網站：查詢頁給 token，下載回樣本 zip。"""

    def __init__(self):
        self.posts = 0

    def get(self, url, **kw):
        return httpx.Response(200, text=PAGE, request=httpx.Request("GET", url))

    def post(self, url, **kw):
        self.posts += 1
        return httpx.Response(200, content=mol_zip(), request=httpx.Request("POST", url))

    def close(self):
        pass


def taipei_items(orgs):
    rows = labor.rows_from_table(csv_table((FX / "labor_taipei_sample.csv").read_bytes()), labor.TAIPEI)
    return list(labor.to_items(labor.TAIPEI, rows, OrgMatcher(orgs)))


class MolIngestTests(TestCase):
    def setUp(self):
        self.source = CrawlerSource.objects.get(key="mol_labor")
        self.maria = Organization.objects.create(ubn="05557110", name="財團法人瑪利亞社會福利基金會")
        self.jiabao = Organization.objects.create(ubn="11111111", name="財團法人臺中市私立家寶社會福利慈善事業基金會")
        self.chengzhi = Organization.objects.create(ubn="55555555", name="財團法人誠致教育基金會")

    def test_source_registered_official_monthly(self):
        self.assertTrue(self.source.auto_approve)
        self.assertEqual(self.source.name, labor.MOL_SOURCE_NAME)

    def test_matched_auto_applied_unmatched_pending(self):
        run = run_source(self.source, client=FakeMol(), min_interval=0)
        # 9 筆：對得上 5 筆（瑪利亞 2、誠致 2、家寶 1）上架；甡光（站上沒有）、家扶、好鄰居協會 2 筆進審核清單
        self.assertEqual((run.created, run.applied, run.pending, run.failed), (9, 5, 4, 0))
        self.assertEqual(Penalty.objects.filter(organization=self.maria).count(), 2)
        p = Penalty.objects.get(organization=self.jiabao)
        self.assertEqual(p.authority, "臺中市政府勞工局")
        self.assertEqual(p.source_name, labor.MOL_SOURCE_NAME)
        fee = Penalty.objects.get(organization=self.maria, document_no="保退一字第11569911105號")
        self.assertEqual(fee.fine_text, "加徵滯納金新臺幣 251 元")
        pending = CrawlRecord.objects.filter(source=self.source, status=CrawlRecord.Status.PENDING)
        self.assertEqual(set(pending.values_list("ubn", flat=True)), {""})

    def test_rerun_no_duplicates(self):
        run_source(self.source, client=FakeMol(), min_interval=0)
        run = run_source(self.source, client=FakeMol(), min_interval=0)
        self.assertEqual(run.created, 0)
        self.assertEqual(Penalty.objects.count(), 5)

    def test_no_responsible_person_name_stored(self):
        run_source(self.source, client=FakeMol(), min_interval=0)
        stored = str(list(CrawlRecord.objects.values_list("payload", flat=True))) + str(
            list(Penalty.objects.values_list("content", "reason", "authority", "fine_text")))
        for owner in FAKE_OWNERS:
            self.assertNotIn(owner, stored)

    def test_api_category_labor(self):
        Penalty.objects.create(organization=self.maria, content="勸募裁處", source_name="衛生福利部公益勸募管理系統",
                               external_id="1")
        run_source(self.source, client=FakeMol(), min_interval=0)
        data = self.client.get("/api/orgs/05557110").json()
        self.assertEqual(sorted(p["category"] for p in data["penalties"]), ["fundraising", "labor", "labor"])


class DedupWithTaipeiTests(TestCase):
    """臺北市總表（tpe_labor）跟勞動部全國系統會列到同一張處分：先收到的算數，另一邊用處分字號跳過。"""

    def setUp(self):
        self.tpe = CrawlerSource.objects.get(key="tpe_labor")
        self.mol = CrawlerSource.objects.get(key="mol_labor")
        Organization.objects.create(ubn="05557110", name="財團法人瑪利亞社會福利基金會")
        Organization.objects.create(ubn="55555555", name="財團法人誠致教育基金會")

    def test_national_skips_documents_taipei_already_has(self):
        items = taipei_items(Organization.objects.values_list("ubn", "name"))
        # 把臺北市樣本裡瑪利亞那筆的字號改成跟勞動部樣本同一張（模擬兩邊列到同一張處分）
        target = next(i for i in items if i.ubn == "05557110")
        target.data["document_no"] = "北市勞動字第11560422191號"
        run_source(self.tpe, items=items)
        self.assertIn("北市勞動字第11560422191號", labor_docs("mol_labor"))
        self.assertNotIn("北市勞動字第11560422191號", labor_docs("tpe_labor"))  # 自己收的不算
        run = run_source(self.mol, client=FakeMol(), min_interval=0)
        self.assertEqual(run.created, 8)
        self.assertEqual(Penalty.objects.filter(document_no="北市勞動字第11560422191號").count(), 1)

    def test_all_digit_document_no_stays_text(self):
        """SQLite 取 JSON 欄位會把全是數字的字號讀成整數；去重清單要照樣是文字，臺北市重跑才不會壞（實跑抓到的錯）。"""
        Organization.objects.create(ubn="66666666", name="社團法人基隆市某某關懷協會")
        item = labor.mol_to_item({"group": "A", "unit": "基隆市", "name": "社團法人基隆市某某關懷協會",
                                  "document_no": "1150253854", "announced_on": None, "decided_on": None,
                                  "articles": [], "violations": [], "fine": 60000, "victims": None, "note": ""},
                                 "66666666")
        run_source(self.mol, items=[item])
        self.assertIn("1150253854", labor_docs("tpe_labor"))
        run = run_source(self.tpe, items=taipei_items(Organization.objects.values_list("ubn", "name")))
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)

    def test_taipei_skips_documents_national_already_has(self):
        run_source(self.mol, client=FakeMol(), min_interval=0)
        docs = labor_docs("tpe_labor")
        self.assertIn("保退一字第11569911105號", docs)
        items = list(labor.to_items(
            labor.TAIPEI,
            labor.rows_from_table(csv_table((FX / "labor_taipei_sample.csv").read_bytes()), labor.TAIPEI),
            OrgMatcher(Organization.objects.values_list("ubn", "name")),
            skip_docs=["北市勞動字第11560099999號"],
        ))
        self.assertNotIn("北市勞動字第11560099999號", {i.data["document_no"] for i in items})


class MonthlyScheduleTests(TestCase):
    def test_crawl_all_skips_within_30_days(self):
        src = CrawlerSource.objects.get(key="mol_labor")
        CrawlerSource.objects.exclude(pk=src.pk).update(enabled=False)
        CrawlRun.objects.create(source=src, status=CrawlRun.Status.SUCCESS,
                                finished_at=timezone.now() - timedelta(days=3))
        out = io.StringIO()
        call_command("crawl", "all", stdout=out)
        self.assertIn(f"每 30 天檢查一次）：{labor.MOL_SOURCE_NAME}", out.getvalue())
        self.assertEqual(CrawlRun.objects.filter(source=src).count(), 1)
