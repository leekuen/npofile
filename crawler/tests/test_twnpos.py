"""自律聯盟會員財務報告（LK-25）。

fixtures（2026-11-27 下載的真實資料）：
- twnpos_report_A0364_114.pdf：台灣性別平等教育協會 114 年度財務報告（有文字的 PDF，捐款收入分三個子科目＋合計）
- twnpos_folder.html：新希望基金會財務報告資料夾的嵌入頁（Google 雲端公開資料夾）
影像辨識的部分用台灣世界展望會 114 年度收支餘絀表實際辨識出的詞與座標測（不在測試裡跑 OCR，太慢）。
"""

import unittest
from pathlib import Path

from npofile_crawler import twnpos

FX = Path(__file__).parent / "fixtures"

# 世界展望會收支餘絀表（掃描檔）辨識結果：(行 y, 左 x, 右 x, 文字)；「计」是辨識成簡體的「計」
WORLD_VISION_OCR = [
    (80, 108, 140, "收入"),
    (484, 124, 220, "捐款收入"), (484, 869, 1000, "3,724,146,641"), (484, 1047, 1070, "94"),
    (494, 559, 700, "3,963,597,229"), (494, 740, 760, "95"),
    (530, 127, 220, "委辨收入"), (530, 578, 700, "158,186,298"), (530, 888, 1000, "188,982,617"),
    (662, 145, 240, "收入合计"), (662, 559, 700, "4,152,603,677"), (662, 732, 760, "100"),
    (662, 869, 1000, "3,953,978,849"), (662, 1040, 1070, "100"),
]


class PickValuesTests(unittest.TestCase):
    def test_ocr_rows_take_leftmost_amount_as_this_year(self):
        self.assertEqual(twnpos.pick_values(WORLD_VISION_OCR, row_tol=18),
                         {"donation": 3_963_597_229, "income_total": 4_152_603_677})

    def test_rejects_donation_larger_than_total(self):
        bad = [(10, 0, 50, "捐款收入"), (10, 100, 200, "9,000,000"), (30, 0, 50, "收入合計"), (30, 100, 200, "1,000,000")]
        self.assertIsNone(twnpos.pick_values(bad, row_tol=5))

    def test_church_offering_counts_as_donation(self):
        # 舊鞋救命協會 114 年度（掃描檔）：「奉獻收入」辨識成「奉獻献收入」，收入總額「额」是簡體
        toks = [(5, 0, 80, "奉獻献收入"), (5, 100, 200, "70,396,875"), (5, 220, 240, "94"), (5, 300, 400, "54,460,493"),
                (20, 0, 80, "收入總额"), (20, 100, 200, "74,557,901"), (20, 300, 400, "57,976,024")]
        self.assertEqual(twnpos.pick_values(toks, row_tol=5), {"donation": 70_396_875, "income_total": 74_557_901})

    def test_total_may_be_missing(self):
        self.assertEqual(twnpos.pick_values([(10, 0, 50, "捐款收入"), (10, 100, 200, "9,000")], row_tol=5),
                         {"donation": 9000, "income_total": None})

    def test_needs_donation_row_and_well_formed_amounts(self):
        self.assertIsNone(twnpos.pick_values([(10, 0, 50, "收入合計"), (10, 100, 200, "9,000")], row_tol=5))
        # 辨識雜訊把千分位拆錯的數字不收
        self.assertIsNone(twnpos.pick_values([(10, 0, 50, "捐款收入"), (10, 100, 200, "45,98,1479")], row_tol=5))


class ParseReportTests(unittest.TestCase):
    def test_text_pdf_uses_donation_subtotal(self):
        r = twnpos.parse_report((FX / "twnpos_report_A0364_114.pdf").read_bytes(), ocr=False)
        # 一般捐款 1,443,951＋公益勸募 329,288＋專案 2,211,666＝合計 3,984,905
        self.assertEqual(r, {"donation": 3_984_905, "income_total": 7_910_950, "method": "文字"})

    def test_unreadable_gives_no_numbers(self):
        self.assertEqual(twnpos.parse_report(b"not a pdf", ocr=False),
                         {"donation": None, "income_total": None, "method": ""})


class FakeResponse:
    def __init__(self, payload=None, text="", content=b"", url=""):
        self._payload, self.text, self.content, self.url = payload, text, content, url

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self):
        self.urls = []

    def get(self, url, params=None, **kw):
        self.urls.append((url, params))
        if "api.oen.tw" in url:
            return FakeResponse({"data": {"articles": [
                {"id": "M1", "title": "財團法人新北市私立新希望基金會", "subtitle": "會員編號：F0587"},
                {"id": "M2", "title": "社團法人台灣性別平等教育協會", "subtitle": "會員編號：A0364"},
                {"id": "M3", "title": "對不到的協會", "subtitle": "會員編號：A9999"},
            ]}, "paging": {"next": None}})
        if url.endswith("/team/M1"):
            return FakeResponse({"post": {"i18nData": {"sections": [
                {"type": "callToAction", "content": {"text": "瀏覽財務報告",
                                                     "link": "https://drive.google.com/drive/folders/1mZW9OW87mpPbgJfiCUsfrE2p_MJF1Ty9"}}]}}})
        if url.endswith("/team/M2"):
            return FakeResponse({"post": {"i18nData": {"sections": [
                {"type": "callToAction", "content": {"text": "瀏覽財務報告", "link": "https://supr.link/abc"}}]}}})
        if url == "https://supr.link/abc":  # 短網址頁面裡才有雲端網址
            return FakeResponse(text='<a href="https://drive.google.com/open?id=FOLDER2abcdefghij&usp=drive_copy">')
        if url.endswith("/embeddedfolderview"):
            if params["id"] == "FOLDER2abcdefghij":
                return FakeResponse(text=(
                    '<a href="https://drive.google.com/file/d/FILE114/view?usp=drive_web"><div class="flip-entry-title">114_financial-report_A0364.pdf</div></a>'
                    '<a href="https://drive.google.com/file/d/FILE109/view?usp=drive_web"><div class="flip-entry-title">109_financial-report_A0364_01.pdf</div></a>'))
            return FakeResponse(text=(FX / "twnpos_folder.html").read_text(encoding="utf-8"))
        if url.endswith("/uc"):
            if params["id"] == "FILE114":
                return FakeResponse(content=(FX / "twnpos_report_A0364_114.pdf").read_bytes())
            return FakeResponse(content=b"<html>not a pdf</html>")
        raise AssertionError(url)


class FetchTests(unittest.TestCase):
    ORGS = [("10000587", "財團法人新北市私立新希望基金會"), ("10000364", "社團法人台灣性別平等教育協會")]

    def test_items_follow_short_links_and_skip_old_years(self):
        client = FakeClient()
        items = list(twnpos.fetch(client, since_roc=111, orgs=self.ORGS))
        self.assertEqual([(i.ubn, i.external_id) for i in items], [("10000587", "F0587-114"), ("10000364", "A0364-114")])
        a0364 = items[1]
        self.assertEqual(a0364.data["contributions"], 3_984_905)
        self.assertEqual(a0364.data["total_revenue"], 7_910_950)
        self.assertEqual(a0364.data["method"], "text")
        self.assertEqual(a0364.data["document_url"], "https://drive.google.com/file/d/FILE114/view")
        self.assertEqual(a0364.source_url, "https://drive.google.com/file/d/FILE114/view")
        # 新希望的檔案下載回來不是 PDF：照樣記一筆（留報告連結），數字留空
        self.assertIsNone(items[0].data["contributions"])
        self.assertFalse(any("M3" in u for u, _ in client.urls))  # 對不到的會員不看會員頁

    def test_known_reports_not_downloaded(self):
        client = FakeClient()
        items = list(twnpos.fetch(client, since_roc=111, orgs=self.ORGS, have={"A0364-114"}))
        self.assertEqual([i.external_id for i in items], ["F0587-114"])
        self.assertFalse(any(p and p.get("id") == "FILE114" for u, p in client.urls if u.endswith("/uc")))


if __name__ == "__main__":
    unittest.main()
