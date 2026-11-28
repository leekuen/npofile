"""LK-39：上市櫃公司 ESG 彙總資料的解析。

fixture 是 2026-11-28 從證交所、櫃買中心 OpenAPI 下載的真實資料（華碩 2357、台泥 1101、茂生農經 1240），
公司基本資料的董事長、總經理、發言人、電話、電子郵件、會計師欄已拿掉。
"""

import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx

from npofile_crawler import esg
from npofile_crawler.http import PoliteClient

FX = json.loads((Path(__file__).parent / "fixtures" / "esg_sample.json").read_text(encoding="utf-8"))


def topics(market: str) -> dict[int, list[dict]]:
    suffix = "L" if market == "listed" else "O"
    return {n: FX[f"t187ap46_{suffix}_{n}"] for n in esg.TOPICS}


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.listed = {r["code"]: r for r in esg.parse_market(esg.LISTED, FX["t187ap03_L"], topics("listed"))}
        self.otc = {r["code"]: r for r in esg.parse_market(esg.OTC, FX["mopsfin_t187ap03_O"], topics("otc"))}

    def test_listed_company(self):
        asus = self.listed["2357"]
        self.assertEqual(asus["market"], "listed")
        self.assertEqual(asus["name"], "華碩電腦股份有限公司")
        self.assertEqual(asus["short_name"], "華碩")
        self.assertEqual(asus["ubn"], "23638777")
        self.assertEqual(asus["website"], "https://www.asus.com")
        self.assertEqual(asus["report_year"], 114)
        self.assertEqual(asus["published_on"], date(2026, 11, 28))
        self.assertTrue(asus["climate_governance"])
        self.assertTrue(asus["climate_strategy"])
        self.assertTrue(asus["climate_actions"])
        # 華碩轉型計畫、氣候目標兩欄是空白 → 不顯示
        self.assertEqual(asus["transition_plan"], "")
        self.assertEqual(asus["climate_targets"], "")

    def test_numbers(self):
        tcc = self.listed["1101"]
        self.assertEqual(tcc["scope1"], Decimal("41020073.6100"))
        self.assertEqual(tcc["scope1_verified"], "是")
        self.assertEqual(tcc["scope3_verified"], "否")
        self.assertEqual(tcc["renewable_ratio"], Decimal("6.5900"))
        self.assertEqual(tcc["female_manager_ratio"], Decimal("18.00"))
        # 上市的欄名後面有空白：「非擔任主管之全時員工薪資中位數(仟元/人) 」
        self.assertEqual(tcc["salary_median"], 895)

    def test_otc_english_headers_and_na(self):
        r = self.otc["1240"]
        self.assertEqual(r["market"], "otc")
        self.assertEqual(r["name"], "茂生農經股份有限公司")
        self.assertEqual(r["ubn"], "18795706")
        self.assertEqual(r["scope1"], Decimal("286.9000"))
        self.assertIsNone(r["scope3"])  # N/A
        self.assertIsNone(r["renewable_ratio"])  # N/A
        self.assertEqual(r["salary_median"], 675)
        self.assertTrue(r["climate_governance"].startswith("本公司董事會"))

    def test_no_personal_fields(self):
        for rec in [*self.listed.values(), *self.otc.values()]:
            self.assertNotIn("chairman", rec)
            for value in rec.values():
                self.assertNotIn("張安平", str(value))

    def test_company_without_esg_rows_is_skipped(self):
        only_base = esg.parse_market(esg.LISTED, FX["t187ap03_L"], {n: [] for n in esg.TOPICS})
        self.assertEqual(only_base, [])

    def test_clean_helpers(self):
        self.assertEqual(esg.clean(" N/A "), "")
        self.assertEqual(esg.clean("-"), "")
        self.assertEqual(esg.clean("CIMP6\x1c模型\r\n第二行"), "CIMP6模型\n第二行")
        self.assertIsNone(esg.number("abc"))
        self.assertEqual(esg.number("1,234.5%"), Decimal("1234.5"))
        self.assertEqual(esg.website("www.pegatroncorp.com"), "https://www.pegatroncorp.com")
        self.assertIsNone(esg.roc_date("1151399"))


class FetchTests(unittest.TestCase):
    def test_one_market_failing_does_not_stop_the_other(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if "tpex" in request.url.host:
                return httpx.Response(404)
            name = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=FX[name])

        client = PoliteClient(min_interval=0, retries=0)
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        results = dict((m.key, r) for m, r in esg.fetch(client))
        self.assertEqual({r["code"] for r in results["listed"]}, {"2357", "1101"})
        self.assertIsInstance(results["otc"], Exception)


if __name__ == "__main__":
    unittest.main()
