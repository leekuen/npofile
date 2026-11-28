"""財團法人年度捐贈名單清冊（LK-48）：認清冊、讀 PDF／Excel／ODS／網頁表格、分類與個人門檻、官網爬蟲收檔。"""

import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from npofile_crawler import annual_donors as ad
from npofile_crawler import orgsite

from test_orgsite import SITE, FakeClient, FakeResponse

FX = Path(__file__).parent / "fixtures"


class DirectionTests(unittest.TestCase):
    def test_titles(self):
        cases = {
            "113年創世支付獎助捐贈名單清冊": ad.PAY,
            "112年創世接受補助清冊": ad.RECEIVE,
            "114年接受政府補(捐)助名單清冊": ad.RECEIVE,
            "113年度捐贈名單清冊": ad.RECEIVE,  # 沒寫方向：當成接受
            "2024年度支付獎助、捐贈名單清冊": ad.PAY,
            "113年4月份捐款芳名錄": None,  # 每月的不收
            "113年度捐款徵信錄": None,
            "113 年徵信 /files/113捐款徵信名單.pdf": None,
            "113年度財務報告": None,
        }
        for text, want in cases.items():
            self.assertEqual(ad.direction(text), want, text)


def line(*cells):
    """（x 左, 字）… → PDF 的一列"""
    return [(x, x + 10 * len(t), t) for x, t in cells]


class PdfRowTests(unittest.TestCase):
    HEADER = line((196, "NO"), (223, "日期"), (290, "補助單位"), (361, "補助金額/物品"), (412, "備註"))

    def test_name_next_to_date_and_number_cells(self):
        rows = ad.rows_from_pdf_lines([
            line((100, "2024年度接受補助清冊")),
            self.HEADER,
            line((201, "1 2024/01/02"), (252, "衛福部"), (380, "1,502,200")),
            line((201, "2 2024/01/02"), (252, "台灣港務股份有限公司"), (388, "10,000"), (412, "物資")),
            line((201, "3"), (223, "2024/01/03"), (252, "財團法人範例基金會"), (388, "8,000")),
            line((201, "合計"), (380, "1,520,200")),
        ])
        self.assertEqual([(r.name, r.amount) for r in rows],
                         [("衛福部", 1502200), ("台灣港務股份有限公司", 10000), ("財團法人範例基金會", 8000)])

    def test_wrapped_name_from_line_above(self):
        rows = ad.rows_from_pdf_lines([
            self.HEADER,
            line((252, "社團法人國際社會福利協會中華民國總會")),
            line((201, "106 2024/04/29"), (252, "補助辦理113年社工專業知能加強計畫乙案"), (370, "1,700,000")),
            line((201, "104 2023/01~2023/12 社團法人台北市心生活協會附設心朋友的店"), (388, "53,575"), (412, "水餃")),
        ])
        self.assertEqual([(r.name, r.amount) for r in rows],
                         [("社團法人國際社會福利協會中華民國總會", 1700000), ("社團法人台北市心生活協會附設心朋友的店", 53575)])

    def test_real_text_pdf(self):
        parsed = ad.parse("x.pdf", (FX / "annual_list_pts_114.pdf").read_bytes())
        self.assertEqual((parsed.format, parsed.scanned, len(parsed.rows)), ("pdf", False, 9))
        result = ad.summarize(ad.RECEIVE, parsed.rows)
        totals = {}
        for r in result["rows"]:
            totals[(r["name"], r["kind"])] = totals.get((r["name"], r["kind"]), 0) + r["amount"]
        self.assertEqual(totals[("文化部", "group")], 900000000 + 586273307 + 778525244 + 1131856332)
        self.assertEqual(totals[("客家委員會", "group")], 594929286)
        self.assertEqual(result["summary"]["small_individual_count"], 0)

    def test_scanned_pdf(self):
        self.assertTrue(ad.parse_pdf(b"%PDF-1.4 not really").scanned)


def ods_bytes(rows):
    ns = ('xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"')
    body = "".join(
        "<table:table-row>" + "".join(f"<table:table-cell><text:p>{c}</text:p></table:table-cell>" for c in r)
        + "</table:table-row>" for r in rows
    )
    xml = f'<?xml version="1.0"?><office:document-content {ns}><office:body><office:spreadsheet>' \
          f'<table:table>{body}</table:table></office:spreadsheet></office:body></office:document-content>'
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        zf.writestr("content.xml", xml)
    return buf.getvalue()


def xlsx_bytes(rows):
    from openpyxl import Workbook

    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


TABLE = [
    ["財團法人範例基金會 113年度接受捐贈名單清冊"],
    ["編號", "捐贈者姓名或名稱", "捐贈金額"],
    ["1", "範例科技股份有限公司", "1,000,000"],
    ["2", "王小明", "500"],
    ["3", "總計", "1,000,500"],
]


class TableFormatTests(unittest.TestCase):
    def check(self, parsed, fmt):
        self.assertEqual(parsed.format, fmt)
        self.assertEqual([(r.name, r.amount) for r in parsed.rows], [("範例科技股份有限公司", 1000000), ("王小明", 500)])

    def test_xlsx(self):
        self.check(ad.parse("x.xlsx", xlsx_bytes([[c or None for c in r] for r in TABLE])), "xlsx")

    def test_ods(self):
        self.check(ad.parse("x.ods", ods_bytes(TABLE)), "ods")

    def test_html(self):
        html = "<html><body><table>" + "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in TABLE
        ) + "</table></body></html>"
        self.check(ad.parse("https://npo.example.org/list", html.encode("utf-8"), "text/html"), "html")

    def test_old_xls_not_read(self):
        self.assertIsNone(ad.parse("x.xls", b"\xd0\xcf\x11\xe0 old excel"))


class SummarizeTests(unittest.TestCase):
    def test_receive_threshold_per_list(self):
        rows = [ad.RawRow(n, a) for n, a in [("陳大華", 60000), ("陳 大華", 50000), ("王小明", 500), ("善心人士", 100),
                                              ("文化部捐贈", 9000), ("原民會", 1000)]]
        result = ad.summarize(ad.RECEIVE, rows)
        self.assertEqual(sorted((r["name"], r["kind"]) for r in result["rows"]),
                         sorted([("陳大華", "individual"), ("陳 大華", "individual"), ("文化部", "group"),
                                 ("原民會", "group")]))
        s = result["summary"]
        self.assertEqual((s["small_individual_count"], s["anonymous_rows"], s["total_rows"]), (1, 1, 6))

    def test_pay_drops_individual_recipients(self):
        rows = [ad.RawRow("林〇儀喪葬補助費", 20000), ad.RawRow("社團法人範例協會", 500000), ad.RawRow("王大明", 200000)]
        result = ad.summarize(ad.PAY, rows)
        self.assertEqual([r["name"] for r in result["rows"]], ["社團法人範例協會"])
        self.assertEqual(result["summary"]["small_individual_count"], 2)


DISCLOSURE = """<html><body>
<a href="/files/113年創世支付獎助捐贈名單清冊.pdf">113年支付獎助捐贈名單清冊</a>
<a href="/files/113receive.xlsx">113年接受捐贈名單清冊</a>
<a href="/files/113年度財務報告.pdf">113年度財務報告</a>
<a href="/files/105年接受捐贈名單清冊.pdf">105年接受捐贈名單清冊</a>
<a href="/files/捐贈名單清冊.pdf">捐贈名單清冊</a>
<a href="/files/113年3月份捐款芳名錄.pdf">113年3月份捐款芳名錄</a>
<a href="/donor-list-112">112年度接受捐贈名單清冊</a>
</body></html>"""


class OrgSiteListTests(unittest.TestCase):
    def test_parse_links_finds_lists_without_touching_reports(self):
        docs, _ = orgsite.parse_links(DISCLOSURE, SITE + "disclosure")
        got = {(d.year, d.doc_kind, d.url.rsplit("/", 1)[-1]) for d in docs}
        self.assertEqual(got, {
            (113, "donor_pay", "113年創世支付獎助捐贈名單清冊.pdf"),
            (113, "donor_receive", "113receive.xlsx"),
            (113, "financial", "113年度財務報告.pdf"),
            (105, "donor_receive", "105年接受捐贈名單清冊.pdf"),
            (112, "donor_receive", "donor-list-112"),
        })  # 看不出年度的、每月芳名錄不收
        self.assertEqual(orgsite.pick_for_extraction(docs)[0].doc_kind, "financial")

    def test_fetch_downloads_and_parses_lists(self):
        client = FakeClient({
            SITE: '<a href="/disclosure">資訊公開</a>', SITE + "disclosure": DISCLOSURE,
            SITE + "files/113年創世支付獎助捐贈名單清冊.pdf": (FX / "annual_list_pts_114.pdf").read_bytes(),
            SITE + "donor-list-112": "<table>" + "".join(
                "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in TABLE) + "</table>",
        })
        xlsx = xlsx_bytes([[c or None for c in r] for r in TABLE])
        original = client.get

        def get(url, **kw):
            if url.endswith("113receive.xlsx"):
                return FakeResponse(url, content=xlsx, ctype="application/vnd.openxmlformats")
            resp = original(url, **kw)
            if url.endswith("donor-list-112"):
                resp.content = resp.text.encode("utf-8")
            return resp

        client.get = get
        items = list(orgsite.fetch(client, targets=[("12345678", SITE)], since_roc=111))
        lists = {i.data["url"].rsplit("/", 1)[-1]: i for i in items if i.kind == "annual_list"}
        self.assertEqual(set(lists), {"113年創世支付獎助捐贈名單清冊.pdf", "113receive.xlsx", "donor-list-112"})
        self.assertTrue(all(i.ubn == "12345678" for i in lists.values()))
        x = lists["113receive.xlsx"].data
        self.assertEqual((x["year"], x["direction"], x["format"]), (113, "receive", "xlsx"))
        self.assertEqual([r["name"] for r in x["rows"]], ["範例科技股份有限公司"])
        self.assertEqual(lists["donor-list-112"].data["format"], "html")
        self.assertEqual({i.kind for i in items} - {"annual_list"}, {"document"})


if __name__ == "__main__":
    unittest.main()
