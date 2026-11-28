"""LK-49：重大訊息捐贈公告與保險業捐贈情形表的解析。頁面結構照 2026-11-28 實測的寫法縮小。"""

import unittest
from datetime import date
from unittest import mock

from npofile_crawler import corporate_gifts as g

ORGS = [("11111111", "財團法人國巨基金會"), ("22222222", "財團法人台灣世界展望會")]


def mops_form(n, short, code, subject, detail, typek="sii", spoke="20251030"):
    h = f"h{n}"
    vals = [short, code, spoke, "170000", subject, "1", "43", spoke, detail]
    hidden = "".join(f"<input type='hidden' name='{h}{i}' value='{v}'>" for i, v in enumerate(vals))
    return (f"<form action='/mops/web/ajax_t05st02' method='post' name='{typek}_fm{n}'>"
            "<input type='hidden' name='off' value='1'><input type='hidden' name='TYPEK' value=''>"
            f"{hidden}<input type='button' value='詳細資料' onclick='document.{typek}_fm{n}.TYPEK.value=\"{typek}\";'></form>")


GIFT = ("1.事實發生日:114/10/30\n2.捐贈原由:推動公益\n3.捐贈金額:新台幣3,000萬元\n4.受贈對象:財團法人國巨基金會\n"
        "5.與公司關係:實質關係人\n6.表示反對或保留意見之獨立董事姓名及簡歷:無\n7.其他應敘明事項:無")
RANGE = GIFT.replace("新台幣3,000萬元", "新台幣20-30萬元(以實際名冊人數為準)").replace("財團法人國巨基金會", "財團法人遠雄文教公益基金會")
OTHER = "1.董事會決議日期:114/10/30\n2.買回股份目的:轉讓股份予員工\n3.其他應敘明事項:無"


def mops_page(*forms):
    return "<html><body><table>" + "".join(f"<tr><td>{f}</td></tr>" for f in forms) + "</table></body></html>"


class FakeClient:
    min_interval = 0.0

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def post(self, url, data):
        self.calls.append(data)
        text = self.pages.pop(0) if self.pages else mops_page()
        return type("R", (), {"text": text})()


INSURER = """<table id="ctl00_MainContent_GridView1">
<tr><th>資料日期：中華民國115年11月 捐贈對象類別</th><th>受捐贈團體名稱</th><th>捐贈日期</th><th>捐贈金額 (元)</th><th>備註</th></tr>
<tr><td>公益團體</td><td>財團法人台灣世界展望會</td><td>2026-10-06</td><td>15,488</td><td></td></tr>
<tr><td>公益團體</td><td>財團法人台灣世界展望會</td><td>2026-10-06</td><td>15,488</td><td></td></tr>
<tr><td>公益團體</td><td>財團法人育成社會福利基金會</td><td>2025-06-13</td><td>$0</td><td>設備一批</td></tr>
<tr><td>政黨</td><td>某某黨</td><td>2025-01-02</td><td>100,000</td><td></td></tr>
<tr><td>公益團體</td><td>財團法人台灣世界展望會</td><td>2015-01-02</td><td>100,000</td><td></td></tr>
</table>"""


class FakeInsClient:
    min_interval = 0.0

    def get(self, url):
        text = INSURER if "Info4-21" in url else "<html></html>"
        return type("R", (), {"text": text})()


class CorporateGiftsTest(unittest.TestCase):
    def test_parse_amount(self):
        assert g.parse_amount("新台幣130萬元") == 1_300_000
        assert g.parse_amount("新臺幣 4,870,204 元") == 4_870_204
        assert g.parse_amount("新台幣壹佰萬元") == 1_000_000
        assert g.parse_amount("新臺幣貳仟伍佰萬元整") == 25_000_000
        assert g.parse_amount("新台幣1.5億元") == 150_000_000
        assert g.parse_amount("15,488") == 15_488
        assert g.parse_amount("新台幣20-30萬元(以新北市政府實際名冊人數為準)") is None
        assert g.parse_amount("最高新台幣50萬元") is None
        assert g.parse_amount("$0") is None
        assert g.parse_amount("") is None

    def test_parse_mops_day_picks_donations_only(self):
        page = mops_page(
            mops_form(1, "國巨*", "2327", "公告本公司董事會決議捐贈", GIFT),
            mops_form(2, "國巨*", "2327", "公告本公司董事會決議買回庫藏股", OTHER),
            mops_form(3, "台新新光金", "2887", "代子公司國際票券金融股份有限公司公告董事會通過捐贈", GIFT, typek="otc"),
        )
        total, gifts = g.parse_mops_day(page)
        assert total == 3
        assert [x["company_code"] for x in gifts] == ["2327", "2887"]
        assert gifts[0]["amount_text"] == "新台幣3,000萬元"
        assert gifts[0]["recipient"] == "財團法人國巨基金會"
        assert gifts[0]["relation"] == "實質關係人"
        assert gifts[1]["subsidiary"] == "國際票券金融股份有限公司"
        assert gifts[1]["market"] == "otc"

    def test_mops_items_match_dedupe_and_range(self):
        page = mops_page(
            mops_form(1, "國巨*", "2327", "公告本公司董事會決議捐贈", GIFT),
            mops_form(2, "國巨*", "2327", "公告本公司董事會決議捐贈（更正）", GIFT),  # 重發：同一筆
            mops_form(3, "遠壽", "5859", "公告董事會決議捐贈", RANGE),
        )
        _, gifts = g.parse_mops_day(page)
        items = list(g.mops_items(gifts, g.OrgMatcher(ORGS), date(2025, 10, 30)))
        assert items[0].ubn == "11111111"
        assert items[0].data["donor_name"] == "國巨"  # 簡稱後的 * 去掉
        assert items[0].data["amount"] == 30_000_000
        assert items[0].data["donated_on"] == date(2025, 10, 30)
        assert items[0].external_id == items[1].external_id
        assert items[2].ubn == ""  # 對不到組織：統編空白，後端放進審核清單
        assert items[2].data["amount"] is None
        assert items[2].data["amount_text"].startswith("新台幣20-30萬元")

    def test_fetch_mops_walks_back_and_retries_when_throttled(self):
        pages = ["<html>查詢過於頻繁，請稍後再查詢</html>", mops_page(mops_form(1, "國巨*", "2327", "公告捐贈", GIFT)), mops_page()]
        client = FakeClient(pages)
        waits = []
        listed = [0]
        items = list(g.fetch_mops(client, 2, orgs=ORGS, listed=listed, today=date(2025, 10, 31), sleep=waits.append))
        assert len(items) == 1
        assert [c["day"] for c in client.calls] == ["31", "31", "30"]
        assert waits[0] == g.THROTTLE_WAIT
        assert listed == [1]

    def test_fetch_mops_stops_at_since_date(self):
        client = FakeClient([])
        list(g.fetch_mops(client, None, orgs=ORGS, since_date=date(2025, 10, 28), since_roc=110,
                          today=date(2025, 10, 31), sleep=lambda s: None))
        assert [c["day"] for c in client.calls] == ["31", "30", "29", "28"]

    def test_parse_insurer_table(self):
        rows = g.parse_insurer_table(INSURER)
        assert len(rows) == 5
        assert rows[0] == {"category": "公益團體", "recipient": "財團法人台灣世界展望會", "donated_on": date(2026, 10, 6),
                           "amount": 15_488, "amount_text": "", "note": ""}
        assert rows[2]["amount"] is None and rows[2]["amount_text"] == "設備一批"

    def test_fetch_insurers(self):
        patcher = mock.patch.object(g, "insurers", lambda client: [("03374707", "國泰人壽保險股份有限公司")])
        patcher.start()
        self.addCleanup(patcher.stop)
        items = list(g.fetch_insurers(FakeInsClient(), None, since_roc=110, orgs=ORGS))
        assert len(items) == 4  # 2015 年那列在近 5 年外
        assert items[0].ubn == "22222222" and items[0].data["donor_ubn"] == "03374707"
        assert items[0].external_id != items[1].external_id  # 同一天同金額列兩次＝兩筆
        assert items[2].ubn == ""  # 對不到組織
        party = items[3]
        assert party.ubn == "" and party.data["party"] is True  # 政黨捐贈只留後台


if __name__ == "__main__":
    unittest.main()
