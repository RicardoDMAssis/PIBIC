from __future__ import annotations

import json
import hashlib
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .textutil import repair_text


SOURCE_FIELDS = (
    "numeroProcesso",
    "tribunal",
    "grau",
    "classe",
    "assuntos",
    "orgaoJulgador",
    "dataAjuizamento",
    "dataHoraUltimaAtualizacao",
    "@timestamp",
    "nivelSigilo",
    "sistema",
    "formato",
    "prioridade",
    "movimentos",
)

QUERY_VERSION = "datajud-bpc-v2"


def query_manifest(
    assuntos: Sequence[int], source_mode: str, municipio_codigos: Sequence[int] = (),
    graus: Sequence[str] = (), ano_ajuizamento: int | None = None,
) -> dict[str, Any]:
    if source_mode not in {"completo", "essencial"}:
        raise ValueError("source_mode deve ser 'completo' ou 'essencial'")
    manifest = {
        "versao": QUERY_VERSION,
        "assuntos": sorted(int(code) for code in assuntos),
        "source_mode": source_mode,
        "source_fields": None if source_mode == "completo" else list(SOURCE_FIELDS),
        "sort": ["@timestamp:asc", "id.keyword:asc"],
    }
    if municipio_codigos:
        manifest["orgao_julgador_municipio_codigos"] = sorted(set(int(code) for code in municipio_codigos))
    if graus:
        manifest["graus"] = sorted(set(graus))
    if ano_ajuizamento is not None:
        manifest["ano_ajuizamento"] = ano_ajuizamento
    return manifest


def query_fingerprint(
    assuntos: Sequence[int], source_mode: str, municipio_codigos: Sequence[int] = (),
    graus: Sequence[str] = (), ano_ajuizamento: int | None = None,
) -> str:
    canonical = json.dumps(
        query_manifest(assuntos, source_mode, municipio_codigos, graus, ano_ajuizamento),
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class SearchHit:
    index: str
    document_id: str
    source: dict[str, Any]
    sort: list[Any]

    def raw_document(self) -> dict[str, Any]:
        return {
            "_index": self.index,
            "_id": self.document_id,
            "_source": self.source,
            "sort": self.sort,
        }


@dataclass(frozen=True)
class SearchPage:
    hits: list[SearchHit]
    next_search_after: list[Any]

    @property
    def sources(self) -> list[dict[str, Any]]:
        """Compatibilidade com consumidores antigos."""
        return [hit.source for hit in self.hits]


def formatar_numero_processo(numero: str) -> str:
    digitos = "".join(c for c in str(numero) if c.isdigit())
    if len(digitos) != 20:
        raise ValueError(f"Número CNJ inválido: {numero!r}")
    return (
        f"{digitos[:7]}-{digitos[7:9]}.{digitos[9:13]}."
        f"{digitos[13]}.{digitos[14:16]}.{digitos[16:]}"
    )


def normalizar_data(valor: Any) -> str | None:
    if valor in (None, ""):
        return None
    texto = str(valor)
    if texto.isdigit() and len(texto) in (8, 14):
        formato = "%Y%m%d" if len(texto) == 8 else "%Y%m%d%H%M%S"
        data = datetime.strptime(texto, formato).replace(tzinfo=timezone.utc)
    else:
        data = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        if data.tzinfo is None:
            data = data.replace(tzinfo=timezone.utc)
        data = data.astimezone(timezone.utc)
    return data.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalizar_complemento(complemento: dict[str, Any]) -> dict[str, Any]:
    return {
        "codigo": complemento.get("codigo"),
        "nome": repair_text(complemento.get("nome")),
        "descricao": repair_text(complemento.get("descricao")),
        "valor": repair_text(complemento.get("valor")),
    }


def normalizar_processo(source: dict[str, Any], coletado_em: str) -> dict[str, Any]:
    assuntos = [
        {"codigo": assunto.get("codigo"), "nome": repair_text(assunto.get("nome"))}
        for assunto in source.get("assuntos", [])
    ]
    movimentos = []
    for movimento in source.get("movimentos", []):
        movimentos.append(
            {
                "codigo": movimento.get("codigo"),
                "nome": repair_text(movimento.get("nome")),
                "data_hora": normalizar_data(movimento.get("dataHora")),
                "complementos": [
                    _normalizar_complemento(item)
                    for item in movimento.get("complementosTabelados", [])
                ],
            }
        )

    orgao = source.get("orgaoJulgador") or {}
    classe = source.get("classe") or {}
    return {
        "numero_processo": formatar_numero_processo(source["numeroProcesso"]),
        "tribunal": repair_text(source.get("tribunal")),
        "grau": repair_text(source.get("grau")),
        "classe": {"codigo": classe.get("codigo"), "nome": repair_text(classe.get("nome"))},
        "assuntos": assuntos,
        "orgao_julgador": {"codigo": orgao.get("codigo"), "nome": repair_text(orgao.get("nome"))},
        "nivel_sigilo": source.get("nivelSigilo"),
        "data_ajuizamento": normalizar_data(source.get("dataAjuizamento")),
        "data_ultima_atualizacao": normalizar_data(
            source.get("dataHoraUltimaAtualizacao") or source.get("@timestamp")
        ),
        "movimentacoes": movimentos,
        "fonte": "datajud",
        "coletado_em": coletado_em,
    }


def normalizar_hit(hit: SearchHit, coletado_em: str) -> dict[str, Any]:
    processo = normalizar_processo(hit.source, coletado_em)
    processo.update(
        {
            "datajud_index": hit.index,
            "datajud_id": hit.document_id,
            "cursor_sort": hit.sort,
            "payload_original": hit.source,
        }
    )
    return processo


class DatajudClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        page_size: int = 1000,
        timeout: float = 60,
        max_retries: int = 4,
        source_mode: str = "completo",
    ) -> None:
        if not 10 <= page_size <= 10_000:
            raise ValueError("page_size deve estar entre 10 e 10000")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.page_size = page_size
        self.timeout = timeout
        self.max_retries = max_retries
        query_manifest((), source_mode)
        self.source_mode = source_mode

    def _search(self, tribunal: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/api_publica_{tribunal.lower()}/_search"
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"APIKey {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.max_retries:
                    raise RuntimeError(f"Datajud retornou HTTP {exc.code} para {tribunal}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt == self.max_retries:
                    reason = getattr(exc, "reason", exc)
                    raise RuntimeError(f"Falha de rede ao consultar {tribunal}: {reason}") from exc
            time.sleep(min(2**attempt, 30))
        raise AssertionError("loop de retentativas terminou inesperadamente")

    def iter_pages(
        self,
        tribunal: str,
        assuntos: Sequence[int],
        search_after: Sequence[Any] | None = None,
        max_records: int | None = None,
        municipio_codigos: Sequence[int] = (),
        graus: Sequence[str] = (),
        ano_ajuizamento: int | None = None,
    ) -> Iterator[SearchPage]:
        cursor = list(search_after) if search_after is not None else None
        emitted = 0
        while True:
            remaining = None if max_records is None else max_records - emitted
            if remaining is not None and remaining <= 0:
                return
            subject_query: dict[str, Any] = {
                "terms": {"assuntos.codigo": list(assuntos)}
            }
            filters = [subject_query]
            if municipio_codigos:
                filters.append({"terms": {"orgaoJulgador.codigoMunicipioIBGE": list(municipio_codigos)}})
            if graus:
                filters.append({"terms": {"grau.keyword": list(graus)}})
            if ano_ajuizamento is not None:
                filters.append({"range": {"dataAjuizamento": {
                    "gte": f"{ano_ajuizamento}0101000000",
                    "lt": f"{ano_ajuizamento + 1}0101000000",
                }}})
            query = {"bool": {"must": filters}} if len(filters) > 1 else subject_query
            body: dict[str, Any] = {
                "size": self.page_size if remaining is None else min(self.page_size, remaining),
                "query": query,
                "sort": [
                    {"@timestamp": {"order": "asc"}},
                    {"id.keyword": {"order": "asc"}},
                ],
            }
            if self.source_mode == "essencial":
                body["_source"] = list(SOURCE_FIELDS)
            if cursor is not None:
                body["search_after"] = cursor
            response = self._search(tribunal, body)
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                return
            next_search_after = hits[-1].get("sort")
            if not next_search_after:
                raise RuntimeError("Resposta do Datajud sem cursor 'sort' para search_after")
            if next_search_after == cursor:
                raise RuntimeError("Cursor search_after não avançou")
            search_hits = [
                SearchHit(
                    index=str(hit.get("_index", "")),
                    document_id=str(hit.get("_id", "")),
                    source=hit["_source"],
                    sort=list(hit.get("sort") or []),
                )
                for hit in hits
            ]
            emitted += len(search_hits)
            yield SearchPage(hits=search_hits, next_search_after=next_search_after)
            cursor = next_search_after

    def iter_hits(
        self,
        tribunal: str,
        assuntos: Sequence[int],
        max_records: int | None = None,
        search_after: Sequence[Any] | None = None,
        municipio_codigos: Sequence[int] = (),
        graus: Sequence[str] = (),
        ano_ajuizamento: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        for page in self.iter_pages(
            tribunal,
            assuntos,
            search_after=search_after,
            max_records=max_records,
            municipio_codigos=municipio_codigos,
            graus=graus,
            ano_ajuizamento=ano_ajuizamento,
        ):
            yield from page.sources
