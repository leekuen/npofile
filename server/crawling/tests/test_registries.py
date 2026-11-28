"""LK-32 主管機關名冊與發票捐贈碼：匯入、對不上的記下不顯示、管理員指定不被蓋、不動財政部欄位與分類、每月檢查。"""

import json
from dataclasses import replace
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from npofile_crawler import fia, registries
from npofile_crawler.grants import OrgMatcher

from crawling import ingest
from crawling.ingest import run_source
from crawling.models import CrawlerSource, CrawlRecord, CrawlRun
from orgs.models import CRAWLABLE_FIELDS, DonationCode, OrgCategory, Organization, RegistryEntry

FX = Path(__file__).resolve().parents[3] / "crawler" / "tests" / "fixtures"
PERSONAL = ("測試董事長", "測試執行長", "測試聯絡人", "02-0000-0000", "contact@example.test")


def moe_items(orgs):
    rows = registries.parse_moe(registries.decode_moe((FX / "moe_registry_sample.csv").read_bytes()))
    return list(registries.moe_items(rows, OrgMatcher(orgs), timezone.localdate().replace(month=9, day=23)))


def code_items():
    return list(registries.parse_einvoice((FX / "einvoice_codes_sample.csv").read_bytes().decode("utf-8-sig")))


def snapshot(org: Organization) -> dict:
    org.refresh_from_db()
    return {f: getattr(org, f) for f in (*CRAWLABLE_FIELDS, "source_links", "locked_fields")}


class RegistryIngestTests(TestCase):
    def setUp(self):
        self.moe = CrawlerSource.objects.get(key="moe_registry")
        self.codes = CrawlerSource.objects.get(key="einvoice_codes")
        self.org = Organization.objects.create(
            ubn="11111111", name="財團法人主計協進社", org_type="財團法人", representative="財政部名冊上的負責人",
            city="臺北市",
        )
        self.wish = Organization.objects.create(ubn="92000392", name="社團法人台北市喜願協會")
        self.orgs = list(Organization.objects.values_list("ubn", "name"))

    def test_moe_import_keeps_unmatched_hidden(self):
        self.assertTrue(self.moe.auto_approve)
        run = run_source(self.moe, items=moe_items(self.orgs))
        self.assertEqual(run.status, CrawlRun.Status.SUCCESS)
        self.assertEqual((run.created, run.applied, run.failed), (5, 5, 0))
        self.assertEqual(RegistryEntry.objects.count(), 5)  # 對不上的也記下
        matched = RegistryEntry.objects.get(organization=self.org)
        self.assertEqual((matched.authority, matched.status, matched.registered_assets), ("教育部", "正常", 30000000))
        self.assertEqual(RegistryEntry.objects.filter(organization__isnull=True).count(), 4)

    def test_rerun_does_not_duplicate(self):
        run_source(self.moe, items=moe_items(self.orgs))
        run = run_source(self.moe, items=moe_items(self.orgs))
        self.assertEqual(run.created, 0)
        self.assertEqual(RegistryEntry.objects.count(), 5)

    def test_admin_assignment_survives_reimport(self):
        run_source(self.moe, items=moe_items(self.orgs))
        entry = RegistryEntry.objects.get(registry_name="財團法人國防管理學院校友文教基金會")
        target = Organization.objects.create(ubn="22222222", name="財團法人國防管理學院校友文教基金會（舊名）")
        admin = get_user_model().objects.create_superuser("admin", "a@example.test", "pw")
        self.client.force_login(admin)
        url = f"/admin/orgs/registryentry/{entry.pk}/change/"
        form = self.client.get(url).context["adminform"].form
        data = {k: ("" if v is None else v) for k, v in form.initial.items()}
        data.update(organization=target.pk, org_manual="")
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", None) and resp.context["adminform"].form.errors)
        entry.refresh_from_db()
        self.assertEqual((entry.organization, entry.org_manual), (target, True))
        # 名冊更新（資產數字變了）重新匯入：數字更新、指定的組織不變
        items = moe_items(list(Organization.objects.values_list("ubn", "name")))
        for i in items:
            i.data["registered_assets"] = (i.data["registered_assets"] or 0) + 1
        run_source(self.moe, items=items)
        entry.refresh_from_db()
        self.assertEqual(entry.organization, target)
        self.assertEqual(entry.registered_assets, 7000001)

    def test_codes_match_by_ubn_at_read_time(self):
        run = run_source(self.codes, items=code_items())
        self.assertEqual((run.created, run.applied, run.failed), (4, 4, 0))
        self.assertEqual(DonationCode.objects.count(), 4)  # 統編不在名冊的也記下
        data = self.client.get("/api/orgs/92000392").json()
        self.assertEqual([(c["code"], c["short_name"]) for c in data["donation_codes"]], [("2718", "喜願協會")])
        # 組織之後才進財政部名冊：清單沒變也對得到
        Organization.objects.create(ubn="01031190", name="財團法人海棠文教基金會")
        self.assertEqual([c["code"] for c in self.client.get("/api/orgs/01031190").json()["donation_codes"]], ["1151"])

    def test_api_only_shows_matched_and_no_personal_data(self):
        run_source(self.moe, items=moe_items(self.orgs))
        run_source(self.codes, items=code_items())
        data = self.client.get("/api/orgs/11111111").json()
        self.assertEqual(len(data["registries"]), 1)
        reg = data["registries"][0]
        self.assertEqual((reg["authority"], reg["status"], reg["registered_assets"]), ("教育部", "正常", 30000000))
        self.assertEqual(data["donation_codes"], [])
        blob = json.dumps(data, ensure_ascii=False)
        for value in PERSONAL:
            self.assertNotIn(value, blob)

    def test_no_personal_data_in_database(self):
        run_source(self.moe, items=moe_items(self.orgs))
        stored = json.dumps(
            [list(CrawlRecord.objects.values_list("payload", flat=True)),
             list(RegistryEntry.objects.values())], ensure_ascii=False, default=str,
        )
        for value in PERSONAL:
            self.assertNotIn(value, stored)

    def test_org_without_registry_data_has_empty_lists(self):
        data = self.client.get("/api/orgs/92000392").json()
        self.assertEqual((data["registries"], data["donation_codes"]), ([], []))

    def test_does_not_touch_fia_fields_or_categories(self):
        OrgCategory.objects.create(organization=self.org, code="education", source=OrgCategory.Source.ADMIN)
        before_org, before_cats = snapshot(self.org), list(self.org.categories.values_list("code", "source", "excluded"))
        score = self.org.disclosure_level
        run_source(self.moe, items=moe_items(self.orgs))
        run_source(self.codes, items=code_items())
        self.assertEqual(snapshot(self.org), before_org)
        self.assertEqual(list(self.org.categories.values_list("code", "source", "excluded")), before_cats)
        self.assertEqual(Organization.objects.get(pk=self.org.pk).disclosure_level, score)

    def test_fia_rerun_keeps_registry(self):
        fia_src = CrawlerSource.objects.get(key="fia")
        fia_items = list(fia.parse_csv((FX / "fia_sample.csv").read_text(encoding="utf-8")))
        run_source(fia_src, items=fia_items)
        orgs = list(Organization.objects.values_list("ubn", "name"))
        run_source(self.moe, items=moe_items(orgs))
        run_source(self.codes, items=code_items())
        fia_orgs = Organization.objects.filter(ubn__in=[i.ubn for i in fia_items])
        before = {o.ubn: snapshot(o) for o in fia_orgs}
        regs = list(RegistryEntry.objects.values_list("external_id", "organization_id"))
        run_source(fia_src, items=list(fia.parse_csv((FX / "fia_sample.csv").read_text(encoding="utf-8"))))
        self.assertEqual({o.ubn: snapshot(o) for o in fia_orgs}, before)
        self.assertEqual(list(RegistryEntry.objects.values_list("external_id", "organization_id")), regs)
        self.assertEqual(DonationCode.objects.count(), 4)

    def test_classify_orgs_unchanged(self):
        """W3：匯入名冊後重跑 classify_orgs，分類結果跟匯入前一樣。"""
        call_command("classify_orgs", stdout=StringIO())
        before = sorted(OrgCategory.objects.values_list("organization_id", "code", "source", "excluded"))
        run_source(self.moe, items=moe_items(self.orgs))
        run_source(self.codes, items=code_items())
        call_command("classify_orgs", stdout=StringIO())
        self.assertEqual(sorted(OrgCategory.objects.values_list("organization_id", "code", "source", "excluded")), before)


class MonthlyCheckTests(TestCase):
    def _crawl(self, *args):
        calls = []

        def fake(client, limit=None, **kw):
            calls.append(1)
            return iter(code_items())

        src = replace(ingest.SOURCES["einvoice_codes"], fetch=fake, options=())
        only = CrawlerSource.objects.exclude(key="einvoice_codes")
        only.update(enabled=False)
        with mock.patch.dict(ingest.SOURCES, {"einvoice_codes": src}):
            call_command("crawl", *args, stdout=StringIO(), stderr=StringIO())
        return len(calls)

    def test_crawl_all_skips_until_30_days(self):
        self.assertEqual(self._crawl("all"), 1)
        self.assertEqual(self._crawl("all"), 0)  # 剛檢查過：略過
        self.assertEqual(self._crawl("einvoice_codes"), 1)  # 指名跑不受限
        CrawlRun.objects.update(started_at=timezone.now() - timedelta(days=31))
        self.assertEqual(self._crawl("all"), 1)

    def test_failed_run_does_not_count(self):
        self._crawl("all")
        CrawlRun.objects.update(status=CrawlRun.Status.FAILED)
        self.assertEqual(self._crawl("all"), 1)
