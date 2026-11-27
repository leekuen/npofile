"""把爬蟲解析出來的 Item 存成 CrawlRecord，並在核准（或自動上架）時寫進組織資料。"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date

from django.db import transaction
from django.utils import timezone
from npofile_crawler.http import PoliteClient
from npofile_crawler.items import Item
from npofile_crawler.sources import SOURCES

from orgs import scoring
from orgs.models import CRAWLABLE_FIELDS, AnnualFundraising, Organization, Penalty, Project
from orgs.signals import suspend_scoring

from .models import CrawlerSource, CrawlRecord, CrawlRun

log = logging.getLogger(__name__)

BATCH = 500
KIND_ORDER = {"org": 0, "annual": 1, "project": 2, "penalty": 3}


def ensure_sources() -> None:
    for s in SOURCES.values():
        CrawlerSource.objects.get_or_create(
            key=s.key,
            defaults={"name": s.name, "url": s.url, "auto_approve": s.official, "description": "政府公開資料" if s.official else ""},
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
                    items = SOURCES[source.key].fetch(client, limit)
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
        if touched:
            scoring.recompute(Organization.objects.filter(ubn__in=touched))
        run.finished_at = timezone.now()
        run.save()
        source.last_run_at = run.finished_at
        source.save(update_fields=["last_run_at"])
    return run


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
    """把紀錄寫進組織資料；回傳（成功筆數, 失敗筆數）。失敗的保持原狀態並寫備註。"""
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
                _apply_child(rec, org, sources[rec.source_id].name)
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
        link = {"name": sources[rec.source_id].name, "url": rec.source_url}
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
        Project.objects.update_or_create(
            organization=org, source_name=source_name, external_id=rec.external_id,
            defaults={
                "name": d["name"][:300],
                "category": d.get("category", ""),
                "start_date": _date(d.get("start_date")),
                "end_date": _date(d.get("end_date")),
                "target": d.get("target"),
                "raised": d.get("raised"),
                "permit_no": d.get("permit_no", ""),
                "result_filed_on": _date(d.get("result_filed_on")),
                "closed_filed_on": _date(d.get("closed_filed_on")),
                "description": d.get("description", ""),
                "source_url": rec.source_url,
            },
        )
    elif rec.kind == "penalty":
        Penalty.objects.update_or_create(
            organization=org, source_name=source_name, external_id=rec.external_id,
            defaults={
                "decided_on": _date(d.get("decided_on")),
                "authority": d.get("authority", ""),
                "content": d.get("content", ""),
                "fine_text": d.get("fine_text", "")[:300],
                "source_url": rec.source_url,
            },
        )
