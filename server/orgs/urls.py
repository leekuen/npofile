from django.urls import path

from . import category_api, views

urlpatterns = [
    path("stats", views.stats, name="stats"),
    path("home/discover", views.home_discover, name="home-discover"),
    path("home/picks", views.home_picks, name="home-picks"),
    path("filters", views.filters, name="filters"),
    path("orgs", views.OrganizationList.as_view(), name="org-list"),
    path("orgs/<str:ubn>", views.organization_detail, name="org-detail"),
    path("donors", views.DonorList.as_view(), name="donor-list"),
    path("taxonomy", category_api.taxonomy_tree, name="taxonomy"),
    path("categories/<str:code>", category_api.category_overview, name="category-overview"),
    path("donors/<int:pk>", views.donor_detail, name="donor-detail"),
]
