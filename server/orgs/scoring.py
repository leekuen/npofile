"""揭露指數（口徑見 tickets/LK-03〈數字口徑〉）與近五年裁罰的期間定義。

只有這裡算分；後台、API、統計都讀這支。
"""

from __future__ import annotations

from datetime import date

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from .models import Organization

BASIC_FIELDS = ("ubn", "org_type", "address", "phone", "website", "purposes")
BASIC_POINTS = 5
FUNDRAISING_POINTS = 25
PROJECT_POINTS = 20
RESULT_POINTS = 25


def today() -> date:
    return timezone.localdate()


def five_years_ago(ref: date | None = None) -> date:
    ref = ref or today()
    try:
        return ref.replace(year=ref.year - 5)
    except ValueError:  # 2/29
        return ref.replace(year=ref.year - 5, day=28)


def recent_roc_years(ref: date | None = None) -> range:
    ry = (ref or today()).year - 1911
    return range(ry - 4, ry + 1)


def penalty_5y_filter(prefix: str = "") -> Q:
    return Q(**{f"{prefix}decided_on__gte": five_years_ago()})


def with_penalty_count(qs: QuerySet[Organization]) -> QuerySet[Organization]:
    return qs.annotate(penalty_count_5y=Count("penalties", filter=penalty_5y_filter("penalties__"), distinct=True))


def breakdown(org: Organization, annual=None, donations_exist=None, projects=None, ref: date | None = None) -> dict:
    """回傳四項分數與總分。annual/projects 可傳入已預先載入的清單，避免重複查詢。"""
    annual = list(org.annual_records.all()) if annual is None else annual
    projects = list(org.projects.all()) if projects is None else projects
    if donations_exist is None:
        donations_exist = org.donations.exists()

    present = {
        "ubn": bool(org.ubn),
        "org_type": bool(org.org_type.strip()),
        "address": bool(org.registered_address.strip() or org.contact_address.strip()),
        "phone": bool(org.phone.strip()),
        "website": bool(org.website.strip()),
        "purposes": bool(org.purposes.strip()),
    }
    basic = sum(BASIC_POINTS for f in BASIC_FIELDS if present[f])

    years = set(recent_roc_years(ref))
    has_fundraising = donations_exist or any(a.year in years and (a.raised or 0) > 0 for a in annual)
    fundraising = FUNDRAISING_POINTS if has_fundraising else 0

    project = PROJECT_POINTS if projects else 0

    funded = [p for p in projects if (p.raised or 0) > 0]
    filed = [p for p in funded if p.result_filed_on]
    result = round(RESULT_POINTS * len(filed) / len(funded)) if funded else 0

    return {
        "basic": basic,
        "basic_max": BASIC_POINTS * len(BASIC_FIELDS),
        "basic_present": present,
        "fundraising": fundraising,
        "fundraising_max": FUNDRAISING_POINTS,
        "project": project,
        "project_max": PROJECT_POINTS,
        "result": result,
        "result_max": RESULT_POINTS,
        "result_funded_projects": len(funded),
        "result_filed_projects": len(filed),
        "total": basic + fundraising + project + result,
    }


def recompute(orgs: QuerySet[Organization] | None = None, chunk: int = 2000) -> int:
    """重算揭露指數並寫回；回傳有變動的組織數。"""
    qs = (orgs if orgs is not None else Organization.objects.all()).order_by("pk")
    qs = qs.prefetch_related("annual_records", "projects").annotate(_donations=Count("donations"))
    changed = 0
    batch: list[Organization] = []
    for org in qs.iterator(chunk_size=chunk):
        total = breakdown(
            org,
            annual=list(org.annual_records.all()),
            projects=list(org.projects.all()),
            donations_exist=org._donations > 0,
        )["total"]
        if total != org.disclosure_score:
            org.disclosure_score = total
            batch.append(org)
        if len(batch) >= chunk:
            changed += _flush(batch)
    changed += _flush(batch)
    return changed


def _flush(batch: list[Organization]) -> int:
    n = len(batch)
    if n:
        Organization.objects.bulk_update(batch, ["disclosure_score"])
        batch.clear()
    return n
