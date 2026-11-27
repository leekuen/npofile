import json
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from npofile_crawler import judicial

FX = Path(__file__).parent / "fixtures" / "judicial"

# 名稱照本機資料庫（財政部名冊）的寫法；兩個「測試」組織只給合成判決用
ORGS = {
    "財團法人基督教更生團契": "00985373",
    "財團法人基督教更生團契桃園市私立少年之家": "72856004",
    "財團法人桃園市樂福社會福利基金會": "11111111",
    "財團法人測試兒童福利基金會": "22222222",
    "社團法人測試動物保護協會": "33333333",
    "慈雲宮": "44444444",
}


def load(name: str):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def judgment(name: str) -> judicial.Judgment:
    j = judicial.parse_doc(load(name))
    assert j is not None
    return j


class FakeClient:
    """照 API 規格回應：Auth → Token；JList → 清單；JDoc → 依 jid 回 fixture。"""

    def __init__(self, docs: dict[str, object]):
        self.docs = docs
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, json=None):
        self.calls.append((url, json))
        if url == judicial.AUTH_URL:
            body = {"Token": "t0k"} if json == {"user": "u", "password": "p"} else {"error": "驗證失敗"}
        elif url == judicial.LIST_URL:
            body = load("jlist.json")
        else:
            body = self.docs[json["j"]]
        return _Resp(body)


class _Resp:
    def __init__(self, body):
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


NIGHT = datetime(2026, 11, 28, 2, 0, tzinfo=judicial.TAIPEI)


class NameIndexTests(unittest.TestCase):
    def test_longest_name_wins_and_line_breaks_ignored(self):
        idx = judicial.NameIndex(ORGS)
        text = judicial.normalize("給付與財團法\n  人基督教更生團契桃園市私立少年\n之家，另基督教更生團契也有")
        hits = [(ubn, name) for _, _, ubn, name in idx.find(text)]
        self.assertEqual(hits, [("72856004", ORGS_NAME_72856004), ("00985373", "財團法人基督教更生團契")])

    def test_tai_variants_and_short_names(self):
        idx = judicial.NameIndex({"臺灣測試協會總會": "1", "慈雲宮": "2"})
        self.assertEqual([h[2] for h in idx.find(judicial.normalize("台灣測試協會總會與慈雲宮"))], ["1"])


ORGS_NAME_72856004 = "財團法人基督教更生團契桃園市私立少年之家"


class ParseTests(unittest.TestCase):
    def test_api_doc(self):
        j = judgment("synthetic_staff_embezzle.json")
        self.assertEqual(j.jid, "TCDM,115,訴,999,20261020,1")
        self.assertEqual(j.kind, "M")
        self.assertEqual(j.case_no, "115年度訴字第999號")
        self.assertEqual(j.decided_on, date(2026, 10, 20))
        self.assertEqual(j.court, "臺灣臺中地方法院")
        self.assertIn("TCDM%2C115%2C", j.url)

    def test_archive_shape_uses_jfull(self):
        j = judicial.parse_doc({"JID": "TPBA,115,訴,1,20261021,1", "JDATE": "20261021", "JFULL": "臺北高等行政法院判決"})
        self.assertEqual(j.text, "臺北高等行政法院判決")
        self.assertEqual(j.court, "臺北高等行政法院")

    def test_worth_reading_only_criminal_and_admin(self):
        self.assertTrue(judicial.worth_reading("TYDM,106,審侵簡,13,20180202,1"))
        self.assertTrue(judicial.worth_reading("TPBA,115,訴,888,20261021,1"))
        self.assertFalse(judicial.worth_reading("TYDV,114,訴,1537,20251128,2"))


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.idx = judicial.NameIndex(ORGS)

    def test_real_donation_recipient_is_not_a_record(self):
        # 真實判決：性侵案被告和解時「給付…與」兩家機構，機構只是捐款對象
        self.assertEqual(judicial.match(judgment("real_donation.json"), self.idx), [])

    def test_real_traffic_case_is_not_serious(self):
        # 真實判決：機構的車被酒駕撞到（公共危險），不是機構的紀錄
        self.assertEqual(judicial.match(judgment("real_traffic.json"), self.idx), [])

    def test_staff_embezzlement(self):
        items = judicial.match(judgment("synthetic_staff_embezzle.json"), self.idx)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.kind, "penalty")
        self.assertEqual(item.ubn, "22222222")
        self.assertEqual(item.external_id, "TCDM,115,訴,999,20261020,1")
        self.assertEqual(item.data["authority"], "臺灣臺中地方法院")
        self.assertEqual(item.data["document_no"], "115年度訴字第999號")
        self.assertEqual(item.data["content"], "刑事判決：業務侵占（組織人員涉案）")
        self.assertIn("主文：王○○犯業務侵占罪", item.data["reason"])
        self.assertIn("執行長", item.data["reason"])
        self.assertTrue(item.source_url.startswith("https://judgment.judicial.gov.tw/FJUD/data.aspx"))

    def test_admin_party(self):
        items = judicial.match(judgment("synthetic_admin_party.json"), self.idx)
        self.assertEqual([(i.ubn, i.data["content"]) for i in items], [("33333333", "行政判決：公益勸募條例（組織為原告）")])

    def test_same_judgment_same_hash(self):
        a = judicial.match(judgment("synthetic_admin_party.json"), self.idx)[0]
        b = judicial.match(judgment("synthetic_admin_party.json"), self.idx)[0]
        self.assertEqual(a.content_hash("judicial"), b.content_hash("judicial"))


class FetchTests(unittest.TestCase):
    def docs(self):
        return {
            "TCDM,115,訴,999,20261020,1": load("synthetic_staff_embezzle.json"),
            "TPBA,115,訴,888,20261021,1": load("synthetic_admin_party.json"),
            "TYDM,106,審侵簡,13,20180202,1": load("real_donation.json"),
            "KSDM,115,易,1,20261020,1": load("deleted.json"),
        }

    def test_daily_run(self):
        client = FakeClient(self.docs())
        items = list(judicial.fetch(client, None, ORGS, ("u", "p"), now=NIGHT))
        self.assertEqual([(i.ubn, i.extra.get("deleted", False)) for i in items],
                         [("22222222", False), ("33333333", False), ("", True)])
        self.assertEqual(items[2].external_id, "KSDM,115,易,1,20261020,1")
        read = [body["j"] for url, body in client.calls if url == judicial.DOC_URL]
        self.assertNotIn("TYDV,114,訴,1537,20251128,2", read)  # 民事判決不取全文
        self.assertTrue(all(body["token"] == "t0k" for url, body in client.calls if url != judicial.AUTH_URL))

    def test_limit_counts_documents_read(self):
        client = FakeClient(self.docs())
        list(judicial.fetch(client, 2, ORGS, ("u", "p"), now=NIGHT))
        self.assertEqual(sum(1 for url, _ in client.calls if url == judicial.DOC_URL), 2)

    def test_refuses_outside_service_hours(self):
        noon = datetime(2026, 11, 28, 12, 0, tzinfo=judicial.TAIPEI)
        with self.assertRaisesRegex(judicial.JudicialError, "00:00–06:00"):
            list(judicial.fetch(FakeClient({}), None, ORGS, ("u", "p"), now=noon))

    def test_missing_credentials(self):
        with self.assertRaisesRegex(judicial.JudicialError, "JUDICIAL_API_USER"):
            list(judicial.fetch(FakeClient({}), None, ORGS, ("", ""), now=NIGHT))

    def test_bad_credentials(self):
        with self.assertRaisesRegex(judicial.JudicialError, "驗證失敗"):
            list(judicial.fetch(FakeClient({}), None, ORGS, ("u", "wrong"), now=NIGHT))


class ArchiveTests(unittest.TestCase):
    def test_reads_json_files_recursively(self):
        with TemporaryDirectory() as tmp:
            sub = Path(tmp) / "202610" / "臺中地方法院刑事"
            sub.mkdir(parents=True)
            doc = load("synthetic_staff_embezzle.json")
            archive_doc = {k: v for k, v in doc.items() if k != "JFULLX"}
            archive_doc["JFULL"] = doc["JFULLX"]["JFULLCONTENT"]
            (sub / "a.json").write_text(json.dumps(archive_doc, ensure_ascii=False), encoding="utf-8")
            (sub / "civil.json").write_text(json.dumps({"JID": "TYDV,114,訴,1,20251128,2"}), encoding="utf-8")
            (sub / "broken.json").write_text("{not json", encoding="utf-8")
            items = list(judicial.iter_archive(tmp, ORGS))
        self.assertEqual([i.ubn for i in items], ["22222222"])


if __name__ == "__main__":
    unittest.main()
