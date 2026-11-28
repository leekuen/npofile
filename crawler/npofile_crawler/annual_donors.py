"""財團法人年度捐贈名單清冊（LK-48）：《財團法人法》第 25 條第 3 項第 2 款要財團法人每年主動公開
前一年度的「接受補助、捐贈名單清冊」與「支付獎助、捐贈名單清冊」，只公開名稱（姓名）與金額。

這裡只管「認出是哪一種清冊」與「從檔案讀出名稱、金額」：
- 文字 PDF：依字的位置把同一列的字排回來，用表頭（受助者／補助單位…、金額）分欄；讀不出字的當掃描檔。
- Excel（xlsx）、ODS、網頁表格：找有名稱欄與金額欄的表頭列，往下讀。
分類（企業／團體／個人／匿名）與個人門檻沿用 donors.py；對組織（支付清冊的受捐者）在後端做。
"""

from __future__ import annotations

import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from io import BytesIO
from xml.etree.ElementTree import iterparse

from bs4 import BeautifulSoup

from . import donors
from .items import money

RECEIVE, PAY = "receive", "pay"
DIRECTION_LABELS = {RECEIVE: "接受", PAY: "支付"}

_LIST_WORD = r"(?:清冊|名單|名冊)"
PAY_RE = re.compile(r"(?:支付|支出|捐出|撥付)\S{0,8}?(?:獎助|捐贈|補助|捐助)\S{0,6}?" + _LIST_WORD)
RECEIVE_RE = re.compile(r"(?:接受|收受|受贈|獲得)\S{0,8}?(?:捐贈|補助|捐款|捐助)\S{0,6}?" + _LIST_WORD)
# 標題只寫「捐贈名單清冊」沒寫方向：當成接受（法條的第一份）
GENERIC_RE = re.compile(r"捐贈名單" + _LIST_WORD)
# 每月徵信、芳名錄、徵信錄不是年度清冊，不收（條件確認第 1 條）
NOT_ANNUAL_RE = re.compile(r"(?<![年\d])\d{1,2}\s*月(?:份)?|月份|月報|季|徵信錄|芳名|收據")

NAME_HEADER_RE = re.compile(r"受[獎補捐]?助者|受贈|受捐|補助單位|補\(?捐\)?助單位|捐[贈助款]者|捐[贈款]人|捐助單位|名稱|姓名|單位|對象")
AMOUNT_HEADER_RE = re.compile(r"金額|金\s*額|amount", re.I)
# 表頭之外、看起來不像人名或單位名的字（說明列、合計列、計畫名稱）
NOT_A_NAME_RE = re.compile(r"合計|總計|小計|共計|總額|以下空白|計畫|乙案|專案|活動|依據|財團法人法")
MAX_NAME = 60
MONEY_CELL_RE = re.compile(r"^(?:NT\$|\$)?\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?\s*元?$|^(?:NT\$|\$)?\s*\d+\s*元?$")
# 只有序號或日期的格（「12」「2024/01/31」「113.05.02」）
NO_DATE_ONLY_RE = re.compile(r"^[\d\s/.\-~～]+$")
# PDF 的同一段字常把「序號 日期」黏在名稱前面：「104 2023/01~2023/12 某某協會」
LEADING_NO_DATE_RE = re.compile(r"^\d{1,5}\s+(?:\d{2,4}[/.\-]\d{1,2}(?:[/.\-]\d{1,2})?(?:\s*[~～\-]\s*\d{2,4}[/.\-]\d{1,2}(?:[/.\-]\d{1,2})?)?\s*)?")
SCANNED_MIN_TEXT = 40


def direction(text: str) -> str | None:
    """標題（連結文字＋檔名）看得出是年度接受／支付清冊就回傳方向；每月徵信、芳名錄回 None。"""
    t = re.sub(r"[\s()（）]", "", text or "")  # 「補(捐)助」→「補捐助」
    if NOT_ANNUAL_RE.search(t):
        return None
    if PAY_RE.search(t):
        return PAY
    if RECEIVE_RE.search(t) or GENERIC_RE.search(t):
        return RECEIVE
    return None


@dataclass
class RawRow:
    name: str
    amount: int


@dataclass
class Parsed:
    format: str  # pdf | xlsx | ods | html
    rows: list[RawRow]
    scanned: bool = False


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("　", " ")).strip()


def _name_ok(name: str) -> bool:
    return bool(name) and len(name) <= MAX_NAME and not NOT_A_NAME_RE.search(name) and not name.isdigit()


def rows_from_table(table: Iterable[list[str]]) -> list[RawRow]:
    """表格（每列一串格子）→ 名稱與金額。表頭要同時有名稱欄與金額欄；同一份檔可以有好幾段表頭（分頁、分表）。"""
    out: list[RawRow] = []
    name_i = amount_i = None
    for cells in table:
        cells = [_clean(c) for c in cells]
        ni = next((i for i, c in enumerate(cells) if c and NAME_HEADER_RE.search(c) and len(c) <= 20), None)
        ai = next((i for i, c in enumerate(cells) if c and AMOUNT_HEADER_RE.search(c) and len(c) <= 20), None)
        if ni is not None and ai is not None and ni != ai:
            name_i, amount_i = ni, ai
            continue
        if name_i is None or amount_i is None:
            continue
        name = cells[name_i] if name_i < len(cells) else ""
        amount = money(cells[amount_i]) if amount_i < len(cells) else None
        if amount and _name_ok(name):
            out.append(RawRow(name, amount))
    return out


# ---- 文字 PDF ----

def _pdf_lines(data: bytes) -> Iterator[list[tuple[float, float, str]]]:
    """每一頁每一列（同一條水平線上的字）：[(x 左, x 右, 字)…]，由上往下。"""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextLine

    for page in extract_pages(BytesIO(data)):
        chunks: list[tuple[float, float, float, str]] = []

        def walk(obj):
            if isinstance(obj, LTTextLine):
                text = _clean(obj.get_text())
                if text:
                    chunks.append(((obj.y0 + obj.y1) / 2, obj.x0, obj.x1, text))
            elif hasattr(obj, "__iter__"):
                for child in obj:
                    walk(child)

        walk(page)
        rows: dict[float, list[tuple[float, float, str]]] = {}
        for y, x0, x1, text in chunks:
            key = next((k for k in rows if abs(k - y) <= 3), y)
            rows.setdefault(key, []).append((x0, x1, text))
        for y in sorted(rows, reverse=True):
            yield sorted(rows[y])


def parse_pdf(data: bytes) -> Parsed:
    try:
        lines = list(_pdf_lines(data))
    except Exception:  # 壞檔、加密檔：當成讀不出來
        return Parsed("pdf", [], scanned=True)
    if sum(len(t) for line in lines for _, _, t in line) < SCANNED_MIN_TEXT:
        return Parsed("pdf", [], scanned=True)
    return Parsed("pdf", rows_from_pdf_lines(lines))


def rows_from_pdf_lines(lines: Iterable[list[tuple[float, float, str]]]) -> list[RawRow]:
    """PDF 的每一列（[(x 左, x 右, 字)…]）→ 名稱與金額。"""
    out: list[RawRow] = []
    amount_x: float | None = None  # 金額欄表頭的中心
    carry = ""  # 名稱太長折到上一行、這一列名稱格空著時接回去
    for line in lines:
        texts = [t for _, _, t in line]
        amount_head = [(x0 + x1) / 2 for x0, x1, t in line if AMOUNT_HEADER_RE.search(t) and len(t) <= 20]
        if amount_head and any(NAME_HEADER_RE.search(t) and len(t) <= 20 for t in texts):
            amount_x = amount_head[0]
            carry = ""
            continue
        if amount_x is None:
            continue
        # 字擠在一起時「依位置分欄」會把貼著日期的名稱分錯欄：金額＝離金額表頭最近的純數字格，
        # 名稱＝金額左邊、去掉序號與日期後還有字的格（序號、日期、名稱、金額、備註是常見順序，備註在金額右邊不讀）
        numbers = [(abs((x0 + x1) / 2 - amount_x), i) for i, (x0, x1, t) in enumerate(line) if MONEY_CELL_RE.match(t)]
        if not numbers:
            name = " ".join(n for n in (LEADING_NO_DATE_RE.sub("", t) for _, _, t in line) if n and not NO_DATE_ONLY_RE.match(n))
            # 只有名稱、沒有金額：多半是折行的名稱，留給下一列
            carry = name if len(line) == 1 else ""
            continue
        amount_i = min(numbers)[1]
        amount = money(line[amount_i][2])
        parts = [LEADING_NO_DATE_RE.sub("", t) for _, _, t in line[:amount_i]]
        name = _clean(" ".join(p for p in parts if p and not NO_DATE_ONLY_RE.match(p)))
        if carry and not _name_ok(name):
            name = carry  # 名稱折到上一行，這一列名稱格放的是說明（「補助辦理…計畫乙案」）或空的
        carry = ""
        if _name_ok(name):
            out.append(RawRow(name, amount))
    return out


# ---- Excel / ODS / 網頁表格 ----

def parse_xlsx(data: bytes) -> Parsed:
    from openpyxl import load_workbook

    wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    rows: list[RawRow] = []
    for ws in wb.worksheets:
        rows.extend(rows_from_table(["" if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)))
    return Parsed("xlsx", rows)


_NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_ROW = f"{{{_NS_TABLE}}}table-row"


def parse_ods(data: bytes) -> Parsed:
    def table() -> Iterator[list[str]]:
        with zipfile.ZipFile(BytesIO(data)) as zf, zf.open("content.xml") as fh:
            for _event, elem in iterparse(fh, events=("end",)):
                if elem.tag == _ROW:
                    yield donors._cells(elem)
                    elem.clear()

    return Parsed("ods", rows_from_table(table()))


def parse_html(html: str) -> Parsed:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[RawRow] = []
    for t in soup.find_all("table"):
        rows.extend(rows_from_table([c.get_text(" ") for c in tr.find_all(["td", "th"])] for tr in t.find_all("tr")))
    return Parsed("html", rows)


def file_format(url: str, content: bytes, content_type: str = "") -> str | None:
    path = url.lower().split("?", 1)[0]
    if content.startswith(b"%PDF"):
        return "pdf"
    if content.startswith(b"PK"):
        if path.endswith(".ods") or b"opendocument.spreadsheet" in content[:200]:
            return "ods"
        return "xlsx"
    if "html" in content_type or content.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
        return "html"
    return None  # 舊版 .xls、Word 檔、圖片：不讀


def parse(url: str, content: bytes, content_type: str = "") -> Parsed | None:
    fmt = file_format(url, content, content_type)
    try:
        if fmt == "pdf":
            return parse_pdf(content)
        if fmt == "xlsx":
            return parse_xlsx(content)
        if fmt == "ods":
            return parse_ods(content)
        if fmt == "html":
            return parse_html(content.decode("utf-8", errors="replace"))
    except Exception:  # 壞檔：跳過這一份
        return None
    return None


# 清冊上常把「捐贈／補助」接在機關名後面（公視：「文化部捐贈」「教育部補助」）
TRAILING_KIND_RE = re.compile(r"\s*(?:捐贈|補助|捐助|補\(?捐\)?助|獎助)$")
# 政府機關與基金：donors.py 沒認出來的縮寫（「原民會」「衛福部」）與「…發展基金」
GOV_SUFFIX_RE = re.compile(r"(?:部|署|局|會|府|院|處|公所|基金)$")


def clean_name(name: str) -> str:
    return TRAILING_KIND_RE.sub("", donors.normalize(name)) or donors.normalize(name)


def kind_of(name: str) -> str:
    kind = donors.classify(name)
    if kind == donors.INDIVIDUAL and GOV_SUFFIX_RE.search(name):
        return donors.GROUP
    return kind


def summarize(direction_: str, rows: list[RawRow], threshold: int = donors.DEFAULT_INDIVIDUAL_THRESHOLD) -> dict:
    """一份清冊＝一個組織一個年度。
    接受清冊：企業、團體全留；個人同一份累計達門檻才留姓名，其餘只留人數與金額（同衛福部清冊的規則）。
    支付清冊：受捐者只留團體與企業（之後對組織用）；個人受助者（喪葬補助、獎學金）一律不留姓名。"""
    kept: list[dict] = []
    individuals: dict[str, list[dict]] = defaultdict(list)
    summary = {"total_rows": 0, "total_amount": 0, "small_individual_count": 0, "small_individual_amount": 0,
               "anonymous_rows": 0, "anonymous_amount": 0, "threshold": threshold}
    for r in rows:
        summary["total_rows"] += 1
        summary["total_amount"] += r.amount
        name = clean_name(r.name)
        kind = kind_of(name)
        row = {"name": name, "kind": kind, "amount": r.amount}
        if kind == donors.ANONYMOUS:
            summary["anonymous_rows"] += 1
            summary["anonymous_amount"] += r.amount
        elif kind == donors.INDIVIDUAL:
            individuals[donors.identity_key(name)].append(row)
        else:
            kept.append(row)
    for rs in individuals.values():
        total = sum(x["amount"] for x in rs)
        if direction_ == RECEIVE and total >= threshold:
            kept.extend(rs)
        else:
            summary["small_individual_count"] += 1
            summary["small_individual_amount"] += total
    return {"summary": summary, "rows": kept}
