"""LK-32：教育部財團法人名冊（cp950）與電子發票捐贈碼（UTF-8 BOM）的解析。

fixtures 是 2026-11-27 下載的真實檔前幾列；董事長、執行長、聯絡人欄換成假資料（測試資料也不留真名）。
"""

import json
import unittest
from datetime import date
from pathlib import Path

import httpx

from npofile_crawler import registries
from npofile_crawler.grants import OrgMatcher
from npofile_crawler.http import PoliteClient

FX = Path(__file__).parent / "fixtures"
MOE = FX / "moe_registry_sample.csv"
CODES = FX / "einvoice_codes_sample.csv"
PERSONAL = ("測試董事長", "測試執行長", "測試聯絡人", "02-0000-0000", "contact@example.test")


class MoeParseTests(unittest.TestCase):
    def setUp(self):
        raw = MOE.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        with self.assertRaises(UnicodeDecodeError):  # 真的是 Big5，不是 UTF-8
            raw.decode("utf-8")
        self.rows = list(registries.parse_moe(registries.decode_moe(raw)))

    def test_fields(self):
        self.assertEqual(len(self.rows), 5)
        first = self.rows[0]
        self.assertEqual(first["name"], "財團法人主計協進社")
        self.assertEqual(first["authority"], "教育部")
        self.assertEqual(first["permit_no"], "台(51)高3888號")
        self.assertEqual(first["founded_on"], date(1962, 5, 3))
        self.assertEqual(first["permitted_assets"], 600000)
        self.assertEqual(first["registered_assets"], 30000000)
        self.assertEqual(first["status"], "正常")
        self.assertIn("青少年", first["service_targets"])
        self.assertIn("獎助學金", first["business_category"])
        self.assertTrue(first["purpose"])
        self.assertTrue(first["main_business"])
        self.assertEqual(self.rows[3]["status"], "解散")
        self.assertEqual(self.rows[4]["permit_no"], "")

    def test_no_personal_names_or_contacts(self):
        blob = json.dumps(self.rows, ensure_ascii=False, default=str)
        for value in PERSONAL:
            self.assertNotIn(value, blob)
        keys = set(self.rows[0])
        self.assertFalse(keys & {"chair", "ceo", "contact", "phone", "email", "address"})

    def test_items_match_by_exact_unique_name(self):
        matcher = OrgMatcher([
            ("11111111", "財團法人主計協進社"),
            ("22222222", "財團法人國防管理學院校友文教基金會"),
            ("33333333", "財團法人國防管理學院校友文教基金會"),  # 同名兩個：不連
        ])
        items = list(registries.moe_items(self.rows, matcher, date(2026, 9, 23)))
        self.assertEqual(len(items), 5)  # 對不上的也回傳（統編留空），後端記下不顯示
        self.assertEqual([i.ubn for i in items[:3]], ["11111111", "", ""])
        self.assertTrue(all(i.kind == "registry" for i in items))
        self.assertEqual(items[0].data["data_date"], date(2026, 9, 23))
        self.assertEqual(items[0].external_id, registries.registry_id("教育部", "財團法人主計協進社"))
        # 台／臺、全形括號不同仍是同一個編號
        self.assertEqual(registries.registry_id("教育部", "財團法人臺灣（測試）基金會"),
                         registries.registry_id("教育部", "財團法人台灣(測試)基金會"))
        self.assertLessEqual(len(items[0].external_id), 50)


class EinvoiceParseTests(unittest.TestCase):
    def test_utf8_bom_and_fields(self):
        raw = CODES.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        items = list(registries.parse_einvoice(raw.decode("utf-8-sig")))
        self.assertEqual(len(items), 4)
        first = items[0]
        self.assertEqual((first.kind, first.ubn, first.external_id), ("einvoice", "92000392", "2718"))
        self.assertEqual(first.data, {"code": "2718", "name": "社團法人台北市喜願協會", "short_name": "喜願協會",
                                      "county": "臺北市"})
        # 統編開頭的 0 保留；簡稱只有空白的存成空字串
        self.assertEqual(items[2].ubn, "01051934")
        self.assertEqual(items[2].data["short_name"], "")

    def test_bom_left_in_text_still_finds_header(self):
        text = CODES.read_bytes().decode("utf-8")  # 沒拿掉 BOM
        self.assertEqual(len(list(registries.parse_einvoice(text))), 4)


class FetchTests(unittest.TestCase):
    def _client(self, dataset, csv_bytes, modified="2026-09-23 15:12:45"):
        def handler(request: httpx.Request) -> httpx.Response:
            if "/api/v2/rest/dataset/" in str(request.url):
                return httpx.Response(200, json={"result": {"modifiedDate": modified, "distribution": [
                    {"resourceFormat": "CSV", "resourceDownloadUrl": "https://example.test/file.csv"}]}})
            return httpx.Response(200, content=csv_bytes)

        client = PoliteClient(min_interval=0)
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        return client

    def test_fetch_moe_uses_dataset_date(self):
        client = self._client(registries.MOE_DATASET, MOE.read_bytes())
        items = list(registries.fetch_moe(client, orgs=[("11111111", "財團法人主計協進社")]))
        self.assertEqual(len(items), 5)
        self.assertEqual(items[0].ubn, "11111111")
        self.assertEqual(items[0].data["data_date"], date(2026, 9, 23))
        self.assertEqual(len(list(registries.fetch_moe(client, limit=2))), 2)

    def test_fetch_einvoice(self):
        client = self._client(registries.EINVOICE_DATASET, CODES.read_bytes())
        self.assertEqual([i.external_id for i in registries.fetch_einvoice(client)], ["2718", "1151", "17520", "9199"])


if __name__ == "__main__":
    unittest.main()
