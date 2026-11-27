from django.contrib import admin, messages
from django.utils import timezone

from .models import Comment, DonorProfile


class CommentStatusFilter(admin.SimpleListFilter):
    """預設只看審核中；選「全部」才看全部。"""

    title = "狀態"
    parameter_name = "review"

    def lookups(self, request, model_admin):
        return [*Comment.Status.choices, ("all", "全部")]

    def choices(self, changelist):
        for value, label in self.lookup_choices:
            yield {
                "selected": (self.value() or Comment.Status.PENDING) == value,
                "query_string": changelist.get_query_string({self.parameter_name: value}),
                "display": label,
            }

    def queryset(self, request, queryset):
        value = self.value() or Comment.Status.PENDING
        return queryset if value == "all" else queryset.filter(status=value)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("short_body", "organization", "author_display", "status", "created_at")
    list_filter = (CommentStatusFilter,)
    search_fields = ("body", "organization__name", "organization__ubn", "author__email")
    readonly_fields = ("organization", "author", "body", "created_at", "reviewed_at", "reviewed_by")
    fields = ("organization", "author", "body", "status", "reject_reason", "created_at", "reviewed_at", "reviewed_by")
    actions = ["approve", "reject"]

    def has_add_permission(self, request):
        return False

    @admin.display(description="內容")
    def short_body(self, obj):
        return obj.body[:40]

    @admin.display(description="作者")
    def author_display(self, obj):
        return f"{obj.author_name}（{obj.author.email}）"

    def save_model(self, request, obj, form, change):
        if "status" in form.changed_data:
            obj.reviewed_at = timezone.now()
            obj.reviewed_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="核准（公開顯示）")
    def approve(self, request, queryset):
        n = queryset.update(status=Comment.Status.APPROVED, reviewed_at=timezone.now(), reviewed_by=request.user)
        self.message_user(request, f"已核准 {n} 則留言", messages.SUCCESS)

    @admin.action(description="退回（不公開；要附原因請進留言頁填寫）")
    def reject(self, request, queryset):
        n = queryset.update(status=Comment.Status.REJECTED, reviewed_at=timezone.now(), reviewed_by=request.user)
        self.message_user(request, f"已退回 {n} 則留言", messages.SUCCESS)


@admin.register(DonorProfile)
class DonorProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "email", "is_active", "date_joined")
    search_fields = ("display_name", "user__email")
    readonly_fields = ("user",)
    actions = ["deactivate", "activate"]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Email")
    def email(self, obj):
        return obj.user.email

    @admin.display(description="啟用", boolean=True)
    def is_active(self, obj):
        return obj.user.is_active

    @admin.display(description="註冊時間")
    def date_joined(self, obj):
        return obj.user.date_joined

    @admin.action(description="停用帳號（不能再登入與留言）")
    def deactivate(self, request, queryset):
        n = 0
        for p in queryset.select_related("user"):
            p.user.is_active = False
            p.user.save(update_fields=["is_active"])
            n += 1
        self.message_user(request, f"已停用 {n} 個帳號", messages.SUCCESS)

    @admin.action(description="恢復帳號")
    def activate(self, request, queryset):
        n = 0
        for p in queryset.select_related("user"):
            p.user.is_active = True
            p.user.save(update_fields=["is_active"])
            n += 1
        self.message_user(request, f"已恢復 {n} 個帳號", messages.SUCCESS)
