from django.contrib.auth import get_user_model, password_validation
from django.db import transaction
from rest_framework import serializers

from .models import Comment, DonorProfile

User = get_user_model()
BODY_MAX = 1000


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=150)
    display_name = serializers.CharField(max_length=50, trim_whitespace=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("這個 Email 已經註冊過了")
        return value

    def validate(self, attrs):
        user = User(username=attrs["email"], email=attrs["email"])
        try:
            password_validation.validate_password(attrs["password"], user)
        except Exception as exc:  # django ValidationError → 欄位錯誤
            raise serializers.ValidationError({"password": list(getattr(exc, "messages", [str(exc)]))})
        return attrs

    @transaction.atomic
    def create(self, data):
        user = User.objects.create_user(username=data["email"], email=data["email"], password=data["password"])
        DonorProfile.objects.create(user=user, display_name=data["display_name"])
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)


def me_payload(user) -> dict:
    profile = getattr(user, "donor_profile", None)
    return {
        "email": user.email,
        "display_name": profile.display_name if profile else user.get_username(),
        "is_staff": user.is_staff,
    }


class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    is_mine = serializers.SerializerMethodField()
    reject_reason = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ("id", "author_name", "body", "status", "status_label", "reject_reason", "created_at", "is_mine")
        read_only_fields = ("id", "status", "created_at")

    def _is_mine(self, obj) -> bool:
        user = self.context["request"].user
        return user.is_authenticated and obj.author_id == user.id

    def get_is_mine(self, obj):
        return self._is_mine(obj)

    def get_reject_reason(self, obj):
        return obj.reject_reason if self._is_mine(obj) and obj.status == Comment.Status.REJECTED else ""

    def validate_body(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("留言內容不能是空白")
        if len(value) > BODY_MAX:
            raise serializers.ValidationError(f"留言最多 {BODY_MAX} 字")
        return value
