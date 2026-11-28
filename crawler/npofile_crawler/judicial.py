"""司法院法人登記公告（LK-31）：全國社團法人、財團法人的設立、變更、解散、清算登記。

列表 https://www.judicial.gov.tw/tw/lp-144-1-{頁}-{每頁筆數}.html（新的在前；每頁 20／40／60 筆，最早到 108-12-10），
每筆有法院別、登記案號、登記號數、類別、法人名稱、案由、公告日期、內頁連結（/tw/cp-144-…-1.html）。
內頁是法院公告全文，裡面有董事、監察人、聲請人、登記處主任的姓名——**一律不存**，只取：
登記日期、財產總額、變更了哪幾類事項（固定的類別名稱，不留原文）。

詳細資料所在的「法人及夫妻財產登記公告系統」aomp109.judicial.gov.tw 的 robots.txt 是 `Disallow: /`，
這裡只請求 www.judicial.gov.tw，`_get` 會擋掉其他主機。

名稱對組織：照 LK-19 的規則（正規化後完全相同且唯一）；同名的不只一個時，用登記法院管轄的縣市挑，
挑完剩一個才算。對不到的也回傳（ubn 空白），後端記下、不顯示，後台可以手動指定。
"""

from __future__ import annotations

import html as htmllib
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .grants import normalize
from .http import PoliteClient
from .items import Item

SOURCE_NAME = "司法院 法人登記公告"
HOST = "www.judicial.gov.tw"
BASE = f"https://{HOST}"
LIST_URL = BASE + "/tw/lp-144-1-{page}-{size}.html"
LIST_PAGE = BASE + "/tw/lp-144-1.html"
PAGE_SIZE = 60
# 列表查得到的最早公告日（更早的在舊網站，不抓）：回補抓到這天以前就算補齊
FLOOR = date(2019, 12, 9)

CASE_TYPES = {
    "設立登記": "setup",
    "變更登記": "change",
    "解散登記": "dissolution",
    "清算人任免或變更登記": "liquidator",
    "清算終結登記": "liquidation_end",
}
CATEGORIES = {"社團": "association", "財團": "foundation"}

# 法院 → 管轄的縣市（只在同名組織不只一個時用來挑）
COURT_COUNTIES = {
    "臺灣臺北地方法院": ("臺北市", "新北市"),
    "臺灣士林地方法院": ("臺北市", "新北市"),
    "臺灣新北地方法院": ("新北市",),
    "臺灣桃園地方法院": ("桃園市",),
    "臺灣新竹地方法院": ("新竹縣", "新竹市"),
    "臺灣苗栗地方法院": ("苗栗縣",),
    "臺灣臺中地方法院": ("臺中市",),
    "臺灣南投地方法院": ("南投縣",),
    "臺灣彰化地方法院": ("彰化縣",),
    "臺灣雲林地方法院": ("雲林縣",),
    "臺灣嘉義地方法院": ("嘉義縣", "嘉義市"),
    "臺灣臺南地方法院": ("臺南市",),
    "臺灣高雄地方法院": ("高雄市",),
    "臺灣橋頭地方法院": ("高雄市",),
    "臺灣屏東地方法院": ("屏東縣",),
    "臺灣臺東地方法院": ("臺東縣",),
    "臺灣花蓮地方法院": ("花蓮縣",),
    "臺灣宜蘭地方法院": ("宜蘭縣",),
    "臺灣基隆地方法院": ("基隆市", "新北市"),
    "臺灣澎湖地方法院": ("澎湖縣",),
    "福建金門地方法院": ("金門縣",),
    "福建連江地方法院": ("連江縣",),
}

# 變更事項的類別：依編號標題的關鍵字分，存類別名稱、不存原文（原文常帶董監事姓名）
CHANGE_KINDS = (
    ("法人名稱", ("名稱",)),
    ("主事務所", ("事務所", "地址")),
    ("目的", ("目的",)),
    ("財產總額", ("財產",)),
    ("章程", ("章程",)),
    ("存立時期", ("存立",)),
    ("董監事", ("董事", "理事", "監事", "監察人", "代表")),
)
IGNORED_CHANGE = ("印鑑", "圖記")

ROC_DATE_RE = re.compile(r"(\d{2,3})-(\d{1,2})-(\d{1,2})")
REGISTERED_RE = re.compile(r"於中華民國\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*登記")
# 「財產總額：新臺幣0元」「財產總額為新臺幣3,000萬元」；「最低捐助財產總額新台幣3,000萬元」（沒有冒號或「為」）不算
PROPERTY_RE = re.compile(r"財產總額\s*(?:[：:]|變更為|為)\s*新[臺台]幣\s*([0-9０-９,，.]+)\s*(億|萬)?\s*元")
NUMBERED_RE = re.compile(r"^\s*[一二三四五六七八九十]+\s*、\s*(.*)$")


def registration_id(court: str, case_no: str) -> str:
    """同一筆＝法院＋登記案號。"""
    return f"{court}|{case_no}"


def _roc(text: str) -> date | None:
    m = ROC_DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el is not None else ""


def parse_list(html: str) -> tuple[list[dict], int | None]:
    """列表頁 → （每筆公告, 最後一頁頁碼；讀不到是 None）。"""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table.table_sprite tbody tr"):
        cells = {td.get("data-title"): td for td in tr.find_all("td")}
        court = _text(cells.get("法院別"))
        case_no = _text(cells.get("登記案號"))
        name = _text(cells.get("法人名稱"))
        if not (court and case_no and name):
            continue
        link = cells.get("公告內容").find("a") if cells.get("公告內容") else None
        case_label = _text(cells.get("案由"))
        rows.append({
            "court": court,
            "case_no": case_no,
            "reg_no": _text(cells.get("登記號數")),
            "category": CATEGORIES.get(_text(cells.get("類別")), ""),
            "name": name,
            "case_type": CASE_TYPES.get(case_label, ""),
            "case_label": case_label,
            "posted_on": _roc(_text(cells.get("公告日期"))),
            "url": urljoin(BASE + "/tw/", link["href"]) if link and link.get("href") else "",
        })
    last = None
    a = soup.select_one("ul.page li.last a")
    if a and (m := re.search(r"lp-144-1-(\d+)-\d+\.html", a.get("href", ""))):
        last = int(m.group(1))
    else:
        pages = [int(x) for x in re.findall(r"lp-144-1-(\d+)-\d+\.html", html)]
        last = max(pages) if pages else None
    return rows, last


def _lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    cp = soup.select_one("section.cp") or soup
    for br in cp.find_all(["br"]):
        br.replace_with("\n")
    out = []
    for block in cp.find_all(["div", "p"]) or [cp]:
        if block.find(["div", "p"]):
            continue
        text = htmllib.unescape(block.get_text("", strip=False)).replace("　", " ")
        out.extend(t.strip() for t in text.split("\n") if t.strip())
    return out


def _amount(digits: str, unit: str | None) -> int | None:
    digits = digits.translate(str.maketrans("０１２３４５６７８９，", "0123456789,")).replace(",", "")
    try:
        value = float(digits)
    except ValueError:
        return None
    return int(round(value * {"億": 100_000_000, "萬": 10_000}.get(unit or "", 1)))


def change_kinds(lines: Iterable[str]) -> list[str]:
    """編號標題（一、二、…）→ 變更了哪幾類事項（固定類別名稱，依 CHANGE_KINDS 的順序，不重複）。"""
    found: set[str] = set()
    for line in lines:
        m = NUMBERED_RE.match(line)
        if not m:
            continue
        head = re.split(r"[：:。]", m.group(1), maxsplit=1)[0]
        if any(k in head for k in IGNORED_CHANGE) and not any(k in head for k in ("名稱", "事務所", "財產")):
            continue
        kind = next((label for label, keys in CHANGE_KINDS if any(k in head for k in keys)), "其他")
        found.add(kind)
    order = [label for label, _ in CHANGE_KINDS] + ["其他"]
    return [k for k in order if k in found]


def parse_detail(html: str, case_type: str = "") -> dict:
    """內頁 → 組織層級的資料（登記日期、財產總額、變更事項類別）。不回傳任何人名或原文段落。"""
    lines = _lines(html)
    text = "".join(lines)
    data: dict = {"registered_on": None, "property_total": None, "change_items": []}
    if m := REGISTERED_RE.search(text):
        try:
            data["registered_on"] = date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    if case_type in ("setup", "change") and (m := PROPERTY_RE.search(text)):
        data["property_total"] = _amount(m.group(1), m.group(2))
    if case_type == "change":
        # 只看「變更登記事項」之後的編號標題
        start = next((i for i, l in enumerate(lines) if "變更" in l and "事項" in l), None)
        after = lines[start + 1:] if start is not None else []
        items = change_kinds(after)
        if not items and after:  # 只變更一項時常常沒有編號：「第4屆監察人姓名及住所如下：」
            items = change_kinds(["一、" + after[0]])
        data["change_items"] = items
    return data


class CourtMatcher:
    """法人名稱 → 統編。正規化後完全相同且唯一才算；同名的不只一個時，用法院管轄縣市挑，剩一個才算。"""

    def __init__(self, orgs: Iterable[tuple]):
        by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for row in orgs:
            ubn, name = row[0], row[1]
            city = row[2] if len(row) > 2 else ""
            if ubn and name:
                by_name[normalize(name)].append((ubn, (city or "").replace("台", "臺")))
        self._by_name = by_name

    def match(self, name: str, court: str = "") -> str | None:
        hits = {u: c for u, c in self._by_name.get(normalize(name), [])}
        if len(hits) == 1:
            return next(iter(hits))
        counties = COURT_COUNTIES.get(court.replace("台", "臺"), ())
        if len(hits) > 1 and counties:
            local = [u for u, c in hits.items() if c in counties]
            if len(local) == 1:
                return local[0]
        return None


def _get(client: PoliteClient, url: str):
    if urlparse(url).hostname != HOST:
        raise ValueError(f"只抓 {HOST}，不請求 {url}")
    return client.get(url)


def to_item(row: dict, ubn: str | None, detail: dict | None) -> Item:
    data = {k: row[k] for k in ("court", "case_no", "reg_no", "category", "name", "case_type", "posted_on")}
    data.update(detail or {"registered_on": None, "property_total": None, "change_items": []})
    data["detail_fetched"] = detail is not None
    return Item(
        kind="court_reg",
        ubn=ubn or "",
        external_id=registration_id(row["court"], row["case_no"]),
        source_url=row["url"] or LIST_PAGE,
        data=data,
    )


def fetch(client: PoliteClient, limit: int | None = None, orgs_city: Iterable[tuple] = (),
          seen_regs: Iterable[str] = (), floor_reached: bool = False, listed: list | None = None,
          page_size: int = PAGE_SIZE) -> Iterator[Item]:
    """從最新一頁往舊的抓。已存過的（seen_regs）跳過；對到組織的才抓內頁。

    - 補齊之後（floor_reached）：遇到整頁都存過就停——每天只抓新的。
    - 還沒補齊：遇到整頁都存過，跳到大約是「已存筆數」那一頁接著往舊的抓（上次回補被時間上限切斷的地方），
      抓到最後一頁為止。limit 算的是 Item 數。
    - listed：給一個 [0]，會累加列表上讀到幾筆（含已存過的）；一筆都讀不到＝網站改版，週末沒有新公告不算。
    """
    matcher = CourtMatcher(orgs_city)
    seen = set(seen_regs)
    stored_before = len(seen)
    count = 0
    page = 1
    jumped = False
    last: int | None = None
    while last is None or page <= last:
        rows, last_on_page = parse_list(_get(client, LIST_URL.format(page=page, size=page_size)).text)
        last = last_on_page or last or page
        if listed is not None:
            listed[0] += len(rows)
        if not rows:
            return
        fresh = [r for r in rows if registration_id(r["court"], r["case_no"]) not in seen]
        if not fresh:
            if floor_reached:
                return
            if not jumped:
                jumped = True
                page = max(page + 1, stored_before // page_size)
                continue
        for row in fresh:
            if limit is not None and count >= limit:
                return
            seen.add(registration_id(row["court"], row["case_no"]))
            ubn = matcher.match(row["name"], row["court"])
            detail = None
            if ubn and row["url"]:
                detail = parse_detail(_get(client, row["url"]).text, row["case_type"])
            count += 1
            yield to_item(row, ubn, detail)
        page += 1


def fetch_details(client: PoliteClient, url: str, case_type: str) -> dict:
    """後台手動指定組織或重新比對後補抓內頁用。"""
    return parse_detail(_get(client, url).text, case_type)


def backfill_done(oldest_posted: date | None) -> bool:
    """已存的最早一筆公告落在列表最早那個月（108 年 12 月）＝回補完了，之後每天只抓新的。"""
    return oldest_posted is not None and oldest_posted < date(2020, 1, 1)
