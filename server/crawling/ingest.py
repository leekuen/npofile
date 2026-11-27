"""把爬蟲解析出來的 Item 存成 CrawlRecord，並在核准（或自動上架）時寫進組織資料。"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from npofile_crawler.http import PoliteClient
from npofile_crawler.items import Item
from npofile_crawler.sources import SOURCES

from orgs import period, scoring
from orgs.models import (
    CRAWLABLE_FIELDS,
    AnnualFundraising,
    Donation,
    Donor,
    DonorListSummary,
    Organization,
    Penalty,
    Project,
)
from orgs.signals import suspend_scoring

from .models import CrawlerSource, CrawlRecord, CrawlRun

log = logging.getLogger(__name__)

BATCH = 500
KIND_ORDER = {"org": 0, "annual": 1, "project": 2, "penalty": 3, "donor_list": 4}
PROJECT_FIELDS = (
    "category", "start_date", "end_date", "target", "raised", "permit_no", "region",
    "result_filed_on", "closed_filed_on", "description",
)
DATE_FIELDS = {"start_date", "end_date", "result_filed_on", "closed_filed_on"}


def record_source_name(source: CrawlerSource) -> str:
    s = SOURCES.get(source.key)
    return s.record_name if s else source.name


def ensure_sources() -> None:
    for s in SOURCES.values():
        CrawlerSource.objects.get_or_create(
            key=s.key,
            defaults={"name": s.name, "url": s.url, "auto_approve": s.official, "description": s.description},
        )


def run_source(source: CrawlerSource, limit: int | None = None, items: Iterable[Item] | None = None,
               min_interval: float = 1.0) -> CrawlRun:
    run = CrawlRun.objects.create(source=source)
    limit = limit if limit is not None else (source.max_items or None)
    client = None
    touched: set[str] = set()
    batch: list[Item] = []
    known = set(CrawlRecord.objects.filter(source=source).values_list("content_hash", flat=True))
    try:
        with suspend_scoring():
            try:
                if items is None:
                    client = PoliteClient(min_interval=min_interval)
                    src = SOURCES[source.key]
                    values = {"threshold": settings.DONOR_INDIVIDUAL_THRESHOLD, "since_roc": period.since_roc_year()}
                    items = src.fetch(client, limit, **{k: values[k] for k in src.options})
                for item in items:
                    run.fetched += 1
                    batch.append(item)
                    if len(batch) >= BATCH:
                        _store_batch(source, run, batch, known, touched)
                        batch = []
                run.status = CrawlRun.Status.SUCCESS
            except Exception as exc:  # 抓到一半失敗：已抓到的照樣存，錯誤記進執行紀錄
                log.exception("crawl %s failed", source.key)
                run.status = CrawlRun.Status.FAILED
                run.error = f"{type(exc).__name__}: {exc}"[:2000]
            _store_batch(source, run, batch, known, touched)
    finally:
        if client is not None:
            client.close()
        recompute_ubns(touched)
        run.finished_at = timezone.now()
        run.save()
        source.last_run_at = run.finished_at
        source.save(update_fields=["last_run_at"])
    return run


def recompute_ubns(ubns: set[str], chunk: int = 900) -> None:
    # SQLite 單一查詢的參數有上限，分批送
    items = sorted(ubns)
    for i in range(0, len(items), chunk):
        scoring.recompute(Organization.objects.filter(ubn__in=items[i : i + chunk]))


def _store_batch(source: CrawlerSource, run: CrawlRun, batch: list[Item], known: set[str], touched: set[str]) -> None:
    fresh: list[CrawlRecord] = []
    for item in batch:
        h = item.content_hash(source.key)
        if h in known:
            continue
        known.add(h)
        fresh.append(
            CrawlRecord(
                source=source, run=run, kind=item.kind, ubn=item.ubn, external_id=item.external_id,
                payload=item.payload(), source_url=item.source_url, content_hash=h,
            )
        )
    if not fresh:
        return
    CrawlRecord.objects.bulk_create(fresh, ignore_conflicts=True)
    saved = list(CrawlRecord.objects.filter(source=source, run=run, content_hash__in=[r.content_hash for r in fresh]))
    run.created += len(saved)
    if source.auto_approve:
        ok, failed = apply_records(saved, CrawlRecord.Status.AUTO)
        run.applied += ok
        run.failed += failed
        touched.update(r.ubn for r in saved)
    else:
        run.pending += len(saved)
    run.save(update_fields=["fetched", "created", "applied", "pending", "failed"])


@transaction.atomic
def apply_records(records: list[CrawlRecord], status: str, user=None) -> tuple[int, int]:
    """把紀錄寫進組織資料；回傳（成功筆數, 失敗筆數）。失敗的保持原狀態並寫備註。
    揭露指數不在這裡逐筆重算：呼叫的人寫完後用 recompute_ubns 一次算。"""
    with suspend_scoring():
        return _apply_records(records, status, user)


def _apply_records(records: list[CrawlRecord], status: str, user) -> tuple[int, int]:
    records = sorted(records, key=lambda r: KIND_ORDER[r.kind])
    sources = {r.source_id: r.source for r in records}
    orgs = _apply_org_records([r for r in records if r.kind == "org"], sources)
    for ubn, org in Organization.objects.in_bulk(
        {r.ubn for r in records} - set(orgs), field_name="ubn"
    ).items():
        orgs[ubn] = org

    now = timezone.now()
    ok = failed = 0
    for rec in records:
        org = orgs.get(rec.ubn)
        if org is None:
            rec.review_note = "找不到這個統一編號的組織，請先核准該組織的基本資料"
            failed += 1
        else:
            if rec.kind != "org":
                _apply_child(rec, org, record_source_name(sources[rec.source_id]))
            rec.organization = org
            rec.status = status
            rec.reviewed_at = now
            rec.reviewed_by = user
            ok += 1
    CrawlRecord.objects.bulk_update(records, ["organization", "status", "reviewed_at", "reviewed_by", "review_note"])
    return ok, failed


def _apply_org_records(records: list[CrawlRecord], sources: dict) -> dict[str, Organization]:
    if not records:
        return {}
    existing = Organization.objects.in_bulk({r.ubn for r in records}, field_name="ubn")
    created: dict[str, Organization] = {}
    changed: dict[str, Organization] = {}
    for rec in records:
        data = rec.payload
        link = {"name": record_source_name(sources[rec.source_id]), "url": rec.source_url}
        org = existing.get(rec.ubn) or created.get(rec.ubn)
        if org is None:
            fields = {f: str(data.get(f) or "").strip() for f in CRAWLABLE_FIELDS if data.get(f)}
            org = Organization(ubn=rec.ubn, source_links=[link], **fields)
            if not org.name:
                continue
            created[rec.ubn] = org
            continue
        dirty = False
        for f in CRAWLABLE_FIELDS:
            value = str(data.get(f) or "").strip()
            if value and f not in (org.locked_fields or []) and getattr(org, f) != value:
                setattr(org, f, value)
                dirty = True
        links = [l for l in (org.source_links or []) if l.get("name") != link["name"]] + [link]
        if links != org.source_links:
            org.source_links = links
            dirty = True
        if dirty and org.pk:
            org.updated_at = timezone.now()
            changed[rec.ubn] = org
    if created:
        Organization.objects.bulk_create(list(created.values()), ignore_conflicts=True)
    if changed:
        Organization.objects.bulk_update(list(changed.values()), [*CRAWLABLE_FIELDS, "source_links", "updated_at"])
    return Organization.objects.in_bulk({r.ubn for r in records}, field_name="ubn")


def _date(value) -> date | None:
    return date.fromisoformat(value) if value else None


def _apply_child(rec: CrawlRecord, org: Organization, source_name: str) -> None:
    d = rec.payload
    if rec.kind == "annual":
        AnnualFundraising.objects.update_or_create(
            organization=org, year=d["year"], source_name=source_name,
            defaults={"raised": d.get("raised") or 0, "target": d.get("target") or 0, "source_url": rec.source_url},
        )
    elif rec.kind == "project":
        # 團體頁與活動頁各有一部分欄位：只寫有值的，不拿空值蓋掉另一頁抓到的
        values = {f: (_date(d.get(f)) if f in DATE_FIELDS else d.get(f)) for f in PROJECT_FIELDS}
        values = {f: v for f, v in values.items() if v not in (None, "")}
        project, created = Project.objects.get_or_create(
            organization=org, source_name=source_name, external_id=rec.external_id,
            defaults={"name": d["name"][:300], "source_url": rec.source_url, **values},
        )
        if not created:
            for f, v in values.items():
                setattr(project, f, v)
            project.name = d["name"][:300]
            project.save()
    elif rec.kind == "penalty":
        # 團體頁的裁處卡片欄位少、違規公告的完整：同一筆（同編號）只補有值的欄位，不拿空值蓋掉
        values = {
            "decided_on": _date(d.get("decided_on")),
            "authority": d.get("authority", ""),
            "document_no": (d.get("document_no") or "")[:200],
            "content": d.get("content", ""),
            "fine_text": (d.get("fine_text") or "")[:300],
            "reason": d.get("reason", ""),
        }
        values = {k: v for k, v in values.items() if v not in (None, "")}
        penalty, created = Penalty.objects.get_or_create(
            organization=org, source_name=source_name, external_id=rec.external_id,
            defaults={"source_url": rec.source_url, **values},
        )
        if not created:
            for k, v in values.items():
                setattr(penalty, k, v)
            if "violationDetails" in rec.source_url:
                penalty.source_url = rec.source_url
            penalty.save()
    elif rec.kind == "donor_list":
        _apply_donor_list(rec, org, source_name)


def _apply_donor_list(rec: CrawlRecord, org: Organization, source_name: str) -> None:
    """一份清冊整份取代：先刪這個專案這個來源的舊逐筆，再寫新的；摘要同步更新。"""
    d = rec.payload
    project, _ = Project.objects.get_or_create(
        organization=org, source_name=source_name, external_id=rec.external_id,
        defaults={"name": d.get("project_name", "")[:300] or "（未命名活動）", "source_url": rec.source_url},
    )
    kinds = {r["name"]: r["kind"] for r in d.get("rows", []) if r.get("name")}
    donors: dict[str, Donor] = {}
    names = sorted(kinds)
    for i in range(0, len(names), 900):
        donors.update(Donor.objects.in_bulk(names[i : i + 900], field_name="name"))
    missing = [Donor(name=n[:200], kind=kinds[n]) for n in names if n not in donors]
    if missing:
        Donor.objects.bulk_create(missing, ignore_conflicts=True)
        for i in range(0, len(names), 900):
            donors.update(Donor.objects.in_bulk(names[i : i + 900], field_name="name"))

    Donation.objects.filter(project=project, source_name=source_name).delete()
    Donation.objects.bulk_create(
        [
            Donation(
                organization=org, project=project, donor=donors.get(r["name"]), donor_name=r["name"][:200],
                amount=r.get("amount") or 0, donated_on=_date(r.get("donated_on")),
                receipt_no=(r.get("receipt_no") or "")[:50], purpose=(r.get("purpose") or "")[:200],
                source_name=source_name, source_url=rec.source_url,
            )
            for r in d.get("rows", [])
            if r.get("name")
        ],
        batch_size=500,
    )
    summary = d.get("summary", {})
    DonorListSummary.objects.update_or_create(
        project=project,
        defaults={
            **{k: summary.get(k, 0) for k in (
                "total_rows", "total_amount", "small_individual_count", "small_individual_amount",
                "anonymous_rows", "anonymous_amount", "threshold",
            )},
            "source_name": source_name,
            "source_url": rec.source_url,
        },
    )
