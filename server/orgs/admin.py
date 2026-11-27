from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Sum

from . import taxonomy

from .models import (
    CRAWLABLE_FIELDS,
    AnnualFundraising,
    CourtRegistration,
    Donation,
    DonationCode,
    Donor,
    DonorListSummary,
    FinancialYear,
    Grant,
    OrgCategory,
    OrgDocument,
    Organization,
    Penalty,
    Project,
    RegistryEntry,
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
        ("name", "category", "channel"),
        ("start_date", "end_date", "region"),
        ("target", "raised", "permit_no"),
        ("monthly_raised", "backers"),
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


FINANCIAL_ADMIN_FIELDS = (
    "year",
    ("total_revenue", "contributions", "government_grants"),
    ("program_service_revenue", "investment_income", "other_revenue"),
    ("total_expenses", "program_expenses", "admin_expenses", "fundraising_expenses"),
    ("surplus", "total_assets", "total_liabilities", "net_assets"),
    ("audited", "method", "locked"),
    ("document_title", "document_url"),
    "notes",
)


class FinancialYearInline(admin.StackedInline):
    model = FinancialYear
    extra = 0
    fields = FINANCIAL_ADMIN_FIELDS
    readonly_fields = ("method",)
    verbose_name_plural = "年度財務（金額單位：元；改過的年度會自動勾「管理員改過」，爬蟲不再覆蓋）"


class OrgDocumentInline(admin.TabularInline):
    model = OrgDocument
    extra = 0
    fields = ("year", "kind", "title", "url", "found_on")
    verbose_name_plural = "官網報告文件"


def _lock_financials(formset) -> None:
    """管理員新增或改過的年度財務：標成管理員輸入、鎖住不讓爬蟲覆蓋。"""
    changed = formset.save(commit=False)
    for obj in formset.deleted_objects:
        obj.delete()
    for row in changed:
        row.organization = formset.instance
        row.locked = True
        row.method = FinancialYear.Method.MANUAL
        row.save()


def _category_choices():
    choices = []
    for f in taxonomy.FIELDS:
        choices.append((f.code, f.label))
        choices.extend((s.code, f"{f.label} › {s.label}") for s in f.subs)
    choices.extend((t.code, f"服務對象：{t.label}") for t in taxonomy.TARGETS)
    return choices


class OrgCategoryForm(forms.ModelForm):
    code = forms.ChoiceField(label="分類", choices=_category_choices)

    class Meta:
        model = OrgCategory
        fields = ("code", "excluded")


class OrgCategoryInline(admin.TabularInline):
    model = OrgCategory
    form = OrgCategoryForm
    extra = 0
    fields = ("code", "source", "excluded")
    readonly_fields = ("source",)
    verbose_name_plural = "分類（自動分類判錯：勾「管理員拿掉」；要補上：新增一列）"


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "ubn", "city", "status", "disclosure_score", "updated_at")
    list_filter = ("status", "city", "org_type")
    search_fields = ("ubn", "name")
    readonly_fields = ("disclosure_score", "created_at", "updated_at")
    inlines = [OrgCategoryInline, AnnualInline, FinancialYearInline, OrgDocumentInline, DonationInline, ProjectInline,
               PenaltyInline]
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

    def save_formset(self, request, form, formset, change):
        if formset.model is FinancialYear:
            return _lock_financials(formset)
        if formset.model is not OrgCategory:
            return super().save_formset(request, form, formset, change)
        changed = formset.save(commit=False)  # 只含新增與改過的列；也讓後台的變更紀錄拿得到資料
        for obj in formset.deleted_objects:
            obj.delete()
        for row in changed:
            row.organization = form.instance
            row.source = OrgCategory.Source.ADMIN  # 管理員動過的列，自動分類不再改
            row.save()
            parent = taxonomy.PARENT.get(row.code)
            if parent and not row.excluded:
                OrgCategory.objects.get_or_create(
                    organization=row.organization, code=parent, defaults={"source": OrgCategory.Source.ADMIN}
                )

    @admin.action(description="解除手動鎖定（讓爬蟲可以再更新這些欄位）")
    def unlock_fields(self, request, queryset):
        n = queryset.update(locked_fields=[])
        self.message_user(request, f"已解除 {n} 個組織的手動鎖定。", messages.SUCCESS)


@admin.register(Grant)
class GrantAdmin(admin.ModelAdmin):
    list_display = ("organization", "year", "agency", "purpose", "amount", "approved_on")
    list_filter = ("year", "source_name", "agency")
    search_fields = ("organization__name", "organization__ubn", "recipient", "purpose")
    autocomplete_fields = ("organization",)


class MatchedFilter(admin.SimpleListFilter):
    title = "對到組織"
    parameter_name = "matched"

    def lookups(self, request, model_admin):
        return (("yes", "有"), ("no", "沒有（前台不顯示）"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(organization__isnull=False)
        if self.value() == "no":
            return queryset.filter(organization__isnull=True)
        return queryset


@admin.register(RegistryEntry)
class RegistryEntryAdmin(admin.ModelAdmin):
    """主管機關名冊（LK-32）：名稱對不上的列在這裡，管理員指定組織後重新匯入不會改掉。"""

    list_display = ("registry_name", "authority", "organization", "status", "registered_assets", "org_manual")
    list_filter = (MatchedFilter, "authority", "status", "org_manual")
    search_fields = ("registry_name", "permit_no", "organization__name", "organization__ubn")
    autocomplete_fields = ("organization",)
    fields = (
        "organization", "org_manual", "authority", "registry_name", "permit_no", "founded_on", "permitted_assets",
        "registered_assets", "status", "purpose", "main_business", "service_targets", "business_category",
        "data_date", "source_name", "source_url",
    )

    def save_model(self, request, obj, form, change):
        if "organization" in form.changed_data:
            obj.org_manual = True
        super().save_model(request, obj, form, change)


class CodeMatchedFilter(admin.SimpleListFilter):
    title = "對到組織"
    parameter_name = "matched"

    def lookups(self, request, model_admin):
        return (("yes", "有"), ("no", "沒有（前台不顯示）"))

    def queryset(self, request, queryset):
        known = Organization.objects.values("ubn")
        if self.value() == "yes":
            return queryset.filter(ubn__in=known)
        if self.value() == "no":
            return queryset.exclude(ubn__in=known)
        return queryset


@admin.register(DonationCode)
class DonationCodeAdmin(admin.ModelAdmin):
    """發票捐贈碼（LK-32）：用統編對組織；統編不在組織名冊的前台不顯示。"""

    list_display = ("code", "registered_name", "short_name", "ubn", "county")
    list_filter = (CodeMatchedFilter, "county")
    search_fields = ("code", "registered_name", "short_name", "ubn")


@admin.register(FinancialYear)
class FinancialYearAdmin(admin.ModelAdmin):
    list_display = ("organization", "year", "total_revenue", "total_expenses", "net_assets", "method", "locked")
    list_filter = ("year", "method", "locked")
    search_fields = ("organization__name", "organization__ubn")
    autocomplete_fields = ("organization",)
    fields = ("organization", *FINANCIAL_ADMIN_FIELDS)
    readonly_fields = ("method",)

    def save_model(self, request, obj, form, change):
        obj.locked = True
        obj.method = FinancialYear.Method.MANUAL
        super().save_model(request, obj, form, change)


@admin.register(OrgDocument)
class OrgDocumentAdmin(admin.ModelAdmin):
    list_display = ("organization", "year", "kind", "title")
    list_filter = ("kind", "year")
    search_fields = ("organization__name", "organization__ubn", "title")
    autocomplete_fields = ("organization",)


@admin.register(Penalty)
class PenaltyAdmin(admin.ModelAdmin):
    list_display = ("organization", "decided_on", "authority", "fine_text", "source_name")
    list_filter = ("source_name", "decided_on")
    search_fields = ("organization__name", "organization__ubn", "content", "document_no")
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
    list_display = ("name", "organization", "channel", "target", "raised", "result_filed_on")
    list_filter = ("channel",)
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


class MatchedFilter(admin.SimpleListFilter):
    title = "對到組織"
    parameter_name = "matched"

    def lookups(self, request, model_admin):
        return (("yes", "對到"), ("no", "沒對到"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(organization__isnull=False)
        if self.value() == "no":
            return queryset.filter(organization__isnull=True)
        return queryset


@admin.register(CourtRegistration)
class CourtRegistrationAdmin(admin.ModelAdmin):
    """法院登記公告（LK-31）：公告內容來自法院、不能改；只能指定（或清掉）對到的組織。"""

    list_display = ("posted_on", "court", "name", "case_type", "organization", "org_manual", "property_total")
    list_filter = ("case_type", MatchedFilter, "org_manual", "category", "court")
    search_fields = ("name", "case_no", "organization__name", "organization__ubn")
    autocomplete_fields = ("organization",)
    date_hierarchy = "posted_on"
    list_select_related = ("organization",)
    readonly_fields = (
        "court", "case_no", "reg_no", "category", "name", "case_type", "posted_on", "registered_on",
        "property_total", "change_items", "detail_fetched", "source_name", "source_link", "updated_at",
    )
    fields = ("organization", "org_manual", *readonly_fields)
    actions = ["rematch"]

    @admin.display(description="公告網址")
    def source_link(self, obj):
        from django.utils.html import format_html

        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', obj.source_url, obj.source_url) if obj.source_url else "—"

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        if "organization" in form.changed_data:
            obj.org_manual = True  # 管理員指定（或清掉）過，重新比對不改
        super().save_model(request, obj, form, change)

    @admin.action(description="重新比對組織（管理員指定過的不動）")
    def rematch(self, request, queryset):
        from .court_match import rematch

        n = rematch(queryset)
        self.message_user(request, f"重新比對完成：{n} 筆的組織有變動。內頁還沒讀過的，下次排程會用 match_court_registrations 補抓。", messages.SUCCESS)
