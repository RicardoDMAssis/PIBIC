import json
import unittest

from bpc_ingestion.sqlite_store import SqliteStore


class SqliteStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = SqliteStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_upsert_raw_e_conteudo_e_idempotente(self):
        raw = {
            "numero_processo": "0000001-00.2026.4.01.0001",
            "tribunal": "TRF1",
            "assuntos": [{"codigo": 11946, "nome": "Pessoa com Deficiência"}],
            "coletado_em": "2026-08-17T00:00:00.000Z",
        }
        conteudo = {
            "numero_processo": raw["numero_processo"],
            "fonte": "datajud_movimentacoes",
            "peca": {"texto_bruto": "Distribuição"},
        }
        self.assertEqual(self.store.upsert_raw([raw]), 1)
        self.assertEqual(self.store.upsert_raw([{**raw, "grau": "G1"}]), 1)
        self.assertEqual(self.store.upsert_conteudo([conteudo]), 1)

        count = self.store.connection.execute(
            "SELECT COUNT(*) FROM processos_raw"
        ).fetchone()[0]
        payload = self.store.connection.execute(
            "SELECT payload_json FROM processos_raw"
        ).fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(json.loads(payload)["grau"], "G1")


if __name__ == "__main__":
    unittest.main()
