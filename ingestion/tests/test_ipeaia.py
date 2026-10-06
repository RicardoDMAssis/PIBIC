import io
import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from bpc_ingestion.ipeaia import IpeaIaClient, PROMPT_VERSION, build_input, validate_result


class IpeaIaTest(unittest.TestCase):
    def setUp(self):
        self.source = build_input("0000000-00.2021.4.01.0000", [{
            "id": 7, "tribunal": "TRF1", "grau": "JE",
            "classe": {"codigo": 1, "nome": "classe"},
            "orgao_julgador": {"codigo": 2, "nome": "órgão", "codigo_municipio_datajud": "743"},
            "data_ajuizamento": "2021-01-01",
            "assuntos": [{"codigo": 11946, "nome": "BPC"}],
            "movimentacoes": [
                {"sequencia": i, "codigo": 26, "nome": "Distribuição", "data_hora": None}
                for i in range(8)
            ],
        }], max_movements=4)
        self.result = {
            "versao_prompt": PROMPT_VERSION,
            "numero_processo": self.source["numero_processo"],
            "escopo_pedido": "indeterminado",
            "aderencia_geografica": "orgao_brasilia",
            "desfecho": "indeterminado",
            "nivel_evidencia": "insuficiente",
            "revisao_humana": True,
            "evidencias": [{"registro_id": 7, "campo": "assuntos", "referencia": "11946", "sustenta": "candidato"}],
            "lacunas": ["pedido", "sentença"],
            "observacao_curta": "Dados insuficientes.",
        }

    def test_input_trunca_e_nao_inclui_payload(self):
        record = self.source["registros"][0]
        self.assertEqual([m["sequencia"] for m in record["movimentacoes"]], [0, 1, 6, 7])
        self.assertTrue(record["movimentacoes_truncadas"])
        self.assertNotIn("payload", json.dumps(self.source))

    def test_valida_taxonomia_e_proibe_desfecho_sem_documento(self):
        self.assertEqual(validate_result(self.result, self.source), self.result)
        invalid = dict(self.result, desfecho="procedente")
        with self.assertRaises(ValueError):
            validate_result(invalid, self.source)
        invalid = dict(self.result, evidencias=[dict(self.result["evidencias"][0], registro_id=999)])
        with self.assertRaises(ValueError):
            validate_result(invalid, self.source)

    @patch("bpc_ingestion.ipeaia.urlopen")
    def test_cliente_usa_bearer_sem_token_na_url(self, open_url):
        response = {"choices": [{"message": {"content": json.dumps(self.result)}}]}
        open_url.return_value.__enter__.return_value = io.BytesIO(json.dumps(response).encode())
        client = IpeaIaClient("https://ipeagpt.ipea.gov.br/api/v1", "segredo", interval=0)
        self.assertEqual(client.classify("glm-5.1", self.source), self.result)
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer segredo")
        self.assertNotIn("segredo", request.full_url)
        self.assertEqual(json.loads(request.data)["model"], "glm-5.1")

    @patch("bpc_ingestion.ipeaia.urlopen")
    def test_cliente_aceita_conteudo_em_blocos(self, open_url):
        response = {"choices": [{"message": {"content": [{"type": "text", "text": json.dumps(self.result)}]}}]}
        open_url.return_value.__enter__.return_value = io.BytesIO(json.dumps(response).encode())
        client = IpeaIaClient("https://ipeagpt.ipea.gov.br/api/v1", "segredo", interval=0)
        self.assertEqual(client.classify("glm-5.1", self.source), self.result)

    @patch("bpc_ingestion.ipeaia.urlopen")
    def test_timeout_configuravel_sem_repetir_geracao(self, open_url):
        for failure in (TimeoutError("timed out"), URLError(TimeoutError("timed out"))):
            with self.subTest(failure=type(failure).__name__):
                open_url.reset_mock()
                open_url.side_effect = failure
                client = IpeaIaClient("https://example.test", "segredo", timeout=900, interval=0, max_retries=3)
                with self.assertRaisesRegex(RuntimeError, "Timeout IpeaIA.*900s"):
                    client.classify("modelo", self.source)
                self.assertEqual(open_url.call_count, 1)
                self.assertEqual(open_url.call_args.kwargs["timeout"], 900)

    @patch("bpc_ingestion.ipeaia.urlopen")
    def test_erro_de_rede_mostra_causa_sem_token(self, open_url):
        open_url.side_effect = URLError("certificate verify failed segredo")
        client = IpeaIaClient("https://example.test", "segredo", interval=0)
        with self.assertRaises(RuntimeError) as caught:
            client.models()
        self.assertIn("certificate verify failed", str(caught.exception))
        self.assertNotIn("segredo", str(caught.exception))
        self.assertEqual(open_url.call_count, 1)

    def test_rejeita_timeout_invalido(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                IpeaIaClient("https://example.test", "segredo", timeout=timeout)


if __name__ == "__main__":
    unittest.main()
