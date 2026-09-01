import unittest

from pydantic import ValidationError

from bpc_ingestion.api import DatajudTaskRequest, STATIC_DIR


class DashboardTest(unittest.TestCase):
    def test_static_dashboard_is_packaged(self):
        page = STATIC_DIR / "index.html"
        self.assertTrue(page.exists())
        self.assertIn("Painel local de coleta", page.read_text(encoding="utf-8"))

    def test_rejects_unknown_tribunal(self):
        with self.assertRaises(ValidationError):
            DatajudTaskRequest(tribunais=["TRF7"])

    def test_accepts_full_collection_as_null_limit(self):
        request = DatajudTaskRequest(tribunais=["TRF1"], max_records=None)
        self.assertIsNone(request.max_records)

    def test_accepts_stj_and_exploratory_state_courts(self):
        request = DatajudTaskRequest(
            tribunais=["STJ"], include_state_courts=True, source_mode="completo"
        )
        self.assertEqual(request.tribunais, ["STJ"])
        self.assertTrue(request.include_state_courts)


if __name__ == "__main__":
    unittest.main()
