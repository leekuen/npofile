"""捐款人的可見規則只寫在這裡（口徑見 tickets/LK-06）：組織頁、捐款企業排行與內頁都讀這支。

- 企業、團體：未隱藏就公開，有跨組織頁面。
- 個人：清冊只存大額個人；只出現在捐給的那個組織頁，沒有跨組織頁面、不進搜尋。
- 被隱藏的捐款人：哪裡都不出現，金額併入匿名摘要。
- 收據編號：不出現在任何公開輸出。
"""

from __future__ import annotations

from django.db.models import Count, Q, QuerySet, Sum

from . import period
from .models import Donation, Donor, DonorListSummary, Organization

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


def public_donors() -> QuerySet[Donor]:
    return (
        Donor.objects.filter(kind__in=Donor.PUBLIC_KINDS, hidden=False)
        .annotate(
            total=Sum("donations__amount", filter=period.donation_q("donations__")),
            donation_count=Count("donations", filter=period.donation_q("donations__"), distinct=True),
            org_count=Count("donations__organization", filter=period.donation_q("donations__"), distinct=True),
        )
        .filter(donation_count__gt=0)
    )


def donor_by_org(donor: Donor) -> list[dict]:
    return donations_by_org(donor.donations.all())


def donations_by_org(donations: QuerySet[Donation]) -> list[dict]:
    """依受捐組織加總（企業頁、集團頁共用）。"""
    rows = (
        donations.filter(period.donation_q())
        .values("organization__ubn", "organization__name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total")
    )
    return [
        {"ubn": r["organization__ubn"], "name": r["organization__name"], "total": r["total"], "count": r["count"]}
        for r in rows
    ]
