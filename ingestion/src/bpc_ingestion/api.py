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
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    Assunto,
    ComunicacaoPje,
    ConsultaPje,
    Movimento,
    Processo,
    ReferenciaTpu,
    RegistroAssunto,
    RegistroDatajud,
    RecursoExterno,
    TarefaPainel,
)


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://bpc:bpc@localhost:5432/bpc"
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
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
    page_size: Annotated[int, Field(ge=10, le=1000)] = 50
    max_records: Annotated[int | None, Field(ge=1, le=1_000_000)] = 100
    restart: bool = False
    source_mode: Literal["completo", "essencial"] = "completo"
    include_state_courts: bool = False


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
    }
    pje_status = dict(
        session.execute(select(ConsultaPje.status, func.count()).group_by(ConsultaPje.status)).all()
    )
    tribunals = [
        dict(row._mapping)
        for row in session.execute(text("SELECT * FROM vw_resumo_tribunais ORDER BY tribunal"))
    ]
    return {"totais": totals, "cobertura_pje": pje_status, "tribunais": tribunals}


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
        "--page-size",
        str(payload.page_size),
    ]
    if payload.max_records is not None:
        args.extend(["--max-records", str(payload.max_records)])
    if payload.restart:
        args.append("--restart")
    args.extend(["--source-mode", payload.source_mode])
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
