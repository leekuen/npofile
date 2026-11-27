import json
import unittest
from datetime import date
from pathlib import Path

import httpx

from npofile_crawler import labor
from npofile_crawler.grants import OrgMatcher, csv_table

FX = Path(__file__).parent / "fixtures"
SAMPLE = FX / "labor_taipei_sample.csv"

ORGS = [
    ("05557110", "財團法人瑪利亞社會福利基金會"),
    ("33333333", "詠馨長照社團法人"),
    ("44444444", "臺北好人有限公司"),  # 名冊裡有這個名字：名稱不像非營利組織也收
]


def rows():
    return list(labor.rows_from_table(csv_table(SAMPLE.read_bytes()), labor.TAIPEI))


def items():
    return list(labor.to_items(labor.TAIPEI, rows(), OrgMatcher(ORGS)))


class ParseTests(unittest.TestCase):
    def test_rows_parsed_without_responsible_person(self):
        rs = rows()
        self.assertEqual(len(rs), 8)
        r = next(r for r in rs if r["document_no"] == "北市勞動字第11560629671號")
        self.assertEqual(r["name"], "財團法人興毅社會福利慈善事業基金會")
        self.assertEqual(r["decided_on"], date(2026, 6, 10))
        self.assertEqual(r["announced_on"], date(2026, 7, 15))
        self.assertEqual(r["articles"], ["勞動基準法第38條第4項"])
        self.assertEqual(r["fine"], 20000)
        # 負責人姓名欄不讀
        self.assertNotIn("王大明", json.dumps(rs, ensure_ascii=False, default=str))

    def test_only_npo_names_or_known_orgs(self):
        names = {i.data["org_name"] for i in items()}
        self.assertEqual(names, {
            "詠馨長照社團法人附設台北市私立詠馨住宿長照機構",
            "中華民國勞工安全衛生教育協會",
            "財團法人興毅社會福利慈善事業基金會",
            "財團法人瑪利亞社會福利基金會",
            "台北 好人有限公司",
        })

    def test_matching_and_unmatched(self):
        by_name = {i.data["org_name"]: i for i in items()}
        self.assertEqual(by_name["財團法人瑪利亞社會福利基金會"].ubn, "05557110")
        self.assertEqual(by_name["詠馨長照社團法人附設台北市私立詠馨住宿長照機構"].ubn, "33333333")
        self.assertEqual(by_name["台北 好人有限公司"].ubn, "44444444")
        # 名稱像非營利組織但對不上：統編空白，等管理員指定
        self.assertEqual(by_name["財團法人興毅社會福利慈善事業基金會"].ubn, "")

    def test_item_fields(self):
        i = next(i for i in items() if i.ubn == "05557110")
        self.assertEqual(i.kind, "penalty")
        self.assertEqual(i.data["authority"], "臺北市政府勞動局")
        self.assertEqual(i.data["county"], "臺北市")
        self.assertEqual(i.data["category"], "labor")
        self.assertEqual(i.data["content"], "勞動基準法第38條第4項；勞工之特別休假，因年度終結或契約終止而未休之日數，雇主未發給工資")
        self.assertEqual(i.data["fine_text"], "罰鍰新臺幣 20,000 元")
        self.assertEqual(i.data["reason"], "訴願駁回")
        self.assertEqual(i.source_url, "https://data.gov.tw/dataset/121435")
        self.assertLessEqual(len(i.external_id), 50)

    def test_same_document_same_id_across_runs(self):
        a, b = items(), items()
        self.assertEqual([i.external_id for i in a], [i.external_id for i in b])
        self.assertEqual(len({i.external_id for i in a}), len(a))
        # 同一字號列了兩家：名稱不同就是不同筆
        dup = [r for r in rows() if r["document_no"] == "北市勞動字第10760394541號"]
        self.assertEqual(len({labor.penalty_id(labor.TAIPEI, r) for r in dup}), 2)


class FetchTests(unittest.TestCase):
    def test_fetch_reads_csv_from_dataset(self):
        meta = {"result": {"distribution": [
            {"resourceFormat": "CSV", "resourceDownloadUrl": "https://data.taipei/x.csv"},
        ]}}

        class FakeClient:
            def get(self, url):
                req = httpx.Request("GET", url)
                if "data.gov.tw" in url:
                    return httpx.Response(200, json=meta, request=req)
                return httpx.Response(200, content=SAMPLE.read_bytes(), request=req)

        client = FakeClient()
        got = list(labor.fetch(client, orgs=ORGS))
        self.assertEqual(len(got), 5)
        self.assertEqual(len(list(labor.fetch(client, limit=2, orgs=ORGS))), 2)
