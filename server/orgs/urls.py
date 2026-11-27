from django.urls import path

from . import views

urlpatterns = [
    path("stats", views.stats, name="stats"),
    path("filters", views.filters, name="filters"),
    path("orgs", views.OrganizationList.as_view(), name="org-list"),
    path("orgs/<str:ubn>", views.organization_detail, name="org-detail"),
    path("donors", views.DonorList.as_view(), name="donor-list"),
    path("donors/<int:pk>", views.donor_detail, name="donor-detail"),
]
