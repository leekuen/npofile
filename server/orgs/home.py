"""首頁的探索區與領域區（口徑見 tickets/LK-18；這些規則只寫在這裡）。

探索區：快截止的公益勸募活動、最新裁罰、清冊上最近的企業捐款。
領域區：選了領域或服務對象時，列近五年沒有受裁罰、近 5 年有公益勸募紀錄的組織。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from django.core.cache import cache
from django.db.models import Count, Exists, F, Max, OuterRef, Q, Subquery, Sum
from django.utils import timezone

from . import category_api, period, scoring, taxonomy
from .models import AnnualFundraising, Donation, Donor, Organization, Penalty, Project

ENDING_DAYS = 14
ENDING_LIMIT = 6
PENALTY_LIMIT = 5
GIFT_MIN_AMOUNT = 100_000
GIFT_LIMIT = 6
PICK_LIMIT = 3
PICK_SCAN = 3000  # 依揭露層級排好的候選，最多看這麼多個找「名稱看得出相關」的
GUIDE_CACHE_SECONDS = 6 * 3600
# 推薦卡「裁罰紀錄」那一行寫的「查過的來源」：受裁罰紀錄的每一種類別各是哪個機關的資料（LK-52）
PENALTY_SOURCES = {
    Penalty.Category.FUNDRAISING: "衛福部",
    Penalty.Category.ENVIRONMENT: "環境部",
    Penalty.Category.LABOR: "勞動部",
    Penalty.Category.PROCUREMENT: "工程會",
}

# 處分理由 → 白話的違規類型（依序比對，第一個中的算；都沒中就不寫，不硬湊）
PENALTY_KINDS = (
    ("超過許可期間仍在募款", r"仍.{0,40}?持續募款|逾.{0,6}期間.{0,10}勸募|逾許可勸募|逾期募款箱"),
    ("未經許可募款", r"未經許可"),
    ("沒有開立收據", r"未開立收據"),
    ("公開的資料不實", r"資料不實|內容不實"),
    ("沒有按時公開收支與成果", r"公開徵信|成果報告|期滿之翌日起"),
)
# 清冊上被遮住的名字（「米〇國際」「米O國際」）：同一家可能另外有完整名字，列出來像重複
MASKED_NAME = re.compile(r"[一-鿿][O○〇Ｏ*＊][一-鿿]")


def penalty_kind(penalty: Penalty) -> str:
    text = f"{penalty.reason}\n{penalty.content}"
    return next((label for label, rx in PENALTY_KINDS if re.search(rx, text)), "")


def _live(prefix: str = "", today: date | None = None) -> Q:
    """進行中的公益勸募活動（已開始、還沒結束、有預募金額）。"""
    today = today or timezone.localdate()
    return Q(**{
        f"{prefix}channel": Project.Channel.PERMIT,
        f"{prefix}end_date__gte": today,
        f"{prefix}target__gt": 0,
    }) & (Q(**{f"{prefix}start_date__lte": today}) | Q(**{f"{prefix}start_date__isnull": True}))


def ending_campaigns(today: date | None = None) -> list[dict]:
    today = today or timezone.localdate()
    qs = (Project.objects.filter(_live(today=today), end_date__lte=today + timedelta(days=ENDING_DAYS))
          .select_related("organization").order_by("end_date", "-target", "id")[:ENDING_LIMIT])
    return [{
        "project_id": p.external_id, "name": p.name, "end_date": p.end_date, "target": p.target,
        "days_left": (p.end_date - today).days,
        "org_ubn": p.organization.ubn, "org_name": p.organization.name, "org_level": p.organization.disclosure_level,
    } for p in qs]


def latest_penalties() -> list[dict]:
    qs = Penalty.objects.select_related("organization").exclude(decided_on=None).order_by("-decided_on", "-id")[:PENALTY_LIMIT]
    return [{
        "decided_on": p.decided_on, "kind": penalty_kind(p), "fine_text": p.fine_text,
        "org_ubn": p.organization.ubn, "org_name": p.organization.name,
    } for p in qs]


def recent_company_gifts() -> list[dict]:
    qs = (Donation.objects.filter(donor__kind=Donor.Kind.COMPANY, donor__hidden=False, amount__gte=GIFT_MIN_AMOUNT,
                                  donated_on__isnull=False, project__isnull=False)
          .filter(period.donation_q())
          .select_related("donor", "organization").order_by("-donated_on", "-amount", "id"))
    rows, seen = [], set()
    for d in qs.iterator(chunk_size=200):
        if d.organization_id in seen or MASKED_NAME.search(d.donor.name):
            continue
        seen.add(d.organization_id)
        rows.append({
            "donated_on": d.donated_on, "amount": d.amount, "donor_id": d.donor_id, "donor_name": d.donor.name,
            "org_ubn": d.organization.ubn, "org_name": d.organization.name,
        })
        if len(rows) == GIFT_LIMIT:
            break
    return rows


def discover() -> dict:
    return {"ending": ending_campaigns(), "penalties": latest_penalties(), "gifts": recent_company_gifts()}


def pick_code(params) -> str:
    """領域區看哪一個分類：小類 > 大類 > 服務對象；非公益類不出現。"""
    for key in ("sub", "field", "target"):
        code = (params.get(key) or "").strip()
        if code in taxonomy.LABELS and not code.startswith("other"):
            return code
    return ""


def _related(code: str, org: Organization) -> int | None:
    """這個組織跟這個分類的關係：0＝名稱看得出相關、1＝官方勸募用途、None＝都不是（是活動名稱推測的，不列）。"""
    if code in taxonomy.infer_codes([org.name]):
        return 0
    if code in taxonomy.official_codes(org.purposes):  # 官方勸募用途只有大類；小類與服務對象只能靠名稱
        return 1
    return None


def _campaign(org: Organization, code: str, today: date) -> dict | None:
    """跟這個分類相關的進行中募款（活動的勸募用途或名稱），最快截止的那一筆。"""
    for p in org.projects.filter(_live(today=today)).order_by("end_date", "id"):
        if code in taxonomy.official_codes(p.category) or code in taxonomy.infer_codes([p.name]):
            return {"project_id": p.external_id, "name": p.name, "end_date": p.end_date, "target": p.target}
    return None


def _latest_project(org: Organization) -> dict | None:
    """沒有進行中募款時，「捐款用途」寫最近一次公益勸募活動（LK-52）。"""
    p = org.projects.filter(channel=Project.Channel.PERMIT).order_by(
        F("start_date").desc(nulls_last=True), F("period_year").desc(nulls_last=True), "-id").first()
    if not p:
        return None
    return {"project_id": p.external_id, "name": p.name, "year": p.period_year}


def _pick_card(org: Organization, code: str, today: date) -> dict:
    """推薦卡一張（引導模式與領域區共用，LK-52）：捐款用途、裁罰、經費、揭露層級。"""
    campaign = _campaign(org, code, today)
    return {
        "ubn": org.ubn, "name": org.name, "city": org.city, "level": org.disclosure_level,
        "raised_5y": org.raised_5y or 0,
        "campaign": campaign,
        "latest_project": None if campaign else _latest_project(org),
        # 推薦條件已排除近五年有裁罰的，這裡只數更早的（含日期不明）
        "older_penalties": org.penalties.exclude(scoring.penalty_5y_filter()).count(),
    }


def field_picks(params) -> dict | None:
    code = pick_code(params)
    if not code:
        return None
    return _picks_for(code, params)


def _picks_for(code: str, params) -> dict:
    today = timezone.localdate()
    since = period.since_roc_year()
    qs = Organization.objects.all()
    if city := (params.get("city") or "").strip():
        qs = qs.filter(city=city)
    if status := (params.get("status") or "").strip():
        qs = qs.filter(status=status)
    qs = category_api.filter_orgs(qs, params)
    raised = (AnnualFundraising.objects.filter(organization=OuterRef("pk"), year__gte=since)
              .values("organization").annotate(s=Sum("raised")).values("s"))
    penalized = Penalty.objects.filter(organization=OuterRef("pk")).filter(scoring.penalty_5y_filter())
    live = Project.objects.filter(_live(today=today), organization=OuterRef("pk"))
    ranked = (qs.annotate(pen=Exists(penalized), has_live=Exists(live), raised_5y=Subquery(raised))
              .filter(pen=False).filter(Q(has_live=True) | Q(raised_5y__gt=0))
              .order_by("-disclosure_level", "-has_live", F("raised_5y").desc(nulls_last=True), "name"))
    by_relation: dict[int, list[Organization]] = {0: [], 1: []}
    for org in ranked[:PICK_SCAN]:
        rel = _related(code, org)
        if rel is not None:
            by_relation[rel].append(org)
        if len(by_relation[0]) >= PICK_LIMIT:
            break
    orgs = (by_relation[0] + by_relation[1])[:PICK_LIMIT]
    return {
        "code": code,
        "label": taxonomy.LABELS[code],
        "penalty_sources": list(PENALTY_SOURCES.values()),
        "orgs": [_pick_card(o, code, today) for o in orgs],
    }


def _data_stamp() -> str:
    """推薦結果會跟著變的資料摘要：日期（進行中募款每天變）＋層級／實募總和（recompute_scores 改了就變）＋裁罰與專案。
    快取放在各 worker 自己的記憶體，排程容器碰不到，所以不靠「跑完去清快取」，而是資料一變 key 就跟著變。"""
    org = Organization.objects.aggregate(level=Sum("disclosure_level"), raised=Sum("public_raised_5y"))
    pen = Penalty.objects.aggregate(n=Count("id"), last=Max("id"))
    proj = Project.objects.aggregate(n=Count("id"), last=Max("id"))
    return ":".join(str(v) for v in (
        timezone.localdate(), org["level"], org["raised"], pen["n"], pen["last"], proj["n"], proj["last"]))


def guide() -> dict:
    """首頁引導模式（LK-51）：每個公益大類各推薦最多三個；挑法跟領域區同一套（LK-18）。"""
    key = f"home:guide:{_data_stamp()}"
    data = cache.get(key)
    if data is None:
        data = _build_guide()
        cache.set(key, data, GUIDE_CACHE_SECONDS)
    return data


def _build_guide() -> dict:
    counts = category_api.code_counts()
    fields, empty = [], []
    for f in taxonomy.FIELDS:
        if f.code.startswith("other"):
            continue
        picks = _picks_for(f.code, {"field": f.code})
        if picks["orgs"]:
            fields.append({"code": f.code, "label": f.label, "count": counts.get(f.code, 0), "orgs": picks["orgs"]})
        else:
            empty.append({"code": f.code, "label": f.label})
    return {"penalty_sources": list(PENALTY_SOURCES.values()), "fields": fields, "empty": empty}
