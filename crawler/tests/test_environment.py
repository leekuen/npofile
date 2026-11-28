"""LK-36 環境部列管事業污染源裁處：欄位對照、只收名冊裡的統編、個人資料不存、翻頁與只抓新的。"""

import json
import unittest
from datetime import date
from pathlib import Path

from npofile_crawler import environment

FX = Path(__file__).parent / "fixtures"
SAMPLE = json.loads((FX / "moenv_penalties_sample.json").read_text(encoding="utf-8"))

ORGS = [("06479492", "財團法人私立長榮大學"), ("12345678", "財團法人台灣環境測試基金會")]


class FakeResponse:
    def __init__(self, body):
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class RawClient:
    """依序回固定的文字回應。"""

    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0

    def get(self, url, params=None):
        self.calls += 1
        r = FakeResponse("")
        r.text = self.texts.pop(0)
        return r


class FakeClient:
    """依 offset 回不同頁；記下送出的參數。"""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(params)
        idx = params["offset"] // environment.PAGE_SIZE
        return FakeResponse(self.pages[idx] if idx < len(self.pages) else [])


def page(rec, n, penalty_date):
    return [dict(rec, document_no=f"D-{penalty_date}-{i}", penalty_date=penalty_date) for i in range(n)]


class ToItemTests(unittest.TestCase):
    def test_field_mapping(self):
        item = environment.to_item(SAMPLE[1])
        self.assertEqual(item.kind, "penalty")
        self.assertEqual(item.ubn, "06479492")
        d = item.data
        self.assertEqual(d["category"], "environment")
        self.assertEqual(d["authority"], "臺南市政府環境保護局")
        self.assertEqual(d["decided_on"], date(2026, 9, 11))
        self.assertEqual(d["document_no"], "41-115-090090")
        self.assertEqual(d["law"], "廢棄物清理法第27條第11款")
        self.assertTrue(d["content"].startswith("違反廢棄物清理法第27條第11款；罰鍰新臺幣6000元整"))
        self.assertEqual(d["fine_text"], "罰鍰新臺幣 6,000 元")
        self.assertIn("冷卻水塔", d["reason"])
        self.assertEqual(item.source_url, environment.DATASET_PAGE)

    def test_petition_result_appended(self):
        d = environment.to_item(SAMPLE[2]).data
        self.assertTrue(d["reason"].endswith("訴願結果：訴願駁回"))
        self.assertEqual(d["fine_text"], "罰鍰新臺幣 100,000 元")

    def test_no_personal_name_or_address(self):
        payload = json.dumps([environment.to_item(r).data for r in SAMPLE[:3]], ensure_ascii=False, default=str)
        self.assertNotIn("王大明", payload)
        self.assertNotIn("某路", payload)

    def test_missing_ubn_skipped(self):
        self.assertIsNone(environment.to_item(SAMPLE[3]))

    def test_same_penalty_same_id(self):
        self.assertEqual(environment.penalty_id(SAMPLE[1]), environment.penalty_id(dict(SAMPLE[1])))
        self.assertNotEqual(environment.penalty_id(SAMPLE[1]), environment.penalty_id(SAMPLE[2]))

    def test_authority_names(self):
        self.assertEqual(environment.authority("臺北市"), "臺北市政府環境保護局")
        self.assertEqual(environment.authority("金門縣"), "金門縣環境保護局")
        self.assertEqual(environment.authority("桃環處"), "桃環處")
        self.assertEqual(environment.authority(""), "環境部")


class FetchTests(unittest.TestCase):
    def test_only_known_ubns(self):
        client = FakeClient([SAMPLE])
        listed = [0]
        items = list(environment.fetch(client, orgs=ORGS, moenv_api_key="k", listed=listed))
        self.assertEqual([i.ubn for i in items], ["06479492", "12345678"])
        self.assertEqual(listed, [4])
        self.assertEqual(client.calls[0]["api_key"], "k")
        self.assertEqual(client.calls[0]["sort"], "ImportDate desc")

    def test_full_backfill_pages_until_short_page(self):
        npo = SAMPLE[1]
        client = FakeClient([page(npo, 1000, "2026-09-01"), page(npo, 1000, "2020-01-01"), page(npo, 3, "2015-01-01")])
        items = list(environment.fetch(client, orgs=ORGS, moenv_api_key="k"))
        self.assertEqual(len(items), 2003)
        self.assertEqual([c["offset"] for c in client.calls], [0, 1000, 2000])

    def test_since_date_stops_after_old_page(self):
        npo = SAMPLE[1]
        client = FakeClient([page(npo, 1000, "2026-09-01"), page(npo, 1000, "2020-01-01"), page(npo, 1000, "2015-01-01")])
        list(environment.fetch(client, orgs=ORGS, moenv_api_key="k", since_date=date(2026, 6, 1)))
        # 第二頁整頁都早於 since_date，讀完就停，不再翻第三頁
        self.assertEqual([c["offset"] for c in client.calls], [0, 1000])

    def test_limit_counts_items(self):
        client = FakeClient([page(SAMPLE[1], 1000, "2026-09-01")])
        self.assertEqual(len(list(environment.fetch(client, limit=5, orgs=ORGS, moenv_api_key="k"))), 5)

    def test_missing_key_raises(self):
        with self.assertRaisesRegex(RuntimeError, "MOENV_API_KEY"):
            list(environment.fetch(FakeClient([]), orgs=ORGS))

    def test_control_characters_in_text(self):
        rec = dict(SAMPLE[1], openinfor="第一行\n第二行\t結尾")
        # 真實回應的字串裡直接夾著換行、tab（不是 \n 跳脫），標準 JSON 解析會拒絕
        raw = json.dumps([rec], ensure_ascii=False).replace("\\n", "\n").replace("\\t", "\t")
        items = list(environment.fetch(RawClient([raw]), orgs=ORGS, moenv_api_key="k"))
        self.assertEqual(items[0].data["reason"], "第一行\n第二行\t結尾")

    def test_truncated_page_retried(self):
        good = json.dumps([SAMPLE[1]], ensure_ascii=False)
        client = RawClient([good[: len(good) // 2], good])
        self.assertEqual(len(list(environment.fetch(client, orgs=ORGS, moenv_api_key="k"))), 1)
        self.assertEqual(client.calls, 2)

    def test_bad_key_response_raises(self):
        with self.assertRaisesRegex(RuntimeError, "api_key 不存在"):
            list(environment.fetch(FakeClient(["api_key 不存在。"]), orgs=ORGS, moenv_api_key="bad"))


if __name__ == "__main__":
    unittest.main()
