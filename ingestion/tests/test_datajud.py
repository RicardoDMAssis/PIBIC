import unittest
from pathlib import Path
from unittest.mock import patch

from bpc_ingestion.checkpoint import CheckpointStore
from bpc_ingestion.content import criar_conteudo_de_movimentacoes
from bpc_ingestion.datajud import (
    DatajudClient,
    formatar_numero_processo,
    normalizar_processo,
    query_fingerprint,
)


SOURCE = {
    "numeroProcesso": "10446132820214013900",
    "tribunal": "TRF1",
    "grau": "G1",
    "classe": {"codigo": 120, "nome": "Mandado de Segurança Cível"},
    "assuntos": [{"codigo": 11946, "nome": "Deficiente"}],
    "orgaoJulgador": {"codigo": 16551, "nome": "05ª - Belém"},
    "dataAjuizamento": "20211215080550",
    "dataHoraUltimaAtualizacao": "2026-03-14T01:55:12.083000Z",
    "movimentos": [
        {
            "codigo": 26,
            "nome": "Distribuição",
            "dataHora": "2021-12-15T08:05:52.000Z",
            "complementosTabelados": [
                {"codigo": 2, "valor": 2, "nome": "sorteio", "descricao": "tipo"}
            ],
        }
    ],
}


class NormalizacaoTest(unittest.TestCase):
    def test_formata_numero_cnj(self):
        self.assertEqual(
            formatar_numero_processo(SOURCE["numeroProcesso"]),
            "1044613-28.2021.4.01.3900",
        )

    def test_normaliza_payload_real(self):
        processo = normalizar_processo(SOURCE, "2026-08-11T00:00:00.000Z")
        self.assertEqual(
            set(processo),
            {
                "numero_processo",
                "tribunal",
                "grau",
                "classe",
                "assuntos",
                "orgao_julgador",
                "nivel_sigilo",
                "data_ajuizamento",
                "data_ultima_atualizacao",
                "movimentacoes",
                "fonte",
                "coletado_em",
            },
        )
        self.assertEqual(processo["assuntos"], [{"codigo": 11946, "nome": "Deficiente"}])
        self.assertNotIn("principal", processo["assuntos"][0])
        self.assertEqual(processo["data_ajuizamento"], "2021-12-15T08:05:50.000Z")
        self.assertEqual(processo["movimentacoes"][0]["complementos"][0]["valor"], 2)

    def test_cria_conteudo_limitado_as_movimentacoes(self):
        processo = normalizar_processo(SOURCE, "2026-08-11T00:00:00.000Z")
        conteudo = criar_conteudo_de_movimentacoes(processo, processo["coletado_em"])
        self.assertEqual(
            set(conteudo), {"numero_processo", "fonte", "peca", "coletado_em"}
        )
        self.assertEqual(
            set(conteudo["peca"]), {"tipo", "texto_bruto", "url_documento", "data"}
        )
        self.assertEqual(conteudo["fonte"], "datajud_movimentacoes")
        self.assertIn("Distribuição", conteudo["peca"]["texto_bruto"])
        self.assertIsNone(conteudo["peca"]["url_documento"])


class PaginacaoTest(unittest.TestCase):
    @patch("bpc_ingestion.datajud.time.sleep")
    @patch("bpc_ingestion.datajud.urlopen")
    def test_timeout_tem_retenta_e_erro_legivel(self, open_url, sleep):
        open_url.side_effect = TimeoutError("read timed out")
        client = DatajudClient("https://example.test", "key", max_retries=1)
        with self.assertRaisesRegex(RuntimeError, "Falha de rede ao consultar TRF1"):
            client._search("TRF1", {"query": {"match_all": {}}})
        self.assertEqual(open_url.call_count, 2)
        sleep.assert_called_once()

    @patch.object(DatajudClient, "_search")
    def test_search_after_usa_cursor_da_ultima_resposta(self, search):
        search.side_effect = [
            {"hits": {"hits": [{"_source": {"id": 1}, "sort": [100]}]}},
            {"hits": {"hits": [{"_source": {"id": 2}, "sort": [200]}]}},
            {"hits": {"hits": []}},
        ]
        client = DatajudClient(
            "https://example.test", "key", page_size=10, source_mode="essencial"
        )
        self.assertEqual(list(client.iter_hits("TRF1", [6114])), [{"id": 1}, {"id": 2}])
        self.assertNotIn("search_after", search.call_args_list[0].args[1])
        self.assertEqual(search.call_args_list[1].args[1]["search_after"], [100])

    @patch.object(DatajudClient, "_search")
    def test_ordenacao_tem_desempate_estavel(self, search):
        search.return_value = {"hits": {"hits": []}}
        client = DatajudClient(
            "https://example.test", "key", page_size=10, source_mode="essencial"
        )
        list(client.iter_hits("TRF1", [6114]))
        body = search.call_args.args[1]
        self.assertEqual(
            body["sort"],
            [
                {"@timestamp": {"order": "asc"}},
                {"id.keyword": {"order": "asc"}},
            ],
        )
        self.assertIn("numeroProcesso", body["_source"])

    @patch.object(DatajudClient, "_search")
    def test_modo_completo_nao_filtra_source(self, search):
        search.return_value = {"hits": {"hits": []}}
        client = DatajudClient("https://example.test", "key", page_size=10)
        list(client.iter_hits("STJ", [6114]))
        self.assertNotIn("_source", search.call_args.args[1])

    def test_fingerprint_muda_com_modo_de_coleta(self):
        self.assertNotEqual(
            query_fingerprint([6114], "completo"),
            query_fingerprint([6114], "essencial"),
        )

    @patch.object(DatajudClient, "_search")
    def test_filtro_municipio_e_checkpoint_distintos(self, search):
        search.return_value = {"hits": {"hits": []}}
        client = DatajudClient("https://example.test", "key", page_size=10)
        list(client.iter_pages(
            "TRF1", [6114, 11946, 11947], municipio_codigos=[743], graus=["G1", "JE"]
        ))
        body = search.call_args.args[1]
        self.assertEqual(
            body["query"]["bool"]["must"][1],
            {"terms": {"orgaoJulgador.codigoMunicipioIBGE": [743]}},
        )
        self.assertEqual(body["query"]["bool"]["must"][2], {"terms": {"grau.keyword": ["G1", "JE"]}})
        self.assertNotEqual(
            query_fingerprint([6114, 11946, 11947], "completo"),
            query_fingerprint([6114, 11946, 11947], "completo", [743]),
        )
        self.assertNotEqual(
            query_fingerprint([6114, 11946, 11947], "completo", [743]),
            query_fingerprint([6114, 11946, 11947], "completo", [743], ["G1", "JE"]),
        )

    @patch.object(DatajudClient, "_search")
    def test_ano_ajuizamento_restringe_busca_e_checkpoint(self, search):
        search.return_value = {"hits": {"hits": []}}
        client = DatajudClient("https://example.test", "key", page_size=10)
        list(client.iter_pages("TRF1", [11946], ano_ajuizamento=2023))
        self.assertIn(
            {"range": {"dataAjuizamento": {"gte": "20230101000000", "lt": "20240101000000"}}},
            search.call_args.args[1]["query"]["bool"]["must"],
        )
        self.assertNotEqual(
            query_fingerprint([11946], "completo"),
            query_fingerprint([11946], "completo", ano_ajuizamento=2023),
        )

    @patch.object(DatajudClient, "_search")
    def test_retomada_envia_cursor_inicial(self, search):
        search.return_value = {"hits": {"hits": []}}
        client = DatajudClient("https://example.test", "key", page_size=10)
        list(client.iter_hits("TRF2", [11946], search_after=[123, "processo-1"]))
        self.assertEqual(
            search.call_args.args[1]["search_after"], [123, "processo-1"]
        )


class CheckpointTest(unittest.TestCase):
    def test_salva_le_remove_checkpoint(self):
        path = Path.cwd() / ".checkpoint-test.json"
        self.assertFalse(path.exists())
        try:
            store = CheckpointStore(path)
            self.assertIsNone(store.get("TRF1"))
            store.save("trf1", [123, "processo-1"])
            store.save("TRF2", [456, "processo-2"])
            store.save("STJ", [789, "processo-3"], "consulta-v2")
            self.assertEqual(store.get("TRF1"), [123, "processo-1"])
            self.assertEqual(store.get("trf2"), [456, "processo-2"])
            store.clear("TRF1")
            self.assertIsNone(store.get("TRF1"))
            self.assertEqual(store.get("TRF2"), [456, "processo-2"])
            self.assertEqual(store.get("STJ", "consulta-v2"), [789, "processo-3"])
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
