"""依 taxonomy 的規則替組織寫分類；管理員指定或拿掉的分類不動。"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Prefetch, QuerySet

from . import period, taxonomy
from .models import OrgCategory, Organization, Project

AUTO_SOURCES = (OrgCategory.Source.OFFICIAL, OrgCategory.Source.INFERRED)


def desired_codes(org: Organization, project_names: list[str]) -> dict[str, str]:
    return taxonomy.classify(org.name, org.purposes, project_names)


def categorize(orgs: QuerySet[Organization] | None = None, chunk: int = 2000) -> dict[str, int]:
    qs = (orgs if orgs is not None else Organization.objects.all()).order_by("pk").prefetch_related(
        Prefetch("projects", queryset=Project.objects.filter(period.project_q()).only("id", "name", "organization_id")),
        "categories",
    )
    stats = {"added": 0, "removed": 0, "changed": 0}
    to_add: list[OrgCategory] = []
    to_remove: list[int] = []
    to_update: list[OrgCategory] = []
    for org in qs.iterator(chunk_size=chunk):
        want = desired_codes(org, [p.name for p in org.projects.all()])
        have = {c.code: c for c in org.categories.all()}
        for code, source in want.items():
            row = have.get(code)
            if row is None:
                to_add.append(OrgCategory(organization=org, code=code, source=source))
            elif row.source in AUTO_SOURCES and not row.excluded and row.source != source:
                row.source = source
                to_update.append(row)
        for code, row in have.items():
            if code not in want and row.source in AUTO_SOURCES and not row.excluded:
                to_remove.append(row.pk)
        if len(to_add) + len(to_remove) + len(to_update) >= chunk:
            _flush(to_add, to_remove, to_update, stats)
    _flush(to_add, to_remove, to_update, stats)
    return stats


def _flush(to_add, to_remove, to_update, stats) -> None:
    with transaction.atomic():
        if to_add:
            OrgCategory.objects.bulk_create(to_add, ignore_conflicts=True)
        for i in range(0, len(to_remove), 900):
            OrgCategory.objects.filter(pk__in=to_remove[i : i + 900]).delete()
        if to_update:
            OrgCategory.objects.bulk_update(to_update, ["source"])
    stats["added"] += len(to_add)
    stats["removed"] += len(to_remove)
    stats["changed"] += len(to_update)
    to_add.clear()
    to_remove.clear()
    to_update.clear()


def active(qs: QuerySet[OrgCategory]) -> QuerySet[OrgCategory]:
    return qs.filter(excluded=False)


def org_filter_q(code: str):
    """套在 Organization 查詢上：有這個分類（大類也包含它所有小類的組織，因為小類一定帶上大類）。"""
    from django.db.models import Exists, OuterRef

    return Exists(OrgCategory.objects.filter(organization=OuterRef("pk"), code=code, excluded=False))
