import unittest

from bpc_ingestion.comunica import ComunicaPjeClient


class ComunicaPjeClientTest(unittest.TestCase):
    def test_normalizes_cnj_number(self):
        self.assertEqual(
            ComunicaPjeClient._digits("1044613-28.2021.4.01.3900"),
            "10446132820214013900",
        )

    def test_rejects_invalid_number(self):
        with self.assertRaises(ValueError):
            ComunicaPjeClient._digits("123")


if __name__ == "__main__":
    unittest.main()
