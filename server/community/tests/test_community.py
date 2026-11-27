from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from community.models import Comment
from orgs.models import Organization

PW = "Str0ng-pass-9"


class AuthFlowMixin:
    def register(self, client, email="donor@example.com", name="小明"):
        return client.post("/api/auth/register", {"email": email, "display_name": name, "password": PW}, format="json")


class AuthTests(AuthFlowMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_register_logs_in(self):
        r = self.register(self.client)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["user"]["display_name"], "小明")
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["email"], "donor@example.com")

    def test_register_duplicate_and_weak_password(self):
        self.register(self.client)
        r = self.register(APIClient())
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.json()["error"]["fields"])
        r = APIClient().post("/api/auth/register", {"email": "b@example.com", "display_name": "b", "password": "123"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.json()["error"]["fields"])

    def test_login_logout(self):
        self.register(self.client)
        self.client.post("/api/auth/logout")
        self.assertIsNone(self.client.get("/api/auth/me").json()["user"])
        r = self.client.post("/api/auth/login", {"email": "DONOR@example.com", "password": PW}, format="json")
        self.assertEqual(r.status_code, 200)
        r = APIClient().post("/api/auth/login", {"email": "donor@example.com", "password": "wrong"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["message"], "Email 或密碼不正確")

    def test_login_lockout_after_failures(self):
        self.register(self.client)
        c = APIClient()
        for _ in range(5):
            c.post("/api/auth/login", {"email": "donor@example.com", "password": "wrong"}, format="json")
        r = c.post("/api/auth/login", {"email": "donor@example.com", "password": PW}, format="json")
        self.assertEqual(r.status_code, 429)

    def test_login_requires_csrf(self):
        self.register(self.client)
        c = APIClient(enforce_csrf_checks=True)
        r = c.post("/api/auth/login", {"email": "donor@example.com", "password": PW}, format="json")
        self.assertEqual(r.status_code, 403)
        c.get("/api/auth/csrf")
        token = c.cookies["csrftoken"].value
        r = c.post("/api/auth/login", {"email": "donor@example.com", "password": PW}, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)

    def test_donor_cannot_enter_admin(self):
        self.register(self.client)
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 302)


class CommentTests(AuthFlowMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(ubn="12345678", name="甲協會")
        self.alice = APIClient()
        self.register(self.alice, "alice@example.com", "愛麗絲")
        self.bob = APIClient()
        self.register(self.bob, "bob@example.com", "鮑伯")
        self.anon = APIClient()
        self.url = "/api/orgs/12345678/comments"

    def post(self, client, body="捐款後很快收到收據"):
        return client.post(self.url, {"body": body}, format="json")

    def test_anonymous_cannot_post(self):
        r = self.post(self.anon)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["message"], "登入後才能留言")

    def test_pending_visible_only_to_author_until_approved(self):
        r = self.post(self.alice)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["status_label"], "審核中")
        self.assertEqual(len(self.alice.get(self.url).json()["results"]), 1)
        self.assertEqual(self.bob.get(self.url).json()["results"], [])
        self.assertEqual(self.anon.get(self.url).json()["results"], [])

        Comment.objects.update(status=Comment.Status.APPROVED)
        rows = self.anon.get(self.url).json()["results"]
        self.assertEqual(rows[0]["author_name"], "愛麗絲")
        self.assertNotIn("email", rows[0])
        self.assertNotIn("alice@example.com", str(self.anon.get(self.url).content))

    def test_reject_reason_only_for_author(self):
        self.post(self.alice)
        Comment.objects.update(status=Comment.Status.REJECTED, reject_reason="內容無法查證")
        mine = self.alice.get(self.url).json()["results"][0]
        self.assertEqual((mine["status_label"], mine["reject_reason"]), ("未通過", "內容無法查證"))
        self.assertEqual(self.bob.get(self.url).json()["results"], [])

    def test_delete_own_only(self):
        cid = self.post(self.alice).json()["id"]
        Comment.objects.update(status=Comment.Status.APPROVED)
        self.assertEqual(self.bob.delete(f"/api/comments/{cid}").status_code, 403)
        self.assertEqual(self.anon.delete(f"/api/comments/{cid}").status_code, 403)
        self.assertEqual(self.alice.delete(f"/api/comments/{cid}").status_code, 204)
        self.assertFalse(Comment.objects.exists())

    def test_length_validation(self):
        self.assertEqual(self.post(self.alice, "   ").status_code, 400)
        self.assertEqual(self.post(self.alice, "字" * 1001).status_code, 400)
        self.assertEqual(self.post(self.alice, "字" * 1000).status_code, 201)

    def test_throttle_fourth_comment_in_a_minute(self):
        for i in range(3):
            self.assertEqual(self.post(self.alice, f"第{i}則").status_code, 201)
        r = self.post(self.alice, "第四則")
        self.assertEqual(r.status_code, 429)
        self.assertIn("每分鐘最多 3 則", r.json()["error"]["message"])

    def test_deactivated_user_cannot_login(self):
        get_user_model().objects.filter(email="bob@example.com").update(is_active=False)
        r = APIClient().post("/api/auth/login", {"email": "bob@example.com", "password": PW}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_admin_moderation_actions(self):
        self.post(self.alice)
        get_user_model().objects.create_superuser("admin", "admin@example.com", "pw-123456789")
        self.client.login(username="admin", password="pw-123456789")
        listing = self.client.get("/admin/community/comment/")
        self.assertEqual(listing.context["cl"].result_count, 1)
        cid = Comment.objects.get().pk
        self.client.post("/admin/community/comment/", {"action": "approve", "_selected_action": [str(cid)]})
        self.assertEqual(Comment.objects.get().status, "approved")
        self.assertEqual(len(self.anon.get(self.url).json()["results"]), 1)
