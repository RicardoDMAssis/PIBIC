import io
import json
import unittest
from datetime import date
from unittest.mock import patch

from bpc_ingestion.transparencia import (
    TransparenciaClient, meses_no_periodo, normalizar_indicador,
)


ITEM = {
    "id": 123,
    "dataReferencia": "2026-07-01",
    "municipio": {"codigoIBGE": "5300108", "nomeIBGE": "BRASÍLIA", "uf": {"sigla": "DF"}},
    "tipo": {"id": 5, "descricao": "BPC"},
    "valor": 131276767.55,
    "quantidadeBeneficiados": 70480,
}


class TransparenciaTest(unittest.TestCase):
    def test_meses_inclusivos_e_virada_do_ano(self):
        self.assertEqual(meses_no_periodo(202512, 202602), [202512, 202601, 202602])
        with self.assertRaises(ValueError):
            meses_no_periodo(202613, 202701)
        with self.assertRaises(ValueError):
            meses_no_periodo(202602, 202601)

    def test_normaliza_e_valida_geografia_periodo(self):
        result = normalizar_indicador(ITEM, 202607, "5300108")
        self.assertEqual(result["data_referencia"], date(2026, 7, 1))
        self.assertEqual(result["quantidade_beneficiados"], 70480)
        self.assertEqual(result["valor"], "131276767.55")
        with self.assertRaisesRegex(ValueError, "Código IBGE"):
            normalizar_indicador(ITEM, 202607, "5208707")
        with self.assertRaisesRegex(ValueError, "Mês de referência"):
            normalizar_indicador(ITEM, 202606, "5300108")

    @patch("bpc_ingestion.transparencia.urlopen")
    def test_cliente_usa_token_sem_incluir_na_url(self, open_url):
        open_url.return_value.__enter__.return_value = io.BytesIO(json.dumps([ITEM]).encode())
        client = TransparenciaClient("https://example.test/api-de-dados", "secret", interval=0)
        self.assertEqual(client.fetch_page(202607, "5300108", 1), [ITEM])
        request = open_url.call_args.args[0]
        self.assertNotIn("secret", request.full_url)
        self.assertEqual(request.get_header("Chave-api-dados"), "secret")
        self.assertIn("mesAno=202607", request.full_url)


if __name__ == "__main__":
    unittest.main()
