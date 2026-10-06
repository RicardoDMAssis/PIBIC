import argparse
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bpc_ingestion import api
from bpc_ingestion.cli import ipeaia_triage
from bpc_ingestion.config import Settings
from bpc_ingestion.database import make_engine
from bpc_ingestion.ipeaia import (RejectedIpeaResponse, finish_attempt, pending_processes,
                                  reserve_pending_processes, save_rejected_response)
from bpc_ingestion.models import Base, ExtracaoIa, Processo, RegistroDatajud, TentativaIa
from bpc_ingestion.portable import export_package, initialize


class PortableDatabaseTest(unittest.TestCase):
    @staticmethod
    def _create_candidate(engine) -> tuple[int, str]:
        number = "0000001-00.2021.4.01.3400"
        with Session(engine) as session:
            process = Processo(numero_processo=number)
            session.add(process)
            session.flush()
            process_id = process.id
            session.add(RegistroDatajud(
                processo_id=process.id, datajud_index="trf1", datajud_id="test",
                tribunal="TRF1", grau="JE", nivel_sigilo=0,
                payload={"orgaoJulgador": {"codigoMunicipioIBGE": 743}, "texto": "ação"},
                cursor_sort=[], coletado_em=datetime.now(timezone.utc),
            ))
            session.commit()
            return process_id, number

    def test_copy_api_filters_and_ai_persistence(self):
        source = make_engine("sqlite://")
        Base.metadata.create_all(source)
        _, number = self._create_candidate(source)
        try:
            with tempfile.TemporaryDirectory() as work:
                package = Path(work) / "base.sqlite.gz"
                target = Path(work) / "base.sqlite"
                counts = export_package(source, package)
                self.assertEqual(counts["processos"], 1)
                initialize(package, target)
                with self.assertRaises(ValueError):
                    initialize(package, target)
                url = "sqlite:///" + target.as_posix()
                db = make_engine(url)
                try:
                    sessions = sessionmaker(db)

                    def dependency():
                        with sessions() as session:
                            yield session

                    api.app.dependency_overrides[api.get_session] = dependency
                    with patch.object(api, "SessionLocal", sessions), TestClient(api.app) as client:
                        response = client.get("/resumo")
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()["totais"]["processos"], 1)
                        response = client.get("/admin/api/processos?municipio_codigo=743&numero=0000001")
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()["total"], 1)
                        self.assertEqual(client.get(f"/admin/api/processos/{number}").status_code, 200)
                    args = argparse.Namespace(
                        limit=1, model=None, max_movimentos=100, executar=True,
                        timeout=None, retry_rejeitadas=False,
                    )
                    settings = Settings(database_url=url, ipeaia_api_token="test")
                    rejected = RejectedIpeaResponse("evidencias[0].registro_id: inválido", {"choices": []})
                    diagnostics = Path(work) / "rejeitadas"
                    with patch("bpc_ingestion.cli.IpeaIaClient") as client, patch(
                        "bpc_ingestion.cli.save_rejected_response",
                        side_effect=lambda error, data, model, token: save_rejected_response(
                            error, data, model, token, diagnostics),
                    ):
                        client.return_value.token = "test"
                        client.return_value.classify.side_effect = rejected
                        self.assertEqual(ipeaia_triage(args, settings), 0)
                    self.assertEqual(len(list(diagnostics.glob("*.json"))), 1)
                    with Session(db) as session:
                        self.assertIsNone(session.scalar(select(ExtracaoIa)))
                        self.assertEqual(len(pending_processes(session, settings.ipeaia_model, 1)), 0)
                    args.retry_rejeitadas = True
                    with patch("bpc_ingestion.cli.IpeaIaClient") as client:
                        client.return_value.classify.return_value = {"desfecho": "indeterminado"}
                        ipeaia_triage(args, settings)
                    with Session(db) as session:
                        row = session.scalar(select(ExtracaoIa))
                        self.assertGreater(row.id, 0)
                        self.assertEqual(row.status_validacao, "pendente")
                finally:
                    api.app.dependency_overrides.clear()
                    db.dispose()
        finally:
            source.dispose()

    def test_attempt_states_require_explicit_retry_and_expired_lease_is_recovered(self):
        engine = make_engine("sqlite://")
        Base.metadata.create_all(engine)
        process_id, _ = self._create_candidate(engine)
        model = "modelo"
        try:
            with Session(engine) as session:
                reserved = reserve_pending_processes(session, model, 1, lease_seconds=60)
                self.assertEqual([item.id for item in reserved], [process_id])
                finish_attempt(session, process_id, model, "falhou", "timeout")
                session.commit()
            with Session(engine) as session:
                self.assertEqual(pending_processes(session, model, 1), [])
                self.assertEqual(
                    [item.id for item in pending_processes(session, model, 1, retry_failed=True)],
                    [process_id],
                )
            with Session(engine) as session:
                reserved = reserve_pending_processes(
                    session, model, 1, lease_seconds=60, retry_failed=True,
                )
                self.assertEqual([item.id for item in reserved], [process_id])
                finish_attempt(session, process_id, model, "rejeitada", "campo inválido")
                session.commit()
            with Session(engine) as session:
                self.assertEqual(pending_processes(session, model, 1), [])
                self.assertEqual(
                    [item.id for item in pending_processes(session, model, 1, retry_rejected=True)],
                    [process_id],
                )
                attempt = session.scalar(select(TentativaIa))
                attempt.status = "reservada"
                attempt.expira_em = datetime.now(timezone.utc) - timedelta(seconds=1)
                session.commit()
            with Session(engine) as session:
                self.assertEqual([item.id for item in pending_processes(session, model, 1)], [process_id])
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
