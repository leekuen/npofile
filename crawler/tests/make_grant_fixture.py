"""產生 tests/fixtures/grants_sample.csv 與 grants_sample.ods：欄位與表頭照衛福部「對民間團體及個人補(捐)助經費彙總表」
（114 年第 4 季的 CSV、111 年第 4 季的 ODS）。受補助對象用登記的法人名稱，個人一律寫「個人」，金額與事項是編的。
grants_esf_big5.csv：勞動部就業安定基金的寫法（全形括號、「114年05月28日」、Big5 編碼）。
grants_no_seq.csv：勞動部勞動力發展署的寫法（沒有「項次」「補(捐)助機關」欄，第一欄是補助種類）。
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


if __name__ == "__main__":
    fx = Path(__file__).parent / "fixtures"
    build_csv(fx / "grants_sample.csv")
    build_ods(fx / "grants_sample.ods")
    build_esf(fx / "grants_esf_big5.csv")
    build_no_seq(fx / "grants_no_seq.csv")
