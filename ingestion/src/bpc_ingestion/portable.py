"""Copia completa dos dados da aplicacao para SQLite; execucao remota sem Docker."""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import URL
from dotenv import load_dotenv

from .database import make_engine
from .models import Base


SQLITE_VIEWS = {
    "vw_resumo_tribunais": """
        SELECT r.tribunal, COUNT(DISTINCT r.processo_id) AS processos,
        COUNT(DISTINCT r.id) AS registros_datajud, COUNT(DISTINCT m.id) AS movimentos,
        COUNT(DISTINCT c.id) AS comunicacoes_pje
        FROM registros_datajud r LEFT JOIN movimentos m ON m.registro_id=r.id
        LEFT JOIN comunicacoes_pje c ON c.processo_id=r.processo_id GROUP BY r.tribunal
    """,
    "vw_cobertura_comunica": """
        WITH universo AS (SELECT DISTINCT tribunal, processo_id FROM registros_datajud)
        SELECT u.tribunal, COUNT(*) AS processos, COUNT(q.processo_id) AS consultados,
        COUNT(*) FILTER (WHERE q.status='encontrado') AS encontrados,
        COUNT(*) FILTER (WHERE q.status='sem_resultado') AS sem_resultado,
        COUNT(*) FILTER (WHERE q.status LIKE 'erro%') AS erros,
        ROUND(100.0*COUNT(q.processo_id)/NULLIF(COUNT(*),0),2) AS cobertura_consulta_pct,
        ROUND(100.0*COUNT(*) FILTER (WHERE q.status='encontrado')/NULLIF(COUNT(q.processo_id),0),2) AS taxa_encontro_pct
        FROM universo u LEFT JOIN consultas_pje q ON q.processo_id=u.processo_id GROUP BY u.tribunal
    """,
    "vw_processos_analiticos": """
        SELECT r.id AS registro_id, p.numero_processo, r.tribunal, r.grau,
        r.classe_codigo, r.classe_nome, r.orgao_codigo, r.orgao_nome,
        r.data_ajuizamento, r.data_ultima_atualizacao,
        CAST(julianday(r.data_ultima_atualizacao)-julianday(r.data_ajuizamento) AS INTEGER) AS dias_ate_ultima_atualizacao,
        COUNT(DISTINCT m.id) AS quantidade_movimentos, MIN(m.data_hora) AS primeiro_movimento,
        MAX(m.data_hora) AS ultimo_movimento, COUNT(DISTINCT c.id) AS quantidade_comunicacoes,
        COALESCE(q.status,'nao_consultado') AS status_comunica
        FROM registros_datajud r JOIN processos p ON p.id=r.processo_id
        LEFT JOIN movimentos m ON m.registro_id=r.id
        LEFT JOIN comunicacoes_pje c ON c.processo_id=p.id
        LEFT JOIN consultas_pje q ON q.processo_id=p.id GROUP BY r.id,p.numero_processo,q.status
    """,
}


def copy_database(source, output: Path) -> dict[str, int]:
    if output.exists():
        raise ValueError(f"Arquivo ja existe: {output}. Escolha outro nome para preservar a copia anterior.")
    unknown = set(inspect(source).get_table_names()) - set(Base.metadata.tables) - {"alembic_version"}
    if unknown:
        raise ValueError(f"Tabelas nao previstas no contrato: {sorted(unknown)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    target = make_engine(URL.create("sqlite", database=str(output.resolve())))
    counts = {}
    try:
        Base.metadata.create_all(target)
        with source.connect() as read:
            if source.dialect.name == "postgresql":
                read = read.execution_options(isolation_level="REPEATABLE READ")
            with read.begin(), target.begin() as write:
                for table in Base.metadata.sorted_tables:
                    expected = read.scalar(select(func.count()).select_from(table))
                    for batch in read.execute(select(table).execution_options(stream_results=True)).mappings().partitions(1000):
                        rows = [dict(row) for row in batch]
                        if "embedding" in table.c:
                            for row in rows:
                                if hasattr(row.get("embedding"), "tolist"):
                                    row["embedding"] = row["embedding"].tolist()
                        write.execute(table.insert(), rows)
                    actual = write.scalar(select(func.count()).select_from(table))
                    if actual != expected:
                        raise RuntimeError(f"Contagem divergente na tabela {table.name}")
                    counts[table.name] = actual
                for name, sql in SQLITE_VIEWS.items():
                    write.execute(text(f"CREATE VIEW {name} AS {sql}"))
                if write.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
                    raise RuntimeError("Vinculos entre tabelas inconsistentes")
                if write.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok":
                    raise RuntimeError("SQLite falhou no teste de integridade")
        return counts
    finally:
        target.dispose()


def export_package(source, output: Path) -> dict[str, int]:
    if output.exists():
        raise ValueError(f"Pacote ja existe: {output}. Escolha outro nome.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bpc-sqlite-") as work:
        sqlite_file = Path(work) / "bpc.sqlite"
        counts = copy_database(source, sqlite_file)
        package_file = Path(work) / "bpc.sqlite.gz"
        with sqlite_file.open("rb") as raw, gzip.open(package_file, "wb", compresslevel=9) as compressed:
            shutil.copyfileobj(raw, compressed)
        shutil.copyfile(package_file, output)
    return counts


def initialize(package: Path, output: Path) -> None:
    if output.exists():
        raise ValueError(f"Banco ja existe: {output}. Ele foi preservado; nao inicialize novamente.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bpc-init-", dir=output.parent) as work:
        sqlite_file = Path(work) / "bpc.sqlite"
        with gzip.open(package, "rb") as compressed, sqlite_file.open("wb") as raw:
            shutil.copyfileobj(compressed, raw)
        engine = make_engine(URL.create("sqlite", database=str(sqlite_file.resolve())))
        try:
            with engine.connect() as connection:
                if connection.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok":
                    raise RuntimeError("Pacote SQLite inconsistente")
                if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
                    raise RuntimeError("Vinculos entre tabelas inconsistentes")
                count = connection.scalar(text("SELECT count(*) FROM processos"))
        finally:
            engine.dispose()
        shutil.copyfile(sqlite_file, output)
    print(f"Banco pronto: {output} ({count} processos)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Base portatil BPC sem Docker")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("exportar")
    export.add_argument("--output", type=Path, default=Path("transferencia/bpc-jud.sqlite.gz"))
    init = sub.add_parser("inicializar")
    init.add_argument("--package", type=Path, default=Path("transferencia/bpc-jud.sqlite.gz"))
    init.add_argument("--output", type=Path, default=Path("data/bpc-remote.sqlite"))
    args = parser.parse_args()
    if args.command == "inicializar":
        initialize(args.package, args.output)
        return
    load_dotenv(override=False)
    url = os.getenv("DATABASE_URL") or URL.create(
        "postgresql+psycopg", username=os.getenv("POSTGRES_USER", "bpc"),
        password=os.getenv("POSTGRES_PASSWORD", "bpc"), host="localhost",
        port=int(os.getenv("POSTGRES_PORT", "5432")), database=os.getenv("POSTGRES_DB", "bpc"),
    )
    source = make_engine(url)
    try:
        counts = export_package(source, args.output)
        for name, count in counts.items():
            print(f"{name}: {count}")
        print(f"Pacote: {args.output} ({args.output.stat().st_size / 1048576:.1f} MiB)")
    finally:
        source.dispose()


if __name__ == "__main__":
    main()
