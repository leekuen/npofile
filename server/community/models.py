from django.conf import settings
from django.db import models


class DonorProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="donor_profile")
    display_name = models.CharField("顯示名稱", max_length=50)

    class Meta:
        verbose_name = "捐款人"
        verbose_name_plural = "捐款人"

    def __str__(self):
        return self.display_name


class Comment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "審核中"
        APPROVED = "approved", "已核准"
        REJECTED = "rejected", "未通過"

    organization = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="comments", verbose_name="組織")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments", verbose_name="作者")
    body = models.TextField("內容", max_length=1000)
    status = models.CharField("狀態", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    reject_reason = models.CharField("退回原因", max_length=300, blank=True)
    created_at = models.DateTimeField("留言時間", auto_now_add=True)
    reviewed_at = models.DateTimeField("審核時間", null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="審核人"
    )

    class Meta:
        verbose_name = "留言"
        verbose_name_plural = "留言"
        ordering = ["-created_at"]

    def __str__(self):
        return self.body[:30]

    @property
    def author_name(self) -> str:
        profile = getattr(self.author, "donor_profile", None)
        return profile.display_name if profile else "管理員"
