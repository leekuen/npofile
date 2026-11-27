import re

from django.db.models import OuterRef, Prefetch, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from . import category_api, donor_rules, period, scoring
from .models import AnnualFundraising, Donor, Organization, Project
from .serializers import (
    DonorDetailSerializer,
    DonorListSerializer,
    OrganizationDetailSerializer,
    OrganizationListSerializer,
)

# 預設「近 5 年實募」：同組織頁摘要的數字（口徑見 tickets/LK-08、LK-20）；沒有實募的組織排在後面，依揭露指數、名稱
ORDERINGS = {
    "raised": ("-raised_5y", "-disclosure_score", "name"),
    "score": ("-disclosure_score", "name"),
    "name": ("name",),
}
DEFAULT_ORDERING = "raised"


def with_raised_5y(qs):
    """近 5 年年度募款的實募合計；用子查詢，避免跟裁罰次數的 join 互相放大。"""
    total = (
        AnnualFundraising.objects.filter(period.annual_q(), organization=OuterRef("pk"))
        .order_by()
        .values("organization")
        .annotate(s=Sum("raised"))
        .values("s")
    )
    return qs.annotate(raised_5y=Coalesce(Subquery(total), Value(0)))


class OrganizationList(ListAPIView):
    serializer_class = OrganizationListSerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = Organization.objects.all()
        q = params.get("q", "").strip()
        if q:
            cond = Q(name__icontains=q)
            if re.fullmatch(r"\d{8}", q):
                cond |= Q(ubn=q)
            qs = qs.filter(cond)
        if city := params.get("city", "").strip():
            qs = qs.filter(city=city)
        if status := params.get("status", "").strip():
            qs = qs.filter(status=status)
        qs = category_api.filter_orgs(qs, params)
        ordering = ORDERINGS.get(params.get("ordering", DEFAULT_ORDERING), ORDERINGS[DEFAULT_ORDERING])
        qs = with_raised_5y(scoring.with_penalty_count(qs))
        return qs.prefetch_related("categories").order_by(*ordering)


@api_view(["GET"])
def organization_detail(request, ubn):
    qs = scoring.with_penalty_count(
        Organization.objects.prefetch_related(
            Prefetch("annual_records", queryset=AnnualFundraising.objects.filter(period.annual_q())),
            Prefetch("projects", queryset=Project.objects.filter(period.project_q())),
            "penalties",
            "categories",
        )
    )
    org = get_object_or_404(qs, ubn=ubn)
    return Response(OrganizationDetailSerializer(org).data)


@api_view(["GET"])
def stats(request):
    orgs = Organization.objects.all()
    return Response(
        {
            "organizations": orgs.count(),
            "with_fundraising": orgs.filter(
                period.annual_q("annual_records__") | (Q(projects__isnull=False) & period.project_q("projects__"))
            ).distinct().count(),
            "since_roc_year": period.since_roc_year(),
            "penalized_5y": orgs.filter(scoring.penalty_5y_filter("penalties__")).distinct().count(),
        }
    )


@api_view(["GET"])
def filters(request):
    cities = (
        Organization.objects.exclude(city="").values_list("city", flat=True).distinct().order_by("city")
    )
    return Response(
        {
            "cities": list(cities),
            "statuses": [{"value": v, "label": label} for v, label in Organization.Status.choices],
        }
    )


DONOR_ORDERINGS = {"total": ("-total", "name"), "name": ("name",)}


class DonorList(ListAPIView):
    """捐款企業與團體排行（個人不在這裡：見 donor_rules）。"""

    serializer_class = DonorListSerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = donor_rules.public_donors()
        q = params.get("q", "").strip()
        if q:
            cond = Q(name__icontains=q) | Q(registered_name__icontains=q)
            if re.fullmatch(r"\d{8}", q):
                cond |= Q(ubn=q)
            qs = qs.filter(cond)
        kind = params.get("kind", "").strip()
        if kind in Donor.PUBLIC_KINDS:
            qs = qs.filter(kind=kind)
        return qs.order_by(*DONOR_ORDERINGS.get(params.get("ordering", "total"), DONOR_ORDERINGS["total"]))


@api_view(["GET"])
def donor_detail(request, pk):
    donor = get_object_or_404(donor_rules.public_donors(), pk=pk)
    return Response(DonorDetailSerializer(donor).data)
