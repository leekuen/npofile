from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotAuthenticated, PermissionDenied, Throttled
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from orgs.models import Organization

from .models import Comment
from .serializers import CommentSerializer, LoginSerializer, RegisterSerializer, me_payload

LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 15 * 60


def _enforce_csrf(request):
    """登入／註冊時還沒登入，DRF 不會自動檢查 CSRF；這兩支手動檢查，防止被別的網站代為登入。"""
    SessionAuthentication().enforce_csrf(request)


def _client_ip(request) -> str:
    return request.META.get("REMOTE_ADDR", "")


class CommentCreateThrottle(UserRateThrottle):
    scope = "comment_create"


@api_view(["GET"])
@ensure_csrf_cookie
def csrf(request):
    return Response({})


@api_view(["GET"])
def me(request):
    return Response({"user": me_payload(request.user) if request.user.is_authenticated else None})


@api_view(["POST"])
def register(request):
    _enforce_csrf(request)
    ser = RegisterSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    user = ser.save()
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return Response({"user": me_payload(user)}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def login_view(request):
    _enforce_csrf(request)
    ser = LoginSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    email = ser.validated_data["email"].strip().lower()
    key = f"login-fail:{email}:{_client_ip(request)}"
    if cache.get(key, 0) >= LOGIN_MAX_FAILURES:
        raise Throttled(wait=LOGIN_LOCK_SECONDS, detail="登入失敗太多次，請 15 分鐘後再試")
    user = authenticate(request, username=email, password=ser.validated_data["password"])
    if user is None:
        cache.set(key, cache.get(key, 0) + 1, LOGIN_LOCK_SECONDS)
        return Response(
            {"error": {"code": "invalid_credentials", "message": "Email 或密碼不正確", "fields": {}}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    cache.delete(key)
    login(request, user)
    return Response({"user": me_payload(user)})


@api_view(["POST"])
def logout_view(request):
    logout(request)
    return Response({"user": None})


def _visible_comments(request, org):
    cond = Q(status=Comment.Status.APPROVED)
    if request.user.is_authenticated:
        cond |= Q(author=request.user)
    return org.comments.filter(cond).select_related("author__donor_profile")


@api_view(["GET", "POST"])
@throttle_classes([])
def org_comments(request, ubn):
    org = get_object_or_404(Organization, ubn=ubn)
    if request.method == "GET":
        ser = CommentSerializer(_visible_comments(request, org), many=True, context={"request": request})
        return Response({"results": ser.data})

    if not request.user.is_authenticated:
        raise NotAuthenticated("登入後才能留言")
    throttle = CommentCreateThrottle()
    if not throttle.allow_request(request, None):
        raise Throttled(wait=throttle.wait(), detail="留言太頻繁，請稍後再試（每分鐘最多 3 則）")
    ser = CommentSerializer(data=request.data, context={"request": request})
    ser.is_valid(raise_exception=True)
    comment = ser.save(organization=org, author=request.user)
    return Response(CommentSerializer(comment, context={"request": request}).data, status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def comment_delete(request, pk):
    comment = get_object_or_404(Comment, pk=pk)
    if comment.author_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied("只能刪除自己的留言")
    comment.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
