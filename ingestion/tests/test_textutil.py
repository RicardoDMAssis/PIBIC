import unittest

from bpc_ingestion.textutil import repair_text


class RepairTextTest(unittest.TestCase):
    def test_repairs_mojibake(self):
        self.assertEqual(repair_text("Procedimento CÃ­vel"), "Procedimento Cível")

    def test_keeps_valid_unicode(self):
        self.assertEqual(repair_text("Benefício Assistencial"), "Benefício Assistencial")


if __name__ == "__main__":
    unittest.main()
