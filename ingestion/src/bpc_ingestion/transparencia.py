from __future__ import annotations

import json
import time
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .textutil import repair_text


def meses_no_periodo(inicial: int, final: int) -> list[int]:
    def parse(valor: int) -> date:
        ano, mes = divmod(valor, 100)
        if not 2010 <= ano <= 2100 or not 1 <= mes <= 12:
            raise ValueError("Mês deve estar no formato AAAAMM, entre 201001 e 210012")
        return date(ano, mes, 1)

    inicio, fim = parse(inicial), parse(final)
    if inicio > fim:
        raise ValueError("Mês inicial deve ser anterior ou igual ao final")
    meses = []
    ano, mes = inicio.year, inicio.month
    while (ano, mes) <= (fim.year, fim.month):
        meses.append(ano * 100 + mes)
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return meses


def normalizar_indicador(item: dict[str, Any], mes_ano: int, codigo_ibge: str) -> dict[str, Any]:
    municipio = item.get("municipio") or {}
    tipo = item.get("tipo") or {}
    if str(municipio.get("codigoIBGE")) != codigo_ibge:
        raise ValueError("Código IBGE da resposta difere da consulta")
    referencia = date.fromisoformat(str(item["dataReferencia"])[:10])
    if (referencia.year, referencia.month) != divmod(mes_ano, 100):
        raise ValueError("Mês de referência da resposta difere da consulta")
    if tipo.get("descricao") != "BPC":
        raise ValueError("Tipo inesperado na resposta de BPC")
    return {
        "fonte": "portal_transparencia",
        "mes_ano": mes_ano,
        "data_referencia": referencia,
        "codigo_ibge": codigo_ibge,
        "municipio_nome": repair_text(municipio.get("nomeIBGE")),
        "uf": (municipio.get("uf") or {}).get("sigla"),
        "tipo_id": int(tipo["id"]),
        "quantidade_beneficiados": int(item["quantidadeBeneficiados"]),
        "valor": str(item["valor"]),
        "payload": item,
    }


class TransparenciaClient:
    def __init__(
        self, base_url: str, token: str, timeout: float = 30,
        max_retries: int = 3, interval: float = 0.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.interval = interval
        self._last_request = 0.0

    def fetch_page(self, mes_ano: int, codigo_ibge: str, pagina: int) -> list[dict[str, Any]]:
        query = urlencode({"mesAno": mes_ano, "codigoIbge": codigo_ibge, "pagina": pagina})
        request = Request(
            f"{self.base_url}/bpc-por-municipio?{query}",
            headers={"chave-api-dados": self.token, "Accept": "application/json"},
        )
        for attempt in range(self.max_retries + 1):
            wait = self.interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                if not isinstance(payload, list):
                    raise RuntimeError("Resposta inesperada do Portal da Transparência")
                return payload
            except HTTPError as exc:
                if exc.code == 401:
                    raise RuntimeError("Token do Portal da Transparência inválido ou expirado") from exc
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.max_retries:
                    raise RuntimeError(f"Portal da Transparência retornou HTTP {exc.code}") from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            except (URLError, TimeoutError) as exc:
                if attempt == self.max_retries:
                    raise RuntimeError(f"Falha de rede no Portal da Transparência: {exc}") from exc
                delay = 2**attempt
            time.sleep(min(delay, 60))
        raise AssertionError("Retentativas esgotadas")
