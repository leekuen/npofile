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


class OtherAgencyFormatTests(unittest.TestCase):
    """LK-24：勞動部的表（全形括號、文字日期、Big5、沒有項次欄）。"""

    def test_esf_big5_fullwidth_and_text_dates(self):
        rows = list(grants.rows_from_table(table("grants_esf_big5.csv")))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["agency"], "勞動部")
        self.assertEqual(rows[0]["recipient"], "財團法人瑪利亞社會福利基金會")
        self.assertEqual(rows[0]["approved_on"], date(2025, 1, 15))
        self.assertEqual(rows[0]["amount"], 3650000)

    def test_table_without_seq_or_agency_columns(self):
        rows = list(grants.rows_from_table(table("grants_no_seq.csv")))
        self.assertEqual([r["recipient"] for r in rows], ["就業安定基金", "財團法人瑪利亞社會福利基金會"])
        self.assertEqual(rows[1]["agency"], "")
        f = grants.GrantFile(114, 4, "CSV", "x", 143623)
        items = list(grants.to_items(f, rows, grants.OrgMatcher(ORGS), agency="勞動部勞動力發展署"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].data["agency"], "勞動部勞動力發展署")
        self.assertEqual(items[0].source_url, "https://data.gov.tw/dataset/143623")

    def test_esf_titles_have_no_title_filter_and_short_year(self):
        dist = [
            {"resourceDescription": f"114第{q}季就業安定基金對民間團體及個人之補(捐)助情形季報表",
             "resourceFormat": "CSV", "resourceDownloadUrl": f"https://example.test/esf114q{q}.csv"} for q in (1, 2, 3, 4)
        ] + [
            {"resourceDescription": "115第3季就業安定基金對民間團體及個人之補(捐)助情形季報表",
             "resourceFormat": "CSV", "resourceDownloadUrl": "https://example.test/esf115q3.csv"},
            {"resourceDescription": "115第3季就業安定基金對民間團體及個人之補(捐)助情形季報表",
             "resourceFormat": "JSON", "resourceDownloadUrl": "https://example.test/esf115q3.json"},
        ]
        files = grants.pick_files(dist, since_roc=111, spec=grants.ESF)
        self.assertEqual([(f.year, f.quarter, f.url) for f in files],
                         [(115, 3, "https://example.test/esf115q3.csv"), (114, 4, "https://example.test/esf114q4.csv")])
        self.assertTrue(all(f.dataset == grants.ESF.id for f in files))


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


LK30_ORGS = [
    ("10000001", "社團法人台中市親子閱讀協會"),
    ("10000002", "社團法人中華民國全國中小企業總會"),
    ("05557110", "財團法人瑪利亞社會福利基金會"),
    ("10000003", "雲林縣紫色姊妹協會"),
    ("10000004", "社團法人臺南市整體造型交流協會"),
    ("10000005", "財團法人原住民族文化事業基金會"),
]


class MoreAgenciesParseTests(unittest.TestCase):
    """LK-30：每個新資料集用一季真實樣本（節錄）。"""

    def items(self, name, spec, year, quarter=3):
        f = grants.GrantFile(year, quarter, "CSV" if name.endswith(".csv") else "ODS", "u", spec.id)
        return list(grants.to_items(f, grants.rows_from_table(table(name)), grants.OrgMatcher(LK30_ORGS),
                                    spec.agency, spec.prefix_re))

    def test_k12ea(self):
        rows = list(grants.rows_from_table(table("grants_k12ea_115q3.csv")))
        self.assertEqual(len(rows), 5)  # 空白列跳過；遮名的個人照讀，對組織時對不到
        self.assertEqual(rows[0]["agency"], "教育部國民及學前教育署")
        self.assertEqual(rows[0]["approved_on"], date(2026, 1, 1))
        self.assertEqual(rows[0]["amount"], 66442)
        items = self.items("grants_k12ea_115q3.csv", grants.K12EA, 115)
        self.assertEqual([(i.ubn, i.data["amount"]) for i in items], [("10000001", 60000), ("10000001", 130000)])
        self.assertTrue(all(i.source_url == "https://data.gov.tw/dataset/48670" for i in items))

    def test_wda_skips_individuals_and_strips_branch_prefix(self):
        rows = list(grants.rows_from_table(table("grants_wda_115q3.csv")))
        self.assertEqual(len(rows), 4)  # 「對個人之補(捐)助」兩列不收
        self.assertFalse(any("○" in r["recipient"] or "學員" in r["recipient"] for r in rows))
        items = self.items("grants_wda_115q3.csv", grants.WDA, 115)
        by_ubn = {i.ubn: i.data for i in items}
        self.assertEqual(set(by_ubn), {"10000002", "05557110"})
        self.assertEqual(by_ubn["10000002"]["recipient"], "社團法人中華民國全國中小企業總會")
        self.assertEqual(by_ubn["10000002"]["agency"], "勞動部勞動力發展署北基宜花金馬分署")
        self.assertEqual(by_ubn["10000002"]["approved_on"], date(2026, 5, 27))
        self.assertEqual(by_ubn["05557110"]["agency"], "勞動部勞動力發展署")

    def test_nidf_big5_dot_dates_and_relay_suffix(self):
        rows = list(grants.rows_from_table(table("grants_nidf_115q2_big5.csv")))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["approved_on"], date(2025, 9, 16))
        self.assertEqual(rows[0]["amount"], 1230523)
        items = self.items("grants_nidf_115q2_big5.csv", grants.NIDF, 115, 2)
        # 「（雲林縣政府層轉）」這種結尾括號拿掉再對
        self.assertEqual(sorted(i.ubn for i in items), ["10000003", "10000004"])
        self.assertTrue(all(i.data["agency"] == "新住民發展基金" for i in items))

    def test_oac_ods_skips_subtotal_rows(self):
        rows = list(grants.rows_from_table(table("grants_oac_115q3.ods")))
        self.assertEqual([r["recipient"] for r in rows],
                         ["財團法人吳三連台灣史料基金會", "財團法人原住民族文化事業基金會", "退休人員"])
        self.assertEqual(rows[1]["approved_on"], date(2026, 6, 3))
        items = self.items("grants_oac_115q3.ods", grants.OAC, 115)
        self.assertEqual([(i.ubn, i.data["amount"]) for i in items], [("10000005", 1000000)])


class MoreAgenciesPickTests(unittest.TestCase):
    def test_k12ea_only_cumulative_summary_tables(self):
        dist = [
            {"resourceDescription": f"教育部國民及學前教育署{y}年度截至第{q}季止對民間團體補(捐)助經費彙總表",
             "resourceFormat": "CSV", "resourceDownloadUrl": f"https://example.test/k{y}q{q}.csv"}
            for y in (114, 115) for q in (1, 2, 3, 4) if (y, q) != (115, 4)
        ] + [{"resourceDescription": "教育部國民及學前教育署 110年度第4季對民間團體及個人補(捐)助項目執行情形表",
              "resourceFormat": "CSV", "resourceDownloadUrl": "https://example.test/k110.csv"}]
        files = grants.pick_files(dist, since_roc=110, spec=grants.K12EA)
        self.assertEqual([(f.year, f.quarter) for f in files], [(115, 3), (114, 4)])

    def test_wda_keeps_one_file_per_budget_kind(self):
        t = "{y}年第{q}季勞動部勞動力發展署及所屬{b}對民間團體及個人補(捐)助經費季報表{x}"
        dist = [
            {"resourceDescription": t.format(y=115, q=q, b=b, x=x), "resourceFormat": "CSV",
             "resourceDownloadUrl": f"https://example.test/{q}{b}{x}.csv"}
            for q, b, x in [(2, "公務預算", ""), (3, "公務預算", ""), (2, "特別預算", ""), (3, "特別預算", ""),
                            (2, "特別預算", "(經濟部產業發展署核定)")]
        ] + [{"resourceDescription": t.format(y=115, q=3, b="公務預算", x=""), "resourceFormat": "JSON",
              "resourceDownloadUrl": "https://example.test/x.json"}]
        files = grants.pick_files(dist, since_roc=111, spec=grants.WDA)
        self.assertEqual(sorted((f.quarter, f.variant) for f in files),
                         [(2, "特別預算(經濟部產業發展署核定)"), (3, "公務預算"), (3, "特別預算")])

    def test_nidf_only_individuals_and_groups(self):
        dist = [
            {"resourceDescription": f"115年獎補助經費季報表截至第2季-基金-{who}", "resourceFormat": "CSV",
             "resourceDownloadUrl": f"https://example.test/{who}.csv"} for who in ("個人及團體", "縣市政府")
        ]
        files = grants.pick_files(dist, since_roc=111, spec=grants.NIDF)
        self.assertEqual([f.url for f in files], ["https://example.test/個人及團體.csv"])

    def test_oac_index_and_page_attachment(self):
        dist = list(grants.index_distributions(table("grants_oac_index_big5.csv")))
        self.assertEqual([d["resourceFormat"] for d in dist], ["PDF", "PAGE", "PAGE"])
        files = grants.pick_files(dist, since_roc=111, spec=grants.OAC)
        self.assertEqual([(f.year, f.quarter, f.fmt) for f in files], [(115, 3, "PAGE")])  # PDF 讀不到，112 年沒有
        page = (FX / "grants_oac_page.html").read_text(encoding="utf-8")
        url, fmt = grants.page_attachment(page, files[0].url)
        self.assertEqual(fmt, "ODS")
        self.assertTrue(url.startswith("https://www.oac.gov.tw/filedownload?file=govinfo/202610141657501.ods&"))
        self.assertIsNone(grants.page_attachment("<a href='/x.pdf'>pdf</a>", files[0].url))

    def test_oac_fetch_follows_index_then_page(self):
        index_url = "https://www.oac.gov.tw/index.csv"
        page = (FX / "grants_oac_page.html").read_text(encoding="utf-8")
        page_url = ("https://www.oac.gov.tw/ch/home.jsp?id=1242&parentpath=0,684&mcustomize=multimessages_view.jsp"
                    "&dataserno=202610140004")
        ods_url = "https://www.oac.gov.tw/filedownload?file=govinfo/202610141657501.ods&filedisplay=%E6%B5%B7.ods&flag=doc"
        client = FakeClient({
            grants.DATASET_API.format(id=grants.OAC.id): {"result": {"distribution": [
                {"resourceDescription": "本會主管預算對民間團體及個人補(捐)助經費彙總表", "resourceFormat": "CSV",
                 "resourceDownloadUrl": index_url}]}},
            index_url: (FX / "grants_oac_index_big5.csv").read_bytes(),
            page_url: page.encode("utf-8"),
            ods_url: (FX / "grants_oac_115q3.ods").read_bytes(),
        })
        items = list(grants.fetcher(grants.OAC)(client, since_roc=111, orgs=LK30_ORGS))
        self.assertEqual([(i.ubn, i.data["year"], i.data["quarter"]) for i in items], [("10000005", 115, 3)])
        self.assertEqual(items[0].source_url, "https://data.gov.tw/dataset/139265")


if __name__ == "__main__":
    unittest.main()
