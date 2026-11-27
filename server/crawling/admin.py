import json

from django.conf import settings
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from . import progress
from .ingest import apply_records, recompute_ubns, run_source
from .models import ActivityProgress, CrawlerSource, CrawlRecord, CrawlRun, OrgSiteCheck

TRIAL_LIMIT = 5


@admin.register(CrawlerSource)
class CrawlerSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "enabled", "auto_approve", "max_items", "max_minutes", "last_run_at")
    list_editable = ("enabled", "auto_approve", "max_items", "max_minutes")
    readonly_fields = ("key", "last_run_at", "activity_progress")
    actions = ["trial_run"]

    @admin.display(description="抓取進度")
    def activity_progress(self, obj):
        return progress.summary_text() if obj.key == "mohw_activities" else "—"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

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


@admin.register(CrawlRecord)
class CrawlRecordAdmin(admin.ModelAdmin):
    list_display = ("kind", "ubn", "summary", "source", "status", "created_at")
    list_filter = (ReviewStatusFilter, "kind", "source")
    search_fields = ("ubn", "external_id")
    readonly_fields = (
        "source", "run", "kind", "ubn", "external_id", "pretty_payload", "link", "status",
        "organization", "created_at", "reviewed_at", "reviewed_by",
    )
    fields = readonly_fields + ("review_note",)
    actions = ["approve", "reject"]

    def has_add_permission(self, request):
        return False

    @admin.display(description="內容摘要")
    def summary(self, obj):
        p = obj.payload
        if obj.kind == CrawlRecord.Kind.FINANCIAL:
            total = p.get("total_revenue")
            return f"{p.get('year')} 年 總收入 {total:,}" if isinstance(total, int) else f"{p.get('year')} 年"
        return str(p.get("name") or p.get("content") or p.get("title") or p.get("year") or "")[:40]

    @admin.display(description="內容")
    def pretty_payload(self, obj):
        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", json.dumps(obj.payload, ensure_ascii=False, indent=2))

    @admin.display(description="來源網址")
    def link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', obj.source_url, obj.source_url) if obj.source_url else "—"

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


@admin.register(OrgSiteCheck)
class OrgSiteCheckAdmin(admin.ModelAdmin):
    list_display = ("ubn", "website", "checked_at")
    search_fields = ("ubn", "website")
    readonly_fields = ("ubn", "website", "checked_at")

    def has_add_permission(self, request):
        return False
