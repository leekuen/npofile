"""揭露層級（口徑見 tickets/LK-35）、近 5 年公開募款與近五年裁罰的期間定義。

只有這裡算分；後台、API、統計都讀這支。
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count, Prefetch, Q, QuerySet
from django.utils import timezone

from . import period
from .models import AnnualFundraising, FinancialYear, OrgDocument, Organization, Project

# 揭露層級（口徑見 tickets/LK-35）：四層依序達成，每一層的條件全部達到才算
LEVEL_NAMES = {0: "資料不足", 1: "身分可查", 2: "活動可查", 3: "財務可查", 4: "長期可查"}
# 給人看的等級名稱（使用者 2026-11-28 定案：銅銀金鑽石，最高一級參考台灣綠建築標章的「鑽石級」）
LEVEL_MEDALS = {0: "未分級", 1: "銅", 2: "銀", 3: "金", 4: "鑽石"}
MAX_LEVEL = 4
FINANCIAL_RECENT_YEARS = 2  # 第 3 層：年度 ≥ 今年 − 2
CONSECUTIVE_YEARS = 3  # 第 4 層：連續 3 個年度


def today() -> date:
    return timezone.localdate()


def five_years_ago(ref: date | None = None) -> date:
    ref = ref or today()
    try:
        return ref.replace(year=ref.year - 5)
    except ValueError:  # 2/29
        return ref.replace(year=ref.year - 5, day=28)


def penalty_5y_filter(prefix: str = "") -> Q:
    return Q(**{f"{prefix}decided_on__gte": five_years_ago()})


def with_penalty_count(qs: QuerySet[Organization]) -> QuerySet[Organization]:
    return qs.annotate(penalty_count_5y=Count("penalties", filter=penalty_5y_filter("penalties__"), distinct=True))


def _check(key: str, label: str, met: bool, hint: str = "") -> dict:
    return {"key": key, "label": label, "met": bool(met), "hint": hint}


RESULT_DAYS = timedelta(days=30)  # 公益勸募條例第 18 條：勸募活動期滿之翌日起 30 日內成果備查


def result_due(p: Project, ref: date) -> bool:
    """這個勸募活動的成果備查到期了沒（LK-43）：先看活動頁的法定期限，沒有就用期滿日 + 30 日，
    都沒有（只抓過團體頁的舊資料）才退回「活動年度早於今年」。"""
    if p.result_due_on:
        return p.result_due_on < ref
    if p.end_date:
        return p.end_date + RESULT_DAYS < ref
    return p.period_year is not None and p.period_year < ref.year - 1911


def result_filed(p: Project) -> bool:
    """已成果備查：團體頁列表有備查日期，或活動頁看得到已備查（逾期補交也算交了）。"""
    return bool(p.result_filed_on or p.result_done)


def _has_numbers(f) -> bool:
    return f.total_revenue is not None and f.total_expenses is not None


def levels(org: Organization, *, projects=None, financials=None, documents=None, registries=None,
           has_grants=None, ref: date | None = None) -> dict:
    """揭露層級：回傳層級（0～4）、名稱與四層各條件有沒有達到。

    只用站上收錄的公開資料；可傳入已預先載入的清單，避免重複查詢。裁罰不影響層級（另外標示）。
    """
    ref = ref or today()
    roc = ref.year - 1911
    since = period.since_roc_year(ref)
    projects = list(org.projects.all()) if projects is None else projects
    financials = list(org.financials.all()) if financials is None else financials
    documents = list(org.documents.all()) if documents is None else documents
    registries = list(org.registry_entries.all()) if registries is None else registries
    if has_grants is None:
        has_grants = org.grants.filter(year__gte=since).exists()

    # 第 1 層：身分可查
    purpose = bool(org.purposes.strip()) or any(r.purpose.strip() for r in registries)
    layer1 = [
        _check("active", "營運中", org.status == Organization.Status.ACTIVE),
        _check("ubn", "統一編號", bool(org.ubn)),
        _check("org_type", "團體類型", bool(org.org_type.strip())),
        _check("address", "地址", bool(org.registered_address.strip() or org.contact_address.strip())),
        _check("purpose", "宗旨或勸募用途", purpose),
        _check("contact", "電話或官網", bool(org.phone.strip() or org.website.strip())),
    ]

    # 第 2 層：活動可查；有辦勸募的，到期的活動要全部成果備查
    permits = [p for p in projects if p.channel == Project.Channel.PERMIT and period.in_window(p.period_year, ref)]
    has_business = any(r.main_business.strip() for r in registries)
    due = [p for p in permits if (p.raised or 0) > 0 and result_due(p, ref)]
    filed = [p for p in due if result_filed(p)]
    layer2 = [
        _check("activity", f"{since} 年以後有看得到的活動（勸募活動、政府補助或主管機關名冊的主要業務）",
               bool(permits) or has_grants or has_business),
        _check("results_filed", "到期的勸募活動都已成果備查", len(filed) == len(due),
               f"已備查 {len(filed)}／{len(due)}" if due else "沒有到期的勸募活動"),
    ]

    # 第 3 層：財務可查
    fin_years = sorted({f.year for f in financials if _has_numbers(f)}, reverse=True)
    recent_from = roc - FINANCIAL_RECENT_YEARS
    layer3 = [
        _check("financial_recent", f"{recent_from} 年以後的財務報告（至少有總收入、總支出）",
               bool(fin_years) and fin_years[0] >= recent_from),
    ]

    # 第 4 層：長期可查
    years = set(fin_years)
    consecutive = any(
        all(y - i in years for i in range(CONSECUTIVE_YEARS)) for y in fin_years if y >= recent_from
    )
    # 不看會計師查核：衛福部決算不公布查核與否，「敢發出財報就算有提供」（使用者 2026-11-28，LK-45）
    reports = any(d.kind in (OrgDocument.Kind.ANNUAL, OrgDocument.Kind.WORK) and d.year >= recent_from
                  for d in documents)
    layer4 = [
        _check("financial_consecutive", f"連續 {CONSECUTIVE_YEARS} 個年度的財務報告", consecutive),
        _check("report", f"{recent_from} 年以後的年報或工作／成果報告", reports),
    ]

    layers = []
    level = 0
    for n, checks in enumerate((layer1, layer2, layer3, layer4), start=1):
        met = all(c["met"] for c in checks)
        layers.append({"level": n, "medal": LEVEL_MEDALS[n], "name": LEVEL_NAMES[n], "met": met, "checks": checks})
        if met and level == n - 1:
            level = n
    return {
        "level": level,
        "medal": LEVEL_MEDALS[level],
        "name": LEVEL_NAMES[level],
        "max_level": MAX_LEVEL,
        "active": org.status == Organization.Status.ACTIVE,
        "layers": layers,
        "results_due": len(due),
        "results_filed": len(filed),
    }


def public_raised(annual, projects, ref: date | None = None) -> dict:
    """近 5 年公開募款（LK-20）。

    群眾集資平台沒有勸募字號，分不出哪些錢之後也會報進勸募。為了不重複算，逐年判斷：
    那一年勸募已申報（實募 > 0）就用勸募；還沒申報（0）才用當年開始的群眾集資補上。
    群眾集資只算一次性／累計募得，不算每月定期定額。
    """
    since = period.since_roc_year(ref)
    permit_by_year: dict[int, int] = {}
    for a in annual:
        if a.year >= since:
            permit_by_year[a.year] = permit_by_year.get(a.year, 0) + (a.raised or 0)
    crowd_by_year: dict[int, int] = {}
    for p in projects:
        if p.channel == Project.Channel.CROWDFUNDING and period.in_window(p.period_year, ref) and (p.raised or 0) > 0:
            # 沒有日期的集資當作今年（最可能還沒申報的年度）
            y = p.period_year if p.period_year is not None else since + period.YEARS - 1
            crowd_by_year[y] = crowd_by_year.get(y, 0) + p.raised
    permit = sum(permit_by_year.values())
    crowd = sum(crowd_by_year.values())
    crowd_counted = sum(v for y, v in crowd_by_year.items() if permit_by_year.get(y, 0) <= 0)
    return {
        "total": permit + crowd_counted,
        "permit": permit,
        "crowdfunding": crowd,
        "crowdfunding_counted": crowd_counted,
    }


def donation_trend(annual, projects, grants, ref: date | None = None) -> list[dict]:
    """近 5 年受捐款趨勢（LK-33）：每年勸募實募、群眾集資、政府補助各自加總（元），給組織頁折線圖。

    三種錢來源不同、可能重疊（勸募申報可能已含集資），所以只分開列、不相加。
    勸募與集資的年度歸屬跟 public_raised 同一套；補助要先用 distinct_grants 去重再傳進來。
    沒有紀錄的年度是 0；今年三種都還是 0（多半是還沒申報）就不列今年，免得圖尾掉到 0。
    """
    since = period.since_roc_year(ref)
    years = list(range(since, since + period.YEARS))
    rows = {y: {"year": y, "permit": 0, "crowdfunding": 0, "grants": 0} for y in years}
    for a in annual:
        if a.year in rows:
            rows[a.year]["permit"] += a.raised or 0
    for p in projects:
        if p.channel == Project.Channel.CROWDFUNDING and period.in_window(p.period_year, ref) and (p.raised or 0) > 0:
            y = p.period_year if p.period_year is not None else years[-1]
            if y in rows:
                rows[y]["crowdfunding"] += p.raised
    for g in grants:
        if g.year in rows:
            rows[g.year]["grants"] += g.amount or 0
    out = [rows[y] for y in years]
    last = out[-1]
    if not (last["permit"] or last["crowdfunding"] or last["grants"]):
        out.pop()
    return out


def recompute(orgs: QuerySet[Organization] | None = None, chunk: int = 2000) -> int:
    """重算揭露層級與近 5 年公開募款並寫回；回傳有變動的組織數。"""
    since = period.since_roc_year()
    qs = (orgs if orgs is not None else Organization.objects.all()).order_by("pk")
    qs = qs.prefetch_related(
        Prefetch("annual_records", queryset=AnnualFundraising.objects.filter(year__gte=since)),
        Prefetch("projects", queryset=Project.objects.filter(period.project_q())),
        Prefetch("financials", queryset=FinancialYear.objects.filter(year__gte=since)),
        Prefetch("documents", queryset=OrgDocument.objects.filter(year__gte=since)),
        "registry_entries",
    ).annotate(_grants=Count("grants", filter=Q(grants__year__gte=since)))
    changed = 0
    batch: list[Organization] = []
    for org in qs.iterator(chunk_size=chunk):
        annual = list(org.annual_records.all())
        projects = list(org.projects.all())
        level = levels(
            org, projects=projects, financials=list(org.financials.all()), documents=list(org.documents.all()),
            registries=list(org.registry_entries.all()), has_grants=org._grants > 0,
        )["level"]
        raised = public_raised(annual, projects)["total"]
        if level != org.disclosure_level or raised != org.public_raised_5y:
            org.disclosure_level = level
            org.public_raised_5y = raised
            batch.append(org)
        if len(batch) >= chunk:
            changed += _flush(batch)
    changed += _flush(batch)
    return changed


def _flush(batch: list[Organization]) -> int:
    n = len(batch)
    if n:
        Organization.objects.bulk_update(batch, ["disclosure_level", "public_raised_5y"])
        batch.clear()
    return n
