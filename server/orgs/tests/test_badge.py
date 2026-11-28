"""揭露徽章與升級指南（LK-42）。"""

import re
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from orgs import badge, scoring
from orgs.models import Organization

from .test_orgs import make_org

GUIDE = Path(__file__).resolve().parents[3] / "web" / "lib" / "level-guide.ts"


class BadgeRenderTests(SimpleTestCase):
    def test_each_level_text_and_color(self):
        for n, medal in scoring.LEVEL_MEDALS.items():
            svg = badge.render(n, True)
            self.assertIn(f">{medal}</text>", svg)
            self.assertIn(badge.LEVEL_COLORS[n], svg)
            self.assertIn("<title>NPOFile 揭露層級：", svg)

    def test_inactive_and_unknown(self):
        self.assertIn(">不分層級</text>", badge.render(3, False))
        self.assertNotIn(">金</text>", badge.render(3, False))
        self.assertIn(">未收錄</text>", badge.render(None, None))

    def test_out_of_range_level_is_clamped(self):
        self.assertIn(">鑽石</text>", badge.render(9, True))
        self.assertIn(">未分級</text>", badge.render(-1, True))

    def test_width_grows_with_text(self):
        def width(svg):
            return int(re.search(r'width="(\d+)"', svg).group(1))

        self.assertGreater(width(badge.render(0, True)), width(badge.render(1, True)))  # 未分級 比 銅 長


def org_at(ubn, level, **kw):
    """存檔時訊號會重算層級，測試直接改資料庫上的值。"""
    make_org(ubn, **kw)
    Organization.objects.filter(ubn=ubn).update(disclosure_level=level)


class BadgeApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def get(self, ubn):
        return self.client.get(f"/api/orgs/{ubn}/badge.svg")

    def test_active_org(self):
        org_at("11111111", 2)
        r = self.get("11111111")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("image/svg+xml"))
        self.assertEqual(r["Cache-Control"], "public, max-age=21600")
        self.assertEqual(r["Cross-Origin-Resource-Policy"], "cross-origin")
        self.assertIn(">銀</text>", r.content.decode())

    def test_unrated_org(self):
        org_at("22222222", 0)
        self.assertIn(">未分級</text>", self.get("22222222").content.decode())

    def test_inactive_org(self):
        org_at("33333333", 4, status=Organization.Status.CANCELLED)
        body = self.get("33333333").content.decode()
        self.assertIn(">不分層級</text>", body)
        self.assertNotIn(">鑽石</text>", body)

    def test_unknown_ubn_still_returns_svg(self):
        r = self.get("99999999")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(r["Content-Type"].startswith("image/svg+xml"))
        self.assertIn(">未收錄</text>", r.content.decode())

    def test_detail_api_unaffected(self):
        make_org("44444444")
        self.assertEqual(self.client.get("/api/orgs/44444444").status_code, 200)


class GuideCoverageTests(TestCase):
    """前台升級指南（web/lib/level-guide.ts）要涵蓋後端每一個條件代號；後端加條件時這裡會紅。"""

    def test_every_check_key_has_guide_text(self):
        if not GUIDE.exists():
            self.skipTest("沒有前台原始碼（只部署後端時）")
        src = GUIDE.read_text(encoding="utf-8")
        org = make_org("55555555")
        keys = [c["key"] for layer in scoring.levels(org)["layers"] for c in layer["checks"]]
        self.assertGreater(len(keys), 10)
        missing = [k for k in keys if not re.search(rf"^\s*{k}:\s*\{{", src, re.M)]
        self.assertEqual(missing, [], f"level-guide.ts 缺這些條件的「怎麼做」：{missing}")
