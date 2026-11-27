"""分類相關的公開 API：分類樹（含組織數）、領域頁、組織與企業的分類輸出。"""

from __future__ import annotations

from django.db.models import Count, Sum
from django.http import Http404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import donor_rules, period, scoring, taxonomy
from .categorize import org_filter_q
from .models import AnnualFundraising, Donation, Donor, OrgCategory, Organization, Penalty

TOP = 10
PENALTIES = 20


def code_counts() -> dict[str, int]:
    rows = OrgCategory.objects.filter(excluded=False).values("code").annotate(n=Count("organization", distinct=True))
    return {r["code"]: r["n"] for r in rows}


@api_view(["GET"])
def taxonomy_tree(request):
    counts = code_counts()
    return Response(
        {
            "fields": [
                {
                    "code": f.code,
                    "label": f.label,
                    "count": counts.get(f.code, 0),
                    "subs": [{"code": s.code, "label": s.label, "count": counts.get(s.code, 0)} for s in f.subs],
                }
                for f in taxonomy.FIELDS
            ],
            "targets": [{"code": t.code, "label": t.label, "count": counts.get(t.code, 0)} for t in taxonomy.TARGETS],
        }
    )


def org_categories(org: Organization) -> dict:
    """組織頁用：大類底下掛它的小類；服務對象另列。用 prefetch 過的 categories。"""
    rows = [c for c in org.categories.all() if not c.excluded]
    by_code = {c.code: c for c in rows}
    fields = []
    for f in taxonomy.FIELDS:
        subs = [
            {"code": s.code, "label": s.label, "source": by_code[s.code].source} for s in f.subs if s.code in by_code
        ]
        if f.code in by_code or subs:
            src = by_code[f.code].source if f.code in by_code else subs[0]["source"]
            fields.append({"code": f.code, "label": f.label, "source": src, "subs": subs})
    targets = [{"code": t.code, "label": t.label, "source": by_code[t.code].source} for t in taxonomy.TARGETS if t.code in by_code]
    return {"fields": fields, "targets": targets}


def short_tags(org: Organization, limit: int = 3) -> list[dict]:
    """列表用：小類優先（比大類有資訊量），再補沒有小類的大類，最後服務對象。"""
    cats = org_categories(org)
    tags: list[dict] = []
    for f in cats["fields"]:
        if f["subs"]:
            tags.extend({"code": s["code"], "label": s["label"], "source": s["source"]} for s in f["subs"])
        else:
            tags.append({"code": f["code"], "label": f["label"], "source": f["source"]})
    tags.extend(cats["targets"])
    return tags[:limit]


def _org_brief(org: Organization, extra: dict | None = None) -> dict:
    return {"ubn": org.ubn, "name": org.name, "city": org.city, "disclosure_score": org.disclosure_score, **(extra or {})}


@api_view(["GET"])
def category_overview(request, code):
    if code not in taxonomy.LABELS:
        raise Http404
    orgs = Organization.objects.filter(org_filter_q(code))
    since = period.since_roc_year()
    annual = AnnualFundraising.objects.filter(period.annual_q(), organization__in=orgs)
    raised_by_org = (
        annual.values("organization").annotate(total=Sum("raised")).filter(total__gt=0).order_by("-total")[:TOP]
    )
    top_raised_ids = [r["organization"] for r in raised_by_org]
    raised_orgs = Organization.objects.in_bulk(top_raised_ids)
    donations = donor_rules.ranked_donations(
        Donation.objects.filter(organization__in=orgs, donor__kind__in=Donor.PUBLIC_KINDS)
    )
    donors = (
        donations.values("donor_id", "donor__name", "donor__kind")
        .annotate(total=Sum("amount"), org_count=Count("organization", distinct=True))
        .order_by("-total")[:TOP]
    )
    labels = dict(Donor.Kind.choices)
    penalties = Penalty.objects.filter(organization__in=orgs).select_related("organization").order_by("-decided_on")
    parent = taxonomy.PARENT.get(code)
    return Response(
        {
            "code": code,
            "label": taxonomy.LABELS[code],
            "dimension": taxonomy.dimension(code),
            "parent": {"code": parent, "label": taxonomy.LABELS[parent]} if parent else None,
            "subs": [
                {"code": s.code, "label": s.label}
                for f in taxonomy.FIELDS if f.code == code for s in f.subs
            ],
            "since_roc_year": since,
            "org_count": orgs.count(),
            "raised_5y": annual.aggregate(t=Sum("raised"))["t"] or 0,
            "penalized_5y": orgs.filter(scoring.penalty_5y_filter("penalties__")).distinct().count(),
            "top_score": [_org_brief(o) for o in orgs.order_by("-disclosure_score", "name")[:TOP]],
            "top_raised": [
                _org_brief(raised_orgs[r["organization"]], {"raised_5y": r["total"]})
                for r in raised_by_org if r["organization"] in raised_orgs
            ],
            "top_donors": [
                {"donor_id": d["donor_id"], "name": d["donor__name"], "kind_label": labels[d["donor__kind"]],
                 "total": d["total"], "org_count": d["org_count"]}
                for d in donors
            ],
            "penalties": [
                {"id": p.id, "decided_on": p.decided_on, "content": p.content, "fine_text": p.fine_text,
                 "org_ubn": p.organization.ubn, "org_name": p.organization.name}
                for p in penalties[:PENALTIES]
            ],
            "penalty_total": penalties.count(),
        }
    )


def donor_field_breakdown(donor: Donor) -> list[dict]:
    """企業捐給哪些領域：依受捐組織的大類加總；組織屬多個大類時各算全額（口徑見 LK-09）。"""
    donations = donor.donations.filter(period.donation_q())
    org_totals = {r["organization"]: r["total"] for r in donations.values("organization").annotate(total=Sum("amount"))}
    if not org_totals:
        return []
    field_codes = {f.code for f in taxonomy.FIELDS}
    cats = OrgCategory.objects.filter(organization__in=org_totals, excluded=False, code__in=field_codes)
    totals: dict[str, int] = {}
    seen: set[int] = set()
    for c in cats.values("organization", "code"):
        totals[c["code"]] = totals.get(c["code"], 0) + org_totals[c["organization"]]
        seen.add(c["organization"])
    uncategorized = sum(v for k, v in org_totals.items() if k not in seen)
    rows = [{"code": k, "label": taxonomy.LABELS[k], "total": v} for k, v in totals.items()]
    if uncategorized:
        rows.append({"code": "", "label": "未分類", "total": uncategorized})
    return sorted(rows, key=lambda r: -r["total"])


def filter_orgs(qs, params):
    """首頁篩選：field（大類）、sub（小類）、target（服務對象），不認得的代號忽略。"""
    for key in ("field", "sub", "target"):
        code = params.get(key, "").strip()
        if code in taxonomy.LABELS:
            qs = qs.filter(org_filter_q(code))
    return qs

