from django.contrib import admin, messages

from .models import CRAWLABLE_FIELDS, AnnualFundraising, Donation, Organization, Penalty, Project

admin.site.site_header = "非營利檔案 NPOFile 管理後台"
admin.site.site_title = "NPOFile 後台"
admin.site.index_title = "資料管理"


class AnnualInline(admin.TabularInline):
    model = AnnualFundraising
    extra = 0
    fields = ("year", "raised", "target", "source_name", "source_url")


class DonationInline(admin.TabularInline):
    model = Donation
    extra = 0
    fields = ("donor_name", "is_anonymous", "amount", "donated_on", "source_name", "source_url")


class ProjectInline(admin.StackedInline):
    model = Project
    extra = 0
    fields = (
        ("name", "category"),
        ("start_date", "end_date"),
        ("target", "raised", "permit_no"),
        ("result_filed_on", "closed_filed_on"),
        "description",
        ("source_name", "source_url", "external_id"),
    )


class PenaltyInline(admin.StackedInline):
    model = Penalty
    extra = 0
    fields = (("decided_on", "authority"), "content", "fine_text", ("source_name", "source_url", "external_id"))


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


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "target", "raised", "result_filed_on")
    search_fields = ("name", "organization__name", "organization__ubn")
    autocomplete_fields = ("organization",)


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ("organization", "donor_name", "is_anonymous", "amount", "donated_on")
    search_fields = ("donor_name", "organization__name", "organization__ubn")
    autocomplete_fields = ("organization",)
