from __future__ import annotations

import os
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker
from dotenv import load_dotenv
from .database import make_engine

from .models import (
    Assunto,
    ComunicacaoPje,
    ConsultaPje,
    DocumentoChunk,
    ExtracaoIa,
    Movimento,
    Processo,
    ReferenciaTpu,
    RegistroAssunto,
    RegistroDatajud,
    RecursoExterno,
    TarefaPainel,
)


load_dotenv(override=False)
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://bpc:bpc@localhost:5432/bpc"
)
engine = make_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
STATIC_DIR = Path(__file__).parent / "static"
Tribunal = Literal["TRF1", "TRF2", "TRF3", "TRF4", "TRF5", "TRF6", "STJ"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    with SessionLocal.begin() as session:
        session.execute(
            update(TarefaPainel)
            .where(TarefaPainel.status.in_(["na_fila", "executando"]))
            .values(
                status="interrompida",
                finalizado_em=datetime.now(timezone.utc),
                log=TarefaPainel.log + "\n[PAINEL] A API reiniciou durante a tarefa.\n",
            )
        )
    yield


app = FastAPI(title="BPC Jud API", version="0.4.0", lifespan=lifespan)


class DatajudTaskRequest(BaseModel):
    tribunais: list[Tribunal] = Field(default_factory=lambda: ["TRF1"])
    assuntos: list[Literal[6114, 11946, 11947]] = Field(
        default_factory=lambda: [6114, 11946, 11947], min_length=1
    )
    page_size: Annotated[int, Field(ge=10, le=1000)] = 50
    max_records: Annotated[int | None, Field(ge=1, le=1_000_000)] = 100
    restart: bool = False
    source_mode: Literal["completo", "essencial"] = "completo"
    include_state_courts: bool = False
    municipio_codigos: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list, max_length=100)
    graus: list[Literal["G1", "G2", "JE", "TR"]] = Field(default_factory=list)


class ComunicaTaskRequest(BaseModel):
    limit: Annotated[int, Field(ge=1, le=10_000)] = 100
    retry_errors: bool = False


def get_session():
    with SessionLocal() as session:
        yield session


def _task_dict(task: TarefaPainel, include_log: bool = True) -> dict[str, Any]:
    value = {
        "id": str(task.id),
        "tipo": task.tipo,
        "status": task.status,
        "parametros": task.parametros,
        "comando": task.comando,
        "codigo_saida": task.codigo_saida,
        "criado_em": task.criado_em,
        "iniciado_em": task.iniciado_em,
        "finalizado_em": task.finalizado_em,
    }
    if include_log:
        value["log"] = task.log
    return value


def _append_log(job_id: uuid.UUID, line: str) -> None:
    with SessionLocal.begin() as session:
        task = session.get(TarefaPainel, job_id)
        if task is not None:
            task.log = (task.log or "") + line


def _run_task(job_id: uuid.UUID, command: list[str]) -> None:
    with SessionLocal.begin() as session:
        task = session.get(TarefaPainel, job_id)
        if task is None:
            return
        task.status = "executando"
        task.iniciado_em = datetime.now(timezone.utc)
        task.log = (task.log or "") + "[PAINEL] Tarefa iniciada.\n"

    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    exit_code = -1
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
        )
        if process.stdout:
            for line in process.stdout:
                _append_log(job_id, line)
        exit_code = process.wait()
    except Exception as exc:  # pragma: no cover - protecao operacional
        _append_log(job_id, f"[PAINEL] Falha ao iniciar tarefa: {exc}\n")

    with SessionLocal.begin() as session:
        task = session.get(TarefaPainel, job_id)
        if task is not None:
            task.codigo_saida = exit_code
            task.status = "concluida" if exit_code == 0 else "falhou"
            task.finalizado_em = datetime.now(timezone.utc)
            task.log = (task.log or "") + f"[PAINEL] Tarefa finalizada (codigo {exit_code}).\n"


def _schedule_task(
    session: Session,
    background: BackgroundTasks,
    task_type: str,
    parameters: dict[str, Any],
    cli_args: list[str],
) -> dict[str, Any]:
    active = session.scalar(
        select(func.count())
        .select_from(TarefaPainel)
        .where(TarefaPainel.status.in_(["na_fila", "executando"]))
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail="Ja existe uma tarefa em execucao. Aguarde a conclusao.",
        )
    command = [sys.executable, "-m", "bpc_ingestion", *cli_args]
    task = TarefaPainel(
        id=uuid.uuid4(),
        tipo=task_type,
        status="na_fila",
        parametros=parameters,
        comando=command,
        log="[PAINEL] Tarefa criada e aguardando execucao.\n",
    )
    session.add(task)
    session.commit()
    background.add_task(_run_task, task.id, command)
    return _task_dict(task)


@app.get("/", include_in_schema=False)
@app.get("/painel", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin/processos", include_in_schema=False)
def process_admin() -> FileResponse:
    return FileResponse(STATIC_DIR / "processos.html")


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/resumo")
def summary(session: Session = Depends(get_session)) -> dict[str, Any]:
    totals = {
        "processos": session.scalar(select(func.count()).select_from(Processo)) or 0,
        "registros_datajud": session.scalar(select(func.count()).select_from(RegistroDatajud)) or 0,
        "movimentos": session.scalar(select(func.count()).select_from(Movimento)) or 0,
        "comunicacoes_pje": session.scalar(select(func.count()).select_from(ComunicacaoPje)) or 0,
        "referencias_tpu": session.scalar(select(func.count()).select_from(ReferenciaTpu)) or 0,
        "recursos_externos": session.scalar(select(func.count()).select_from(RecursoExterno)) or 0,
        "extracoes_ia": session.scalar(select(func.count()).select_from(ExtracaoIa)) or 0,
        "documento_chunks": session.scalar(select(func.count()).select_from(DocumentoChunk)) or 0,
    }
    pje_status = dict(
        session.execute(select(ConsultaPje.status, func.count()).group_by(ConsultaPje.status)).all()
    )
    tribunals = [
        dict(row._mapping)
        for row in session.execute(text("SELECT * FROM vw_resumo_tribunais ORDER BY tribunal"))
    ]
    return {"totais": totals, "cobertura_pje": pje_status, "tribunais": tribunals}


@app.get("/admin/api/processos")
def admin_list_processes(
    numero: str | None = Query(default=None, max_length=25),
    tribunal: str | None = Query(default=None, max_length=20),
    municipio_codigo: int | None = Query(default=None, ge=1),
    grau: Literal["G1", "G2", "JE", "TR"] | None = None,
    com_comunicacao: bool | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    filters = []
    if numero:
        digits = "".join(c for c in numero if c.isdigit())
        if not digits:
            raise HTTPException(status_code=400, detail="Informe ao menos um dígito do número CNJ")
        if len(digits) == 20:
            formatted = f"{digits[:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:]}"
            filters.append(Processo.numero_processo == formatted)
        else:
            filters.append(func.regexp_replace(Processo.numero_processo, r"\D", "", "g").like(f"{digits}%"))
    record_filters = [RegistroDatajud.processo_id == Processo.id]
    if tribunal:
        record_filters.append(RegistroDatajud.tribunal == tribunal.upper())
    if municipio_codigo is not None:
        record_filters.append(
            func.jsonb_extract_path_text(
                RegistroDatajud.payload, "orgaoJulgador", "codigoMunicipioIBGE"
            ) == str(municipio_codigo)
        )
    if grau:
        record_filters.append(RegistroDatajud.grau == grau)
    if len(record_filters) > 1:
        filters.append(
            exists(select(RegistroDatajud.id).where(*record_filters))
        )
    if com_comunicacao is not None:
        has_communication = exists(select(ComunicacaoPje.id).where(ComunicacaoPje.processo_id == Processo.id))
        filters.append(has_communication if com_comunicacao else ~has_communication)

    total = session.scalar(select(func.count()).select_from(Processo).where(*filters)) or 0
    processes = list(session.scalars(
        select(Processo).where(*filters).order_by(Processo.numero_processo).limit(limit).offset(offset)
    ))
    ids = [process.id for process in processes]
    if not ids:
        return {"total": total, "limit": limit, "offset": offset, "items": []}
    tribunal_names = func.string_agg(func.distinct(RegistroDatajud.tribunal), ", ")
    if session.get_bind().dialect.name == "sqlite":
        tribunal_names = func.replace(func.group_concat(func.distinct(RegistroDatajud.tribunal)), ",", ", ")
    records = session.execute(
        select(
            RegistroDatajud.processo_id,
            func.count(RegistroDatajud.id),
            tribunal_names,
            func.max(RegistroDatajud.data_ultima_atualizacao),
        )
        .where(RegistroDatajud.processo_id.in_(ids))
        .group_by(RegistroDatajud.processo_id)
    ).all()
    record_map = {row[0]: row for row in records}
    communication_map = dict(session.execute(
        select(ComunicacaoPje.processo_id, func.count(ComunicacaoPje.id))
        .where(ComunicacaoPje.processo_id.in_(ids)).group_by(ComunicacaoPje.processo_id)
    ).all())
    extraction_map = dict(session.execute(
        select(ExtracaoIa.processo_id, func.count(ExtracaoIa.id))
        .where(ExtracaoIa.processo_id.in_(ids)).group_by(ExtracaoIa.processo_id)
    ).all())
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "numero_processo": process.numero_processo,
                "tribunais": record_map[process.id][2] if process.id in record_map else None,
                "registros_datajud": record_map[process.id][1] if process.id in record_map else 0,
                "ultima_atualizacao_datajud": record_map[process.id][3] if process.id in record_map else None,
                "comunicacoes_pje": communication_map.get(process.id, 0),
                "extracoes_ia": extraction_map.get(process.id, 0),
            }
            for process in processes
        ],
    }


@app.get("/admin/api/processos/{numero_processo}")
def admin_process_detail(
    numero_processo: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    digits = "".join(c for c in numero_processo if c.isdigit())
    if len(digits) != 20:
        raise HTTPException(status_code=400, detail="Informe os 20 dígitos do número CNJ")
    formatted = f"{digits[:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:]}"
    process = session.scalar(select(Processo).where(Processo.numero_processo == formatted))
    if process is None:
        raise HTTPException(status_code=404, detail="Processo não encontrado")
    records = list(session.scalars(
        select(RegistroDatajud).where(RegistroDatajud.processo_id == process.id)
        .order_by(RegistroDatajud.tribunal, RegistroDatajud.grau, RegistroDatajud.id)
    ))
    record_ids = [record.id for record in records]
    subjects: dict[int, list[dict[str, Any]]] = {record_id: [] for record_id in record_ids}
    movements: dict[int, list[dict[str, Any]]] = {record_id: [] for record_id in record_ids}
    if record_ids:
        for record_id, code, name in session.execute(
            select(RegistroAssunto.registro_id, Assunto.codigo, Assunto.nome)
            .join(Assunto, Assunto.codigo == RegistroAssunto.assunto_codigo)
            .where(RegistroAssunto.registro_id.in_(record_ids))
            .order_by(Assunto.codigo)
        ):
            subjects[record_id].append({"codigo": code, "nome": name})
        for movement in session.scalars(
            select(Movimento).where(Movimento.registro_id.in_(record_ids))
            .order_by(Movimento.registro_id, Movimento.sequencia)
        ):
            movements[movement.registro_id].append({
                "codigo": movement.codigo,
                "nome": movement.nome,
                "data_hora": movement.data_hora,
                "complementos": movement.complementos,
            })
    communications = list(session.scalars(
        select(ComunicacaoPje).where(ComunicacaoPje.processo_id == process.id)
        .order_by(ComunicacaoPje.data_disponibilizacao.desc().nullslast(), ComunicacaoPje.id.desc())
    ))
    consultation = session.get(ConsultaPje, process.id)
    extractions = list(session.scalars(
        select(ExtracaoIa).where(ExtracaoIa.processo_id == process.id)
        .order_by(ExtracaoIa.criado_em.desc())
    ))
    chunks = list(session.scalars(
        select(DocumentoChunk).where(DocumentoChunk.processo_id == process.id)
        .order_by(DocumentoChunk.comunicacao_id, DocumentoChunk.numero_chunk)
    ))
    return {
        "numero_processo": process.numero_processo,
        "registros_datajud": [
            {
                "id": record.id,
                "tribunal": record.tribunal,
                "grau": record.grau,
                "classe": {"codigo": record.classe_codigo, "nome": record.classe_nome},
                "orgao_julgador": {"codigo": record.orgao_codigo, "nome": record.orgao_nome},
                "nivel_sigilo": record.nivel_sigilo,
                "data_ajuizamento": record.data_ajuizamento,
                "data_ultima_atualizacao": record.data_ultima_atualizacao,
                "coletado_em": record.coletado_em,
                "assuntos": subjects[record.id],
                "movimentacoes": movements[record.id],
                "payload_original": record.payload,
            }
            for record in records
        ],
        "consulta_comunica": {
            "status": consultation.status,
            "consultado_em": consultation.consultado_em,
            "quantidade": consultation.quantidade,
            "erro": consultation.erro,
        } if consultation else None,
        "comunicacoes_pje": [
            {
                "id": item.id,
                "tipo_comunicacao": item.tipo_comunicacao,
                "tipo_documento": item.tipo_documento,
                "orgao_nome": item.orgao_nome,
                "data_disponibilizacao": item.data_disponibilizacao,
                "texto": item.texto,
                "link": item.link,
                "payload_original": item.payload,
            }
            for item in communications
        ],
        "extracoes_ia": [
            {
                "tipo_extracao": item.tipo_extracao,
                "modelo": item.modelo,
                "versao_prompt": item.versao_prompt,
                "resultado": item.resultado,
                "confianca": item.confianca,
                "status_validacao": item.status_validacao,
                "criado_em": item.criado_em,
            }
            for item in extractions
        ],
        "documento_chunks": [
            {
                "comunicacao_id": item.comunicacao_id,
                "numero_chunk": item.numero_chunk,
                "texto": item.texto,
                "modelo_embedding": item.modelo_embedding,
                "versao_pipeline": item.versao_pipeline,
            }
            for item in chunks
        ],
    }


@app.post("/tarefas/datajud", status_code=202)
def start_datajud_task(
    payload: DatajudTaskRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    args = [
        "datajud",
        "--tribunais",
        *payload.tribunais,
        "--assuntos",
        *(str(code) for code in payload.assuntos),
        "--page-size",
        str(payload.page_size),
    ]
    if payload.max_records is not None:
        args.extend(["--max-records", str(payload.max_records)])
    if payload.restart:
        args.append("--restart")
    args.extend(["--source-mode", payload.source_mode])
    if payload.municipio_codigos:
        args.extend(["--municipio-codigos", *(str(code) for code in payload.municipio_codigos)])
    if payload.graus:
        args.extend(["--graus", *payload.graus])
    if payload.include_state_courts:
        args.append("--include-state-courts")
    return _schedule_task(session, background, "datajud", payload.model_dump(), args)


@app.post("/tarefas/comunica", status_code=202)
def start_comunica_task(
    payload: ComunicaTaskRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    args = ["comunica", "--limit", str(payload.limit)]
    if payload.retry_errors:
        args.append("--retry-errors")
    return _schedule_task(session, background, "comunica_pje", payload.model_dump(), args)


@app.post("/tarefas/importar-tpu", status_code=202)
def start_tpu_task(
    background: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _schedule_task(session, background, "tpu", {}, ["importar-tpu"])


@app.post("/tarefas/catalogar-inss", status_code=202)
def start_inss_catalog_task(
    background: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _schedule_task(
        session, background, "inss_catalogo", {"query": "beneficios"}, ["catalogar-inss"]
    )


@app.get("/fontes/inss")
def list_inss_resources(
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            RecursoExterno.conjunto_nome,
            RecursoExterno.nome,
            RecursoExterno.formato,
            RecursoExterno.url,
            RecursoExterno.atualizado_em,
        )
        .where(RecursoExterno.fonte == "inss")
        .order_by(RecursoExterno.conjunto_nome, RecursoExterno.nome)
        .limit(limit)
    )
    return [dict(row._mapping) for row in rows]


@app.get("/tarefas")
def list_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    tasks = list(
        session.scalars(select(TarefaPainel).order_by(TarefaPainel.criado_em.desc()).limit(limit))
    )
    return [_task_dict(task, include_log=False) for task in tasks]


@app.get("/tarefas/{task_id}")
def task_detail(task_id: uuid.UUID, session: Session = Depends(get_session)) -> dict[str, Any]:
    task = session.get(TarefaPainel, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada")
    return _task_dict(task)


@app.get("/processos")
def list_processes(
    tribunal: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    statement = (
        select(
            Processo.numero_processo,
            RegistroDatajud.tribunal,
            RegistroDatajud.grau,
            RegistroDatajud.classe_codigo,
            RegistroDatajud.classe_nome,
            RegistroDatajud.data_ajuizamento,
            RegistroDatajud.data_ultima_atualizacao,
        )
        .join(RegistroDatajud, RegistroDatajud.processo_id == Processo.id)
        .order_by(Processo.numero_processo, RegistroDatajud.grau)
        .limit(limit)
        .offset(offset)
    )
    if tribunal:
        statement = statement.where(RegistroDatajud.tribunal == tribunal.upper())
    return [dict(row._mapping) for row in session.execute(statement)]


@app.get("/analises/cobertura-comunica")
def pje_coverage(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [
        dict(row._mapping)
        for row in session.execute(text("SELECT * FROM vw_cobertura_comunica ORDER BY tribunal"))
    ]


@app.get("/analises/assuntos-relacionados")
def related_subjects(
    limit: int = Query(default=20, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    seed_codes = (6114, 11946, 11947)
    bpc_records = (
        select(RegistroAssunto.registro_id)
        .where(RegistroAssunto.assunto_codigo.in_(seed_codes))
        .distinct()
        .subquery()
    )
    statement = (
        select(
            RegistroAssunto.assunto_codigo.label("codigo"),
            Assunto.nome,
            func.count(func.distinct(RegistroAssunto.registro_id)).label("registros"),
        )
        .join(Assunto, Assunto.codigo == RegistroAssunto.assunto_codigo)
        .where(
            RegistroAssunto.registro_id.in_(select(bpc_records.c.registro_id)),
            RegistroAssunto.assunto_codigo.not_in(seed_codes),
        )
        .group_by(RegistroAssunto.assunto_codigo, Assunto.nome)
        .order_by(text("registros DESC"), RegistroAssunto.assunto_codigo)
        .limit(limit)
    )
    return [dict(row._mapping) for row in session.execute(statement)]


@app.get("/processos/{numero_processo}")
def process_detail(
    numero_processo: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    process = session.scalar(select(Processo).where(Processo.numero_processo == numero_processo))
    if process is None:
        raise HTTPException(status_code=404, detail="Processo nao encontrado")
    records = list(
        session.scalars(select(RegistroDatajud).where(RegistroDatajud.processo_id == process.id))
    )
    communications = list(
        session.scalars(select(ComunicacaoPje).where(ComunicacaoPje.processo_id == process.id))
    )
    return {
        "numero_processo": process.numero_processo,
        "registros_datajud": [record.payload for record in records],
        "comunicacoes_pje": [communication.payload for communication in communications],
    }
