"""產生 tests/fixtures/grants_sample.csv 與 grants_sample.ods：欄位與表頭照衛福部「對民間團體及個人補(捐)助經費彙總表」
（114 年第 4 季的 CSV、111 年第 4 季的 ODS）。受補助對象用登記的法人名稱，個人一律寫「個人」，金額與事項是編的。
grants_esf_big5.csv：勞動部就業安定基金的寫法（全形括號、「114年05月28日」、Big5 編碼）。
grants_no_seq.csv：勞動部勞動力發展署的寫法（沒有「項次」「補(捐)助機關」欄，第一欄是補助種類）。
grants_k12ea_／wda_／nidf_／oac_*（LK-30）：國教署、勞發署、新住民發展基金、海委會各一季的真實檔案節錄幾列（個人本來就遮名）；
海委會另有資料集的清單 CSV 與公告頁（只留附件連結）。
重新產生：python tests/make_grant_fixture.py
"""

import csv
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HEADER = ["項次", "補(捐)助機關", "受補(捐)助對象所歸屬之直轄市或縣(市)", "受補(捐)助對象", "補(捐)助事項或用途",
          "核准日期", "補(捐)助金額\n(含累積金額)", "備註"]
TOTALS = [
    ["衛生福利部主管總計", "", "", "", "", "", "234,708,801,959", ""],
    ["衛生福利部合計", "", "", "", "", "", "197,548,605,187", ""],
]
ROWS = [
    ["1", "社會及家庭署", "臺中市", "財團法人瑪利亞社會福利基金會", "114年度身心障礙者社區式日間照顧服務", "1140310", "1,200,000 ", ""],
    ["2", "社會及家庭署", "臺中市", "財團法人瑪利亞社會福利基金會", "114年度身心障礙者社區式日間照顧服務", "1140310\n1140925", "2,400,000 ", "第二次撥款"],
    ["3", "衛生福利部", "臺北市", "財團法人勵馨社會福利事業基金會(台中分事務所)", "114年度性侵害被害人服務方案", "1140401", "800,000 ", ""],
    ["4", "社會及家庭署", "臺北市", "財團法人勵馨社會福利事業基金會附設台北市私立少女中途之家", "114年度兒少安置機構服務費", "1140501", "350,000 ", ""],
    ["5", "衛生福利部", "高雄市", "七賢脊椎外科醫院", "114年「三班護病比月整體達標獎勵」", "1140502", "614,483 ", ""],
    ["6", "社會及家庭署", "臺北市", "個人", "114年度急難救助", "1140601", "10,000 ", ""],
    ["7", "社會及家庭署", "新北市", "社團法人同名協會", "114年度社區照顧關懷據點", "1140701", "50,000 ", ""],
    ["8", "疾病管制署", "臺北市", "財團法人  瑪利亞社會福利基金會", "114年度愛滋防治宣導", "1140801", "90,000 ", ""],
]
NOTES = [
    ["註：", "1.依中央政府各機關對民間團體及個人補(捐)助預算執行應注意事項第7點規定辦理。", "", "", "", "", "", ""],
]


def build_csv(path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        for r in [HEADER, *TOTALS, *ROWS, *NOTES]:
            w.writerow(r)


def cell(v: str) -> str:
    paras = "".join(f"<text:p>{escape(p)}</text:p>" for p in v.split("\n"))
    return f'<table:table-cell office:value-type="string">{paras}</table:table-cell>'


def build_ods(path: Path) -> None:
    # ODS 版的表頭沒有換行，金額沒有千分位（照 111 年的檔案）
    header = [h.replace("\n", "") for h in HEADER]
    rows = [[c.replace(",", "") if i == 6 else c for i, c in enumerate(r)] for r in ROWS]
    body = "".join(
        "<table:table-row>" + "".join(cell(v) for v in r)
        + '<table:table-cell table:number-columns-repeated="1016"/></table:table-row>'
        for r in [header, *rows, *NOTES]
    )
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2">'
        f'<office:body><office:spreadsheet><table:table table:name="工作表1">{body}</table:table>'
        "</office:spreadsheet></office:body></office:document-content>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet", compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", content)


ESF_HEADER = ["項次", "補（捐）助機關", "受補（捐）助對象所歸屬之直轄市或縣（市）", "受補（捐）助對象", "補（捐）助事項或用途",
              "核准日期", "補（捐）助金額（含累積金額）", "備註"]
ESF_ROWS = [
    ["1", "勞動部", "臺中市", "財團法人瑪利亞社會福利基金會", "114年度多元就業開發方案-社會型計畫", "114年01月15日", "3650000", ""],
    ["2", "勞動部", "臺北市", "財團法人勵馨社會福利事業基金會附設台北市私立少女中途之家", "114年身心障礙者職業重建服務", "114年03月02日", "420000", ""],
    ["3", "技能檢定中心", "基隆市", "陳○○等2人", "補助特定對象參檢費及證照費", "114年12月31日", "320", ""],
]
NO_SEQ_HEADER = ["受補捐（獎）助種類", "受補（捐）助對象所歸屬之直轄市或縣（市）", "受補（捐）助對象", "補（捐）助事項或用途",
                 "核准日期", "補（捐）助金額含累積金額", "備註"]
NO_SEQ_ROWS = [
    ["對特種基金之補(捐)助", "新北市", "就業安定基金", "補助辦理就業保險業務所需行政事務費", "114年06月20日", "56139000", ""],
    ["對民間團體之補(捐)助", "臺中市", "財團法人瑪利亞社會福利基金會", "114年度職場學習及再適應計畫", "114年07月01日", "120000", ""],
]


def build_esf(path: Path) -> None:
    with path.open("w", encoding="cp950", newline="") as fh:
        w = csv.writer(fh)
        for r in [ESF_HEADER, *ESF_ROWS]:
            w.writerow(r)


def build_no_seq(path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        for r in [NO_SEQ_HEADER, *NO_SEQ_ROWS]:
            w.writerow(r)


# ── LK-30：各部會一季樣本（2026-11-27 從政府資料開放平臺下載的真實檔案節錄幾列；個人本來就遮名） ──

K12EA_HEADER = ["項次", "補(捐)助機關", "受補(捐)助對象所歸屬之直轄市或縣（市）", "受補(捐)助對象", "補(捐)助事項或用途",
                "核准日期", "補(捐)助金額(含累積金額)", "", "", ""]
K12EA_ROWS = [  # 國教署 dataset 48670「115年度截至第3季止對民間團體補(捐)助經費彙總表」
    ["1", "教育部國民及學前教育署", "新竹市", "社團法人新竹市教保人員協會", "2026公共化/準公共化幼教主管與教保人員專業增能課程", "115/01/01", "66,442", "", "", ""],
    ["3", "教育部國民及學前教育署", "臺中市", "台中市台中故事協會", "115年度國民中小學閱讀推動計畫", "115/01/02", "616,000", "", "", ""],
    ["5", "教育部國民及學前教育署", "臺中市", "社團法人台中市親子閱讀協會", "115年辦理新住民語文學習生活營", "115/01/05", "60,000", "", "", ""],
    ["6", "教育部國民及學前教育署", "臺中市", "社團法人台中市親子閱讀協會", "115年辦理新住民語文學習班", "115/01/05", "130,000", "", "", ""],
    ["283", "教育部國民及學前教育署", "嘉義市", "賴○誌", "補助115年本署所轄私立高中職公保養老超額年金費用", "115/01/15", "34,849", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
]
WDA_HEADER = ["受補捐（獎）助種類", "受補（捐）助對象所歸屬之直轄市或縣（市）", "受補（捐）助對象", "補（捐）助事項或用途",
              "核准日期", "補（捐）助金額含累積金額", "備註"]
WDA_ROWS = [  # 勞發署 dataset 143623「115年第3季…公務預算對民間團體及個人補(捐)助經費季報表」
    ["對民間團體之補(捐)助", "臺北市", "北基宜花金馬分署社團法人中華民國全國中小企業總會", "勞工就業通計畫", "115年05月27日", "3443", ""],
    ["對民間團體之補(捐)助", "臺中市", "桃竹苗分署光田醫療社團法人光田綜合醫院", "勞工就業通計畫", "115年09月04日", "12000", ""],
    ["對民間團體之補(捐)助", "苗栗縣", "桃竹苗分署社團法人苗栗縣頭屋鄉象山社區發展協會", "勞工就業通計畫", "115年04月07日", "2600", ""],
    ["對民間團體之補(捐)助", "臺中市", "財團法人瑪利亞社會福利基金會", "114年度多元就業開發方案-社會型計畫", "115年01月15日", "3650000", ""],
    ["對個人之補(捐)助", "新北市", "北基宜花金馬分署李○○1人", "支持減班休息勞工再充電計畫", "115年01月07日", "11200", ""],
    ["對個人之補(捐)助", "臺北市", "參訓學員1,620人", "北基宜花金馬分署補助受貿易自由化影響產業在職勞工赴外參訓", "115年04月21日", "9164912", ""],
]
NIDF_HEADER = ["補捐助機關", "受補（捐）助對象所歸屬之直轄市或縣（市）", "受補助對象", "補（捐）助事項或用途", "核准日期",
               "補（捐）助金額（含累積金額）_元"]
NIDF_ROWS = [  # 新住民發展基金 dataset 86171「115年獎補助經費季報表截至第2季-基金-個人及團體」（Big5）
    ["新住民發展基金", "臺北市", "財團法人台北國際社區文化基金會", "115年新住民心台灣-ICRT廣播電台節目宣傳專案（1152D408）", "114.09.16", "1,230,523"],
    ["新住民發展基金", "雲林縣", "雲林縣紫色姊妹協會（雲林縣政府層轉）", "115年雲嘉南多元文化宣導（1153D411）", "114.09.16", "1,338,576"],
    ["新住民發展基金", "臺南市", "社團法人臺南市整體造型交流協會(臺南市政府社會局層轉)", "新住民剪髮志工培訓及運用（1153F401）", "114.12.16", "214,745"],
    ["", "", "", "", "", ""],
    ["", "", "", "‧", "", ""],
]
OAC_PREAMBLE = [
    ["海洋委員會主管預算對民間團體及個人補(捐)助經費彙總表", "", "", "", "", "", "", "", "", "", "", ""],
    ["115年度截至第3季止", "", "各縣市,臺北市,新北市", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "單位：元", "", "", "", "", ""],
]
OAC_HEADER = ["項次", "補(捐)助機關", "受補(捐)助對象所歸屬之直轄市或縣(市)", "受補(捐)助對象", "補(捐)助事項或用途",
              "核准日期", "補(捐)助金額(含累積金額)", "備註", "決算數", "結案", "處室", "承辦"]
OAC_ROWS = [  # 海委會 115 年第 3 季公告附的 ODS
    ["海洋委員會主管", "", "", "", "100,743,587", "", "", "", "", "", "", ""],
    ["(一)公務預算", "", "", "", "54,591,857", "", "", "", "", "", "", ""],
    ["6", "海洋委員會", "臺北市", "財團法人吳三連台灣史料基金會", "新台灣史料研習營第37屆–烏石春帆．百年啟航", "1141219", "20,000", "", "", "", "科文", ""],
    ["14", "海洋委員會", "臺北市", "財團法人原住民族文化事業基金會", "海路─南島語族航海計畫案", "1150603", "1,000,000", "", "", "", "科文", ""],
    ["1", "國家海洋研究院", "各縣市", "退休人員", "114年度退休金優惠存款差額利息", "1150213", "16,348", "", "", "", "", ""],
]
OAC_INDEX = [  # 海委會 dataset 139265 唯一的 CSV：每季一列，連結是 PDF 或公告頁（Big5）
    ["名稱", "連結", "說明", "期間", "金額"],
    ["112年度第4季公務預算對民間團體及個人補(捐)助經費彙整表", "https://www.oac.gov.tw/filedownload?file=govinfo/202401311509080.pdf&flag=doc",
     "112年度第4季", "112年度第4季", "50000000"],
    ["115年第2季公務預算對民間團體及個人補(捐)助經費彙整表",
     "https://www.oac.gov.tw/ch/home.jsp?id=1242&parentpath=0,684&mcustomize=multimessages_view.jsp&dataserno=202607240001",
     "115年第2季", "115年第2季", "75003144"],
    ["115年第3季公務預算對民間團體及個人補(捐)助經費彙整表",
     "https://www.oac.gov.tw/ch/home.jsp?id=1242&parentpath=0,684&mcustomize=multimessages_view.jsp&dataserno=202610140004",
     "115年第3季", "115年第3季", "100743587"],
]
OAC_PAGE = """<html><body><div class="download">
<a href="/filedownload?file=govinfo/202610141657500.pdf&amp;filedisplay=%E6%B5%B7.pdf&amp;flag=doc" title="pdf">海洋委員會主管115年度第3季.pdf</a>
<a href="/filedownload?file=govinfo/202610141657501.ods&amp;filedisplay=%E6%B5%B7.ods&amp;flag=doc" title="ods">海洋委員會主管115年度第3季.ods</a>
</div></body></html>
"""


def write_csv(path: Path, rows: list[list[str]], encoding: str = "utf-8-sig") -> None:
    with path.open("w", encoding=encoding, newline="") as fh:
        csv.writer(fh).writerows(rows)


def write_ods(path: Path, rows: list[list[str]]) -> None:
    body = "".join("<table:table-row>" + "".join(cell(v) for v in r) + "</table:table-row>" for r in rows)
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2">'
        f'<office:body><office:spreadsheet><table:table table:name="工作表1">{body}</table:table>'
        "</office:spreadsheet></office:body></office:document-content>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet", compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", content)


def build_lk30(fx: Path) -> None:
    write_csv(fx / "grants_k12ea_115q3.csv", [K12EA_HEADER, *K12EA_ROWS])
    write_csv(fx / "grants_wda_115q3.csv", [WDA_HEADER, *WDA_ROWS])
    write_csv(fx / "grants_nidf_115q2_big5.csv", [NIDF_HEADER, *NIDF_ROWS], "cp950")
    write_ods(fx / "grants_oac_115q3.ods", [*OAC_PREAMBLE, OAC_HEADER, *OAC_ROWS])
    write_csv(fx / "grants_oac_index_big5.csv", OAC_INDEX, "cp950")
    (fx / "grants_oac_page.html").write_text(OAC_PAGE, encoding="utf-8")


if __name__ == "__main__":
    fx = Path(__file__).parent / "fixtures"
    build_csv(fx / "grants_sample.csv")
    build_ods(fx / "grants_sample.ods")
    build_esf(fx / "grants_esf_big5.csv")
    build_no_seq(fx / "grants_no_seq.csv")
    build_lk30(fx)
