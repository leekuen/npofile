import re

from django.conf import settings
from django.db.models import OuterRef, Prefetch, Q, Subquery
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.generics import ListAPIView
from npofile_crawler.donors import identity_key
from rest_framework.response import Response

from . import category_api, donor_rules, home, period, scoring
from .models import AnnualFundraising, CourtRegistration, Donor, FinancialYear, Grant, OrgDocument, Organization, Project
from .serializers import (
    DonorDetailSerializer,
    DonorListSerializer,
    OrganizationDetailSerializer,
    OrganizationListSerializer,
)

# 預設「近 5 年公開募款」（勸募申報＋群眾集資，口徑見 tickets/LK-20）；沒有的組織排在後面，依揭露指數、名稱
ORDERINGS = {
    "raised": ("-public_raised_5y", "-disclosure_score", "name"),
    "score": ("-disclosure_score", "name"),
    "name": ("name",),
}
DEFAULT_ORDERING = "raised"


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
        # 卡片上的「總收入（民國 N 年度）」：近 5 年內、有總收入的最近一年（LK-17）
        latest = FinancialYear.objects.filter(
            period.annual_q(), organization=OuterRef("pk"), total_revenue__isnull=False
        ).order_by("-year")
        qs = qs.annotate(
            fin_year=Subquery(latest.values("year")[:1]), fin_revenue=Subquery(latest.values("total_revenue")[:1])
        )
        ordering = ORDERINGS.get(params.get("ordering", DEFAULT_ORDERING), ORDERINGS[DEFAULT_ORDERING])
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
            Prefetch("grants", queryset=Grant.objects.filter(period.grant_q())),
            # 法院登記公告全部保留（組織歷史，跟裁罰一樣不篩年度）；新到舊，第一筆決定頁首的解散標示
            Prefetch("court_registrations", queryset=CourtRegistration.objects.order_by("-posted_on", "-id")),
            "categories",
            "registry_entries",
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
            # 資料說明頁要寫個人捐款人的門檻：從設定讀，畫面不寫死（LK-22）
            "donor_individual_threshold": settings.DONOR_INDIVIDUAL_THRESHOLD,
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
            # 比對用名稱也查：打「台灣」找得到「臺灣」、打「(股)」找得到「股份有限公司」、不看空白與大小寫（LK-16）
            cond = Q(name__icontains=q) | Q(registered_name__icontains=q) | Q(name_key__contains=identity_key(q))
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


@api_view(["GET"])
def home_discover(request):
    """首頁探索區：快截止的募款、最新裁罰、企業捐款（LK-18）。"""
    return Response(home.discover())


@api_view(["GET"])
def home_picks(request):
    """首頁領域區：選了領域或服務對象時的組織（LK-18）；沒有可看的分類回 {"picks": null}。"""
    return Response({"picks": home.field_picks(request.query_params)})
