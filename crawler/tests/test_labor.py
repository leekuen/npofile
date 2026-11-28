import io
import json
import unittest
import zipfile
from unittest import mock
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

    def test_fetch_skips_documents_from_other_labor_source(self):
        """臺北市總表：勞動部全國系統（LK-37）已收過的處分字號不再收。"""
        meta = {"result": {"distribution": [
            {"resourceFormat": "CSV", "resourceDownloadUrl": "https://data.taipei/x.csv"},
        ]}}

        class FakeClient:
            def get(self, url):
                req = httpx.Request("GET", url)
                if "data.gov.tw" in url:
                    return httpx.Response(200, json=meta, request=req)
                return httpx.Response(200, content=SAMPLE.read_bytes(), request=req)

        got = list(labor.fetch(FakeClient(), orgs=ORGS, labor_docs=["北市勞動字第11560629671號"]))
        self.assertEqual(len(got), 4)
        self.assertNotIn("北市勞動字第11560629671號", {i.data["document_no"] for i in got})


# ── 勞動部全國系統（LK-37）──────────────────────────────────────────────

MOL_DIR = FX / "mol_labor"
MOL_ORGS = [
    ("05557110", "財團法人瑪利亞社會福利基金會"),
    ("11111111", "財團法人臺中市私立家寶社會福利慈善事業基金會"),
    ("22222222", "財團法人桃園市私立甡光社會福利基金會"),
    ("55555555", "財團法人誠致教育基金會"),
]
FAKE_OWNERS = ("王大明", "陳小華", "林一二", "李四五", "張三", "趙六", "周七")


def mol_zip() -> bytes:
    """照下載檔的樣子包成 zip（樣本 CSV 是真實檔的格式，負責人姓名都換成假名）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in sorted(MOL_DIR.glob("*.csv")):
            zf.writestr(f.name, f.read_bytes())
    return buf.getvalue()


def mol_rows():
    return list(labor.mol_rows_from_zip(mol_zip()))


def mol_items(skip=()):
    return list(labor.mol_to_items(mol_rows(), OrgMatcher(MOL_ORGS), skip))


class MolParseTests(unittest.TestCase):
    def test_rows_from_all_five_tables(self):
        rs = mol_rows()
        self.assertEqual(len(rs), 10)
        self.assertEqual({r["group"] for r in rs}, {"A", "B", "E"})
        r = next(r for r in rs if r["document_no"] == "北市勞動字第11560422191號")
        self.assertEqual(r["name"], "財團法人誠致教育基金會")
        self.assertEqual(r["unit"], "台北市")
        self.assertEqual(r["decided_on"], date(2026, 10, 7))
        self.assertEqual(r["announced_on"], date(2026, 11, 13))
        self.assertEqual(r["articles"], ["勞動基準法第30條第6項", "勞動基準法第24條第1項"])
        self.assertEqual(r["fine"], 80000)

    def test_responsible_person_never_kept(self):
        dumped = json.dumps([mol_rows(), [i.data for i in mol_items()]], ensure_ascii=False, default=str)
        for owner in FAKE_OWNERS:
            self.assertNotIn(owner, dumped)
        # 職災發生地點（可能是住址）不讀
        self.assertNotIn("某某路", dumped)

    def test_strip_owner(self):
        self.assertEqual(labor.strip_owner("財團法人誠致教育基金會(王大明)"), "財團法人誠致教育基金會")
        self.assertEqual(labor.strip_owner("財團法人某某基金會（王大明）"), "財團法人某某基金會")
        self.assertEqual(labor.strip_owner("醫療財團法人某某醫院"), "醫療財團法人某某醫院")
        self.assertEqual(labor.strip_owner("某某中心(養護型)(王大明)"), "某某中心(養護型)")
        self.assertEqual(labor.strip_owner("李四五即財團法人某某基金會附設某某中心"), "財團法人某某基金會附設某某中心")
        # 「即」後面沒有非營利組織字樣不切
        self.assertEqual(labor.strip_owner("立即救援股份有限公司"), "立即救援股份有限公司")

    def test_strip_owner_irregular_forms_from_real_download(self):
        """2026-11-28 全量實跑時漏切的四種寫法（姓名換成假名）。"""
        # 括號裡還有括號
        self.assertEqual(labor.strip_owner("中華民國某某交流協會(王大明(解任))"), "中華民國某某交流協會")
        # 括號沒寫完
        self.assertEqual(labor.strip_owner("財團法人佛教私立某某育幼院(釋某某"), "財團法人佛教私立某某育幼院")
        # 姓名接在經營組織括號後面（有沒有空白都一樣）：括號留著，給承辦組織比對用
        self.assertEqual(labor.strip_owner("某某市立醫院(委託某某醫療社團法人經營)陳小華"),
                         "某某市立醫院(委託某某醫療社團法人經營)")
        self.assertEqual(labor.strip_owner("某某非營利幼兒園(委託社團法人某某學會辦理) 林一二"),
                         "某某非營利幼兒園(委託社團法人某某學會辦理)")
        # 括號後面接的是機構，不是姓名
        self.assertEqual(labor.strip_owner("財團法人某某基金會(臺中)附設托嬰中心"), "財團法人某某基金會(臺中)附設托嬰中心")
        self.assertEqual(labor.strip_owner("社團法人某某協會(高雄)幼兒園"), "社團法人某某協會(高雄)幼兒園")

    def test_company_names_containing_npo_words_skipped(self):
        rows = [{"group": "A", "unit": "台北市", "name": "艾協會藥聯股份有限公司", "document_no": "x1",
                 "announced_on": None, "decided_on": None, "articles": [], "violations": [], "fine": None,
                 "victims": None, "note": ""}]
        self.assertEqual(list(labor.mol_to_items(rows, OrgMatcher([]))), [])
        # 名冊裡真的有這個名字就照收
        self.assertEqual(len(list(labor.mol_to_items(rows, OrgMatcher([("12345678", "艾協會藥聯股份有限公司")])))), 1)

    def test_operator_name(self):
        self.assertEqual(labor.operator_name("某某教養院(承辦單位：財團法人某某基金會)"), "財團法人某某基金會")
        self.assertEqual(labor.operator_name("某某非營利幼兒園(委託財團法人某某基金會辦理)"), "財團法人某某基金會")
        self.assertEqual(labor.operator_name("某某中心(養護型)"), "")

    def test_authority_full_names(self):
        self.assertEqual(labor.mol_authority("台北市"), "臺北市政府勞動局")
        self.assertEqual(labor.mol_authority("高雄市"), "高雄市政府勞工局")
        self.assertEqual(labor.mol_authority("宜蘭縣"), "宜蘭縣政府")
        self.assertEqual(labor.mol_authority("台東縣"), "臺東縣政府")
        self.assertEqual(labor.mol_authority("職業安全衛生署"), "勞動部職業安全衛生署")
        self.assertEqual(labor.mol_authority("勞動部勞工保險局"), "勞動部勞工保險局")
        self.assertEqual(labor.mol_authority("新竹科學園區"), "國家科學及技術委員會新竹科學園區管理局")


class MolItemTests(unittest.TestCase):
    def test_only_npo_names_or_known_orgs(self):
        names = {i.data["org_name"] for i in mol_items()}
        self.assertNotIn("大好人有限公司", names)
        self.assertEqual(len(mol_items()), 9)

    def test_matching_rules(self):
        ubn = {i.data["document_no"]: i.ubn for i in mol_items() if i.data["document_no"] != "保退一字第11569911105號"}
        self.assertEqual(ubn["高市勞條字第11534567800號"], "05557110")
        # 括號裡寫的承辦組織
        self.assertEqual(ubn["府授勞動字第1150200000號"], "11111111")
        # 「X附設Y」算給 X（切掉「即」前面的自然人姓名後）
        self.assertEqual(ubn["府勞條字第1150100001號"], "22222222")
        # 名稱像非營利組織但對不上：統編空白，進審核清單
        self.assertEqual(ubn["勞職授字第1150285455號"], "")
        self.assertEqual(ubn["府勞資字第1150000002號"], "")

    def test_one_document_lists_several_orgs(self):
        """勞保局一張處分書列好幾個單位：同字號、不同名稱是不同筆，各自對到自己的組織。"""
        same = [i for i in mol_items() if i.data["document_no"] == "保退一字第11569911105號"]
        self.assertEqual({i.ubn for i in same}, {"05557110", "55555555"})
        self.assertEqual(len({i.external_id for i in same}), 2)

    def test_item_fields(self):
        i = next(i for i in mol_items() if i.data["document_no"] == "北市勞動字第11560422191號")
        self.assertEqual(i.kind, "penalty")
        self.assertEqual(i.ubn, "55555555")
        self.assertEqual(i.data["category"], "labor")
        self.assertEqual(i.data["authority"], "臺北市政府勞動局")
        self.assertEqual(i.data["county"], "臺北市")
        self.assertEqual(i.data["law_group"], "勞動基準法／最低工資法／性別平等工作法")
        self.assertEqual(i.data["content"], "勞動基準法第30條第6項、勞動基準法第24條第1項；"
                                            "出勤紀錄未逐日記載勞工出勤情形至分鐘為止；延長工作時間未依規定加給工資")
        self.assertEqual(i.data["fine_text"], "罰鍰新臺幣 80,000 元")
        self.assertEqual(i.source_url, "https://announcement.mol.gov.tw/")
        self.assertTrue(i.external_id.startswith("mol_labor-"))
        self.assertLessEqual(len(i.external_id), 50)
        note = next(i for i in mol_items() if i.data["document_no"] == "高市勞條字第11534567800號")
        self.assertEqual(note.data["reason"], "訴願駁回")

    def test_late_fee_labelled(self):
        i = next(i for i in mol_items() if i.ubn == "05557110" and i.data["document_no"].startswith("保退"))
        self.assertTrue(i.data["content"].startswith("加徵滯納金："))
        self.assertEqual(i.data["fine_text"], "加徵滯納金新臺幣 251 元")
        self.assertEqual(i.data["authority"], "勞動部勞工保險局")
        # 同一張表裡不是滯納金的（勞退第 15 條）照寫罰鍰
        other = next(i for i in mol_items() if i.data["document_no"] == "保退三字第11560162941號")
        self.assertEqual(other.data["fine_text"], "罰鍰新臺幣 5,000 元")

    def test_occupational_accident_victims(self):
        i = next(i for i in mol_items() if i.data["document_no"] == "勞職授字第1150285455號")
        self.assertTrue(i.data["content"].endswith("（職業災害罹災 1 人）"))
        self.assertEqual(i.data["law_group"], "職業安全衛生法")

    def test_skip_documents_already_from_taipei(self):
        got = mol_items(skip=["北市勞動字第11560422191號"])
        self.assertEqual(len(got), 8)
        self.assertNotIn("北市勞動字第11560422191號", {i.data["document_no"] for i in got})

    def test_same_ids_across_runs_and_keywords(self):
        a = mol_items()
        self.assertEqual([i.external_id for i in a], [i.external_id for i in mol_items()])
        # 兩個關鍵字查到同一批：不重複
        doubled = list(labor.mol_to_items(mol_rows() + mol_rows(), OrgMatcher(MOL_ORGS)))
        self.assertEqual(len(doubled), len(a))


class MolFetchTests(unittest.TestCase):
    PAGE = '<form id="searchForm"><input type="hidden" name="_csrf_token" value="tok123"></form>'

    def client(self, download: bytes):
        posts = []

        class FakeClient:
            def get(self, url, **kw):
                return httpx.Response(200, text=MolFetchTests.PAGE, request=httpx.Request("GET", url))

            def post(self, url, data=None, headers=None, **kw):
                posts.append((url, data, headers))
                return httpx.Response(200, content=download, request=httpx.Request("POST", url))

        return FakeClient(), posts

    def test_fetch_posts_each_keyword_with_token(self):
        client, posts = self.client(mol_zip())
        got = list(labor.fetch_mol(client, orgs=MOL_ORGS))
        self.assertEqual(len(got), 9)  # 每個關鍵字回同一份，去重後還是 9 筆
        self.assertEqual([p[1]["UNITNAME"] for p in posts], list(labor.MOL_KEYWORDS))
        url, form, headers = posts[0]
        self.assertEqual(url, "https://announcement.mol.gov.tw/Download/")
        self.assertEqual(form["_csrf_token"], "tok123")
        self.assertEqual(form["downloadType"], "3")
        self.assertEqual(headers["Referer"], "https://announcement.mol.gov.tw/")
        self.assertEqual(len(list(labor.fetch_mol(self.client(mol_zip())[0], limit=3, orgs=MOL_ORGS))), 3)

    def test_blocked_download_raises_after_retries(self):
        client, posts = self.client(b"<html>Request Rejected</html>")
        with mock.patch.object(labor.time, "sleep"), self.assertRaises(RuntimeError):
            list(labor.fetch_mol(client, orgs=MOL_ORGS))
        self.assertEqual(len(posts), 1 + labor.MOL_RETRIES)

    def test_one_bad_response_retried(self):
        """偶爾回一次 HTML：重拿 token 再送一次就好，不整批失敗。"""
        replies = [b"<html>oops</html>", mol_zip()]
        client, posts = self.client(b"")
        client.post = lambda url, data=None, headers=None, **kw: (
            posts.append(data), httpx.Response(200, content=replies.pop(0) if replies else mol_zip(),
                                               request=httpx.Request("POST", url)))[1]
        with mock.patch.object(labor.time, "sleep") as slept:
            got = list(labor.fetch_mol(client, orgs=MOL_ORGS))
        self.assertEqual(len(got), 9)
        self.assertEqual(slept.call_count, 1)
        self.assertEqual(len(posts), len(labor.MOL_KEYWORDS) + 1)
