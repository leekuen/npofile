import json

from django.conf import settings
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from npofile_crawler.financials import AMOUNT_FIELDS

from orgs.models import FinancialYear, OrgDocument, Organization

from . import progress
from .ingest import apply_records, recompute_ubns, run_source
from .models import ActivityProgress, CrawlerSource, CrawlRecord, CrawlRequest, CrawlRun, OrgSiteCheck

TRIAL_LIMIT = 5


@admin.register(CrawlerSource)
class CrawlerSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "enabled", "auto_approve", "max_items", "max_minutes", "last_run_at")
    list_editable = ("enabled", "auto_approve", "max_items", "max_minutes")
    readonly_fields = ("key", "last_run_at", "activity_progress")
    actions = ["queue_full_crawl", "trial_run"]

    @admin.display(description="抓取進度")
    def activity_progress(self, obj):
        return progress.summary_text() if obj.key == "mohw_activities" else "—"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="排入完整爬取（背景執行，一分鐘內開始）")
    def queue_full_crawl(self, request, queryset):
        active = CrawlRequest.objects.filter(
            status__in=[CrawlRequest.Status.QUEUED, CrawlRequest.Status.RUNNING]
        ).first()
        if active:
            self.message_user(
                request,
                f"已經有一個還沒跑完的完整爬取（#{active.pk}，{active.get_status_display()}），等它跑完再排。",
                messages.WARNING,
            )
            return
        sources = [s for s in queryset if s.enabled]
        skipped = [s.name for s in queryset if not s.enabled]
        if not sources:
            self.message_user(request, "勾選的來源都是停用的，沒有排入。要跑的話先把它改成啟用。", messages.WARNING)
            return
        req = CrawlRequest.objects.create(requested_by=request.user)
        req.sources.set(sources)
        self.message_user(
            request,
            f"已排入完整爬取 #{req.pk}：{'、'.join(s.name for s in sources)}。排程一分鐘內會開始，"
            "跑完會清掉舊資料並重算揭露層級；進度看「完整爬取請求」與「爬蟲執行紀錄」。"
            + (f"略過停用的來源：{'、'.join(skipped)}。" if skipped else ""),
            messages.SUCCESS,
        )

    @admin.action(description=f"立即試跑（每個來源只抓 {TRIAL_LIMIT} 筆）")
    def trial_run(self, request, queryset):
        for source in queryset:
            run = run_source(source, limit=TRIAL_LIMIT, min_interval=settings.CRAWLER_MIN_INTERVAL)
            level = messages.SUCCESS if run.status == CrawlRun.Status.SUCCESS else messages.ERROR
            self.message_user(
                request,
                f"{source.name}：{run.get_status_display()}，抓到 {run.fetched}、新資料 {run.created}、"
                f"上架 {run.applied}、待審核 {run.pending}、失敗 {run.failed}"
                + (f"（{run.error}）" if run.error else ""),
                level,
            )


class ProgressStateFilter(admin.SimpleListFilter):
    title = "進度"
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return [("done", "已抓"), ("pending", "還沒抓"), ("unmatched", "對不到")]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "done":
            return queryset.filter(checked_at__isnull=False, unmatched_reason="")
        if value == "pending":
            return queryset.filter(checked_at__isnull=True)
        if value == "unmatched":
            return queryset.exclude(unmatched_reason="")
        return queryset


@admin.register(ActivityProgress)
class ActivityProgressAdmin(admin.ModelAdmin):
    list_display = ("activity_id", "name", "org_name", "ubn", "roc_year", "listed_raised", "has_donor_list",
                    "unmatched_reason", "checked_at")
    list_filter = (ProgressStateFilter, "roc_year", "has_donor_list")
    search_fields = ("activity_id", "name", "org_name", "ubn")
    readonly_fields = [f.name for f in ActivityProgress._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), "title": f"勸募活動抓取進度：{progress.summary_text()}"}
        return super().changelist_view(request, extra_context)


@admin.register(CrawlRun)
class CrawlRunAdmin(admin.ModelAdmin):
    list_display = ("source", "started_at", "finished_at", "status", "fetched", "created", "applied", "pending", "failed",
                    "note")
    list_filter = ("source", "status")
    readonly_fields = [f.name for f in CrawlRun._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ReviewStatusFilter(admin.SimpleListFilter):
    """預設只看待審核；選「全部」才看全部。"""

    title = "狀態"
    parameter_name = "review"

    def lookups(self, request, model_admin):
        return [*CrawlRecord.Status.choices, ("all", "全部")]

    def choices(self, changelist):
        for value, label in self.lookup_choices:
            yield {
                "selected": (self.value() or CrawlRecord.Status.PENDING) == value,
                "query_string": changelist.get_query_string({self.parameter_name: value}),
                "display": label,
            }

    def queryset(self, request, queryset):
        value = self.value() or CrawlRecord.Status.PENDING
        return queryset if value == "all" else queryset.filter(status=value)


DOC_KIND_LABELS = dict(OrgDocument.Kind.choices)
FIELD_LABELS = {f: FinancialYear._meta.get_field(f).verbose_name for f in AMOUNT_FIELDS}


def _ext_link(url, text):
    if not url:
        return "—"
    return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, text)


def _financial_table(rec):
    """年度財務：一個欄位一列，金額加千分位，旁邊放原始報告連結，方便對照 PDF 核准。"""
    p = rec.payload
    rows = [("年度", f"民國 {p.get('year')} 年"), ("報告", p.get("document_title") or "—")]
    rows += [(FIELD_LABELS[f], "—（報告沒列）" if p.get(f) is None else f"{p[f]:,} 元") for f in AMOUNT_FIELDS]
    audited = {True: "有", False: "沒有", None: "看不出來"}[p.get("audited")]
    rows += [("經會計師查核", audited), ("AI 備註", p.get("notes") or "—")]
    body = format_html_join("", "<tr><th style='text-align:left;padding-right:1em'>{}</th><td>{}</td></tr>", rows)
    extra = ""
    if rec.status in (CrawlRecord.Status.APPROVED, CrawlRecord.Status.AUTO) and rec.organization_id:
        fy = FinancialYear.objects.filter(organization_id=rec.organization_id, year=p.get("year")).first()
        if fy:
            extra = format_html(
                '<p>已上架。數字有錯：<a href="{}">到這一年的年度財務修改</a>（改過會鎖住，爬蟲不覆蓋）</p>',
                reverse("admin:orgs_financialyear_change", args=[fy.pk]),
            )
    return format_html(
        "<p>{}　請對照原檔確認數字再核准；AI 讀的數字可能讀錯。</p><table>{}</table>{}",
        _ext_link(p.get("document_url"), "打開原始報告"), body, extra,
    )


class MatchFilter(admin.SimpleListFilter):
    """名稱對不上組織的（統編空白，LK-29 勞動局處分）：管理員指定組織後核准，或退回略過。"""

    title = "對組織"
    parameter_name = "match"

    def lookups(self, request, model_admin):
        return [("unmatched", "對不上組織（待指定）"), ("matched", "有統編")]

    def queryset(self, request, queryset):
        if self.value() == "unmatched":
            return queryset.filter(ubn="")
        if self.value() == "matched":
            return queryset.exclude(ubn="")
        return queryset


@admin.register(CrawlRecord)
class CrawlRecordAdmin(admin.ModelAdmin):
    list_display = ("kind", "ubn", "summary", "source", "status", "created_at")
    list_filter = (ReviewStatusFilter, MatchFilter, "kind", "source")
    search_fields = ("ubn", "external_id", "payload__org_name")
    readonly_fields = (
        "source", "run", "kind", "ubn", "org_name", "external_id", "pretty_payload", "link", "status",
        "organization", "created_at", "reviewed_at", "reviewed_by",
    )
    fields = readonly_fields + ("review_note",)
    autocomplete_fields = ("organization",)
    actions = ["approve", "reject"]

    def has_add_permission(self, request):
        return False

    def get_readonly_fields(self, request, obj=None):
        # 對不上組織、還沒審的：可以在「對應組織」指定組織，按「核准並上架」就掛到那個組織
        if obj is not None and not obj.ubn and obj.status == CrawlRecord.Status.PENDING:
            return tuple(f for f in self.readonly_fields if f != "organization")
        return self.readonly_fields

    @admin.display(description="內容摘要")
    def summary(self, obj):
        p = obj.payload
        if obj.kind == CrawlRecord.Kind.FINANCIAL:
            total = p.get("total_revenue")
            return f"{p.get('year')} 年 總收入 {total:,} 元" if isinstance(total, int) else f"{p.get('year')} 年"
        if obj.kind == CrawlRecord.Kind.DOCUMENT:
            return f"{p.get('year')} 年 {DOC_KIND_LABELS.get(p.get('doc_kind'), '')}：{p.get('title', '')}"[:60]
        if obj.kind == CrawlRecord.Kind.PENALTY and p.get("org_name"):
            return f"{p['org_name']}：{p.get('content', '')}"[:60]
        return str(p.get("name") or p.get("content") or p.get("title") or p.get("year") or "")[:40]

    @admin.display(description="組織")
    def org_name(self, obj):
        if not obj.ubn:
            return f"（對不上組織：來源上的名稱是「{obj.payload.get('org_name', '')}」，請在下方「對應組織」指定，或退回）"
        org = Organization.objects.filter(ubn=obj.ubn).only("name").first()
        return org.name if org else "（還沒有這個統一編號的組織）"

    @admin.display(description="內容")
    def pretty_payload(self, obj):
        p = obj.payload
        if obj.kind == CrawlRecord.Kind.FINANCIAL:
            return _financial_table(obj)
        if obj.kind == CrawlRecord.Kind.DOCUMENT:
            return format_html(
                "<table><tr><th>年度</th><td>民國 {} 年</td></tr><tr><th>種類</th><td>{}</td></tr>"
                "<tr><th>標題</th><td>{}</td></tr><tr><th>檔案</th><td>{}</td></tr><tr><th>在哪一頁找到</th><td>{}</td></tr></table>",
                p.get("year"), DOC_KIND_LABELS.get(p.get("doc_kind"), p.get("doc_kind")), p.get("title", ""),
                _ext_link(p.get("url"), "打開原始報告"), _ext_link(p.get("found_on"), p.get("found_on") or "—"),
            )
        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", json.dumps(p, ensure_ascii=False, indent=2))

    @admin.display(description="來源網址")
    def link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', obj.source_url, obj.source_url) if obj.source_url else "—"

    def response_change(self, request, obj):
        """審核頁上的「核准並上架」「退回」按鈕：照列表動作的同一套規則處理這一筆，回到待審核清單。"""
        qs = CrawlRecord.objects.filter(pk=obj.pk)
        if "_approve" in request.POST:
            self.approve(request, qs)
        elif "_reject" in request.POST:
            self.reject(request, qs)
        else:
            return super().response_change(request, obj)
        return HttpResponseRedirect(reverse("admin:crawling_crawlrecord_changelist"))

    @admin.action(description="核准並上架")
    def approve(self, request, queryset):
        records = list(queryset.filter(status=CrawlRecord.Status.PENDING).select_related("source"))
        ok, failed = apply_records(records, CrawlRecord.Status.APPROVED, user=request.user)
        recompute_ubns({r.ubn for r in records})
        self.message_user(request, f"已核准 {ok} 筆" + (f"，{failed} 筆失敗（看審核備註）" if failed else ""),
                          messages.WARNING if failed else messages.SUCCESS)

    @admin.action(description="退回（不上架）")
    def reject(self, request, queryset):
        n = queryset.filter(status=CrawlRecord.Status.PENDING).update(
            status=CrawlRecord.Status.REJECTED, reviewed_at=timezone.now(), reviewed_by=request.user
        )
        self.message_user(request, f"已退回 {n} 筆", messages.SUCCESS)


@admin.register(CrawlRequest)
class CrawlRequestAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "source_names", "requested_by", "requested_at", "started_at", "finished_at")
    list_filter = ("status",)
    readonly_fields = ("status", "source_names", "requested_by", "requested_at", "started_at", "finished_at",
                       "pretty_output")
    fields = readonly_fields
    actions = ["cancel"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="來源")
    def source_names(self, obj):
        return "、".join(obj.sources.values_list("name", flat=True))

    @admin.display(description="執行紀錄")
    def pretty_output(self, obj):
        if not obj.output:
            return "（還沒有，跑完才會寫入；執行中的進度看「爬蟲執行紀錄」）"
        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", obj.output)

    @admin.action(description="取消（只限排隊中）")
    def cancel(self, request, queryset):
        n = queryset.filter(status=CrawlRequest.Status.QUEUED).update(
            status=CrawlRequest.Status.CANCELED, finished_at=timezone.now()
        )
        self.message_user(request, f"已取消 {n} 筆" + ("（執行中的不能取消）" if n < queryset.count() else ""),
                          messages.SUCCESS)


@admin.register(OrgSiteCheck)
class OrgSiteCheckAdmin(admin.ModelAdmin):
    list_display = ("ubn", "website", "checked_at")
    search_fields = ("ubn", "website")
    readonly_fields = ("ubn", "website", "checked_at")

    def has_add_permission(self, request):
        return False
