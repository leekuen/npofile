from django.core.validators import RegexValidator
from django.db import models

ubn_validator = RegexValidator(r"^\d{8}$", "統一編號必須是 8 碼數字")

# 爬蟲可以覆蓋、管理員手動改過就鎖住的基本欄位
CRAWLABLE_FIELDS = (
    "name",
    "org_type",
    "representative",
    "registered_address",
    "contact_address",
    "phone",
    "website",
    "city",
    "purposes",
    "status",
)


class Organization(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "營運中"
        CANCELLED = "cancelled", "已註銷"
        REVOKED = "revoked", "已撤銷"
        CLOSED = "closed", "擅自歇業"

    ubn = models.CharField("統一編號", max_length=8, unique=True, validators=[ubn_validator])
    name = models.CharField("名稱", max_length=200, db_index=True)
    org_type = models.CharField("團體類型", max_length=50, blank=True)
    representative = models.CharField("負責人", max_length=100, blank=True)
    registered_address = models.CharField("登記地址", max_length=300, blank=True)
    contact_address = models.CharField("聯絡地址", max_length=300, blank=True)
    phone = models.CharField("電話", max_length=50, blank=True)
    website = models.URLField("官網", max_length=500, blank=True)
    city = models.CharField("所在縣市", max_length=10, blank=True, db_index=True)
    purposes = models.CharField("勸募用途", max_length=300, blank=True)
    status = models.CharField("營運狀態", max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    source_links = models.JSONField("基本資料來源", default=list, blank=True)
    locked_fields = models.JSONField(
        "手動鎖定欄位", default=list, blank=True, help_text="管理員手動改過的欄位，爬蟲不會覆蓋。"
    )
    disclosure_score = models.PositiveSmallIntegerField("揭露指數", default=0, db_index=True, editable=False)
    created_at = models.DateTimeField("建立時間", auto_now_add=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        verbose_name = "組織"
        verbose_name_plural = "組織"
        ordering = ["-disclosure_score", "name"]

    def __str__(self):
        return f"{self.name}（{self.ubn}）"


class SourceMixin(models.Model):
    source_name = models.CharField("來源名稱", max_length=100, blank=True)
    source_url = models.URLField("來源網址", max_length=500, blank=True)

    class Meta:
        abstract = True


class AnnualFundraising(SourceMixin):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="annual_records", verbose_name="組織")
    year = models.PositiveSmallIntegerField("年度（民國）")
    raised = models.BigIntegerField("實募金額", default=0)
    target = models.BigIntegerField("預募金額", default=0)

    class Meta:
        verbose_name = "年度募款紀錄"
        verbose_name_plural = "年度募款紀錄"
        ordering = ["-year"]
        constraints = [models.UniqueConstraint(fields=["organization", "year", "source_name"], name="uniq_annual_per_source")]

    def __str__(self):
        return f"{self.year} 年"


class Donation(SourceMixin):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="donations", verbose_name="組織")
    donor_name = models.CharField("捐款人名稱", max_length=200, blank=True)
    is_anonymous = models.BooleanField("匿名", default=False)
    amount = models.BigIntegerField("金額")
    donated_on = models.DateField("捐款日期", null=True, blank=True)

    class Meta:
        verbose_name = "捐款紀錄"
        verbose_name_plural = "捐款紀錄"
        ordering = ["-donated_on", "-amount"]

    def __str__(self):
        return f"{self.public_donor_name} {self.amount}"

    @property
    def public_donor_name(self) -> str:
        """前台與 API 一律走這裡：匿名或沒填名字就是「匿名」。"""
        return "匿名" if self.is_anonymous or not self.donor_name.strip() else self.donor_name


class Project(SourceMixin):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="projects", verbose_name="組織")
    external_id = models.CharField("來源編號", max_length=50, blank=True)
    name = models.CharField("專案名稱", max_length=300)
    category = models.CharField("服務主題／類別", max_length=100, blank=True)
    start_date = models.DateField("開始日期", null=True, blank=True)
    end_date = models.DateField("結束日期", null=True, blank=True)
    target = models.BigIntegerField("預募金額", null=True, blank=True)
    raised = models.BigIntegerField("實募金額", null=True, blank=True)
    permit_no = models.CharField("許可文號", max_length=100, blank=True)
    result_filed_on = models.DateField("成果備查日期", null=True, blank=True)
    closed_filed_on = models.DateField("結案備查日期", null=True, blank=True)
    description = models.TextField("成果／說明", blank=True)

    class Meta:
        verbose_name = "捐款專案"
        verbose_name_plural = "捐款專案"
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return self.name


class Penalty(SourceMixin):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="penalties", verbose_name="組織")
    external_id = models.CharField("來源編號", max_length=50, blank=True)
    decided_on = models.DateField("處分日期", null=True, blank=True)
    authority = models.CharField("處分機關", max_length=200, blank=True)
    content = models.TextField("處分內容")
    fine_text = models.CharField("罰鍰", max_length=300, blank=True)

    class Meta:
        verbose_name = "受裁罰紀錄"
        verbose_name_plural = "受裁罰紀錄"
        ordering = ["-decided_on"]

    def __str__(self):
        return f"{self.decided_on or '日期不明'} {self.content[:20]}"
