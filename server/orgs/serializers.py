from django.db.models import Sum
from rest_framework import serializers

from . import scoring
from .models import AnnualFundraising, Donation, Organization, Penalty, Project

TOP_DONORS = 10
RECENT_DONATIONS = 50


class OrganizationListSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display")
    penalty_count_5y = serializers.IntegerField()

    class Meta:
        model = Organization
        fields = ("ubn", "name", "org_type", "city", "status", "status_label", "disclosure_score", "penalty_count_5y")


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
            "id", "name", "category", "start_date", "end_date", "target", "raised", "permit_no",
            "result_filed_on", "closed_filed_on", "description", "source_name", "source_url",
        )


class PenaltySerializer(serializers.ModelSerializer):
    class Meta:
        model = Penalty
        fields = ("id", "decided_on", "authority", "content", "fine_text", "source_name", "source_url")


class DonationSerializer(serializers.ModelSerializer):
    donor_name = serializers.CharField(source="public_donor_name")

    class Meta:
        model = Donation
        fields = ("id", "donor_name", "amount", "donated_on", "source_name", "source_url")


class OrganizationDetailSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display")
    penalty_count_5y = serializers.IntegerField()
    score = serializers.SerializerMethodField()
    annual_records = AnnualSerializer(many=True)
    projects = ProjectSerializer(many=True)
    penalties = PenaltySerializer(many=True)
    donations = serializers.SerializerMethodField()
    top_donors = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = (
            "ubn", "name", "org_type", "representative", "registered_address", "contact_address", "phone",
            "website", "city", "purposes", "status", "status_label", "source_links", "disclosure_score",
            "penalty_count_5y", "score", "annual_records", "projects", "penalties", "donations", "top_donors",
            "updated_at",
        )

    def get_score(self, obj):
        return scoring.breakdown(obj)

    def get_donations(self, obj):
        return DonationSerializer(obj.donations.all()[:RECENT_DONATIONS], many=True).data

    def get_top_donors(self, obj):
        rows = (
            obj.donations.filter(is_anonymous=False)
            .exclude(donor_name="")
            .values("donor_name")
            .annotate(total=Sum("amount"))
            .order_by("-total", "donor_name")[:TOP_DONORS]
        )
        return [{"donor_name": r["donor_name"], "total": r["total"]} for r in rows]
