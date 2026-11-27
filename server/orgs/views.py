import re

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from . import scoring
from .models import Organization
from .serializers import OrganizationDetailSerializer, OrganizationListSerializer

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
        ordering = ORDERINGS.get(params.get("ordering", "score"), ORDERINGS["score"])
        return scoring.with_penalty_count(qs).order_by(*ordering)


@api_view(["GET"])
def organization_detail(request, ubn):
    qs = scoring.with_penalty_count(
        Organization.objects.prefetch_related("annual_records", "projects", "penalties")
    )
    org = get_object_or_404(qs, ubn=ubn)
    return Response(OrganizationDetailSerializer(org).data)


@api_view(["GET"])
def stats(request):
    orgs = Organization.objects.all()
    return Response(
        {
            "organizations": orgs.count(),
            "with_fundraising": orgs.filter(Q(annual_records__isnull=False) | Q(projects__isnull=False)).distinct().count(),
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
