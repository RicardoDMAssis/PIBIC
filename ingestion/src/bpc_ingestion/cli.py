from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from pathlib import Path

from .bronze import BronzeWriter
from .checkpoint import CheckpointStore
from .comunica import ComunicaPjeClient
from .config import (
    ASSUNTOS_BPC, TRIBUNAIS_DATAJUD, TRIBUNAIS_ESTADUAIS, TRIBUNAIS_PADRAO, Settings,
)
from .datajud import (
    DatajudClient, normalizar_hit, normalizar_processo, query_fingerprint, query_manifest,
)
from .inss import InssCatalogClient
from .persistence import agora_iso
from .postgres_store import PostgresStore
from .sqlite_store import SqliteStore


LOGGER = logging.getLogger("bpc_ingestion")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipeline BPC: DataJud e Comunica PJe")
    commands = parser.add_subparsers(dest="command", required=True)

    datajud = commands.add_parser("datajud", help="Coleta processos BPC no DataJud")
    datajud.add_argument("--tribunais", nargs="+", default=list(TRIBUNAIS_PADRAO))
    datajud.add_argument("--page-size", type=int, default=200)
    datajud.add_argument("--max-records", type=int, help="Limite por tribunal para piloto")
    datajud.add_argument("--restart", action="store_true", help="Reinicia os cursores selecionados")
    datajud.add_argument("--source-mode", choices=("completo", "essencial"), default="completo")
    datajud.add_argument("--include-state-courts", action="store_true")
    datajud.add_argument("--storage", choices=("postgres", "sqlite"), default="postgres")
    datajud.add_argument("--sqlite-path", default="data/bpc_analytics.sqlite3")

    comunica = commands.add_parser(
        "comunica", help="Busca publicacoes no Comunica PJe pelos processos coletados"
    )
    comunica.add_argument("--limit", type=int, default=100)
    comunica.add_argument("--numero", nargs="+", help="Numeros CNJ especificos")
    comunica.add_argument("--retry-errors", action="store_true")
    comunica.add_argument("--interval", type=float, default=0.5)

    commands.add_parser("resumo", help="Exibe contagens e cobertura da base")
    tpu = commands.add_parser("importar-tpu", help="Importa tabelas TPU legadas do CNJ")
    tpu.add_argument("--diretorio", default="/app/resources/tpu")
    inss = commands.add_parser("catalogar-inss", help="Cataloga recursos oficiais do INSS")
    inss.add_argument("--query", default="beneficios")
    inss.add_argument("--rows", type=int, default=100)
    return parser


def _validate_tribunals(values: list[str]) -> list[str]:
    tribunals = [item.upper() for item in values]
    invalid = sorted(set(tribunals) - set(TRIBUNAIS_DATAJUD))
    if invalid:
        raise ValueError(f"Tribunais invalidos: {', '.join(invalid)}")
    return tribunals


def collect_datajud(args: argparse.Namespace, settings: Settings) -> int:
    tribunals = _validate_tribunals(args.tribunais)
    if args.include_state_courts:
        tribunals = list(dict.fromkeys([*tribunals, *TRIBUNAIS_ESTADUAIS]))
    query_id = query_fingerprint(ASSUNTOS_BPC, args.source_mode)
    manifest = query_manifest(ASSUNTOS_BPC, args.source_mode)
    client = DatajudClient(
        settings.datajud_base_url,
        settings.require_datajud_key(),
        page_size=args.page_size,
        source_mode=args.source_mode,
    )
    checkpoints = CheckpointStore(settings.checkpoint_file)
    postgres = PostgresStore(settings.database_url) if args.storage == "postgres" else None
    sqlite = SqliteStore(Path(args.sqlite_path)) if args.storage == "sqlite" else None
    try:
        for tribunal in tribunals:
            if args.restart:
                checkpoints.clear(tribunal, query_id)
            cursor = checkpoints.get(tribunal, query_id)
            run_id = (
                postgres.start_collection(
                    "datajud",
                    tribunal,
                    {
                        "assuntos": list(ASSUNTOS_BPC),
                        "page_size": args.page_size,
                        "max_records": args.max_records,
                        "cursor_inicial": cursor,
                        "query_id": query_id,
                        "query_manifest": manifest,
                    },
                )
                if postgres
                else f"sqlite-{tribunal.lower()}"
            )
            total = 0
            raw_path: str | None = None
            try:
                with BronzeWriter(settings.raw_data_dir, "datajud", tribunal, run_id) as bronze:
                    raw_path = str(bronze.path)
                    for page in client.iter_pages(
                        tribunal,
                        ASSUNTOS_BPC,
                        search_after=cursor,
                        max_records=args.max_records,
                    ):
                        collected_at = agora_iso()
                        bronze.write_many([hit.raw_document() for hit in page.hits])
                        if postgres:
                            total += postgres.upsert_datajud(
                                [normalizar_hit(hit, collected_at) for hit in page.hits], run_id
                            )
                        else:
                            total += sqlite.upsert_raw(  # type: ignore[union-attr]
                                [normalizar_processo(hit.source, collected_at) for hit in page.hits]
                            )
                        checkpoints.save(tribunal, page.next_search_after, query_id)
                        LOGGER.info("%s: %d registros persistidos", tribunal, total)
                if postgres:
                    postgres.finish_collection(run_id, "concluida", total, raw_path)
            except Exception as exc:
                if postgres:
                    postgres.finish_collection(run_id, "falhou", total, raw_path, str(exc))
                raise
    finally:
        if postgres:
            postgres.close()
        if sqlite:
            sqlite.close()
    return 0


def collect_comunica(args: argparse.Namespace, settings: Settings) -> int:
    store = PostgresStore(settings.database_url)
    numbers = args.numero or store.pending_pje_processes(args.limit, args.retry_errors)
    if not numbers:
        LOGGER.info("Nenhum processo pendente para consultar")
        store.close()
        return 0
    client = ComunicaPjeClient(settings.comunica_base_url, request_interval=args.interval)
    run_id = store.start_collection(
        "comunica_pje", "processos", {"limit": args.limit, "quantidade": len(numbers)}
    )
    total = 0
    raw_path: str | None = None
    try:
        with BronzeWriter(settings.raw_data_dir, "comunica_pje", "processos", run_id) as bronze:
            raw_path = str(bronze.path)
            for index, number in enumerate(numbers, start=1):
                result = client.fetch_process(number)
                bronze.write(
                    {
                        "numero_processo": number,
                        "status": result.status,
                        "http_status": result.http_status,
                        "paginas": result.raw_pages,
                    }
                )
                total += store.save_pje_result(
                    number,
                    result.status,
                    result.attempts,
                    result.http_status,
                    result.items,
                    result.error,
                )
                LOGGER.info(
                    "%d/%d %s: %s (%d comunicacoes)",
                    index, len(numbers), number, result.status, len(result.items),
                )
        store.finish_collection(run_id, "concluida", total, raw_path)
    except Exception as exc:
        store.finish_collection(run_id, "falhou", total, raw_path, str(exc))
        raise
    finally:
        store.close()
    return 0


def show_summary(settings: Settings) -> int:
    store = PostgresStore(settings.database_url)
    try:
        print(json.dumps(store.summary(), ensure_ascii=False, indent=2, default=str))
    finally:
        store.close()
    return 0


def import_tpu(args: argparse.Namespace, settings: Settings) -> int:
    store = PostgresStore(settings.database_url)
    try:
        print(json.dumps(store.import_tpu_directory(args.diretorio), ensure_ascii=False, indent=2))
    finally:
        store.close()
    return 0


def catalog_inss(args: argparse.Namespace, settings: Settings) -> int:
    store = PostgresStore(settings.database_url)
    run_id = store.start_collection(
        "inss_catalogo", args.query, {"query": args.query, "rows": args.rows}
    )
    try:
        client = InssCatalogClient(settings.inss_catalog_api_url)
        resources = client.resources(client.search(args.query, args.rows))
        total = store.upsert_external_resources(resources)
        store.finish_collection(run_id, "concluida", total)
        LOGGER.info("INSS: %d recursos oficiais catalogados", total)
    except Exception as exc:
        store.finish_collection(run_id, "falhou", 0, error=str(exc))
        raise RuntimeError(f"Falha ao consultar catalogo oficial do INSS: {exc}") from exc
    finally:
        store.close()
    return 0


def executar(argv: Sequence[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    settings = Settings.from_env()
    if args.command == "datajud":
        return collect_datajud(args, settings)
    if args.command == "comunica":
        return collect_comunica(args, settings)
    if args.command == "resumo":
        return show_summary(settings)
    if args.command == "importar-tpu":
        return import_tpu(args, settings)
    if args.command == "catalogar-inss":
        return catalog_inss(args, settings)
    raise AssertionError(f"Comando inesperado: {args.command}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return executar()
    except (ValueError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2
