from rest_framework import serializers

from . import category_api, donor_rules, period, scoring
from npofile_crawler import labor

from .models import (
    AnnualFundraising,
    CourtRegistration,
    Donation,
    DonationCode,
    Donor,
    FinancialYear,
    Grant,
    OrgDocument,
    Organization,
    Penalty,
    Project,
    RegistryEntry,
)

RECENT_DONATIONS = 50
DONOR_DETAIL_DONATIONS = 200


class OrganizationListSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display")
    penalty_count_5y = serializers.IntegerField()
    tags = serializers.SerializerMethodField()
    latest_revenue = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = (
            "ubn", "name", "org_type", "city", "status", "status_label", "disclosure_level", "penalty_count_5y",
            "public_raised_5y", "tags", "latest_revenue",
        )

    def get_latest_revenue(self, obj):
        year = getattr(obj, "fin_year", None)
        return {"year": year, "total_revenue": obj.fin_revenue} if year is not None else None

    def get_tags(self, obj):
        return category_api.short_tags(obj)


class AnnualSerializer(serializers.ModelSerializer):
    achievement_rate = serializers.SerializerMethodField()

    class Meta:
        model = AnnualFundraising
        fields = ("year", "raised", "target", "achievement_rate", "source_name", "source_url")

    def get_achievement_rate(self, obj):
        if not obj.target:
            return None
        return round(obj.raised * 100 / obj.target, 1)


class FinancialYearSerializer(serializers.ModelSerializer):
    program_expense_ratio = serializers.IntegerField(read_only=True)

    class Meta:
        model = FinancialYear
        fields = (
            "year", "total_revenue", "contributions", "government_grants", "program_service_revenue",
            "investment_income", "other_revenue", "total_expenses", "program_expenses", "admin_expenses",
            "fundraising_expenses", "surplus", "total_assets", "total_liabilities", "net_assets",
            "program_expense_ratio", "audited", "method", "document_url", "document_title",
        )


class OrgDocumentSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display")

    class Meta:
        model = OrgDocument
        fields = ("id", "year", "kind", "kind_label", "title", "url", "found_on")


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = (
            "id", "external_id", "name", "category", "start_date", "end_date", "target", "raised", "permit_no", "region",
            "result_filed_on", "closed_filed_on", "description", "source_name", "source_url",
            "channel", "monthly_raised", "backers",
        )


# 勞動局公布的違反勞基法處分（LK-29）跟公益勸募裁處分開標示
LABOR_SOURCE_NAMES = {spec.source_name for spec in labor.SPECS}


class PenaltySerializer(serializers.ModelSerializer):
    category = serializers.SerializerMethodField()

    class Meta:
        model = Penalty
        fields = (
            "id", "decided_on", "authority", "document_no", "content", "fine_text", "reason", "source_name", "source_url",
            "category",
        )

    def get_category(self, obj) -> str:
        return "labor" if obj.source_name in LABOR_SOURCE_NAMES else "fundraising"


class GrantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Grant
        fields = (
            "id", "year", "quarter", "agency", "county", "recipient", "facility", "purpose", "approved_on", "amount",
            "source_name", "source_url",
        )


def distinct_grants(grants):
    """同一筆補助被兩個部會的表都列出來（例：勞發署跟就業安定基金，LK-30 條件確認）時只留一筆：
    名稱＋事項＋核准日＋金額（同一年度）全同、而且來自不同來源的，留先出現的那個來源。
    同一個來源裡全同的兩行是真的兩筆（例：分兩次核定），不合併。"""
    first_source: dict[tuple, str] = {}
    kept = []
    for g in grants:
        key = (g.year, "".join(g.recipient.split()).replace("臺", "台"), "".join(g.purpose.split()), g.approved_on, g.amount)
        src = first_source.setdefault(key, g.source_name)
        if src == g.source_name:
            kept.append(g)
    return kept


class CourtRegistrationSerializer(serializers.ModelSerializer):
    """法院登記公告（LK-31）：法院公開的資料，只有組織層級的欄位（董監事姓名不存，也就不會出現）。"""

    case_label = serializers.CharField(source="get_case_type_display")
    category_label = serializers.CharField(source="get_category_display")

    class Meta:
        model = CourtRegistration
        fields = (
            "id", "posted_on", "registered_on", "court", "case_no", "reg_no", "category", "category_label",
            "case_type", "case_label", "property_total", "change_items", "source_name", "source_url",
        )


def court_dissolution(regs: list) -> dict | None:
    """最新一筆是解散或清算終結登記 → 頁首標示用的日期、法院；否則 None。regs 要已照新到舊排好。"""
    latest = regs[0] if regs else None
    if latest is None or latest.case_type not in CourtRegistration.DISSOLVED_TYPES:
        return None
    return {
        "posted_on": latest.posted_on, "registered_on": latest.registered_on, "court": latest.court,
        "case_type": latest.case_type, "case_label": latest.get_case_type_display(), "source_url": latest.source_url,
    }


class DonationSerializer(serializers.ModelSerializer):
    donor_name = serializers.CharField(source="public_donor_name")
    donor_id = serializers.SerializerMethodField()
    donor_kind = serializers.SerializerMethodField()

    class Meta:
        model = Donation
        fields = ("id", "donor_name", "donor_id", "donor_kind", "amount", "donated_on", "purpose", "source_name", "source_url")

    def get_donor_id(self, obj):
        return obj.donor_id if obj.donor_id and obj.donor.is_public else None

    def get_donor_kind(self, obj):
        return obj.donor.kind if obj.donor_id else ("individual" if obj.donor_name.strip() else None)


class RegistryEntrySerializer(serializers.ModelSerializer):
    """主管機關名冊（LK-32）：全是政府公開資料；名冊上的個人姓名與聯絡方式本來就沒存。"""

    class Meta:
        model = RegistryEntry
        fields = (
            "authority", "registry_name", "permit_no", "founded_on", "registered_assets", "status",
            "service_targets", "business_category", "data_date", "source_name", "source_url",
        )


class DonationCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DonationCode
        fields = ("code", "short_name", "source_name", "source_url")


class OrganizationDetailSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display")
    penalty_count_5y = serializers.IntegerField()
    levels = serializers.SerializerMethodField()
    public_raised = serializers.SerializerMethodField()
    annual_records = AnnualSerializer(many=True)
    financials = FinancialYearSerializer(many=True)
    documents = OrgDocumentSerializer(many=True)
    projects = ProjectSerializer(many=True)
    penalties = PenaltySerializer(many=True)
    grants = serializers.SerializerMethodField()
    donation_trend = serializers.SerializerMethodField()
    court_registrations = CourtRegistrationSerializer(many=True)
    court_dissolution = serializers.SerializerMethodField()
    registries = RegistryEntrySerializer(source="registry_entries", many=True)
    donation_codes = serializers.SerializerMethodField()
    donations = serializers.SerializerMethodField()
    corporate_donors = serializers.SerializerMethodField()
    individual_donors = serializers.SerializerMethodField()
    donor_summary = serializers.SerializerMethodField()
    since_roc_year = serializers.SerializerMethodField()
    categories = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = (
            "ubn", "name", "org_type", "representative", "registered_address", "contact_address", "phone",
            "website", "city", "purposes", "status", "status_label", "source_links", "disclosure_level",
            "penalty_count_5y", "levels", "public_raised", "annual_records", "financials", "documents", "projects",
            "penalties", "grants", "court_registrations", "court_dissolution", "registries", "donation_codes", "donation_trend", "donations",
            "corporate_donors", "individual_donors", "donor_summary", "since_roc_year", "categories",
            "updated_at",
        )

    def get_grants(self, obj):
        return GrantSerializer(distinct_grants(obj.grants.all()), many=True).data

    def get_donation_trend(self, obj):
        return scoring.donation_trend(
            list(obj.annual_records.all()), list(obj.projects.all()), distinct_grants(obj.grants.all())
        )
    def get_court_dissolution(self, obj):
        return court_dissolution(list(obj.court_registrations.all()))

    def get_levels(self, obj):
        # 組織頁的補助已預先載入近 5 年那幾筆，直接用，不再查一次
        return scoring.levels(obj, has_grants=bool(obj.grants.all()))

    def get_public_raised(self, obj):
        return scoring.public_raised(list(obj.annual_records.all()), list(obj.projects.all()))

    def get_donations(self, obj):
        qs = donor_rules.visible_donations(obj.donations.select_related("donor"))[:RECENT_DONATIONS]
        return DonationSerializer(qs, many=True).data

    def get_corporate_donors(self, obj):
        return donor_rules.corporate_ranking(obj)

    def get_individual_donors(self, obj):
        return donor_rules.individual_ranking(obj)

    def get_donor_summary(self, obj):
        return donor_rules.org_summary(obj)

    def get_donation_codes(self, obj):
        # 用統編對（讀的時候才對）：清單沒變、組織後來才進財政部名冊也對得到
        return DonationCodeSerializer(DonationCode.objects.filter(ubn=obj.ubn).order_by("code"), many=True).data

    def get_since_roc_year(self, obj):
        return period.since_roc_year()

    def get_categories(self, obj):
        return category_api.org_categories(obj)


class DonorListSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display")
    total = serializers.IntegerField()
    org_count = serializers.IntegerField()
    donation_count = serializers.IntegerField()

    class Meta:
        model = Donor
        fields = ("id", "name", "kind", "kind_label", "ubn", "total", "org_count", "donation_count")


class DonorDonationSerializer(serializers.ModelSerializer):
    org_ubn = serializers.CharField(source="organization.ubn")
    org_name = serializers.CharField(source="organization.name")
    project_name = serializers.CharField(source="project.name", default="")

    class Meta:
        model = Donation
        fields = ("id", "donated_on", "amount", "purpose", "org_ubn", "org_name", "project_name", "source_name", "source_url")


class DonorDetailSerializer(DonorListSerializer):
    organizations = serializers.SerializerMethodField()
    donations = serializers.SerializerMethodField()
    fields_breakdown = serializers.SerializerMethodField()

    class Meta(DonorListSerializer.Meta):
        fields = DonorListSerializer.Meta.fields + (
            "registered_name", "representative", "capital", "address", "organizations", "donations", "fields_breakdown",
        )

    def get_fields_breakdown(self, obj):
        return category_api.donor_field_breakdown(obj)

    def get_organizations(self, obj):
        return donor_rules.donor_by_org(obj)

    def get_donations(self, obj):
        qs = obj.donations.filter(period.donation_q()).select_related("organization", "project")
        qs = qs.order_by("-donated_on", "-amount")
        return DonorDonationSerializer(qs[:DONOR_DETAIL_DONATIONS], many=True).data
