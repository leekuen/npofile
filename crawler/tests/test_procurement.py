"""LK-41 工程會拒絕往來廠商：統編補 0、個人跳過、民國日期、欄位對照、個資不存、只收名冊裡的統編。

樣本取自 2026-11-28 真實 JSON 的 7 筆；負責人、身分證、聯絡人、地址已換成假資料（王大明、某路），人口販運那筆的廠商也換成假名。
"""

import json
import unittest
from datetime import date
from pathlib import Path

from npofile_crawler import procurement

FX = Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((FX / "pcc_debarment_sample.json").read_text(encoding="utf-8"))
SAMPLE = PAYLOAD["Rvlmd_List"]["Rvlmd"]
NPO, NPO2, ZERO_PAD, PERSON, NO_CASE, _, MULTI = SAMPLE

ORGS = [("30147375", "社團法人中華美容技藝促進協會附設職業訓練中心"), ("39952863", "社團法人中華髮學苑交流協會"),
        ("00400570", "測試補零的組織")]


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, body):
        self.body = body
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return FakeResponse(self.body)


class UbnTests(unittest.TestCase):
    def test_number_padded(self):
        self.assertEqual(procurement.ubn(400570), "00400570")
        self.assertEqual(procurement.ubn("04423494"), "04423494")
        self.assertEqual(procurement.ubn(30147375), "30147375")

    def test_person_or_blank_skipped(self):
        for value in ("A1234*****", "", None, 0, 123456789, True):
            self.assertEqual(procurement.ubn(value), "", value)

    def test_roc_date(self):
        self.assertEqual(procurement.roc_date("1150409 00:00"), date(2026, 4, 9))
        self.assertEqual(procurement.roc_date("1181029 23:59"), date(2029, 10, 29))
        self.assertIsNone(procurement.roc_date(""))
        self.assertIsNone(procurement.roc_date("1151399 00:00"))


class ToItemTests(unittest.TestCase):
    def test_field_mapping(self):
        item = procurement.to_item(NPO)
        self.assertEqual((item.kind, item.ubn, item.source_url), ("penalty", "30147375", procurement.DATASET_PAGE))
        d = item.data
        self.assertEqual(d["category"], "procurement")
        self.assertEqual(d["decided_on"], date(2026, 4, 9))
        self.assertEqual(d["expires_on"], date(2029, 4, 8))
        self.assertEqual(d["authority"], NPO["Announce_Agency_Name"])
        self.assertEqual(d["document_no"], "nwda1130037")
        self.assertEqual(d["law"], "政府採購法第101條第1項第4款")
        # 前台看得出停權期間
        self.assertEqual(d["content"], "停權 3年（115/04/09～118/04/08）：政府採購法第 101 條第 1 項第 4 款 以虛偽不實之文件投標、訂約或履約，情節重大者")
        self.assertTrue(d["reason"].startswith("採購案：113年度第2次委託辦理失業者職業訓練"))

    def test_appeal_result_appended(self):
        d = procurement.to_item(NPO2).data
        self.assertTrue(d["reason"].endswith("異議／申訴結果：經機關通知後未於期限內提出異議"))

    def test_multiple_clauses(self):
        d = procurement.to_item(MULTI).data
        self.assertEqual(d["law"], "政府採購法第101條第1項第4款、第8款、第12款")
        self.assertIn("第 4 款 以虛偽不實之文件投標、訂約或履約，情節重大者；第 8 款 查驗或驗收不合格", d["content"])

    def test_no_case_number(self):
        self.assertEqual(procurement.to_item(NO_CASE).data["document_no"], "")

    def test_person_skipped(self):
        self.assertIsNone(procurement.to_item(PERSON))

    def test_other_law_when_no_gpa_clause(self):
        rec = dict(PERSON, Corporation_Number="12345678")
        d = procurement.to_item(rec).data
        self.assertEqual(d["law"], "人口販運防制法第41條")
        self.assertIn("依人口販運防制法 第41條", d["content"])
        self.assertIn("犯罪情形：", d["reason"])
        self.assertIn("判決字號：", d["reason"])

    def test_no_personal_data(self):
        payload = json.dumps([procurement.to_item(r).data for r in (NPO, NPO2, ZERO_PAD, NO_CASE, MULTI)],
                             ensure_ascii=False, default=str)
        for secret in ("王大明", "A1234", "李聯絡", "1234-5678", "某路"):
            self.assertNotIn(secret, payload)

    def test_same_record_same_id_distinct_cases_differ(self):
        self.assertEqual(procurement.penalty_id(NPO), procurement.penalty_id(dict(NPO)))
        other_case = dict(NO_CASE, Case_Name="另一個採購案")  # 同一家、同一天、案號都寫「無」
        self.assertNotEqual(procurement.penalty_id(NO_CASE), procurement.penalty_id(other_case))
        # 數字或字串統編算同一筆
        self.assertEqual(procurement.penalty_id(NPO), procurement.penalty_id(dict(NPO, Corporation_Number="30147375")))


class FetchTests(unittest.TestCase):
    def test_only_known_ubns(self):
        client = FakeClient(PAYLOAD)
        listed = [0]
        items = list(procurement.fetch(client, orgs=ORGS, listed=listed))
        self.assertEqual([i.ubn for i in items], ["30147375", "39952863", "00400570"])
        self.assertEqual(listed, [7])
        self.assertEqual(client.urls, [procurement.API])

    def test_limit(self):
        self.assertEqual(len(list(procurement.fetch(FakeClient(PAYLOAD), limit=1, orgs=ORGS))), 1)

    def test_single_record_object(self):
        body = {"Rvlmd_List": {"Rvlmd": NPO}}
        self.assertEqual(len(list(procurement.fetch(FakeClient(body), orgs=ORGS))), 1)

    def test_bad_format_raises(self):
        with self.assertRaisesRegex(RuntimeError, "格式不對"):
            list(procurement.fetch(FakeClient({"error": "x"}), orgs=ORGS))


if __name__ == "__main__":
    unittest.main()
