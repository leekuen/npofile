import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from npofile_crawler import donors as donor_names

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
    # 近 5 年公開募款（勸募申報＋群眾集資，同一年度不重複算；口徑見 tickets/LK-20），跟揭露指數一起重算
    public_raised_5y = models.BigIntegerField("近 5 年公開募款", default=0, db_index=True, editable=False)
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


class Donor(models.Model):
    """清冊上的捐款人（企業、團體、大額個人）。小額個人與匿名不建捐款人，只進專案的清冊摘要。"""

    class Kind(models.TextChoices):
        COMPANY = "company", "企業"
        GROUP = "group", "團體"
        INDIVIDUAL = "individual", "個人"

    PUBLIC_KINDS = (Kind.COMPANY, Kind.GROUP)

    name = models.CharField("名稱", max_length=200, unique=True)
    # 判斷是不是同一位用的寫法（npofile_crawler.donors.identity_key）：台／臺、空白、(股) 不同也算同一位（LK-16）
    name_key = models.CharField("比對用名稱", max_length=200, unique=True, editable=False)
    kind = models.CharField("類型", max_length=12, choices=Kind.choices, db_index=True)
    kind_manual = models.BooleanField(
        "類型由管理員指定", default=False, help_text="管理員改過類型就會勾起；重新分類時不會改掉。"
    )
    hidden = models.BooleanField(
        "隱藏", default=False, help_text="勾選後前台一律不出現（排行、明細、搜尋），金額併入匿名摘要。用於當事人要求等情況。"
    )
    ubn = models.CharField("統一編號", max_length=8, blank=True, db_index=True)
    registered_name = models.CharField("登記名稱", max_length=200, blank=True)
    representative = models.CharField("代表人", max_length=100, blank=True)
    capital = models.BigIntegerField("實收資本額", null=True, blank=True)
    address = models.CharField("登記地址", max_length=300, blank=True)
    registry_checked_at = models.DateTimeField("查過商工登記", null=True, blank=True)

    class Meta:
        verbose_name = "捐款人"
        verbose_name_plural = "捐款人"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = donor_names.normalize(self.name)[:200]
        self.name_key = donor_names.identity_key(self.name)[:200]
        if kwargs.get("update_fields") and "name" in kwargs["update_fields"]:
            kwargs["update_fields"] = {*kwargs["update_fields"], "name_key"}
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        key = donor_names.identity_key(self.name or "")
        same = Donor.objects.filter(name_key=key).exclude(pk=self.pk).first()
        if same:
            raise ValidationError({"name": f"跟另一位捐款人「{same.name}」（編號 {same.pk}）是同一位，請改用那一筆或換個名稱。"})

    @property
    def is_public(self) -> bool:
        return self.kind in self.PUBLIC_KINDS and not self.hidden


class Donation(SourceMixin):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="donations", verbose_name="組織")
    donor = models.ForeignKey(Donor, on_delete=models.CASCADE, null=True, blank=True, related_name="donations", verbose_name="捐款人")
    project = models.ForeignKey(
        "Project", on_delete=models.CASCADE, null=True, blank=True, related_name="donations", verbose_name="專案"
    )
    donor_name = models.CharField("捐款人名稱", max_length=200, blank=True)
    is_anonymous = models.BooleanField("匿名", default=False)
    amount = models.BigIntegerField("金額")
    donated_on = models.DateField("捐款日期", null=True, blank=True)
    receipt_no = models.CharField("收據編號", max_length=50, blank=True)
    purpose = models.CharField("捐贈用途", max_length=200, blank=True)

    class Meta:
        verbose_name = "捐款紀錄"
        verbose_name_plural = "捐款紀錄"
        ordering = ["-donated_on", "-amount"]

    def __str__(self):
        return f"{self.public_donor_name} {self.amount}"

    @property
    def public_donor_name(self) -> str:
        """前台與 API 一律走這裡：匿名、被隱藏、或沒填名字就是「匿名」。"""
        if self.is_anonymous or (self.donor_id and self.donor.hidden):
            return "匿名"
        name = self.donor.name if self.donor_id else self.donor_name
        return name.strip() or "匿名"


class Project(SourceMixin):
    class Channel(models.TextChoices):
        PERMIT = "permit", "勸募活動"
        CROWDFUNDING = "crowdfunding", "群眾集資"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="projects", verbose_name="組織")
    external_id = models.CharField("來源編號", max_length=50, blank=True)
    name = models.CharField("專案名稱", max_length=300)
    category = models.CharField("服務主題／類別", max_length=100, blank=True)
    start_date = models.DateField("開始日期", null=True, blank=True)
    end_date = models.DateField("結束日期", null=True, blank=True)
    target = models.BigIntegerField("預募金額", null=True, blank=True)
    raised = models.BigIntegerField("實募金額", null=True, blank=True)
    permit_no = models.CharField("許可文號", max_length=100, blank=True)
    region = models.CharField("活動地區", max_length=100, blank=True)
    result_filed_on = models.DateField("成果備查日期", null=True, blank=True)
    closed_filed_on = models.DateField("結案備查日期", null=True, blank=True)
    description = models.TextField("成果／說明", blank=True)
    channel = models.CharField(
        "募款管道", max_length=20, choices=Channel.choices, default=Channel.PERMIT,
        help_text="群眾集資專案（例：挖貝）不算進揭露指數，見 LK-15。",
    )
    monthly_raised = models.BigIntegerField("每月定期定額", null=True, blank=True)
    backers = models.PositiveIntegerField("參與人次", null=True, blank=True)
    period_year = models.PositiveSmallIntegerField(
        "年度（民國）", null=True, blank=True, db_index=True, editable=False,
        help_text="依開始日期，沒有就看名稱開頭的年度、再沒有看成果備查日期；用來判斷是否在近 5 年內。",
    )

    class Meta:
        verbose_name = "捐款專案"
        verbose_name_plural = "捐款專案"
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return self.name

    def compute_period_year(self) -> int | None:
        if self.start_date:
            return self.start_date.year - 1911
        m = re.match(r"^\s*(\d{2,3})\s*年", self.name or "")
        if m:
            return int(m.group(1))
        if self.result_filed_on:
            return self.result_filed_on.year - 1911
        return None

    def save(self, *args, **kwargs):
        self.period_year = self.compute_period_year()
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "period_year"}
        super().save(*args, **kwargs)


class DonorListSummary(models.Model):
    """一份捐贈人清冊的摘要：小額個人與匿名只留數字，不存姓名。"""

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="donor_summary", verbose_name="專案")
    total_rows = models.PositiveIntegerField("清冊總筆數", default=0)
    total_amount = models.BigIntegerField("清冊總金額", default=0)
    small_individual_count = models.PositiveIntegerField("小額個人人數", default=0)
    small_individual_amount = models.BigIntegerField("小額個人金額", default=0)
    anonymous_rows = models.PositiveIntegerField("匿名筆數", default=0)
    anonymous_amount = models.BigIntegerField("匿名金額", default=0)
    threshold = models.BigIntegerField("個人顯示門檻", default=0)
    source_name = models.CharField("來源名稱", max_length=100, blank=True)
    source_url = models.URLField("來源網址", max_length=500, blank=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        verbose_name = "捐贈人清冊摘要"
        verbose_name_plural = "捐贈人清冊摘要"

    def __str__(self):
        return f"{self.project} 清冊摘要"


class Grant(SourceMixin):
    """政府對民間團體的補(捐)助（LK-19）：各機關依規定每季公開的核定案件，一行一筆。
    金額是「含累積金額」的核定金額；同一案件下一季的表金額變了就更新同一筆（以 external_id 認）。"""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="grants", verbose_name="組織")
    external_id = models.CharField("來源編號", max_length=40, db_index=True)
    year = models.PositiveSmallIntegerField("年度（民國）", db_index=True)
    quarter = models.PositiveSmallIntegerField("資料截至第幾季", default=4)
    agency = models.CharField("補助機關", max_length=100)
    county = models.CharField("所屬縣市", max_length=20, blank=True)
    recipient = models.CharField("表上的受補助對象", max_length=300)
    facility = models.CharField(
        "附設單位", max_length=200, blank=True, help_text="表上寫「某某基金會附設某某中心」時，補助算給基金會，這裡記附設單位名稱。"
    )
    purpose = models.CharField("補助事項或用途", max_length=500)
    approved_on = models.DateField("核准日期", null=True, blank=True)
    amount = models.BigIntegerField("核定金額（含累積）")

    class Meta:
        verbose_name = "政府補助"
        verbose_name_plural = "政府補助"
        ordering = ["-year", "-amount", "id"]
        constraints = [models.UniqueConstraint(fields=["source_name", "external_id"], name="uniq_grant_source_id")]

    def __str__(self):
        return f"{self.year} {self.agency} {self.purpose}"


class Penalty(SourceMixin):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="penalties", verbose_name="組織")
    external_id = models.CharField("來源編號", max_length=50, blank=True)
    decided_on = models.DateField("處分日期", null=True, blank=True)
    authority = models.CharField("處分機關", max_length=200, blank=True)
    document_no = models.CharField("文號", max_length=200, blank=True)
    content = models.TextField("處分內容")
    fine_text = models.CharField("罰鍰", max_length=300, blank=True)
    reason = models.TextField("處分理由", blank=True)

    class Meta:
        verbose_name = "受裁罰紀錄"
        verbose_name_plural = "受裁罰紀錄"
        ordering = ["-decided_on"]

    def __str__(self):
        return f"{self.decided_on or '日期不明'} {self.content[:20]}"


class OrgCategory(models.Model):
    """組織的分類（代號見 orgs/taxonomy.py）。管理員拿掉的保留成 excluded，自動分類不會再加回來。"""

    class Source(models.TextChoices):
        OFFICIAL = "official", "官方（勸募用途）"
        INFERRED = "inferred", "依名稱推測"
        ADMIN = "admin", "管理員指定"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="categories", verbose_name="組織")
    code = models.CharField("分類代號", max_length=40, db_index=True)
    source = models.CharField("來源", max_length=10, choices=Source.choices)
    excluded = models.BooleanField("管理員拿掉", default=False, help_text="勾選＝這個分類不適用，自動分類不會再加回來。")

    class Meta:
        verbose_name = "組織分類"
        verbose_name_plural = "組織分類"
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["organization", "code"], name="uniq_org_category")]

    def __str__(self):
        from .taxonomy import LABELS

        return LABELS.get(self.code, self.code)


class OrgDocument(models.Model):
    """組織官網上公開的報告檔（LK-17）：財務報告、年報、工作／成果報告。只收近 5 年，年度看 period.annual_q。"""

    class Kind(models.TextChoices):
        FINANCIAL = "financial", "財務報告"
        ANNUAL = "annual", "年報"
        WORK = "work", "工作／成果報告"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="documents", verbose_name="組織")
    year = models.PositiveSmallIntegerField("年度（民國）", db_index=True)
    kind = models.CharField("種類", max_length=10, choices=Kind.choices)
    title = models.CharField("標題", max_length=200)
    url = models.URLField("檔案網址", max_length=1000)
    found_on = models.URLField("在哪一頁找到", max_length=1000, blank=True)
    source_name = models.CharField("來源名稱", max_length=100, blank=True)
    created_at = models.DateTimeField("收錄時間", auto_now_add=True)

    class Meta:
        verbose_name = "報告文件"
        verbose_name_plural = "報告文件"
        ordering = ["-year", "kind", "title"]
        constraints = [models.UniqueConstraint(fields=["organization", "url"], name="uniq_org_document_url")]

    def __str__(self):
        return f"{self.year} {self.title}"


class FinancialYear(models.Model):
    """一個組織一個會計年度的財務摘要（LK-17），欄位參照 Candid 的 Financials：收入、支出、資產負債。

    金額都是新臺幣元；報告沒列的留空（不是 0）。管理員在後台改過就勾 locked，爬蟲不再覆蓋。"""

    class Method(models.TextChoices):
        AI = "ai", "AI 讀取報告"
        MANUAL = "manual", "管理員輸入"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="financials", verbose_name="組織")
    year = models.PositiveSmallIntegerField("年度（民國）", db_index=True)
    # 收入
    total_revenue = models.BigIntegerField("總收入", null=True, blank=True)
    contributions = models.BigIntegerField("捐款收入", null=True, blank=True)
    government_grants = models.BigIntegerField("政府補助", null=True, blank=True)
    program_service_revenue = models.BigIntegerField("業務／服務收入", null=True, blank=True)
    investment_income = models.BigIntegerField("利息與投資收入", null=True, blank=True)
    other_revenue = models.BigIntegerField("其他收入", null=True, blank=True)
    # 支出
    total_expenses = models.BigIntegerField("總支出", null=True, blank=True)
    program_expenses = models.BigIntegerField("業務／服務支出", null=True, blank=True)
    admin_expenses = models.BigIntegerField("行政管理支出", null=True, blank=True)
    fundraising_expenses = models.BigIntegerField("募款支出", null=True, blank=True)
    # 餘絀與資產負債
    surplus = models.BigIntegerField("本期餘絀", null=True, blank=True)
    total_assets = models.BigIntegerField("年底資產總額", null=True, blank=True)
    total_liabilities = models.BigIntegerField("年底負債總額", null=True, blank=True)
    net_assets = models.BigIntegerField("年底淨資產", null=True, blank=True)
    audited = models.BooleanField("經會計師查核", null=True, blank=True)
    document_url = models.URLField("數字出自哪份報告", max_length=1000, blank=True)
    document_title = models.CharField("報告標題", max_length=200, blank=True)
    method = models.CharField("怎麼來的", max_length=10, choices=Method.choices, default=Method.MANUAL)
    notes = models.CharField("備註", max_length=300, blank=True)
    locked = models.BooleanField("管理員改過（爬蟲不覆蓋）", default=False)
    source_name = models.CharField("來源名稱", max_length=100, blank=True)
    updated_at = models.DateTimeField("更新時間", auto_now=True)

    class Meta:
        verbose_name = "年度財務"
        verbose_name_plural = "年度財務"
        ordering = ["-year"]
        constraints = [models.UniqueConstraint(fields=["organization", "year"], name="uniq_financial_year")]

    def __str__(self):
        return f"{self.year} 年度財務"

    @property
    def program_expense_ratio(self) -> int | None:
        """業務支出占比（%）：業務支出 ÷ 總支出，口徑見 tickets/LK-17〈數字口徑〉。"""
        if not self.total_expenses or self.program_expenses is None:
            return None
        return round(self.program_expenses * 100 / self.total_expenses)
