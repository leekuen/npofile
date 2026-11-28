"""企業依法公開的捐贈（LK-49）：哪家公司捐了多少給哪個組織。

1. 公開資訊觀測站重大訊息（上市＋上櫃）：董事會通過對關係人的捐贈、對非關係人的重大捐贈要發重大訊息，
   內容是固定格式「1.事實發生日 2.捐贈原由 3.捐贈金額 4.受贈對象 5.與公司關係…」。
   `ajax_t05st02` 依日期列出當天所有公司的重大訊息（含全文），逐日讀、挑出捐贈公告。
   查太快會回「查詢過於頻繁」：每次間隔幾秒，被擋就等一分鐘再試。
2. 保險業公開資訊觀測站「捐贈情形表」（`Info4-21.aspx?UID=<統編>`）：人身／財產保險業辦理資訊公開管理辦法
   第 8 條第 1 項第 16 款，每家保險公司逐筆公開對政黨、利害關係人及公益團體的捐贈（類別、受贈團體、日期、金額、備註）。
   公司清單從同一站「保險資訊公開查詢」的下拉選單讀（壽險、產險），不用自己維護網址。

受贈對象只有名稱：用組織名冊（`orgs`）對統編，規則同政府補助（名稱正規化後完全相同且唯一）。
對不到的、捐給政黨的照樣回傳（統編空白），後端放進審核清單只給管理員看，前台不出現。
金額寫成範圍或讀不出數字的，金額留空、原文放 amount_text（前台照原文顯示、不算進加總）。
捐款者只帶名稱與代號／統編，後端再對到上市櫃公司全名與統編、建成企業捐款人。
"""

from __future__ import annotations

import hashlib
import html
import re
import time
from collections.abc import Iterable, Iterator
from datetime import date, timedelta

from .grants import OrgMatcher, normalize
from .http import PoliteClient
from .items import Item, roc_date

MOPS_SOURCE_NAME = "公開資訊觀測站重大訊息（企業捐贈）"
MOPS_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st02"
MOPS_PAGE = "https://mops.twse.com.tw/mops/#/web/t05st02"
INS_SOURCE_NAME = "保險業公開資訊觀測站（捐贈情形表）"
INS_INDEX = "https://ins-info.ib.gov.tw/customer/announceinfo.aspx"
INS_PAGE = "https://ins-info.ib.gov.tw/customer/Info4-21.aspx?UID={uid}"

MOPS_INTERVAL = 5.0  # 秒；抽樣時 3 秒一次，31 天裡有 3 天被擋
THROTTLE_WAIT = 60.0
THROTTLE_TRIES = 3
THROTTLED_RE = re.compile(r"查詢過於頻繁|查詢過量|請稍後再查詢")


# ---- 金額 ----

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "貳": 2, "兩": 2, "三": 3, "參": 3, "叁": 3, "四": 4, "肆": 4,
              "五": 5, "伍": 5, "六": 6, "陸": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}
_CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CN_BIG = {"萬": 10_000, "億": 100_000_000}
_CN_RE = re.compile(r"[零〇一壹二貳兩三參叁四肆五伍六陸七柒八捌九玖十拾百佰千仟萬億]+")
_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(億|萬|千)?")
# 範圍：「20-30萬」「20～30萬」「20至30萬」「最高 30 萬」「不超過…」「以內」「為上限」
_RANGE_RE = re.compile(r"\d\s*[-－~～〜至到]\s*\d|上限|以內|不超過|最高|最多|預估|約")


def _cn_number(text: str) -> int | None:
    total, section, digit = 0, 0, 0
    for ch in text:
        if ch in _CN_DIGITS:
            digit = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            section += (digit or 1) * _CN_UNITS[ch]
            digit = 0
        elif ch in _CN_BIG:
            total += (section + digit) * _CN_BIG[ch]
            section = digit = 0
    value = total + section + digit
    return value or None


def parse_amount(text: str) -> int | None:
    """「新台幣130萬元」→ 1300000；「新臺幣 4,870,204 元」→ 4870204；「新台幣壹佰萬元」→ 1000000。
    範圍、上限、約略的（「20-30萬元」「最高 30 萬」）與讀不出數字的回 None。"""
    text = (text or "").translate(str.maketrans("０１２３４５６７８９，．", "0123456789,."))
    if not text or _RANGE_RE.search(text):
        return None
    m = _NUM_RE.search(text)
    if m:
        value = float(m.group(1).replace(",", ""))
        value *= {"億": 100_000_000, "萬": 10_000, "千": 1000}.get(m.group(2) or "", 1)
        return int(round(value)) or None
    m = _CN_RE.search(text.replace("新臺幣", "").replace("新台幣", ""))
    return _cn_number(m.group(0)) if m else None


# ---- 共用 ----

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip(" 　。．.;；")


def gift_id(prefix: str, *parts: str) -> str:
    return prefix + hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:20]


PARTY_RE = re.compile(r"(民主進步|國民|時代力量|民眾|親民|台灣基進|綠|社會民主|新)黨")


def is_party(name: str, category: str = "") -> bool:
    return "政黨" in (category or "") or bool(PARTY_RE.search(name or ""))


def _gift_item(matcher: OrgMatcher, *, recipient: str, external_id: str, source_url: str, data: dict) -> Item:
    party = is_party(recipient, data.get("category", ""))
    hit = None if party else matcher.match(recipient)
    return Item(
        "gift", hit[0] if hit else "",
        {"recipient": recipient[:300], "party": party, **data},
        source_url=source_url, external_id=external_id,
    )


# ---- 公開資訊觀測站重大訊息 ----

_FORM_RE = re.compile(r"<form\b[^>]*>(.*?)</form>", re.S | re.I)
_HIDDEN_RE = re.compile(r"<input type='hidden' name='(h\d+)' value='([^']*)'", re.S)
_TYPEK_RE = re.compile(r'TYPEK\.value="(\w+)"')
_FIELD_RE = re.compile(r"(?:^|\n)\s*\d+\s*[.．、]\s*([^:：\n]{2,20})[:：]\s*(.*?)(?=\n\s*\d+\s*[.．、]\s*[^:：\n]{2,20}[:：]|\Z)", re.S)
SUBSIDIARY_RE = re.compile(r"代(?:重要)?子公司(.+?)公告")


def detail_fields(text: str) -> dict[str, str]:
    """「1.事實發生日:114/11/20\n2.捐贈原由:…」→ {"事實發生日": "114/11/20", "捐贈原由": "…"}。"""
    out: dict[str, str] = {}
    for m in _FIELD_RE.finditer(html.unescape(text or "").replace("\r", "")):
        out.setdefault(re.sub(r"\s+", "", m.group(1)), m.group(2).strip())
    return out


def parse_mops_day(page: str) -> tuple[int, list[dict]]:
    """一天的重大訊息頁 →（公告總數, 捐贈公告）。每則公告是一個表單，隱藏欄位依序是
    公司簡稱、代號、發言日期、時間、主旨、序號、條款、事實發生日、說明。"""
    total = 0
    gifts: list[dict] = []
    for form in _FORM_RE.findall(page):
        values = [html.unescape(v) for _, v in _HIDDEN_RE.findall(form)]
        if len(values) < 9:
            continue
        total += 1
        short, code, spoke, _, subject, _, clause, _, detail = values[-9:]
        fields = detail_fields(detail)
        if not (fields.get("捐贈金額") is not None and fields.get("受贈對象") is not None):
            continue
        m = _TYPEK_RE.search(form)
        sub = SUBSIDIARY_RE.search(subject)
        gifts.append({
            "company_code": code.strip(), "company_short": short.strip(), "market": m.group(1) if m else "",
            "subsidiary": _clean(sub.group(1)) if sub else "",
            "subject": _clean(subject), "spoke_on": spoke.strip(), "clause": clause.strip(),
            "fact_on": fields.get("事實發生日", ""), "purpose": _clean(fields.get("捐贈原由", "")),
            "amount_text": _clean(fields.get("捐贈金額", "")), "recipient": _clean(fields.get("受贈對象", "")),
            "relation": _clean(fields.get("與公司關係", "")),
        })
    return total, gifts


def _western(spoke: str) -> date | None:
    try:
        return date(int(spoke[:4]), int(spoke[4:6]), int(spoke[6:8]))
    except (ValueError, IndexError):
        return None


def mops_items(gifts: Iterable[dict], matcher: OrgMatcher, day: date) -> Iterator[Item]:
    for g in gifts:
        if not g["recipient"]:
            continue
        on = roc_date(g["fact_on"]) or _western(g["spoke_on"]) or day
        amount = parse_amount(g["amount_text"])
        donor = g["subsidiary"] or g["company_short"].rstrip("*＊ ")  # 簡稱後的 * 是外國企業的標記
        yield _gift_item(
            matcher, recipient=g["recipient"],
            # 同一則重發（更正、上市上櫃各發一次、母子公司各發）：同公司、同日、同對象、同金額只留一筆
            external_id=gift_id("m", g["company_code"], g["subsidiary"], on.isoformat(), normalize(g["recipient"]),
                                str(amount if amount is not None else g["amount_text"])),
            source_url=MOPS_PAGE,
            data={
                "donor_name": donor[:200], "company_code": g["company_code"], "company_short": g["company_short"],
                "subsidiary": g["subsidiary"], "donor_ubn": "", "donated_on": on, "amount": amount,
                "amount_text": "" if amount is not None else g["amount_text"][:100],
                "purpose": g["purpose"][:200], "relation": g["relation"][:200], "subject": g["subject"][:300],
                "category": "", "note": "",
            },
        )


def window_start(since_roc: int | None) -> date:
    return date(since_roc + 1911, 1, 1) if since_roc else date.today() - timedelta(days=5 * 365)


def fetch_mops(client: PoliteClient, limit: int | None = None, *, since_roc: int | None = None,
               orgs: Iterable[tuple[str, str]] = (), since_date: date | None = None,
               listed: list[int] | None = None, today: date | None = None,
               sleep=time.sleep) -> Iterator[Item]:
    """從今天往回逐日讀到 since_date（上次讀完的日子往前推一段；沒有就讀到近 5 年的開頭）。
    limit 算的是天數。被擋超過 THROTTLE_TRIES 次的那天略過（下一輪整段重讀時會再試）。"""
    matcher = OrgMatcher(orgs)
    today = today or date.today()
    floor = max(since_date, window_start(since_roc)) if since_date else window_start(since_roc)
    day, days = today, 0
    while day >= floor and (limit is None or days < limit):
        roc = day.year - 1911
        form = {"encodeURIComponent": "1", "step": "1", "step00": "0", "firstin": "1", "off": "1", "TYPEK": "all",
                "year": str(roc), "month": f"{day.month:02d}", "day": f"{day.day:02d}"}
        for _ in range(THROTTLE_TRIES):
            text = client.post(MOPS_URL, data=form).text
            if not THROTTLED_RE.search(text):
                total, gifts = parse_mops_day(text)
                if listed is not None:
                    listed[0] += total
                yield from mops_items(gifts, matcher, day)
                break
            sleep(THROTTLE_WAIT)
        sleep(max(0.0, MOPS_INTERVAL - getattr(client, "min_interval", 0.0)))  # client 本身已經隔了 min_interval
        days += 1
        day -= timedelta(days=1)


# ---- 保險業捐贈情形表 ----

_OPTION_RE = re.compile(r'<option[^>]*value="(\d{8})"[^>]*>(.*?)</option>', re.S)
_ASPNET_RE = re.compile(r'<input type="hidden" name="(__[A-Z]+)" id="[^"]*" value="([^"]*)"')
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def insurers(client: PoliteClient) -> list[tuple[str, str]]:
    """（統編, 公司名稱）：保險資訊公開查詢的公司下拉選單，壽險＋產險。"""
    page = client.get(INS_INDEX).text
    out: dict[str, str] = {}
    for kind in ("1", "2"):  # 1 壽險、2 產險
        form = {k: html.unescape(v) for k, v in _ASPNET_RE.findall(page)}
        form.update({"__EVENTTARGET": "ctl00$MainContent$ddlComapnyType", "ctl00$MainContent$ddlComapnyType": kind})
        result = client.post(INS_INDEX, data=form).text
        m = re.search(r'id="ctl00_MainContent_ddlComapnyName"[^>]*>(.*?)</select>', result, re.S)
        for uid, name in _OPTION_RE.findall(m.group(1) if m else ""):
            out.setdefault(uid, _clean(name))
    return sorted(out.items())


def _date_any(text: str) -> date | None:
    """2026-10-06、2026/10/06、115/10/06、115.10.06 → date。"""
    text = (text or "").strip()
    m = re.match(r"^(\d{2,4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    if y < 1911:
        y += 1911
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_insurer_table(page: str) -> list[dict]:
    """捐贈情形表 → [{category, recipient, donated_on, amount, amount_text, note}]。
    欄位依表頭認（捐贈對象類別、受捐贈團體名稱、捐贈日期、捐贈金額、備註），金額 0 的（多半是捐物品）金額留空、備註當原文。"""
    rows = [[_clean(_TAG_RE.sub("", c)) for c in _CELL_RE.findall(r)] for r in _ROW_RE.findall(page)]
    cols: dict[str, int] | None = None
    out: list[dict] = []
    for cells in rows:
        if cols is None:
            joined = "|".join(cells)
            if "受捐贈" in joined or ("受贈" in joined and "金額" in joined):
                def find(*keys):  # 依序試：表頭第一格常夾著「資料日期：…」，先找完整的欄名
                    return next((i for k in keys for i, c in enumerate(cells) if k in c), None)
                cols = {"category": find("捐贈對象類別", "類別"), "recipient": find("受捐贈", "受贈單位", "受贈", "團體名稱"),
                        "date": find("捐贈日期", "日期"), "amount": find("捐贈金額", "金額"), "note": find("備註", "說明")}
            continue
        def cell(key):
            i = cols.get(key)
            return cells[i] if i is not None and i < len(cells) else ""
        recipient = cell("recipient")
        on = _date_any(cell("date"))
        if not recipient or on is None:
            continue
        raw = cell("amount")
        amount = parse_amount(raw.replace("$", ""))
        note = cell("note")
        out.append({"category": cell("category"), "recipient": recipient, "donated_on": on, "amount": amount,
                    "amount_text": "" if amount else (note or raw or "未列金額")[:100], "note": note[:200]})
    return out


def fetch_insurers(client: PoliteClient, limit: int | None = None, *, since_roc: int | None = None,
                   orgs: Iterable[tuple[str, str]] = ()) -> Iterator[Item]:
    """每家保險公司一頁；近 5 年的列才收。limit 算的是公司數。"""
    matcher = OrgMatcher(orgs)
    floor = window_start(since_roc)
    for n, (uid, company) in enumerate(insurers(client)):
        if limit is not None and n >= limit:
            break
        url = INS_PAGE.format(uid=uid)
        seen: dict[str, int] = {}
        for row in parse_insurer_table(client.get(url).text):
            if row["donated_on"] < floor:
                continue
            base = gift_id("i", uid, row["donated_on"].isoformat(), normalize(row["recipient"]),
                           str(row["amount"] if row["amount"] is not None else row["amount_text"]))
            seen[base] = seen.get(base, 0) + 1  # 同一天同一對象同金額列兩次＝兩筆真的捐款，不互相蓋掉
            yield _gift_item(
                matcher, recipient=row["recipient"],
                external_id=base if seen[base] == 1 else f"{base}-{seen[base]}", source_url=url,
                data={"donor_name": company[:200], "company_code": "", "company_short": "", "subsidiary": "",
                      "donor_ubn": uid, "donated_on": row["donated_on"], "amount": row["amount"],
                      "amount_text": row["amount_text"], "purpose": row["note"], "relation": "",
                      "subject": "", "category": row["category"][:50], "note": row["note"]},
            )
