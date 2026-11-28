"""把爬蟲解析出來的 Item 存成 CrawlRecord，並在核准（或自動上架）時寫進組織資料。"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from npofile_crawler import donors as donor_names
from npofile_crawler import judicial, labor
from npofile_crawler.grants import OrgMatcher
from npofile_crawler.http import PoliteClient
from npofile_crawler.items import Item
from npofile_crawler.sources import SOURCES

from orgs import annual_lists, period, scoring
from orgs.categorize import categorize
from orgs.models import (
    CRAWLABLE_FIELDS,
    AnnualDonorList,
    AnnualFundraising,
    Donation,
    DonationCode,
    Donor,
    DonorListSummary,
    FinancialYear,
    Grant,
    OrgDocument,
    Organization,
    CourtRegistration,
    Penalty,
    Project,
    RegistryEntry,
)
from orgs.signals import suspend_scoring

from . import orgsite_targets, progress
from .models import CrawlerSource, CrawlRecord, CrawlRun
from .progress import DbActivityPlan

log = logging.getLogger(__name__)

BATCH = 500
STORE_EVERY = 60  # 秒
KIND_ORDER = {"org": 0, "annual": 1, "project": 2, "penalty": 3, "donor_list": 4, "grant": 5, "document": 6, "financial": 7,
              "court_reg": 8, "registry": 9, "einvoice": 10, "annual_list": 11}
PROJECT_FIELDS = (
    "category", "start_date", "end_date", "target", "raised", "permit_no", "region",
    "result_filed_on", "closed_filed_on", "description", "channel", "monthly_raised", "backers",
    "result_due_on", "result_done", "result_late", "closed_due_on", "closed_done", "closed_late",
)
DATE_FIELDS = {"start_date", "end_date", "result_filed_on", "closed_filed_on", "result_due_on", "closed_due_on"}
# 名冊類（LK-32）：對不到組織也照樣存（前台不顯示、後台可查），不算失敗
ORGLESS_KINDS = {"registry", "einvoice"}


def record_source_name(source: CrawlerSource) -> str:
    s = SOURCES.get(source.key)
    return s.record_name if s else source.name


# 新建來源時的「每次最多跑幾分鐘」：勸募活動與捐贈人清冊每晚接著抓，不讓一次跑整晚（已存在的來源照後台設定）
DEFAULT_MINUTES = {"mohw_activities": 120, "judicial": 120, "twnpos": 120}  # twnpos：自律聯盟財報要影像辨識，很慢（LK-25）


def ensure_sources() -> None:
    for s in SOURCES.values():
        CrawlerSource.objects.get_or_create(
            key=s.key,
            defaults={"name": s.name, "url": s.url, "auto_approve": s.official, "description": s.description,
                      "max_minutes": DEFAULT_MINUTES.get(s.key, 0)},
        )


INTERRUPTED_ERROR = "沒有正常結束：程式被中斷（多半是 container 重啟或自動更新），這一次抓到的照樣保留，下次重新抓"


def close_interrupted_runs(source: CrawlerSource) -> int:
    """同一個來源又要開始跑時，上一次還是「執行中」的就是被中斷、不會再結束了：標成失敗（LK-44）。
    同一個來源不會同時跑兩份（排程一次跑一輪、後台完整爬取一次一個），所以不用怕標錯正在跑的。"""
    return CrawlRun.objects.filter(source=source, status=CrawlRun.Status.RUNNING).update(
        status=CrawlRun.Status.FAILED, finished_at=timezone.now(), error=INTERRUPTED_ERROR
    )


def run_source(source: CrawlerSource, limit: int | None = None, items: Iterable[Item] | None = None,
               min_interval: float = 1.0, client=None) -> CrawlRun:
    """client：測試可塞假的；不給就照來源設定開一個每秒最多一個請求的。"""
    close_interrupted_runs(source)
    run = CrawlRun.objects.create(source=source)
    limit = limit if limit is not None else (source.max_items or None)
    deadline = time.monotonic() + source.max_minutes * 60 if source.max_minutes else None
    own_client = False
    plan = None
    touched: set[str] = set()
    batch: list[Item] = []
    known = set(CrawlRecord.objects.filter(source=source).values_list("content_hash", flat=True))
    skipped = 0
    values: dict = {}

    last_store = time.monotonic()

    def store() -> None:
        nonlocal last_store
        _store_batch(source, run, batch, known, touched)
        batch.clear()
        last_store = time.monotonic()
        if plan is not None:
            plan.flush()  # 資料寫進去了，才把對應的活動記成已抓

    try:
        with suspend_scoring():
            try:
                if items is None:
                    if client is None:
                        client, own_client = PoliteClient(min_interval=min_interval), True
                    src = SOURCES[source.key]
                    if "plan" in src.options:
                        plan = DbActivityPlan()
                    values = {"threshold": settings.DONOR_INDIVIDUAL_THRESHOLD, "since_roc": period.since_roc_year(),
                              "plan": plan}
                    if "revisit" in src.options:
                        values["revisit"] = revisit_ids(source)
                    if "orgs" in src.options:  # 名稱對統編的名冊（約十萬筆，逐筆讀，不一次載入物件）
                        values["orgs"] = Organization.objects.values_list("ubn", "name").iterator(chunk_size=5000)
                    if "have" in src.options:  # 已經收過的財報（決算、會員財報備查後不會再變），不再下載
                        values["have"] = set(CrawlRecord.objects.filter(source=source).values_list("external_id", flat=True))
                    if "orgs_city" in src.options:
                        values["orgs_city"] = Organization.objects.values_list("ubn", "name", "city").iterator(chunk_size=5000)
                    if "moenv_api_key" in src.options:
                        values["moenv_api_key"] = settings.MOENV_API_KEY
                    if "since_date" in src.options:
                        values["since_date"] = since_last_success(source)
                    if "listed" in src.options:
                        values["listed"] = [0]
                    if "seen_regs" in src.options:
                        values.update(court_registration_options())
                    if "labor_docs" in src.options:
                        values["labor_docs"] = labor_docs(source.key)
                    if source.key == "orgsite":
                        values.update(orgsite_targets.options(source))
                    items = src.fetch(client, limit, **{k: values[k] for k in src.options})
                org_ubns = None
                if source.key in SOURCES and SOURCES[source.key].known_orgs_only:
                    org_ubns = set(Organization.objects.values_list("ubn", flat=True))
                for item in items:
                    run.fetched += 1
                    if org_ubns is not None and item.ubn not in org_ubns:
                        skipped += 1
                        continue
                    batch.append(item)
                    # 記進度的來源至少每分鐘存一次：程式中途被關掉（電腦重開、主機重啟），最多只白做一分鐘
                    if len(batch) >= BATCH or (plan is not None and time.monotonic() - last_store >= STORE_EVERY):
                        store()
                    if deadline is not None and time.monotonic() >= deadline:
                        run.note = f"到達每次最多 {source.max_minutes} 分鐘的上限先停，下次接著抓"
                        break
                run.status = CrawlRun.Status.SUCCESS
                stopped_early = bool(run.note) or (limit is not None and run.fetched >= limit)
                if "since_date" in values and values.get("listed") is not None and not stopped_early:
                    run.note = READ_ALL_NOTE  # 這次有讀完（沒被筆數或分鐘上限切斷），下次才只抓新的
                if values.get("listed") is not None:  # 只抓新的的來源：改看列表有沒有讀到東西
                    run.listed_cards = values["listed"][0]
            except Exception as exc:  # 抓到一半失敗：已抓到的照樣存，錯誤記進執行紀錄
                log.exception("crawl %s failed", source.key)
                run.status = CrawlRun.Status.FAILED
                run.error = f"{type(exc).__name__}: {exc}"[:2000]
            store()
            if skipped:
                run.note = "；".join(x for x in (run.note, f"跳過 {skipped} 筆（提案者不是收錄的組織）") if x)[:300]
            if plan is not None:
                run.note = "；".join(x for x in (run.note, progress.summary_text()) if x)[:300]
                run.listed_cards = plan.listed_count  # 不存資料庫：給 crawl 指令判斷「來源網站是不是改版了」
    finally:
        if hasattr(items, "close"):
            items.close()
        if own_client:
            client.close()
        recompute_ubns(touched)
        run.finished_at = timezone.now()
        run.save()
        source.last_run_at = run.finished_at
        source.save(update_fields=["last_run_at"])
    return run


# 只抓新的來源（環境部裁處，LK-36）：從上次成功的那天再往前推這麼多天，接住晚匯入的舊裁處
SINCE_LOOKBACK_DAYS = 120
READ_ALL_NOTE = "已讀完（下次只抓新的）"


def since_last_success(source: CrawlerSource):
    """上次成功抓取的日期往前推 SINCE_LOOKBACK_DAYS 天；從沒成功過回 None（全部回補）。"""
    last = (source.runs.filter(status=CrawlRun.Status.SUCCESS, note__contains=READ_ALL_NOTE)
            .order_by("-started_at").first())
    if last is None:
        return None
    return timezone.localtime(last.started_at).date() - timedelta(days=SINCE_LOOKBACK_DAYS)


def penalty_category(source_name: str, data: dict) -> str:
    """裁罰的類別（LK-36）：爬蟲在 data["category"] 寫明的為準；沒寫的，名稱含「勞動」算勞動法令（同 0015 回填），其餘公益勸募。"""
    category = data.get("category") or ""
    if category in Penalty.Category.values:
        return category
    return Penalty.Category.LABOR if "勞動" in source_name else Penalty.Category.FUNDRAISING


# 不影響揭露層級與分類的資料：存了不用重算
NO_SCORE_KINDS = {"court_reg"}


def court_registration_options() -> dict:
    """法院登記公告：已存過哪些（法院｜案號），回補完了沒。"""
    seen = {f"{c}|{n}" for c, n in CourtRegistration.objects.values_list("court", "case_no").iterator(chunk_size=5000)}
    oldest = CourtRegistration.objects.order_by("posted_on").values_list("posted_on", flat=True).first()
    return {"seen_regs": seen, "floor_reached": judicial.backfill_done(oldest)}


def labor_docs(key: str) -> set[str]:
    """別的勞動來源已收過的處分字號（LK-37）：臺北市總表與勞動部全國系統會列到同一張處分，先收到的算數，
    另一邊不再收（含退回的：管理員已經判過這張不是收錄的組織）。"""
    others = [k for k in (*(s.key for s in labor.SPECS), labor.MOL_KEY) if k != key]
    # 讀整份 payload 再取欄位：SQLite 用 payload__document_no 取值會把全是數字的字號（例「1150253854」）讀成整數
    payloads = (CrawlRecord.objects.filter(source__key__in=others, kind=CrawlRecord.Kind.PENALTY)
                .values_list("payload", flat=True).iterator(chunk_size=5000))
    return {str(d) for p in payloads if (d := (p or {}).get("document_no"))}


# 已收過的群眾集資專案：長期集資或結束未滿這麼多天的，列表上沒有也要回頭再看（記下結束時的金額）
REVISIT_DAYS = 14


def revisit_ids(source: CrawlerSource) -> list[str]:
    since = timezone.localdate() - timedelta(days=REVISIT_DAYS)
    return list(
        Project.objects.filter(source_name=record_source_name(source), channel=Project.Channel.CROWDFUNDING)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=since))
        .exclude(external_id="")
        .values_list("external_id", flat=True)
        .distinct()
    )


def recompute_ubns(ubns: set[str], chunk: int = 900) -> None:
    """資料有更新的組織：重算揭露層級、重新分類。SQLite 單一查詢的參數有上限，分批送。"""
    items = sorted(ubns)
    for i in range(0, len(items), chunk):
        orgs = Organization.objects.filter(ubn__in=items[i : i + chunk])
        scoring.recompute(orgs)
        categorize(orgs)


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
        # 統編空白＝名稱對不上組織（LK-29 勞動局處分）：不上架，留在審核清單等管理員指定組織或退回
        matched = [r for r in saved if r.ubn or r.kind in NO_SCORE_KINDS or r.kind in ORGLESS_KINDS]  # 法院公告、名冊對不到也照存（LK-31、LK-32）
        ok, failed = apply_records(matched, CrawlRecord.Status.AUTO)
        run.applied += ok
        run.failed += failed
        run.pending += len(saved) - len(matched)
        touched.update(r.ubn for r in matched if r.kind not in NO_SCORE_KINDS and r.kind not in ORGLESS_KINDS)  # 名冊、法院公告不影響指數與分類
    else:
        updates = _approved_updates(source, saved)
        if updates:
            ok, failed = apply_records(updates, CrawlRecord.Status.AUTO)
            run.applied += ok
            run.failed += failed
            touched.update(r.ubn for r in updates if r.kind not in ORGLESS_KINDS)
        run.pending += len(saved) - len(updates)
    run.save(update_fields=["fetched", "created", "applied", "pending", "failed"])


def _approved_updates(source: CrawlerSource, saved: list[CrawlRecord]) -> list[CrawlRecord]:
    """來源設了 update_approved：同一筆（同類型、同編號、同統編）已核准過的，新版本直接上架。"""
    src = SOURCES.get(source.key)
    if not (src and src.update_approved):
        return []
    ids = {r.external_id for r in saved if r.external_id}
    done = set(
        CrawlRecord.objects.filter(
            source=source, external_id__in=ids,
            status__in=[CrawlRecord.Status.APPROVED, CrawlRecord.Status.AUTO],
        ).values_list("kind", "external_id", "ubn")
    )
    return [r for r in saved if (r.kind, r.external_id, r.ubn) in done]


@transaction.atomic
def apply_records(records: list[CrawlRecord], status: str, user=None) -> tuple[int, int]:
    """把紀錄寫進組織資料；回傳（成功筆數, 失敗筆數）。失敗的保持原狀態並寫備註。
    揭露層級不在這裡逐筆重算：呼叫的人寫完後用 recompute_ubns 一次算。"""
    with suspend_scoring():
        return _apply_records(records, status, user)


def _apply_records(records: list[CrawlRecord], status: str, user) -> tuple[int, int]:
    records = sorted(records, key=lambda r: KIND_ORDER[r.kind])
    sources = {r.source_id: r.source for r in records}
    # 對不上組織、管理員在「對應組織」指定了的：用指定的組織的統編上架
    assigned = Organization.objects.in_bulk({r.organization_id for r in records if not r.ubn and r.organization_id})
    for rec in records:
        if not rec.ubn and rec.organization_id in assigned:
            rec.ubn = assigned[rec.organization_id].ubn
    orgs = _apply_org_records([r for r in records if r.kind == "org"], sources)
    for ubn, org in Organization.objects.in_bulk(
        {r.ubn for r in records} - set(orgs), field_name="ubn"
    ).items():
        orgs[ubn] = org

    now = timezone.now()
    ok = failed = 0
    for rec in records:
        org = orgs.get(rec.ubn) if rec.ubn else None
        if rec.kind == "court_reg" or rec.kind in ORGLESS_KINDS:  # 對不到組織也照存（法院公告 LK-31、名冊 LK-32），不算失敗
            if rec.kind == "court_reg":
                _apply_court_registration(rec, org, record_source_name(sources[rec.source_id]))
            else:
                _apply_registry(rec, org, record_source_name(sources[rec.source_id]))
            rec.organization = org
            rec.status = status
            rec.reviewed_at = now
            rec.reviewed_by = user
            ok += 1
        elif not rec.ubn:
            rec.review_note = "名稱對不上組織：先在「對應組織」指定是哪個組織再核准；不是收錄的組織就退回"
            failed += 1
        elif org is None:
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
    CrawlRecord.objects.bulk_update(records, ["ubn", "organization", "status", "reviewed_at", "reviewed_by", "review_note"])
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
            "law": (d.get("law") or "")[:300],
            "category": penalty_category(source_name, d),
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
    elif rec.kind == "grant":
        Grant.objects.update_or_create(
            source_name=source_name, external_id=rec.external_id,
            defaults={
                "organization": org, "source_url": rec.source_url, "year": d["year"], "quarter": d.get("quarter") or 4,
                "agency": (d.get("agency") or "")[:100], "county": (d.get("county") or "")[:20],
                "recipient": (d.get("recipient") or "")[:300], "facility": (d.get("facility") or "")[:200],
                "purpose": (d.get("purpose") or "")[:500], "approved_on": _date(d.get("approved_on")),
                "amount": d.get("amount") or 0,
            },
        )
    elif rec.kind == "donor_list":
        _apply_donor_list(rec, org, source_name)
    elif rec.kind == "document":
        OrgDocument.objects.update_or_create(
            organization=org, url=d["url"][:1000],
            defaults={"year": d["year"], "kind": d["doc_kind"], "title": (d.get("title") or "")[:200],
                      "found_on": (d.get("found_on") or "")[:1000], "source_name": source_name},
        )
    elif rec.kind == "financial":
        _apply_financial(rec, org, source_name)
    elif rec.kind == "annual_list":
        _apply_annual_donor_list(rec, org, source_name)


def _apply_registry(rec: CrawlRecord, org: Organization | None, source_name: str) -> None:
    """名冊與捐贈碼（LK-32）：只寫自己的表，不動組織的基本欄位（財政部名冊那幾欄）。"""
    d = rec.payload
    if rec.kind == "einvoice":
        DonationCode.objects.update_or_create(
            source_name=source_name, code=d["code"][:10],
            defaults={"ubn": rec.ubn, "registered_name": (d.get("name") or "")[:200],
                      "short_name": (d.get("short_name") or "")[:100], "county": (d.get("county") or "")[:10],
                      "source_url": rec.source_url},
        )
        return
    values = {
        "authority": (d.get("authority") or "")[:50], "registry_name": (d.get("name") or "")[:200],
        "permit_no": (d.get("permit_no") or "")[:100], "founded_on": _date(d.get("founded_on")),
        "permitted_assets": d.get("permitted_assets"), "registered_assets": d.get("registered_assets"),
        "purpose": d.get("purpose") or "", "main_business": d.get("main_business") or "",
        "service_targets": (d.get("service_targets") or "")[:300],
        "business_category": (d.get("business_category") or "")[:300],
        "status": (d.get("status") or "")[:20], "data_date": _date(d.get("data_date")), "source_url": rec.source_url,
    }
    entry = RegistryEntry.objects.filter(source_name=source_name, external_id=rec.external_id).first()
    if entry is None:
        RegistryEntry.objects.create(source_name=source_name, external_id=rec.external_id, organization=org, **values)
        return
    for k, v in values.items():
        setattr(entry, k, v)
    if not entry.org_manual:  # 管理員指定過的組織，重新匯入不改
        entry.organization = org
    entry.save()


FINANCIAL_FIELDS = (
    "total_revenue", "contributions", "government_grants", "program_service_revenue", "investment_income",
    "other_revenue", "total_expenses", "program_expenses", "admin_expenses", "fundraising_expenses",
    "surplus", "total_assets", "total_liabilities", "net_assets", "audited",
)


# 同一年有多個來源時誰的數字優先（LK-25）：政府公開決算 > 讀報告（AI／文字）> 影像辨識；
# 沒有任何數字的（只有報告連結）不算數，誰都可以蓋過
METHOD_RANK = {"official": 3, "ai": 2, "text": 2, "manual": 2, "ocr": 1}


def _has_numbers(values) -> bool:
    return any(values.get(f) is not None for f in FINANCIAL_FIELDS)


def _apply_financial(rec: CrawlRecord, org: Organization, source_name: str) -> None:
    """同一年整列取代；管理員改過（locked）的那一年不動；可信度較低的來源不蓋過較高的。"""
    d = rec.payload
    existing = FinancialYear.objects.filter(organization=org, year=d["year"]).first()
    if existing and existing.locked:
        rec.review_note = "這一年的財務數字管理員改過，沒有覆蓋"
        return
    method = d.get("method") if d.get("method") in FinancialYear.Method.values else FinancialYear.Method.MANUAL
    if existing:
        have = METHOD_RANK.get(existing.method, 0) if _has_numbers(vars(existing)) else 0
        new = METHOD_RANK.get(method, 0) if _has_numbers(d) else 0
        if new < have:
            rec.review_note = f"這一年已有{existing.get_method_display()}的數字（{existing.source_name}），沒有覆蓋"
            return
    values = {f: d.get(f) for f in FINANCIAL_FIELDS}
    values.update(
        document_url=(d.get("document_url") or "")[:1000], document_title=(d.get("document_title") or "")[:200],
        method=method, notes=(d.get("notes") or "")[:300], source_name=source_name,
    )
    FinancialYear.objects.update_or_create(organization=org, year=d["year"], defaults=values)


def _apply_donor_list(rec: CrawlRecord, org: Organization, source_name: str) -> None:
    """一份清冊整份取代：先刪這個專案這個來源的舊逐筆，再寫新的；摘要同步更新。"""
    d = rec.payload
    project, _ = Project.objects.get_or_create(
        organization=org, source_name=source_name, external_id=rec.external_id,
        defaults={"name": d.get("project_name", "")[:300] or "（未命名活動）", "source_url": rec.source_url},
    )
    # 用「比對用名稱」對到既有捐款人：台／臺、空白、(股) 不同的寫法都算同一位（LK-16）
    first: dict[str, dict] = {}
    for r in d.get("rows", []):
        if r.get("name"):
            first.setdefault(donor_names.identity_key(r["name"])[:200], r)
    donors: dict[str, Donor] = {}
    keys = sorted(first)
    for i in range(0, len(keys), 900):
        donors.update(Donor.objects.in_bulk(keys[i : i + 900], field_name="name_key"))
    missing = [
        Donor(name=donor_names.normalize(first[k]["name"])[:200], name_key=k, kind=first[k]["kind"])
        for k in keys if k not in donors
    ]
    if missing:
        Donor.objects.bulk_create(missing, ignore_conflicts=True)
        for i in range(0, len(keys), 900):
            donors.update(Donor.objects.in_bulk(keys[i : i + 900], field_name="name_key"))

    Donation.objects.filter(project=project, source_name=source_name).delete()
    Donation.objects.bulk_create(
        [
            Donation(
                organization=org, project=project, donor=donors.get(donor_names.identity_key(r["name"])[:200]),
                donor_name=donor_names.normalize(r["name"])[:200],
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
    annual_lists.mark_duplicates({org.id})  # 衛福部清冊進來後，同一筆在年度清冊上的就不再算（LK-48）


def _donors_for(rows: list[dict]) -> dict[str, Donor]:
    """名稱 → 捐款人（用比對用名稱對到既有的，沒有就建）。"""
    first: dict[str, dict] = {}
    for r in rows:
        if r.get("name"):
            first.setdefault(donor_names.identity_key(r["name"])[:200], r)
    keys = sorted(first)
    donors: dict[str, Donor] = {}
    for i in range(0, len(keys), 900):
        donors.update(Donor.objects.in_bulk(keys[i : i + 900], field_name="name_key"))
    missing = [
        Donor(name=donor_names.normalize(first[k]["name"])[:200], name_key=k, kind=first[k]["kind"])
        for k in keys if k not in donors
    ]
    if missing:
        Donor.objects.bulk_create(missing, ignore_conflicts=True)
        for i in range(0, len(keys), 900):
            donors.update(Donor.objects.in_bulk(keys[i : i + 900], field_name="name_key"))
    return donors


_org_matcher: tuple[int, OrgMatcher] | None = None


def org_matcher() -> OrgMatcher:
    """支付清冊的受捐者對組織：規則同政府補助（名稱正規化後完全相同且唯一；「X附設Y」歸 X）。組織數變了才重建。"""
    global _org_matcher
    n = Organization.objects.count()
    if _org_matcher is None or _org_matcher[0] != n:
        _org_matcher = (n, OrgMatcher(Organization.objects.values_list("ubn", "name").iterator(chunk_size=5000)))
    return _org_matcher[1]


def _apply_annual_donor_list(rec: CrawlRecord, org: Organization, source_name: str) -> None:
    """財團法人年度捐贈名單清冊（LK-48）。一份清冊整份取代：先刪這份的舊捐款再寫新的，最後重算去重。
    接受清冊：列上的＝捐給這個組織的。支付清冊：這個組織＝捐款者，列上的受捐者對得上站上組織才記成對方的捐款。"""
    d = rec.payload
    direction = d["direction"]
    summary = d.get("summary", {})
    rows = d.get("rows", [])
    lst, _ = AnnualDonorList.objects.update_or_create(
        organization=org, url=d["url"][:1000],
        defaults={
            "year": d["year"], "direction": direction, "title": (d.get("title") or "")[:200],
            "found_on": (d.get("found_on") or "")[:1000], "file_format": (d.get("format") or "")[:10],
            "scanned": bool(d.get("scanned")), "source_name": source_name,
            **{k: summary.get(k, 0) for k in (
                "total_rows", "total_amount", "small_individual_count", "small_individual_amount",
                "anonymous_rows", "anonymous_amount", "government_rows", "government_amount", "threshold",
            )},
        },
    )
    old_orgs = set(lst.donations.values_list("organization_id", flat=True))
    lst.donations.all().delete()
    label = lst.source_label
    donations: list[Donation] = []
    unmatched: list[dict] = []
    if direction == AnnualDonorList.Direction.RECEIVE:
        donors = _donors_for(rows)
        for r in rows:
            donor = donors.get(donor_names.identity_key(r["name"])[:200])
            donations.append(Donation(
                organization=org, donor=donor, donor_name=donor_names.normalize(r["name"])[:200], amount=r["amount"],
                year=lst.year, annual_list=lst, source_name=label, source_url=lst.url,
            ))
    else:
        giver = _donors_for([{"name": org.name, "kind": donor_names.classify(org.name)}]).get(
            donor_names.identity_key(org.name)[:200]
        )
        matcher = org_matcher()
        recipients = Organization.objects.in_bulk(
            {hit[0] for r in rows if (hit := matcher.match(r["name"]))} - {org.ubn}, field_name="ubn"
        )
        for r in rows:
            hit = matcher.match(r["name"])
            recipient = recipients.get(hit[0]) if hit else None
            if recipient is None:
                unmatched.append({"name": r["name"], "amount": r["amount"]})
                continue
            donations.append(Donation(
                organization=recipient, donor=giver, donor_name=org.name[:200], amount=r["amount"],
                year=lst.year, annual_list=lst, source_name=label, source_url=lst.url,
            ))
    Donation.objects.bulk_create(donations, batch_size=500)
    lst.kept_rows = len(donations)
    lst.unmatched = unmatched[:500]
    lst.save(update_fields=["kept_rows", "unmatched", "updated_at"])
    affected = old_orgs | {x.organization_id for x in donations}
    annual_lists.mark_duplicates(affected)
    others = Organization.objects.filter(id__in=affected - {org.id}).values_list("ubn", flat=True)
    if others:
        recompute_ubns(set(others))  # 支付清冊的受捐組織：「有資料」可能變了


REG_FIELDS = ("reg_no", "category", "name", "case_type", "posted_on")


def _apply_court_registration(rec: CrawlRecord, org: Organization | None, source_name: str) -> None:
    """同一筆＝法院＋登記案號；管理員指定過組織的不改組織。內頁沒讀到的不拿空值蓋掉已讀到的。"""
    d = rec.payload
    values = {f: d.get(f) or "" for f in REG_FIELDS}
    values["name"] = values["name"][:200]
    values["posted_on"] = _date(d.get("posted_on"))
    values.update(source_name=source_name, source_url=rec.source_url)
    if d.get("detail_fetched"):
        values.update(
            registered_on=_date(d.get("registered_on")), property_total=d.get("property_total"),
            change_items=list(d.get("change_items") or []), detail_fetched=True,
        )
    reg, created = CourtRegistration.objects.get_or_create(
        court=d["court"][:50], case_no=d["case_no"][:80], defaults={**values, "organization": org},
    )
    if not created:
        for k, v in values.items():
            setattr(reg, k, v)
        if not reg.org_manual and org is not None:
            reg.organization = org
        reg.save()
