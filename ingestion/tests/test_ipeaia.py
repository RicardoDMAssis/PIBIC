import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError

from sqlalchemy.dialects import postgresql

from bpc_ingestion.ipeaia import (IpeaIaClient, PROMPT_VERSION, RejectedIpeaResponse,
                                _eligible_process_statement, build_input,
                                save_rejected_response, validate_result)


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

    def test_aceita_tribunal_e_grau_mas_rejeita_rotulo_composto(self):
        valid = dict(self.result, evidencias=[
            dict(self.result["evidencias"][0], campo="tribunal", referencia="TRF1"),
            dict(self.result["evidencias"][0], campo="grau", referencia="JE"),
        ])
        fields = [item["campo"] for item in validate_result(valid, self.source)["evidencias"]]
        self.assertEqual(fields, ["tribunal", "grau"])
        invalid = dict(self.result, evidencias=[
            dict(self.result["evidencias"][0], campo="tribunal / grau"),
        ])
        with self.assertRaisesRegex(ValueError, "caminho existente"):
            validate_result(invalid, self.source)
        invalid = dict(self.result, evidencias=[dict(self.result["evidencias"][0], registro_id=999)])
        with self.assertRaises(ValueError):
            validate_result(invalid, self.source)

    def test_consulta_de_reserva_e_compativel_com_postgresql(self):
        sql = str(_eligible_process_statement("modelo", 1, lock=True).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
        )).upper()
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertNotIn("SELECT DISTINCT", sql)

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

    def test_diagnostico_detalha_evidencia_invalida(self):
        evidence = self.result["evidencias"][0]
        cases = [
            (None, "evidencias\\[0\\]: deve ser objeto"),
            (dict(evidence, fonte="DataJud"), "campos extras=.*fonte"),
            (dict(evidence, registro_id="7"), "registro_id: recebido='7'.*ID inteiro"),
            (dict(evidence, registro_id=999), "registro_id: recebido=999.*\\[7\\]"),
            (dict(evidence, registro_id=[7]), "registro_id"),
            (dict(evidence, campo=["assuntos"]), "campo: recebido"),
            (dict(evidence, referencia=11946), "referencia: deve ser texto"),
            (dict(evidence, sustenta=None), "sustenta: deve ser texto"),
        ]
        for invalid, message in cases:
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, message):
                    validate_result(dict(self.result, evidencias=[invalid]), self.source)

    @patch("bpc_ingestion.ipeaia.urlopen")
    def test_preserva_resposta_rejeitada_e_salva_sem_token(self, open_url):
        invalid = dict(self.result, evidencias=[dict(self.result["evidencias"][0], registro_id=999)])
        response = {"choices": [{"message": {"content": json.dumps(invalid)}}], "extra": "segredo"}
        open_url.return_value.__enter__.return_value = io.BytesIO(json.dumps(response).encode())
        client = IpeaIaClient("https://example.test", "segredo", interval=0)
        with self.assertRaisesRegex(RejectedIpeaResponse, "registro_id") as caught:
            client.classify("modelo", self.source)
        self.assertEqual(caught.exception.response, response)
        with TemporaryDirectory() as directory:
            path = save_rejected_response(caught.exception, self.source, "modelo", client.token,
                                          Path(directory) / "rejeitadas")
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("segredo", text)
            diagnostic = json.loads(text)
            self.assertEqual(diagnostic["entrada"], self.source)
            self.assertEqual(diagnostic["modelo"], "modelo")
            self.assertEqual(json.loads(diagnostic["resposta_api"]["choices"][0]["message"]["content"]), invalid)
        self.assertEqual(open_url.call_count, 1)

    @patch("bpc_ingestion.ipeaia.urlopen")
    def test_preserva_resposta_sem_json_valido(self, open_url):
        response = {"choices": [{"message": {"content": "texto, não JSON"}}]}
        open_url.return_value.__enter__.return_value = io.BytesIO(json.dumps(response).encode())
        with self.assertRaises(RejectedIpeaResponse) as caught:
            IpeaIaClient("https://example.test", "segredo", interval=0).classify("modelo", self.source)
        self.assertEqual(caught.exception.response, response)

    @patch("bpc_ingestion.ipeaia.urlopen")
    def test_aceita_json_em_bloco_markdown_e_caminhos_existentes(self, open_url):
        paths = ["orgao_julgador.nome", "assuntos[0].nome", "classe.nome",
                 "movimentacoes[sequencia=6].nome"]
        result = dict(self.result, evidencias=[
            dict(self.result["evidencias"][0], campo=path) for path in paths
        ])
        response = {"model": "glm-5.3", "choices": [{"message": {
            "content": "```json\n" + json.dumps(result) + "\n```"}}]}
        open_url.return_value.__enter__.return_value = io.BytesIO(json.dumps(response).encode())
        parsed = IpeaIaClient("https://example.test", "segredo", interval=0).classify("glm-5.3", self.source)
        self.assertEqual([e["campo"] for e in parsed["evidencias"]],
                         ["orgao_julgador", "assuntos", "classe", "movimentacoes"])
        self.assertTrue(parsed["evidencias"][3]["referencia"].startswith(paths[3] + ":"))
        self.assertEqual(result["evidencias"][3]["campo"], paths[3])

    def test_rejeita_caminhos_ausentes_ou_movimentos_nao_enviados(self):
        for path in ("classe.inventado", "assuntos[999].nome", "movimentacoes[sequencia=2].nome",
                     "movimentacoes[sequencia=999].nome", "orgao_julgador.nome.inventado"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "caminho existente"):
                validate_result(dict(self.result, evidencias=[
                    dict(self.result["evidencias"][0], campo=path)]), self.source)

    @patch("bpc_ingestion.ipeaia.urlopen")
    def test_rejeita_texto_extra_fora_do_bloco_json(self, open_url):
        response = {"choices": [{"message": {
            "content": "Explicação\n```json\n" + json.dumps(self.result) + "\n```"}}]}
        open_url.return_value.__enter__.return_value = io.BytesIO(json.dumps(response).encode())
        with self.assertRaisesRegex(RejectedIpeaResponse, "JSON válido"):
            IpeaIaClient("https://example.test", "segredo", interval=0).classify("modelo", self.source)

    @patch("bpc_ingestion.ipeaia.urlopen")
    def test_rejeita_modelo_diferente_do_solicitado(self, open_url):
        response = {"model": "glm-5.3", "choices": [{"message": {"content": json.dumps(self.result)}}]}
        open_url.return_value.__enter__.return_value = io.BytesIO(json.dumps(response).encode())
        with self.assertRaisesRegex(RejectedIpeaResponse, "Modelo divergente.*glm-5.2.*glm-5.3"):
            IpeaIaClient("https://example.test", "segredo", interval=0).classify("glm-5.2", self.source)


if __name__ == "__main__":
    unittest.main()
