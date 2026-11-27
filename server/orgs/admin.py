from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Sum

from . import taxonomy

from .models import (
    CRAWLABLE_FIELDS,
    AnnualFundraising,
    CompanyGroup,
    Donation,
    Grant,
    Donor,
    DonorListSummary,
    OrgCategory,
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
    inlines = [OrgCategoryInline, AnnualInline, DonationInline, ProjectInline, PenaltyInline]
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
    list_filter = ("year", "agency")
    search_fields = ("organization__name", "organization__ubn", "recipient", "purpose")
    autocomplete_fields = ("organization",)


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
    readonly_fields = (
        "registered_name", "representative", "capital", "address", "registry_checked_at",
        "juristic_directors", "directors_checked_at",
    )
    autocomplete_fields = ("group",)
    actions = ["hide", "unhide", "release_group"]

    def save_model(self, request, obj, form, change):
        if "kind" in form.changed_data:
            obj.kind_manual = True
        # 管理員改過所屬集團（含清空＝移出集團）就鎖住，重新歸戶不會改回去（LK-23）
        if "group" in form.changed_data:
            obj.group_manual = True
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

    @admin.action(description="集團交回自動歸戶（取消管理員指定）")
    def release_group(self, request, queryset):
        n = queryset.update(group_manual=False)
        self.message_user(request, f"已交回 {n} 家；下次執行 group_companies 會重新歸戶", messages.SUCCESS)

    @admin.action(description="取消隱藏")
    def unhide(self, request, queryset):
        self.message_user(request, f"已取消隱藏 {queryset.update(hidden=False)} 位捐款人", messages.SUCCESS)


class GroupMemberInline(admin.TabularInline):
    model = Donor
    fk_name = "group"
    fields = ("name", "ubn", "group_manual")
    readonly_fields = ("name", "ubn", "group_manual")
    extra = 0
    can_delete = False
    show_change_link = True
    verbose_name = "旗下公司"
    verbose_name_plural = "旗下公司（要移出或加入，到該公司的捐款人頁改「所屬集團」）"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(CompanyGroup)
class CompanyGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "manual", "members_count", "updated_at")
    list_filter = ("manual",)
    search_fields = ("name", "anchor", "members__name")
    readonly_fields = ("anchor", "created_at", "updated_at")
    inlines = [GroupMemberInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_members=Count("members"))

    @admin.display(description="旗下公司數", ordering="_members")
    def members_count(self, obj):
        return obj._members

    def save_model(self, request, obj, form, change):
        if not change:  # 管理員自己建的集團（例：關係企業沒有法人董事），重新歸戶時不動
            obj.manual = True
        super().save_model(request, obj, form, change)
