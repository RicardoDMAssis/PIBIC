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
from .ipeaia import IpeaIaClient, PROMPT_VERSION, load_process_input, pending_processes
from .models import ExtracaoIa, Processo
from .persistence import agora_iso
from .postgres_store import PostgresStore
from .sqlite_store import SqliteStore
from .transparencia import TransparenciaClient, meses_no_periodo, normalizar_indicador


LOGGER = logging.getLogger("bpc_ingestion")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipeline BPC: DataJud e Comunica PJe")
    commands = parser.add_subparsers(dest="command", required=True)

    datajud = commands.add_parser("datajud", help="Coleta processos BPC no DataJud")
    datajud.add_argument("--tribunais", nargs="+", default=list(TRIBUNAIS_PADRAO))
    datajud.add_argument("--page-size", type=int, default=200)
    datajud.add_argument(
        "--assuntos", nargs="+", type=int, default=list(ASSUNTOS_BPC),
        help="Subconjunto dos assuntos BPC 6114, 11946 e 11947",
    )
    datajud.add_argument("--max-records", type=int, help="Limite por tribunal para piloto")
    datajud.add_argument("--restart", action="store_true", help="Reinicia os cursores selecionados")
    datajud.add_argument("--source-mode", choices=("completo", "essencial"), default="completo")
    datajud.add_argument(
        "--municipio-codigos", nargs="+", type=int,
        help="Códigos de município do órgão julgador no DataJud (ex.: 743 para Brasília)",
    )
    datajud.add_argument("--graus", nargs="+", choices=("G1", "G2", "JE", "TR"))
    datajud.add_argument(
        "--ano-ajuizamento", type=int,
        help="Restringe a coleta a processos ajuizados neste ano; usa checkpoint separado",
    )
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
    transparencia = commands.add_parser(
        "transparencia-bpc", help="Coleta indicadores mensais agregados de BPC por município"
    )
    transparencia.add_argument("--municipios", nargs="+", required=True)
    transparencia.add_argument("--mes-inicial", type=int, required=True)
    transparencia.add_argument("--mes-final", type=int, required=True)
    transparencia.add_argument("--interval", type=float, default=0.5)
    commands.add_parser("ipeaia-modelos", help="Lista modelos disponíveis na API IpeaIA")
    triagem = commands.add_parser("ipeaia-triagem", help="Piloto de triagem BPC com revisão pendente")
    triagem.add_argument("--limit", type=int, default=5)
    triagem.add_argument("--model", help="ID do modelo; padrão IPEAIA_MODEL")
    triagem.add_argument("--max-movimentos", type=int, default=100)
    triagem.add_argument("--executar", action="store_true", help="Envia à API e grava; sem isto, só pré-visualiza")
    return parser


def _validate_tribunals(values: list[str]) -> list[str]:
    tribunals = [item.upper() for item in values]
    invalid = sorted(set(tribunals) - set(TRIBUNAIS_DATAJUD))
    if invalid:
        raise ValueError(f"Tribunais invalidos: {', '.join(invalid)}")
    return tribunals


def collect_datajud(args: argparse.Namespace, settings: Settings) -> int:
    tribunals = _validate_tribunals(args.tribunais)
    assuntos = sorted(set(args.assuntos))
    if not assuntos or set(assuntos) - set(ASSUNTOS_BPC):
        raise ValueError("Use apenas os assuntos BPC 6114, 11946 e 11947")
    if args.include_state_courts:
        tribunals = list(dict.fromkeys([*tribunals, *TRIBUNAIS_ESTADUAIS]))
    municipios = args.municipio_codigos or []
    graus = args.graus or []
    if any(code < 1 for code in municipios):
        raise ValueError("Códigos de município devem ser positivos")
    ano = args.ano_ajuizamento
    if ano is not None and not 1900 <= ano <= 2100:
        raise ValueError("Ano de ajuizamento deve estar entre 1900 e 2100")
    query_id = query_fingerprint(assuntos, args.source_mode, municipios, graus, ano)
    manifest = query_manifest(assuntos, args.source_mode, municipios, graus, ano)
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
                        "assuntos": assuntos,
                        "page_size": args.page_size,
                        "max_records": args.max_records,
                        "cursor_inicial": cursor,
                        "query_id": query_id,
                        "query_manifest": manifest,
                        "orgao_julgador_municipio_codigos": municipios,
                        "graus": graus,
                        "ano_ajuizamento": ano,
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
                        assuntos,
                        search_after=cursor,
                        max_records=args.max_records,
                        municipio_codigos=municipios,
                        graus=graus,
                        ano_ajuizamento=ano,
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


def collect_transparencia_bpc(args: argparse.Namespace, settings: Settings) -> int:
    municipios = list(dict.fromkeys(args.municipios))
    if not municipios or any(len(code) != 7 or not code.isdigit() for code in municipios):
        raise ValueError("Use códigos IBGE de município com 7 dígitos")
    meses = meses_no_periodo(args.mes_inicial, args.mes_final)
    if len(meses) * len(municipios) > 120:
        raise ValueError("Limite de 120 combinações município/mês por execução")
    if args.interval < 0:
        raise ValueError("Intervalo deve ser não negativo")
    client = TransparenciaClient(
        settings.transparencia_base_url,
        settings.require_transparencia_token(),
        interval=args.interval,
    )
    store = PostgresStore(settings.database_url)
    run_id = store.start_collection(
        "transparencia_bpc", "municipios",
        {"municipios": municipios, "mes_inicial": meses[0], "mes_final": meses[-1]},
    )
    total = 0
    raw_path: str | None = None
    try:
        with BronzeWriter(settings.raw_data_dir, "transparencia_bpc", "municipios", run_id) as bronze:
            raw_path = str(bronze.path)
            for codigo in municipios:
                for mes in meses:
                    pagina = 1
                    while True:
                        if pagina > 1000:
                            raise RuntimeError("Paginação da Transparência excedeu 1000 páginas")
                        items = client.fetch_page(mes, codigo, pagina)
                        bronze.write(items)
                        if not items:
                            break
                        indicators = [normalizar_indicador(item, mes, codigo) for item in items]
                        total += store.upsert_bpc_municipio(indicators, run_id)
                        LOGGER.info("BPC %s/%s página %d: %d registros", codigo, mes, pagina, len(items))
                        pagina += 1
        store.finish_collection(run_id, "concluida", total, raw_path)
    except Exception as exc:
        store.finish_collection(run_id, "falhou", total, raw_path, str(exc))
        raise
    finally:
        store.close()
    return 0


def ipeaia_models(settings: Settings) -> int:
    client = IpeaIaClient(settings.ipeaia_base_url, settings.require_ipeaia_token())
    for model in client.models():
        print(model)
    return 0


def ipeaia_triage(args: argparse.Namespace, settings: Settings) -> int:
    if not 1 <= args.limit <= 50:
        raise ValueError("Use --limit entre 1 e 50 no piloto")
    if args.max_movimentos < 2:
        raise ValueError("Use --max-movimentos de pelo menos 2")
    model = args.model or settings.ipeaia_model
    store = PostgresStore(settings.database_url)
    try:
        with store.Session() as session:
            processes = pending_processes(session, model, args.limit)
            inputs = [load_process_input(session, process, args.max_movimentos) for process in processes]
        LOGGER.info("Piloto IpeaIA: %d processos pendentes; modelo=%s, prompt=%s, executar=%s",
                    len(inputs), model, PROMPT_VERSION, args.executar)
        if not args.executar:
            for source in inputs:
                LOGGER.info("Prévia %s: %d registros, %d movimentações enviáveis",
                            source["numero_processo"], len(source["registros"]),
                            sum(len(item["movimentacoes"]) for item in source["registros"]))
            return 0
        client = IpeaIaClient(settings.ipeaia_base_url, settings.require_ipeaia_token())
        for source in inputs:
            result = client.classify(model, source)
            with store.Session.begin() as session:
                target = session.query(Processo).filter_by(numero_processo=source["numero_processo"]).one()
                session.add(ExtracaoIa(
                    processo_id=target.id,
                    tipo_extracao="triagem_bpc",
                    modelo=model,
                    versao_prompt=PROMPT_VERSION,
                    resultado=result,
                    status_validacao="pendente",
                ))
            LOGGER.info("Triagem pendente de revisão gravada: %s", source["numero_processo"])
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
    if args.command == "transparencia-bpc":
        return collect_transparencia_bpc(args, settings)
    if args.command == "ipeaia-modelos":
        return ipeaia_models(settings)
    if args.command == "ipeaia-triagem":
        return ipeaia_triage(args, settings)
    raise AssertionError(f"Comando inesperado: {args.command}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return executar()
    except (ValueError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2
