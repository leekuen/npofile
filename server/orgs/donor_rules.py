"""捐款人的可見規則只寫在這裡（口徑見 tickets/LK-06）：組織頁、捐款企業排行與內頁都讀這支。

- 企業、團體：未隱藏就公開，有跨組織頁面。
- 個人：清冊只存大額個人；只出現在捐給的那個組織頁，沒有跨組織頁面、不進搜尋。
- 被隱藏的捐款人：哪裡都不出現，金額併入匿名摘要。
- 收據編號：不出現在任何公開輸出。
"""

from __future__ import annotations

from django.db.models import Count, Max, Min, Q, QuerySet, Sum
from django.db.models.functions import ExtractYear

from . import period
from .models import Donation, Donor, DonorListSummary, Organization, Penalty

RANKING_SIZE = 20


def visible_donations(qs: QuerySet[Donation]) -> QuerySet[Donation]:
    """前台看得到的逐筆：只算近 5 年；被隱藏的捐款人整筆拿掉；標匿名的照列，名稱顯示「匿名」。"""
    return qs.filter(period.donation_q()).exclude(donor__hidden=True)


def ranked_donations(qs: QuerySet[Donation]) -> QuerySet[Donation]:
    """排行只算具名：匿名不進排行。"""
    return visible_donations(qs).filter(is_anonymous=False)


def corporate_ranking(org: Organization, size: int = RANKING_SIZE) -> list[dict]:
    rows = (
        ranked_donations(org.donations.filter(donor__kind__in=Donor.PUBLIC_KINDS))
        .values("donor_id", "donor__name", "donor__kind", "donor__ubn")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total", "donor__name")[:size]
    )
    labels = dict(Donor.Kind.choices)
    return [
        {
            "donor_id": r["donor_id"], "name": r["donor__name"], "kind": r["donor__kind"],
            "kind_label": labels[r["donor__kind"]], "ubn": r["donor__ubn"], "total": r["total"], "count": r["count"],
        }
        for r in rows
    ]


def individual_ranking(org: Organization, size: int = RANKING_SIZE) -> list[dict]:
    """清冊上的大額個人，加上管理員手動輸入、沒連到捐款人的具名捐款。"""
    qs = ranked_donations(org.donations.filter(Q(donor__kind=Donor.Kind.INDIVIDUAL) | Q(donor__isnull=True))).exclude(
        donor__isnull=True, donor_name=""
    )
    totals: dict[str, dict] = {}
    for r in qs.values("donor__name", "donor_name").annotate(total=Sum("amount"), count=Count("id")):
        name = (r["donor__name"] or r["donor_name"]).strip()
        t = totals.setdefault(name, {"name": name, "total": 0, "count": 0})
        t["total"] += r["total"]
        t["count"] += r["count"]
    return sorted(totals.values(), key=lambda x: (-x["total"], x["name"]))[:size]


def org_summary(org: Organization) -> dict | None:
    summaries = DonorListSummary.objects.filter(period.project_q("project__"), project__organization=org)
    agg = summaries.aggregate(
        lists=Count("id"),
        total_rows=Sum("total_rows"),
        total_amount=Sum("total_amount"),
        small_individual_count=Sum("small_individual_count"),
        small_individual_amount=Sum("small_individual_amount"),
        anonymous_rows=Sum("anonymous_rows"),
        anonymous_amount=Sum("anonymous_amount"),
    )
    if not agg["lists"]:
        return None
    hidden = org.donations.filter(period.donation_q(), donor__hidden=True).aggregate(n=Count("id"), amount=Sum("amount"))
    threshold = summaries.values_list("threshold", flat=True).first()
    return {
        "lists": agg["lists"],
        "total_rows": agg["total_rows"] or 0,
        "total_amount": agg["total_amount"] or 0,
        "small_individual_count": agg["small_individual_count"] or 0,
        "small_individual_amount": agg["small_individual_amount"] or 0,
        "anonymous_rows": (agg["anonymous_rows"] or 0) + hidden["n"],
        "anonymous_amount": (agg["anonymous_amount"] or 0) + (hidden["amount"] or 0),
        "threshold": threshold or 0,
    }


def dated_q(prefix: str = "") -> Q:
    """畫進年度趨勢、算「持續幾年」「最近一次」的捐款（LK-38）：有日期、落在近 5 年的西元年、不晚於今天。
    日期在今天之後的多半是清冊打錯（本機看過 2028、2055 年），照算總額與排名，但不畫進年度、不當成最近一次。"""
    today = period.today()
    return Q(**{f"{prefix}donated_on__gte": period.window_start(), f"{prefix}donated_on__lte": today})


def public_donors() -> QuerySet[Donor]:
    in_window = period.donation_q("donations__")
    dated = in_window & dated_q("donations__")
    return (
        Donor.objects.filter(kind__in=Donor.PUBLIC_KINDS, hidden=False)
        .annotate(
            total=Sum("donations__amount", filter=in_window),
            donation_count=Count("donations", filter=in_window, distinct=True),
            org_count=Count("donations__organization", filter=in_window, distinct=True),
            active_year_count=Count(ExtractYear("donations__donated_on"), filter=dated, distinct=True),
            last_donated_on=Max("donations__donated_on", filter=dated),
        )
        .filter(donation_count__gt=0)
    )


def _dated(donor: Donor) -> QuerySet[Donation]:
    return donor.donations.filter(period.donation_q()).filter(dated_q())


def donor_rank(donor: Donor) -> dict:
    """同類（企業比企業、團體比團體）依近 5 年總額排名；同額同名次（比自己多的人數 + 1）。"""
    peers = public_donors().filter(kind=donor.kind)
    total = getattr(donor, "total", None)
    if total is None:
        total = donor.donations.filter(period.donation_q()).aggregate(t=Sum("amount"))["t"] or 0
    return {"rank": peers.filter(total__gt=total).count() + 1, "rank_of": peers.count()}


def donor_yearly(donor: Donor) -> list[dict]:
    """近 5 年每年（民國）捐款總額、捐給幾個組織、幾筆；沒有捐款的年度補 0。"""
    rows = {
        r["y"] - 1911: r
        for r in _dated(donor)
        .annotate(y=ExtractYear("donated_on"))
        .values("y")
        .annotate(total=Sum("amount"), org_count=Count("organization", distinct=True), count=Count("id"))
    }
    this_year = period.today().year - 1911
    out = []
    for y in range(period.since_roc_year(), this_year + 1):
        r = rows.get(y)
        out.append(
            {"year": y, "total": r["total"] if r else 0, "org_count": r["org_count"] if r else 0, "count": r["count"] if r else 0}
        )
    return out


def donor_overview(donor: Donor) -> dict:
    agg = _dated(donor).aggregate(first=Min("donated_on"), last=Max("donated_on"))
    biggest = donor.donations.filter(period.donation_q()).aggregate(m=Max("amount"))["m"]
    years = sorted(
        {y - 1911 for y in _dated(donor).annotate(y=ExtractYear("donated_on")).values_list("y", flat=True)}
    )
    return {
        **donor_rank(donor),
        "active_years": years,
        "first_donated_on": agg["first"],
        "last_donated_on": agg["last"],
        "max_donation": biggest or 0,
        "yearly": donor_yearly(donor),
    }


def donor_by_org(donor: Donor) -> list[dict]:
    rows = list(
        donor.donations.filter(period.donation_q())
        .values("organization_id", "organization__ubn", "organization__name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total", "organization__name")
    )
    org_ids = [r["organization_id"] for r in rows]
    years: dict[int, set[int]] = {}
    for org_id, d in _dated(donor).values_list("organization_id", "donated_on"):
        years.setdefault(org_id, set()).add(d.year - 1911)
    # 裁罰不受 5 年限制（LK-07）：該組織全部的裁罰紀錄
    penalties = dict(
        Penalty.objects.filter(organization_id__in=org_ids)
        .values("organization_id")
        .annotate(n=Count("id"))
        .values_list("organization_id", "n")
    )
    return [
        {
            "ubn": r["organization__ubn"], "name": r["organization__name"], "total": r["total"], "count": r["count"],
            "years": sorted(years.get(r["organization_id"], ())), "penalty_count": penalties.get(r["organization_id"], 0),
        }
        for r in rows
    ]
