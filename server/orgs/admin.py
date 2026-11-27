from django.contrib import admin, messages
from django.db.models import Count, Sum

from .models import (
    CRAWLABLE_FIELDS,
    AnnualFundraising,
    Donation,
    Donor,
    DonorListSummary,
    Organization,
    Penalty,
    Project,
)

admin.site.site_header = "非營利檔案 NPOFile 管理後台"
admin.site.site_title = "NPOFile 後台"
admin.site.index_title = "資料管理"


class AnnualInline(admin.TabularInline):
    model = AnnualFundraising
    extra = 0
    fields = ("year", "raised", "target", "source_name", "source_url")


class DonationInline(admin.TabularInline):
    """組織頁只放手動輸入的捐款；清冊匯入的動輒上千筆，到「捐款紀錄」或「捐款人」看。"""

    model = Donation
    extra = 0
    fields = ("donor_name", "is_anonymous", "amount", "donated_on", "source_name", "source_url")
    verbose_name_plural = "手動輸入的捐款紀錄（清冊匯入的請到「捐款紀錄」查）"

    def get_queryset(self, request):
        return super().get_queryset(request).filter(donor__isnull=True, project__isnull=True)


class ProjectInline(admin.StackedInline):
    model = Project
    extra = 0
    fields = (
        ("name", "category"),
        ("start_date", "end_date", "region"),
        ("target", "raised", "permit_no"),
        ("result_filed_on", "closed_filed_on"),
        "description",
        ("source_name", "source_url", "external_id"),
    )


class PenaltyInline(admin.StackedInline):
    model = Penalty
    extra = 0
    fields = (
        ("decided_on", "authority", "document_no"), "content", "fine_text", "reason",
        ("source_name", "source_url", "external_id"),
    )


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "ubn", "city", "status", "disclosure_score", "updated_at")
    list_filter = ("status", "city", "org_type")
    search_fields = ("ubn", "name")
    readonly_fields = ("disclosure_score", "created_at", "updated_at")
    inlines = [AnnualInline, DonationInline, ProjectInline, PenaltyInline]
    actions = ["unlock_fields"]
    fieldsets = (
        (None, {"fields": ("ubn", "name", "status", "disclosure_score")}),
        ("基本資料", {"fields": ("org_type", "representative", "registered_address", "contact_address", "phone", "website", "city", "purposes")}),
        ("來源與爬蟲", {"fields": ("source_links", "locked_fields", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def save_model(self, request, obj, form, change):
        if change:
            touched = [f for f in form.changed_data if f in CRAWLABLE_FIELDS]
        else:
            touched = [f for f in CRAWLABLE_FIELDS if str(form.cleaned_data.get(f) or "").strip()]
        obj.locked_fields = sorted(set(obj.locked_fields or []) | set(touched))
        super().save_model(request, obj, form, change)

    @admin.action(description="解除手動鎖定（讓爬蟲可以再更新這些欄位）")
    def unlock_fields(self, request, queryset):
        n = queryset.update(locked_fields=[])
        self.message_user(request, f"已解除 {n} 個組織的手動鎖定。", messages.SUCCESS)


@admin.register(Penalty)
class PenaltyAdmin(admin.ModelAdmin):
    list_display = ("organization", "decided_on", "fine_text")
    list_filter = ("decided_on",)
    search_fields = ("organization__name", "organization__ubn", "content")
    autocomplete_fields = ("organization",)


class DonorListSummaryInline(admin.StackedInline):
    model = DonorListSummary
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in DonorListSummary._meta.fields if f.name not in ("id", "project")]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "target", "raised", "result_filed_on")
    search_fields = ("name", "organization__name", "organization__ubn")
    autocomplete_fields = ("organization",)
    inlines = [DonorListSummaryInline]


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ("organization", "donor_display", "amount", "donated_on", "project", "receipt_no")
    list_filter = ("donor__kind",)
    search_fields = ("donor_name", "donor__name", "receipt_no", "organization__name", "organization__ubn")
    autocomplete_fields = ("organization", "donor", "project")
    list_select_related = ("organization", "donor", "project")

    @admin.display(description="捐款人")
    def donor_display(self, obj):
        return obj.donor.name if obj.donor_id else (obj.donor_name or "匿名")


@admin.register(Donor)
class DonorAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "kind_manual", "ubn", "hidden", "total_amount", "org_count")
    list_editable = ("kind", "hidden")
    list_filter = ("kind", "hidden", "kind_manual")
    search_fields = ("name", "ubn", "registered_name")
    readonly_fields = ("registered_name", "representative", "capital", "address", "registry_checked_at")
    actions = ["hide", "unhide"]

    def save_model(self, request, obj, form, change):
        if "kind" in form.changed_data:
            obj.kind_manual = True
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _total=Sum("donations__amount"), _orgs=Count("donations__organization", distinct=True)
        )

    @admin.display(description="捐款總額", ordering="_total")
    def total_amount(self, obj):
        return f"{obj._total or 0:,}"

    @admin.display(description="捐給幾個組織", ordering="_orgs")
    def org_count(self, obj):
        return obj._orgs

    @admin.action(description="隱藏（前台不再出現，金額併入匿名）")
    def hide(self, request, queryset):
        self.message_user(request, f"已隱藏 {queryset.update(hidden=True)} 位捐款人", messages.SUCCESS)

    @admin.action(description="取消隱藏")
    def unhide(self, request, queryset):
        self.message_user(request, f"已取消隱藏 {queryset.update(hidden=False)} 位捐款人", messages.SUCCESS)
