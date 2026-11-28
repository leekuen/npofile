"""組織官網公開的「接受捐贈名單清冊」（財團法人法第 25 條，LK-47）。

財團法人每年要主動公開去年的接受補助、捐贈名單（名稱＋金額），很多基金會放在官網，多半是有文字層的 PDF 表格
（實測善牧 112 年 1638 頁、衡山 114 年 1228 頁）。所以：
- 有文字層：本機把每頁的字依座標排回表格列，認「捐款人」「金額」（有的話「日期」）欄，不花 Claude 費用。
- 只有掃描圖：給了 Claude 讀法（financials.ClaudeExtractor／ClaudeCodeExtractor 換成 DONOR_LIST_TASK）才讀，而且頁數有上限。
讀出來的列交給 donors.summarize：企業、團體逐筆保留，個人只有累計達門檻才留姓名，其餘只留人數與金額。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Iterator
from datetime import date
from io import BytesIO

from . import donors
from .financials import Task
from .items import money

log = logging.getLogger(__name__)

# 名單檔的標題：接受捐贈／捐款的名單、清冊、名冊、芳名錄、徵信錄、捐款明細
LIST_RE = re.compile(
    r"(?:捐贈|捐款|捐助|補助|受贈).{0,6}(?:名單|清冊|名冊|芳名|徵信|明細)|芳名錄|徵信錄|捐款徵信|捐款人清冊|捐贈人清冊"
)
# 只有「支付獎助、捐贈」（組織捐出去的）：標題沒有「接受／接收／收受」才算只有支付
OUTGOING_RE = re.compile(r"支付|獎助|捐贈支出|對外捐贈")
INCOMING_RE = re.compile(r"接受|接收|收受|受贈|收到")
# 物資捐贈（沒有金額）
GOODS_RE = re.compile(r"捐物|物資|物品|實物")
# 名字被遮（「華○工業有限公司」「陳Ｏ朝」）：認不出是誰，一律當匿名
MASK_RE = re.compile(r"[○〇◯Ｏ＊*×✕●◎□]|(?<=[一-鿿])[Oo](?=[一-鿿]|$)")

# 名字後面直接接統編（善牧：「力天防災科技有限公司 24887062」）：去掉，不然同一家會變成兩位
TRAILING_UBN_RE = re.compile(r"\s+\d{8}$")

MAX_TEXT_PAGES = 5000  # 文字型名單最多解析幾頁（善牧一年 1638 頁約 16 秒）
MAX_AI_PAGES = 50  # 掃描型名單超過這個頁數就不交給 Claude（費用）
MIN_TEXT_CHARS = 30  # 前幾頁加起來少於這麼多字＝沒有文字層（掃描圖）


def is_list_title(text: str) -> bool:
    """這個標題／網址是不是「接受」捐贈的名單（支付名單、物資名單不算）。"""
    if not LIST_RE.search(text):
        return False
    if GOODS_RE.search(text) and not re.search(r"捐款", text):
        return False
    return not (OUTGOING_RE.search(text) and not INCOMING_RE.search(text))


# ---- 本機解析有文字層的 PDF ----

NAME_HEAD_RE = re.compile(r"捐款人|捐贈人|捐贈者|捐款者|捐助者|捐助人|芳名|姓名|名稱|捐款單位|捐贈單位|捐款芳名|愛心人士|捐款\s*人")
AMOUNT_HEAD_RE = re.compile(r"金額|金\s*額|捐款額|捐贈額|款額|額度")
DATE_HEAD_RE = re.compile(r"日期|日\s*期|捐款日|捐贈日")
# 支付段的表頭（受贈單位、支付對象）：遇到就跳過，直到下一個接受名單的表頭
OUT_HEAD_RE = re.compile(r"受贈|受款|受補助|支付|獎助對象|受益|發放對象")
DATE_RE = re.compile(r"^(\d{2,4})[/.\-年](\d{1,2})[/.\-月](\d{1,2})日?$")
AMOUNT_RE = re.compile(r"^\$?\s*[\d,，]+(?:\.0+)?\s*元?$")


def parse_date(text: str) -> str | None:
    """114/1/3、114.01.03、2025-01-03、114年1月3日 → ISO 日期；民國或西元都可。"""
    m = DATE_RE.match((text or "").strip().replace(" ", ""))
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    if y < 1911:
        y += 1911
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _segments(page) -> list[tuple[float, float, float, str]]:
    """一頁裡的字串片段（y 中心, x 左, x 右, 字）。"""
    tp = page.get_textpage()
    out = []
    for k in range(tp.count_rects()):
        left, bottom, right, top = tp.get_rect(k)
        text = tp.get_text_bounded(left, bottom, right, top).strip()
        if text:
            out.append(((bottom + top) / 2, left, right, text))
    tp.close()
    return out


def _rows(segments: list[tuple[float, float, float, str]], tol: float = 3.0) -> list[list[tuple[float, float, str]]]:
    """依 y 把片段排成表格列（由上往下），每列的片段由左到右。"""
    rows: list[tuple[float, list[tuple[float, float, str]]]] = []
    for y, left, right, text in sorted(segments, key=lambda s: -s[0]):
        if rows and abs(rows[-1][0] - y) <= tol:
            rows[-1][1].append((left, right, text))
        else:
            rows.append((y, [(left, right, text)]))
    return [sorted(cells) for _, cells in rows]


def _header(cells: list[tuple[float, float, str]]) -> tuple[str, list[tuple[str, float]]] | None:
    """這列是不是表頭：回傳（in｜out, [(欄位, x 中心)…]）；接受名單要同時有捐款人與金額兩欄。"""
    cols: list[tuple[str, float]] = []
    out = False
    for left, right, text in cells:
        t = text.replace(" ", "")
        if len(t) > 12:
            continue
        mid = (left + right) / 2
        if OUT_HEAD_RE.search(t):
            out = True
            cols.append(("name", mid))
        elif AMOUNT_HEAD_RE.search(t):
            cols.append(("amount", mid))
        elif DATE_HEAD_RE.search(t):
            cols.append(("date", mid))
        elif NAME_HEAD_RE.search(t):
            cols.append(("name", mid))
        else:
            cols.append(("other", mid))
    labels = {c for c, _ in cols}
    if "name" not in labels or "amount" not in labels:
        return None
    return ("out" if out else "in"), cols


def _blocks(cols: list[tuple[str, float]]) -> list[dict[str, int]]:
    """表頭裡的每一組（日期？、捐款人、金額）：芳名錄常把兩三組並排在同一頁。回傳每組各欄在 cols 的位置。"""
    names = [i for i, (c, _) in enumerate(cols) if c == "name"]
    blocks = []
    for n, i in enumerate(names):
        nxt = names[n + 1] if n + 1 < len(names) else len(cols)
        prev = names[n - 1] if n > 0 else -1
        amount = next((j for j in range(i + 1, nxt) if cols[j][0] == "amount"), None)
        if amount is None:
            continue
        block = {"name": i, "amount": amount}
        dates = [j for j in range(prev + 1, nxt) if cols[j][0] == "date"]
        if dates:
            block["date"] = min(dates, key=lambda j: abs(j - i))
        blocks.append(block)
    return blocks


def _assign(cells: list[tuple[float, float, str]], cols: list[tuple[str, float]]) -> list[str]:
    """每個片段放進 x 最近的欄；同一欄的片段接起來（名字中間有空白時會被拆成兩段）。"""
    values = [""] * len(cols)
    for left, right, text in cells:
        mid = (left + right) / 2
        i = min(range(len(cols)), key=lambda k: abs(cols[k][1] - mid))
        values[i] = f"{values[i]} {text}".strip() if values[i] else text
    return values


SECTION_RE = re.compile(r"名單|清冊|名冊|芳名|徵信|明細")


def _section(cells: list[tuple[float, float, str]]) -> str | None:
    """段落標題列（「113年度支付獎助、捐贈名單清冊」「接受捐贈名單」）→ out｜in；不是標題列回 None。
    官網連結寫「補助及捐贈清冊」、檔案第一頁才寫「支付獎助」的（萬海），靠這個跳過整段。"""
    text = "".join(t for *_, t in cells).replace(" ", "")
    if len(text) > 80 or not SECTION_RE.search(text):
        return None
    incoming, outgoing = bool(INCOMING_RE.search(text)), bool(OUTGOING_RE.search(text))
    if outgoing and not incoming:
        return "out"
    if incoming and not outgoing:
        return "in"
    return None  # 「接受及支付捐贈名單」這種總標題：看接下來的表頭


def table_rows(pages: Iterable[list[tuple[float, float, float, str]]]) -> list[donors.DonorRow]:
    """每頁的字串片段 → 名單上的每一列捐款。表頭只出現在第一頁時，後面的頁沿用同一組欄位位置。
    遇到支付段（段落標題寫支付獎助、或表頭是受贈單位）就跳過，直到下一段接受名單。"""
    rows: list[donors.DonorRow] = []
    cols: list[tuple[str, float]] | None = None
    mode = "in"
    for segments in pages:
        for cells in _rows(segments):
            head = _header(cells)
            if head is not None:
                kind, cols = head
                if kind == "out":
                    mode = "out"
                continue
            section = _section(cells)
            if section is not None:
                mode = section
                continue
            if cols is None or mode == "out":
                continue
            values = _assign(cells, cols)
            for b in _blocks(cols):
                name = values[b["name"]].strip()
                raw_amount = values[b["amount"]].replace(" ", "")
                if not name or not AMOUNT_RE.match(raw_amount) or NAME_HEAD_RE.fullmatch(name):
                    continue
                amount = money(raw_amount)
                if not amount:
                    continue
                d = parse_date(values[b["date"]]) if "date" in b else None
                rows.append(donors.DonorRow("", d, name, amount, ""))
    return rows


def text_rows(pdf: bytes, max_pages: int = MAX_TEXT_PAGES) -> Iterator[donors.DonorRow] | None:
    """有文字層的名單 → 逐列；沒有文字層（掃描圖）回 None。讀不出任何表頭時回空的。"""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(BytesIO(pdf))
    try:
        sample = sum(len(t) for i in range(min(3, len(doc))) for *_, t in _segments(doc[i]))
        if sample < MIN_TEXT_CHARS:
            return None
        return iter(table_rows(_segments(doc[i]) for i in range(min(len(doc), max_pages))))
    finally:
        doc.close()


def page_count(pdf: bytes) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(BytesIO(pdf))
    try:
        return len(doc)
    finally:
        doc.close()


# ---- 掃描圖交給 Claude ----

AI_SCHEMA = {
    "type": "object",
    "properties": {
        "is_incoming_list": {"type": "boolean"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "amount": {"type": ["integer", "null"]},
                    "date": {"type": ["string", "null"]},
                },
                "required": ["name", "amount", "date"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["is_incoming_list", "rows", "notes"],
    "additionalProperties": False,
}

AI_PROMPT = """這是一個台灣非營利組織在官網公開的捐款名單（標題：{title}，網站上標示的年度：民國 {year} 年）。
請列出名單上「捐給這個組織」的捐款，但只列這兩種：
1. 公司、行號、工作室、基金會、協會、學校、宗教團體、政府機關等「不是個人」的捐款人，每一筆都列；
2. 個人單筆 10 萬元（含）以上的。
其他個人小額捐款、「善心人士」「無名氏」這類匿名的都不要列。

規則：
- name 照名單上的寫法抄（不要補字、不要猜）；名字被遮（例：「華○工業有限公司」）的不要列。
- amount 是新臺幣「元」的整數；名單寫「單位：千元」就乘以 1000。物資捐贈沒有金額的不要列。
- date 有日期就寫成 YYYY-MM-DD（民國 114 年＝西元 2025 年），沒有就填 null。
- 名單裡如果有「支付獎助、捐贈」（組織捐給別人的）那一段，不要列。
- is_incoming_list：這份檔案是「接受捐款」的名單才填 true；只有支付名單、財報、活動成果就填 false，rows 留空。
- notes：一句話寫出讀了哪幾頁、有沒有不確定的地方（繁體中文）。"""


def _ai_clean(raw: dict, hint_year: int) -> dict | None:
    if not raw.get("is_incoming_list"):
        return None
    rows = []
    for r in raw.get("rows") or []:
        name = str(r.get("name") or "").strip()
        amount = r.get("amount")
        if not name or not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            continue
        rows.append({"name": name[:200], "amount": amount, "date": parse_date(str(r.get("date") or ""))})
    return {"rows": rows, "notes": str(raw.get("notes") or "")[:300], "method": "ai"}


DONOR_LIST_TASK = Task("donorlists", AI_SCHEMA, AI_PROMPT, _ai_clean, max_tokens=32000)

AiReader = Callable[[bytes, int, str], "dict | None"]


def year_end(year_roc: int) -> str:
    return date(year_roc + 1911, 12, 31).isoformat()


def is_masked(name: str) -> bool:
    return bool(MASK_RE.search(name))


def read(pdf: bytes, year: int, title: str, ai: AiReader | None = None,
         threshold: int = donors.DEFAULT_INDIVIDUAL_THRESHOLD) -> dict | None:
    """一份名單 → {method, rows（要保留的）, summary}；讀不到（掃描圖又沒有 Claude、或沒有任何捐款列）回 None。

    只有年度沒有日期的列，捐款日期記成該年 12 月 31 日。名字被遮的當匿名。"""
    try:
        parsed = text_rows(pdf)
    except Exception as exc:  # 壞檔、加密：這份略過
        log.info("donorlists: cannot parse %s (%s)", title, exc)
        return None
    method = "text"
    if parsed is None:
        if ai is None:
            return None
        try:
            pages = page_count(pdf)
        except Exception:
            return None
        if pages > MAX_AI_PAGES:
            log.info("donorlists: %s 是 %d 頁的掃描檔，超過 %d 頁不讀", title, pages, MAX_AI_PAGES)
            return None
        got = ai(pdf, year, title)
        if not got:
            return None
        method = "ai"
        parsed = iter([donors.DonorRow("", r["date"], r["name"], r["amount"], "") for r in got["rows"]])
    fallback = year_end(year)
    masked = {"rows": 0, "amount": 0}

    def unmask(rows: Iterator[donors.DonorRow]) -> Iterator[donors.DonorRow]:
        for r in rows:
            r.donated_on = r.donated_on or fallback
            r.name = TRAILING_UBN_RE.sub("", r.name.strip())
            if is_masked(r.name):
                masked["rows"] += 1
                masked["amount"] += r.amount
                r.name = "匿名"  # donors.classify 會當成匿名
            yield r

    result = donors.summarize(unmask(parsed), threshold)
    if result["summary"]["total_rows"] == 0:
        return None
    result["summary"]["masked_rows"] = masked["rows"]
    result["summary"]["masked_amount"] = masked["amount"]
    for r in result["rows"]:
        r.pop("receipt_no", None)
        r.pop("purpose", None)
    return {"method": method, **result}
