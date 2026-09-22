from __future__ import annotations

import hashlib
import csv
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from .models import (
    Assunto,
    Coleta,
    ColetaRegistroDatajud,
    ComunicacaoPje,
    ConsultaPje,
    IndicadorBpcMunicipio,
    Movimento,
    Processo,
    RegistroAssunto,
    RegistroDatajud,
    RecursoExterno,
    ReferenciaTpu,
)
from .textutil import repair_text


def _datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    value = str(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value[:10], fmt).date()
        except ValueError:
            continue
    return None


class PostgresStore:
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def close(self) -> None:
        self.engine.dispose()

    def start_collection(
        self, source: str, partition: str | None, parameters: dict[str, Any]
    ) -> str:
        run_id = str(uuid.uuid4())
        with self.Session.begin() as session:
            session.add(
                Coleta(
                    id=uuid.UUID(run_id),
                    fonte=source,
                    particao=partition,
                    status="executando",
                    parametros=parameters,
                )
            )
        return run_id

    def finish_collection(
        self,
        run_id: str,
        status: str,
        records: int,
        raw_file: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.Session.begin() as session:
            row = session.get(Coleta, uuid.UUID(run_id))
            if row is None:
                return
            row.status = status
            row.registros = records
            row.arquivo_bruto = raw_file
            row.erro = error
            row.finalizado_em = datetime.now(timezone.utc)

    def upsert_datajud(self, documents: list[dict[str, Any]], run_id: str | None = None) -> int:
        if not documents:
            return 0
        numbers = sorted({doc["numero_processo"] for doc in documents})
        with self.Session.begin() as session:
            session.execute(
                insert(Processo)
                .values([{"numero_processo": number} for number in numbers])
                .on_conflict_do_nothing(index_elements=[Processo.numero_processo])
            )
            process_ids = dict(
                session.execute(
                    select(Processo.numero_processo, Processo.id).where(
                        Processo.numero_processo.in_(numbers)
                    )
                ).all()
            )
            for document in documents:
                record_id = self._upsert_record(session, document, process_ids[document["numero_processo"]])
                if run_id:
                    session.execute(
                        insert(ColetaRegistroDatajud)
                        .values(coleta_id=uuid.UUID(run_id), registro_id=record_id)
                        .on_conflict_do_nothing()
                    )
                self._replace_subjects(session, record_id, document.get("assuntos") or [])
                self._replace_movements(session, record_id, document.get("movimentacoes") or [])
        return len(documents)

    def upsert_external_resources(self, resources: list[dict[str, Any]]) -> int:
        with self.Session.begin() as session:
            for resource in resources:
                statement = insert(RecursoExterno).values(
                    fonte=resource["fonte"],
                    conjunto_id=resource["conjunto_id"],
                    conjunto_nome=resource.get("conjunto_nome"),
                    recurso_id=resource["recurso_id"],
                    nome=resource.get("nome"),
                    formato=resource.get("formato"),
                    url=resource["url"],
                    metadata_json=resource.get("metadata") or {},
                )
                session.execute(
                    statement.on_conflict_do_update(
                        constraint="uq_recurso_externo_fonte_id",
                        set_={
                            "conjunto_id": statement.excluded.conjunto_id,
                            "conjunto_nome": statement.excluded.conjunto_nome,
                            "nome": statement.excluded.nome,
                            "formato": statement.excluded.formato,
                            "url": statement.excluded.url,
                            "metadata_json": statement.excluded.metadata_json,
                            "atualizado_em": func.now(),
                        },
                    )
                )
        return len(resources)

    def upsert_bpc_municipio(self, indicators: list[dict[str, Any]], run_id: str) -> int:
        now = datetime.now(timezone.utc)
        with self.Session.begin() as session:
            for indicator in indicators:
                statement = insert(IndicadorBpcMunicipio).values(
                    **indicator,
                    coleta_id=uuid.UUID(run_id),
                    coletado_em=now,
                )
                session.execute(statement.on_conflict_do_update(
                    constraint="uq_indicador_bpc_municipio",
                    set_={
                        "data_referencia": statement.excluded.data_referencia,
                        "municipio_nome": statement.excluded.municipio_nome,
                        "uf": statement.excluded.uf,
                        "quantidade_beneficiados": statement.excluded.quantidade_beneficiados,
                        "valor": statement.excluded.valor,
                        "payload": statement.excluded.payload,
                        "coleta_id": statement.excluded.coleta_id,
                        "coletado_em": statement.excluded.coletado_em,
                    },
                ))
        return len(indicators)

    @staticmethod
    def _upsert_record(session: Session, document: dict[str, Any], process_id: int) -> int:
        classe = document.get("classe") or {}
        orgao = document.get("orgao_julgador") or {}
        values = {
            "processo_id": process_id,
            "datajud_index": document["datajud_index"],
            "datajud_id": document["datajud_id"],
            "tribunal": document.get("tribunal"),
            "grau": document.get("grau"),
            "classe_codigo": classe.get("codigo"),
            "classe_nome": classe.get("nome"),
            "orgao_codigo": orgao.get("codigo"),
            "orgao_nome": orgao.get("nome"),
            "nivel_sigilo": document.get("nivel_sigilo"),
            "data_ajuizamento": _datetime(document.get("data_ajuizamento")),
            "data_ultima_atualizacao": _datetime(document.get("data_ultima_atualizacao")),
            "cursor_sort": document.get("cursor_sort") or [],
            "payload": document.get("payload_original") or {},
            "coletado_em": _datetime(document.get("coletado_em")),
        }
        statement = insert(RegistroDatajud).values(**values)
        update_values = {key: statement.excluded[key] for key in values if key not in {"datajud_index", "datajud_id"}}
        return session.execute(
            statement.on_conflict_do_update(
                constraint="uq_datajud_index_id", set_=update_values
            ).returning(RegistroDatajud.id)
        ).scalar_one()

    @staticmethod
    def _replace_subjects(session: Session, record_id: int, subjects: list[dict[str, Any]]) -> None:
        session.execute(delete(RegistroAssunto).where(RegistroAssunto.registro_id == record_id))
        seen: set[int] = set()
        for subject in subjects:
            code = subject.get("codigo")
            if code is None or int(code) in seen:
                continue
            code = int(code)
            seen.add(code)
            statement = insert(Assunto).values(codigo=code, nome=subject.get("nome"))
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Assunto.codigo], set_={"nome": statement.excluded.nome}
                )
            )
            session.add(RegistroAssunto(registro_id=record_id, assunto_codigo=code))

    @staticmethod
    def _replace_movements(session: Session, record_id: int, movements: list[dict[str, Any]]) -> None:
        session.execute(delete(Movimento).where(Movimento.registro_id == record_id))
        session.add_all(
            Movimento(
                registro_id=record_id,
                sequencia=index,
                codigo=movement.get("codigo"),
                nome=movement.get("nome"),
                data_hora=_datetime(movement.get("data_hora")),
                complementos=movement.get("complementos") or [],
            )
            for index, movement in enumerate(movements)
        )

    def pending_pje_processes(self, limit: int, retry_errors: bool = False) -> list[str]:
        with self.Session() as session:
            eligible = ConsultaPje.processo_id.is_(None)
            if retry_errors:
                eligible = or_(eligible, ConsultaPje.status == "erro_temporario")
            statement = (
                select(Processo.numero_processo)
                .join(RegistroDatajud, RegistroDatajud.processo_id == Processo.id)
                .outerjoin(ConsultaPje, ConsultaPje.processo_id == Processo.id)
                .where(eligible, or_(RegistroDatajud.nivel_sigilo == 0, RegistroDatajud.nivel_sigilo.is_(None)))
                .distinct()
                .order_by(Processo.numero_processo)
                .limit(limit)
            )
            return list(session.scalars(statement))

    def save_pje_result(
        self,
        process_number: str,
        status: str,
        attempts: int,
        http_status: int | None,
        items: list[dict[str, Any]],
        error: str | None,
    ) -> int:
        now = datetime.now(timezone.utc)
        with self.Session.begin() as session:
            process_id = session.scalar(
                select(Processo.id).where(Processo.numero_processo == process_number)
            )
            if process_id is None:
                statement = insert(Processo).values(numero_processo=process_number).returning(Processo.id)
                process_id = session.execute(statement).scalar_one()
            query = insert(ConsultaPje).values(
                processo_id=process_id,
                status=status,
                tentativas=attempts,
                http_status=http_status,
                quantidade=len(items),
                erro=error,
                consultado_em=now,
            )
            session.execute(
                query.on_conflict_do_update(
                    index_elements=[ConsultaPje.processo_id],
                    set_={
                        "status": query.excluded.status,
                        "tentativas": query.excluded.tentativas,
                        "http_status": query.excluded.http_status,
                        "quantidade": query.excluded.quantidade,
                        "erro": query.excluded.erro,
                        "consultado_em": query.excluded.consultado_em,
                    },
                )
            )
            for item in items:
                canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                communication = insert(ComunicacaoPje).values(
                    processo_id=process_id,
                    comunica_id=str(item.get("id")) if item.get("id") is not None else None,
                    hash_conteudo=digest,
                    tribunal=repair_text(item.get("siglaTribunal")),
                    tipo_comunicacao=repair_text(item.get("tipoComunicacao")),
                    tipo_documento=repair_text(item.get("tipoDocumento")),
                    orgao_nome=repair_text(item.get("nomeOrgao")),
                    data_disponibilizacao=_date(
                        item.get("data_disponibilizacao") or item.get("datadisponibilizacao")
                    ),
                    texto=repair_text(item.get("texto")),
                    link=item.get("link"),
                    payload=item,
                    coletado_em=now,
                )
                session.execute(
                    communication.on_conflict_do_update(
                        constraint="uq_comunicacao_hash",
                        set_={
                            "payload": communication.excluded.payload,
                            "texto": communication.excluded.texto,
                            "link": communication.excluded.link,
                            "coletado_em": communication.excluded.coletado_em,
                        },
                    )
                )
        return len(items)

    def summary(self) -> dict[str, Any]:
        with self.Session() as session:
            totals = {
                "processos": session.scalar(select(func.count()).select_from(Processo)) or 0,
                "registros_datajud": session.scalar(select(func.count()).select_from(RegistroDatajud)) or 0,
                "movimentos": session.scalar(select(func.count()).select_from(Movimento)) or 0,
                "comunicacoes_pje": session.scalar(select(func.count()).select_from(ComunicacaoPje)) or 0,
                "recursos_externos": session.scalar(select(func.count()).select_from(RecursoExterno)) or 0,
            }
            coverage = dict(
                session.execute(
                    select(ConsultaPje.status, func.count()).group_by(ConsultaPje.status)
                ).all()
            )
            tribunals = [dict(row._mapping) for row in session.execute(text("SELECT * FROM vw_resumo_tribunais ORDER BY tribunal"))]
            return {"totais": totals, "cobertura_pje": coverage, "tribunais": tribunals}

    def import_tpu_directory(self, directory: str) -> dict[str, int]:
        from pathlib import Path

        root = Path(directory)
        files = {
            "assunto": root / "assuntos_tpu_nome_marcadores.csv",
            "movimento": root / "Movimentos_tpu_nome_marcadores.csv",
            "classe": root / "Classe_tpu_nome_marcadores.csv",
        }
        counts: dict[str, int] = {}
        with self.Session.begin() as session:
            for kind, path in files.items():
                if not path.exists():
                    raise ValueError(f"Arquivo TPU ausente: {path}")
                count = 0
                with path.open("r", encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream)
                    if not reader.fieldnames:
                        continue
                    code_field = reader.fieldnames[0]
                    parent_field = reader.fieldnames[1]
                    for row in reader:
                        if not row.get(code_field):
                            continue
                        segments = {
                            key: value
                            for key, value in row.items()
                            if key not in {code_field, parent_field, "nome"} and value
                        }
                        statement = insert(ReferenciaTpu).values(
                            tipo=kind,
                            codigo=int(row[code_field]),
                            codigo_pai=int(row[parent_field]) if row.get(parent_field) else None,
                            nome=repair_text(row.get("nome") or ""),
                            segmentos=segments,
                            fonte_arquivo=str(path),
                        )
                        session.execute(
                            statement.on_conflict_do_update(
                                index_elements=[ReferenciaTpu.tipo, ReferenciaTpu.codigo],
                                set_={
                                    "codigo_pai": statement.excluded.codigo_pai,
                                    "nome": statement.excluded.nome,
                                    "segmentos": statement.excluded.segmentos,
                                    "fonte_arquivo": statement.excluded.fonte_arquivo,
                                    "importado_em": func.now(),
                                },
                            )
                        )
                        count += 1
                counts[kind] = count
        return counts
