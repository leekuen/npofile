"""衛福部社家署 全國性社福財團法人年度決算（LK-25）。

fixtures 是 2026-11-27 從網站下載的真實「年度決算總表」（114 年度）：
芥菜種會（A0001，金額大、有附屬作業組織另一張收支餘絀表）、鄒梅基金會（A0016，捐贈收入為 0）。
"""

import json
import unittest
from pathlib import Path

from npofile_crawler import swft

FX = Path(__file__).parent / "fixtures"


class ParseSettlementTests(unittest.TestCase):
    def test_reads_donation_and_total_for_both_years(self):
        r = swft.parse_settlement((FX / "swft_settlement_A0001_114.pdf").read_bytes())
        self.assertEqual(r[114], {"donation": 691_692_839, "income_total": 925_529_528})
        self.assertEqual(r[113], {"donation": 466_227_543, "income_total": 667_373_978})

    def test_zero_donation_is_zero_not_missing(self):
        r = swft.parse_settlement((FX / "swft_settlement_A0016_114.pdf").read_bytes())
        self.assertEqual(r[114], {"donation": 0, "income_total": 1_912_111})

    def test_not_a_settlement_pdf(self):
        self.assertEqual(swft.parse_settlement(b"%PDF-1.4\n%%EOF"), {})


class FakeResponse:
    def __init__(self, payload=None, content=b""):
        self._payload, self.content = payload, content

    def json(self):
        return self._payload


class FakeClient:
    """照網站的回應形狀回：兩頁清單、年度清單、年度明細、決算 PDF。"""

    def __init__(self):
        self.calls = []

    def post(self, url, json=None, **kw):
        self.calls.append(("POST", url, json))
        if url.endswith("/searchFront"):
            rows = {
                1: [{"uuid": "U1", "no": "A0001", "name": "財團法人基督教芥菜種會"},
                    {"uuid": "U2", "no": "A0099", "name": "財團法人對不到的基金會"}],
                2: [{"uuid": "U3", "no": "A0016", "name": "財團法人鄒梅基金會"}],
            }[json["page"]]
            return FakeResponse({"pagination": {"total": 3, "page": json["page"], "pageSize": 2}, "resultList": rows})
        if url.endswith("/FF0100"):
            name = {"U1": "A0001", "U3": "A0016"}[json["foundUUID"]]
            return FakeResponse(content=(FX / f"swft_settlement_{name}_114.pdf").read_bytes())
        raise AssertionError(url)

    def get(self, url, **kw):
        self.calls.append(("GET", url, None))
        if "/getYearList/" in url:
            return FakeResponse({"yearList": ["2026", "2025", "2024"], "isSuccess": True})
        if "/getDetail/" in url:
            uuid, ad = url.rsplit("/", 2)[-2:]
            if ad == "2026":  # 今年度只有預算
                return FakeResponse({"fSRSettlementReportList": [], "budgetReportList": [{}]})
            return FakeResponse({"fSRSettlementReportList": [{"uuid": f"S-{uuid}-{ad}", "foundUUID": uuid, "year": ad}]})
        raise AssertionError(url)


class FetchTests(unittest.TestCase):
    ORGS = [("10000001", "財團法人基督教芥菜種會"), ("10000016", "財團法人鄒梅基金會")]

    def run_fetch(self, **kw):
        client = FakeClient()
        return client, list(swft.fetch(client, since_roc=113, orgs=self.ORGS, **kw))

    def test_one_item_per_matched_foundation_and_year(self):
        _, items = self.run_fetch()
        self.assertEqual([(i.ubn, i.external_id) for i in items],
                         [("10000001", "A0001-114"), ("10000001", "A0001-113"),
                          ("10000016", "A0016-114"), ("10000016", "A0016-113")])
        first = items[0]
        self.assertEqual(first.kind, "financial")
        self.assertEqual(first.data["year"], 114)
        self.assertEqual(first.data["donation"], 691_692_839)
        self.assertEqual(first.data["filer_no"], "A0001")
        json.dumps(first.payload())  # 能存成 JSON

    def test_year_not_in_its_own_pdf_is_left_empty(self):
        # 假的 113 年度也回 114 年度的 PDF：113 年那欄是前一年，只取「自己年度」那欄就對得上
        _, items = self.run_fetch()
        self.assertEqual(items[1].data["donation"], 466_227_543)

    def test_skips_known_reports_and_unmatched_names(self):
        client, items = self.run_fetch(have={"A0001-114", "A0001-113"})
        self.assertEqual([i.external_id for i in items], ["A0016-114", "A0016-113"])
        self.assertFalse(any("U2" in c[1] or (c[2] or {}).get("foundUUID") == "U2" for c in client.calls))
        self.assertFalse(any(c[2] and c[2].get("foundUUID") == "U1" for c in client.calls))

    def test_limit_counts_downloaded_reports(self):
        _, items = self.run_fetch(limit=1)
        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
