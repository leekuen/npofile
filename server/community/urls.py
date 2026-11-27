from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf", views.csrf, name="auth-csrf"),
    path("auth/me", views.me, name="auth-me"),
    path("auth/register", views.register, name="auth-register"),
    path("auth/login", views.login_view, name="auth-login"),
    path("auth/logout", views.logout_view, name="auth-logout"),
    path("orgs/<str:ubn>/comments", views.org_comments, name="org-comments"),
    path("comments/<int:pk>", views.comment_delete, name="comment-delete"),
]
