import re

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from . import category_api, donor_rules, period, scoring
from .models import AnnualFundraising, Donor, FinancialYear, OrgDocument, Organization, Project
from .serializers import (
    DonorDetailSerializer,
    DonorListSerializer,
    OrganizationDetailSerializer,
    OrganizationListSerializer,
)

ORDERINGS = {"score": ("-disclosure_score", "name"), "name": ("name",)}


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
        ordering = ORDERINGS.get(params.get("ordering", "score"), ORDERINGS["score"])
        return scoring.with_penalty_count(qs).prefetch_related("categories").order_by(*ordering)


@api_view(["GET"])
def organization_detail(request, ubn):
    qs = scoring.with_penalty_count(
        Organization.objects.prefetch_related(
            Prefetch("annual_records", queryset=AnnualFundraising.objects.filter(period.annual_q())),
            Prefetch("financials", queryset=FinancialYear.objects.filter(period.annual_q())),
            Prefetch("documents", queryset=OrgDocument.objects.filter(period.annual_q())),
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
