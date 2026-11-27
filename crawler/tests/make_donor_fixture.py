"""產生 tests/fixtures/donors_sample.ods：格式照公益勸募系統下載的「捐款人資料.ods」，
個人姓名一律是編的（不把真實個人姓名放進版控）；企業名稱用清冊上常見的型態。
重新產生：python tests/make_donor_fixture.py
"""

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROWS = [
    ("收據編號", "捐贈日期", "捐贈者名稱或姓名", "捐贈金額", "捐贈用途"),
    ("A001", "114/08/06", "範例科技股份有限公司", "1500000", "指定捐款／兒童助學"),
    ("A002", "114/08/07", "範例科技股份有限公司", "500000", "指定捐款／兒童助學"),
    ("A003", "114/08/08", "財團法人範例文教基金會", "1000000", "一般捐款"),
    ("A004", "114/08/09", "台北範例扶輪社", "800000", "一般捐款"),
    ("A005", "114/08/10", "捐款人聲明捐款資訊不公開", "3000", "一般捐款"),
    ("A006", "114/08/11", "MOMO捐款有心人", "45000", "一般捐款"),
    ("A007", "114/08/12", "範例聯合行銷股份有限公司 有心人捐款", "12000", "一般捐款"),
    ("A008", "114/08/13", "甲大明", "60000", "一般捐款"),
    ("A009", "114/09/01", "甲大明(同001772220)", "50000", "一般捐款"),
    ("A010", "114/09/02", "乙小華", "300", "一般捐款"),
    ("A011", "114/09/03", "乙小華", "300", "一般捐款"),
    ("A012", "114/09/04", "Sample Lee", "2000", "一般捐款"),
    ("A013", "114/09/05", "範例美學館", "1000", "一般捐款"),
    ("A014", "", "", "", ""),
]


def cell(v: str) -> str:
    return f'<table:table-cell office:value-type="string"><text:p>{escape(v)}</text:p></table:table-cell>'


def build(path: Path) -> None:
    rows = "".join(
        "<table:table-row>" + "".join(cell(v) for v in r)
        + '<table:table-cell table:number-columns-repeated="1019"/></table:table-row>'
        for r in ROWS
    )
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2">'
        f'<office:body><office:spreadsheet><table:table table:name="捐款人資料">{rows}</table:table>'
        "</office:spreadsheet></office:body></office:document-content>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet", compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", content)


if __name__ == "__main__":
    build(Path(__file__).parent / "fixtures" / "donors_sample.ods")
