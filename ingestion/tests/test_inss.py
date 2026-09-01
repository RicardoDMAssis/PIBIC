import unittest

from bpc_ingestion.inss import InssCatalogClient


class InssCatalogTest(unittest.TestCase):
    def test_normaliza_recursos_ckan(self):
        resources = InssCatalogClient.resources(
            [
                {
                    "id": "beneficios-concedidos",
                    "title": "Benefícios concedidos",
                    "resources": [
                        {
                            "id": "fev-2026",
                            "name": "Fevereiro 2026",
                            "format": "XLSX",
                            "url": "https://example.test/fev-2026.xlsx",
                        }
                    ],
                }
            ]
        )
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["fonte"], "inss")
        self.assertEqual(resources[0]["formato"], "XLSX")
        self.assertEqual(resources[0]["conjunto_id"], "beneficios-concedidos")


if __name__ == "__main__":
    unittest.main()
