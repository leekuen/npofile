from django.conf import settings
from django.db import models


class CrawlerSource(models.Model):
    key = models.SlugField("代號", max_length=30, unique=True)
    name = models.CharField("來源名稱", max_length=100)
    url = models.URLField("來源網址", max_length=500, blank=True)
    enabled = models.BooleanField("啟用", default=True)
    auto_approve = models.BooleanField(
        "自動上架", default=False, help_text="勾選：抓到就直接上架。不勾：先進待審核清單，管理員核准後才上架。"
    )
    max_items = models.PositiveIntegerField("每次最多抓幾筆", default=0, help_text="0 表示不限制。")
    max_minutes = models.PositiveIntegerField(
        "每次最多跑幾分鐘", default=0, help_text="0 表示不限制。到時間就停，下次接著抓（目前只有勸募活動與捐贈人清冊會接著抓）。"
    )
    description = models.TextField("說明", blank=True)
    last_run_at = models.DateTimeField("最近執行", null=True, blank=True)

    class Meta:
        verbose_name = "爬蟲來源設定"
        verbose_name_plural = "爬蟲來源設定"
        ordering = ["key"]

    def __str__(self):
        return self.name


class CrawlRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "執行中"
        SUCCESS = "success", "完成"
        FAILED = "failed", "失敗"

    source = models.ForeignKey(CrawlerSource, on_delete=models.CASCADE, related_name="runs", verbose_name="來源")
    started_at = models.DateTimeField("開始時間", auto_now_add=True)
    finished_at = models.DateTimeField("結束時間", null=True, blank=True)
    status = models.CharField("狀態", max_length=10, choices=Status.choices, default=Status.RUNNING)
    fetched = models.PositiveIntegerField("抓到筆數", default=0)
    created = models.PositiveIntegerField("新資料筆數", default=0)
    applied = models.PositiveIntegerField("已上架筆數", default=0)
    pending = models.PositiveIntegerField("待審核筆數", default=0)
    failed = models.PositiveIntegerField("失敗筆數", default=0)
    error = models.TextField("錯誤訊息", blank=True)
    note = models.CharField("備註", max_length=300, blank=True)

    class Meta:
        verbose_name = "爬蟲執行紀錄"
        verbose_name_plural = "爬蟲執行紀錄"
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.source} {self.started_at:%Y-%m-%d %H:%M}"


class CrawlRecord(models.Model):
    class Kind(models.TextChoices):
        ORG = "org", "組織基本資料"
        ANNUAL = "annual", "年度募款"
        PROJECT = "project", "捐款專案"
        PENALTY = "penalty", "受裁罰紀錄"
        GRANT = "grant", "政府補助"

    class Status(models.TextChoices):
        PENDING = "pending", "待審核"
        APPROVED = "approved", "已核准"
        REJECTED = "rejected", "已退回"
        AUTO = "auto", "已自動上架"

    source = models.ForeignKey(CrawlerSource, on_delete=models.CASCADE, related_name="records", verbose_name="來源")
    run = models.ForeignKey(CrawlRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="records", verbose_name="執行")
    kind = models.CharField("資料類型", max_length=10, choices=Kind.choices)
    ubn = models.CharField("統一編號", max_length=8, db_index=True)
    external_id = models.CharField("來源編號", max_length=50, blank=True)
    payload = models.JSONField("內容")
    source_url = models.URLField("來源網址", max_length=500, blank=True)
    content_hash = models.CharField(max_length=64)
    status = models.CharField("狀態", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    organization = models.ForeignKey(
        "orgs.Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="對應組織"
    )
    created_at = models.DateTimeField("抓取時間", auto_now_add=True)
    reviewed_at = models.DateTimeField("審核時間", null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="審核人"
    )
    review_note = models.CharField("審核備註", max_length=300, blank=True)

    class Meta:
        verbose_name = "爬蟲資料（審核佇列）"
        verbose_name_plural = "爬蟲資料（審核佇列）"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["source", "content_hash"], name="uniq_record_content")]

    def __str__(self):
        return f"{self.get_kind_display()} {self.ubn}"


class ActivityProgress(models.Model):
    """衛福部勸募活動的抓取進度：每晚接著抓、只抓新的與有變動的（規則在 crawling/progress.py）。"""

    activity_id = models.CharField("活動編號", max_length=20, unique=True)
    name = models.CharField("活動名稱", max_length=300, blank=True)
    org_name = models.CharField("申請單位", max_length=200, db_index=True)
    ubn = models.CharField("統一編號", max_length=8, blank=True, db_index=True)
    roc_year = models.PositiveSmallIntegerField("勸募年度", db_index=True)
    end_date = models.DateField("活動結束", null=True, blank=True)
    listed_raised = models.BigIntegerField("列表上的實募金額", null=True, blank=True)
    listed_at = models.DateTimeField("最近在列表上看到", null=True, blank=True)
    checked_raised = models.BigIntegerField("上次檢查時的實募金額", null=True, blank=True)
    donors_raised = models.BigIntegerField("清冊抓到時的實募金額", null=True, blank=True)
    has_donor_link = models.BooleanField("活動頁有清冊", default=False)
    has_donor_list = models.BooleanField("清冊已寫進資料庫", default=False)
    unmatched_reason = models.CharField("對不到的原因", max_length=100, blank=True)
    checked_at = models.DateTimeField("最近檢查", null=True, blank=True)

    class Meta:
        verbose_name = "勸募活動抓取進度"
        verbose_name_plural = "勸募活動抓取進度"
        ordering = ["-roc_year", "activity_id"]

    def __str__(self):
        return f"{self.activity_id} {self.name}"
