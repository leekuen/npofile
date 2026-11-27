from rest_framework import serializers

from . import category_api, donor_rules, period, scoring
from .models import AnnualFundraising, Donation, Donor, Organization, Penalty, Project

RECENT_DONATIONS = 50
DONOR_DETAIL_DONATIONS = 200


class OrganizationListSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display")
    penalty_count_5y = serializers.IntegerField()
    raised_5y = serializers.IntegerField()
    tags = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = (
            "ubn", "name", "org_type", "city", "status", "status_label", "disclosure_score", "penalty_count_5y",
            "raised_5y", "tags",
        )

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


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = (
            "id", "name", "category", "start_date", "end_date", "target", "raised", "permit_no", "region",
            "result_filed_on", "closed_filed_on", "description", "source_name", "source_url",
            "channel", "monthly_raised", "backers",
        )


class PenaltySerializer(serializers.ModelSerializer):
    class Meta:
        model = Penalty
        fields = (
            "id", "decided_on", "authority", "document_no", "content", "fine_text", "reason", "source_name", "source_url",
        )


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


class OrganizationDetailSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display")
    penalty_count_5y = serializers.IntegerField()
    score = serializers.SerializerMethodField()
    annual_records = AnnualSerializer(many=True)
    projects = ProjectSerializer(many=True)
    penalties = PenaltySerializer(many=True)
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
            "website", "city", "purposes", "status", "status_label", "source_links", "disclosure_score",
            "penalty_count_5y", "score", "annual_records", "projects", "penalties", "donations",
            "corporate_donors", "individual_donors", "donor_summary", "since_roc_year", "categories",
            "updated_at",
        )

    def get_score(self, obj):
        return scoring.breakdown(obj)

    def get_donations(self, obj):
        qs = donor_rules.visible_donations(obj.donations.select_related("donor"))[:RECENT_DONATIONS]
        return DonationSerializer(qs, many=True).data

    def get_corporate_donors(self, obj):
        return donor_rules.corporate_ranking(obj)

    def get_individual_donors(self, obj):
        return donor_rules.individual_ranking(obj)

    def get_donor_summary(self, obj):
        return donor_rules.org_summary(obj)

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
