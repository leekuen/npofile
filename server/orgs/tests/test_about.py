from django.test import TestCase, override_settings
from rest_framework.test import APIClient


class StatsThresholdTests(TestCase):
    @override_settings(DONOR_INDIVIDUAL_THRESHOLD=123_000)
    def test_threshold_comes_from_settings(self):
        """資料說明頁寫的個人門檻跟實際規則同一個來源（LK-22）。"""
        self.assertEqual(APIClient().get("/api/stats").json()["donor_individual_threshold"], 123_000)
