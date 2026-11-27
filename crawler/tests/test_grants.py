import json
import unittest
from datetime import date
from pathlib import Path

import httpx

from npofile_crawler import grants

FX = Path(__file__).parent / "fixtures"

ORGS = [
    ("05557110", "財團法人瑪利亞社會福利基金會"),
    ("01234567", "財團法人勵馨社會福利事業基金會"),
    ("11111111", "社團法人同名協會"),
    ("22222222", "社團法人同名協會"),
]


def table(name: str):
    data = (FX / name).read_bytes()
    return grants.csv_table(data) if name.endswith(".csv") else grants.ods_table(data)


class PickFilesTests(unittest.TestCase):
    def setUp(self):
        self.dist = json.loads((FX / "grants_dataset_distributions.json").read_text(encoding="utf-8"))

    def test_latest_quarter_per_year_within_window(self):
        files = grants.pick_files(self.dist, since_roc=111)
        self.assertEqual([(f.year, f.quarter, f.fmt) for f in files],
                         [(115, 1, "CSV"), (114, 4, "CSV"), (113, 4, "CSV"), (112, 3, "ODS"), (111, 4, "ODS")])
        # 只拿彙總表（逐筆受補助對象），不拿「補(捐)助情形季報表」或「補助地方政府情形表」
        self.assertTrue(all(grants.TITLE_RE.search(d["resourceDescription"])
                            for d in self.dist if d["resourceDownloadUrl"] in {f.url for f in files}))


class ParseTests(unittest.TestCase):
    def test_csv_rows_skip_totals_and_notes(self):
        rows = list(grants.rows_from_table(table("grants_sample.csv")))
        self.assertEqual(len(rows), 8)
        first = rows[0]
        self.assertEqual(first["agency"], "社會及家庭署")
        self.assertEqual(first["county"], "臺中市")
        self.assertEqual(first["amount"], 1200000)
        self.assertEqual(first["approved_on"], date(2025, 3, 10))
        # 一格裡有兩個核准日：記最早的，全部留在 approved_dates
        self.assertEqual(rows[1]["approved_on"], date(2025, 3, 10))
        self.assertEqual(rows[1]["approved_dates"], ["2025-03-10", "2025-09-25"])

    def test_ods_same_result_as_csv(self):
        a = list(grants.rows_from_table(table("grants_sample.csv")))
        b = list(grants.rows_from_table(table("grants_sample.ods")))
        self.assertEqual(a, b)


class MatcherTests(unittest.TestCase):
    def setUp(self):
        self.m = grants.OrgMatcher(ORGS)

    def test_exact_and_whitespace(self):
        self.assertEqual(self.m.match("財團法人瑪利亞社會福利基金會"), ("05557110", ""))
        self.assertEqual(self.m.match("財團法人  瑪利亞社會福利基金會"), ("05557110", ""))
        self.assertEqual(self.m.match("財團法人瑪利亞社會福利基金會".replace("台", "臺")), ("05557110", ""))

    def test_branch_office_and_attached_unit_go_to_parent(self):
        self.assertEqual(self.m.match("財團法人勵馨社會福利事業基金會(台中分事務所)"), ("01234567", ""))
        self.assertEqual(self.m.match("財團法人勵馨社會福利事業基金會附設台北市私立少女中途之家"),
                         ("01234567", "台北市私立少女中途之家"))

    def test_attached_unit_keeps_original_spelling(self):
        self.assertEqual(self.m.match("財團法人瑪利亞社會福利基金會附設臺中市私立瑪利亞（日照）中心"),
                         ("05557110", "臺中市私立瑪利亞（日照）中心"))

    def test_ambiguous_individual_and_unknown_are_dropped(self):
        self.assertIsNone(self.m.match("社團法人同名協會"))
        self.assertIsNone(self.m.match("個人"))
        self.assertIsNone(self.m.match("七賢脊椎外科醫院"))


class ItemTests(unittest.TestCase):
    def test_items_only_for_matched_orgs_with_stable_ids(self):
        f = grants.GrantFile(114, 4, "CSV", "https://example.test/g.csv")
        items = list(grants.to_items(f, grants.rows_from_table(table("grants_sample.csv")), grants.OrgMatcher(ORGS)))
        self.assertEqual([i.ubn for i in items], ["05557110", "05557110", "01234567", "01234567", "05557110"])
        self.assertEqual(len({i.external_id for i in items}), 5)
        self.assertEqual(items[3].data["facility"], "台北市私立少女中途之家")
        self.assertEqual(items[0].data["year"], 114)
        self.assertEqual(items[0].kind, "grant")
        # 下一季累計金額變了，同一案件編號不變
        later = dict(next(grants.rows_from_table(table("grants_sample.csv"))), amount=9_999_999)
        self.assertEqual(grants.grant_id(114, later), items[0].external_id)

    def test_same_case_twice_in_one_file_gets_sequence(self):
        f = grants.GrantFile(114, 4, "CSV", "x")
        row = next(grants.rows_from_table(table("grants_sample.csv")))
        items = list(grants.to_items(f, [row, dict(row)], grants.OrgMatcher(ORGS)))
        self.assertEqual(items[1].external_id, items[0].external_id + "-2")


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        body = self.pages[url]
        req = httpx.Request("GET", url)
        if isinstance(body, bytes):
            return httpx.Response(200, content=body, request=req)
        return httpx.Response(200, json=body, request=req)


class FetchTests(unittest.TestCase):
    def test_fetch_downloads_each_year_once(self):
        dist = [
            {"resourceDescription": "衛生福利部主管114年度截至第4季止「公務預算對民間團體及個人補(捐)助經費彙總表」.csv",
             "resourceFormat": "CSV", "resourceDownloadUrl": "https://example.test/114q4.csv"},
            {"resourceDescription": "衛生福利部主管114年度截至第2季止「公務預算對民間團體及個人補(捐)助經費彙總表」.csv",
             "resourceFormat": "CSV", "resourceDownloadUrl": "https://example.test/114q2.csv"},
            {"resourceDescription": "衛生福利部主管111年度截至第4季止「公務預算對民間團體及個人補(捐)助經費彙總表」",
             "resourceFormat": "ODS", "resourceDownloadUrl": "https://example.test/111q4.ods"},
            {"resourceDescription": "衛生福利部主管109年度截至第4季止「公務預算對民間團體及個人補(捐)助經費彙總表」",
             "resourceFormat": "ODS", "resourceDownloadUrl": "https://example.test/109q4.ods"},
        ]
        client = FakeClient({
            grants.DATASET_API.format(id=grants.DATASET_ID): {"result": {"distribution": dist}},
            "https://example.test/114q4.csv": (FX / "grants_sample.csv").read_bytes(),
            "https://example.test/111q4.ods": (FX / "grants_sample.ods").read_bytes(),
        })
        items = list(grants.fetch(client, since_roc=111, orgs=ORGS))
        self.assertEqual(sorted({i.data["year"] for i in items}), [111, 114])
        self.assertEqual(len(items), 10)
        self.assertNotIn("https://example.test/114q2.csv", client.urls)
        self.assertNotIn("https://example.test/109q4.ods", client.urls)

        limited = list(grants.fetch(FakeClient(client.pages), limit=3, since_roc=111, orgs=ORGS))
        self.assertEqual(len(limited), 3)


if __name__ == "__main__":
    unittest.main()
