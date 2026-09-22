import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from bpc_ingestion.api import admin_list_processes, admin_process_detail


class AdminProcessApiTest(unittest.TestCase):
    def test_search_normalizes_complete_cnj_number(self):
        session = MagicMock()
        session.scalar.return_value = 0
        session.scalars.return_value = []
        result = admin_list_processes(
            numero="10446132820214013900", tribunal=None, municipio_codigo=None,
            grau=None, com_comunicacao=None,
            limit=25, offset=0, session=session,
        )
        self.assertEqual(result["items"], [])
        statement = session.scalar.call_args.args[0]
        params = statement.compile(dialect=postgresql.dialect()).params
        self.assertIn("1044613-28.2021.4.01.3900", params.values())

    def test_territory_and_grade_filter_same_datajud_record(self):
        session = MagicMock()
        session.scalar.return_value = 0
        session.scalars.return_value = []
        admin_list_processes(
            numero=None, tribunal="TRF1", municipio_codigo=743, grau="JE",
            com_comunicacao=None, limit=25, offset=0, session=session,
        )
        statement = session.scalar.call_args.args[0]
        compiled = statement.compile(dialect=postgresql.dialect())
        self.assertIn("jsonb_extract_path_text", str(compiled))
        self.assertIn("JE", compiled.params.values())
        self.assertIn("743", compiled.params.values())

    def test_detail_reports_sources_without_inventing_decision(self):
        session = MagicMock()
        session.scalar.return_value = SimpleNamespace(id=7, numero_processo="1044613-28.2021.4.01.3900")
        record = SimpleNamespace(
            id=11, tribunal="TRF1", grau="G1", classe_codigo=120, classe_nome="Classe",
            orgao_codigo=10, orgao_nome="Vara", nivel_sigilo=0,
            data_ajuizamento=None, data_ultima_atualizacao=None, coletado_em=None,
            payload={"numeroProcesso": "10446132820214013900"},
        )
        session.scalars.side_effect = [[record], [], [], [], []]
        session.execute.side_effect = [[], []]
        session.get.return_value = None
        detail = admin_process_detail("10446132820214013900", session=session)
        self.assertEqual(detail["registros_datajud"][0]["tribunal"], "TRF1")
        self.assertEqual(detail["registros_datajud"][0]["payload_original"], record.payload)
        self.assertEqual(detail["extracoes_ia"], [])
        self.assertIsNone(detail["consulta_comunica"])

    def test_detail_rejects_invalid_number(self):
        with self.assertRaises(HTTPException) as raised:
            admin_process_detail("123", session=MagicMock())
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
