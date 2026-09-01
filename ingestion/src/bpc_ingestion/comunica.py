from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class PjeResult:
    status: str
    items: list[dict[str, Any]]
    attempts: int
    http_status: int | None
    error: str | None
    raw_pages: list[dict[str, Any]]


class ComunicaPjeClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 120,
        max_retries: int = 5,
        request_interval: float = 0.5,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_interval = request_interval
        self._last_request = 0.0

    @staticmethod
    def _digits(number: str) -> str:
        digits = "".join(char for char in number if char.isdigit())
        if len(digits) != 20:
            raise ValueError(f"Numero CNJ invalido: {number!r}")
        return digits

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        self._last_request = time.monotonic()

    def fetch_process(self, process_number: str) -> PjeResult:
        number = self._digits(process_number)
        all_items: list[dict[str, Any]] = []
        raw_pages: list[dict[str, Any]] = []
        attempts = 0
        page = 1
        last_http: int | None = None
        with httpx.Client(
            timeout=self.timeout,
            headers={"Accept": "application/json", "User-Agent": "bpc-jud-pibic/0.2"},
        ) as client:
            while True:
                response: httpx.Response | None = None
                for retry in range(self.max_retries):
                    attempts += 1
                    self._throttle()
                    try:
                        response = client.get(
                            self.base_url,
                            params={"numeroProcesso": number, "pagina": page, "itensPorPagina": 100},
                        )
                        last_http = response.status_code
                        if response.status_code == 403:
                            return PjeResult("bloqueado", [], attempts, 403, "HTTP 403", raw_pages)
                        if response.status_code == 404:
                            return PjeResult("sem_resultado", [], attempts, 404, None, raw_pages)
                        if response.status_code == 429 or response.status_code >= 500:
                            wait = min(float(response.headers.get("Retry-After", 2**retry)), 120)
                            time.sleep(max(wait, 1))
                            continue
                        response.raise_for_status()
                        break
                    except (httpx.TimeoutException, httpx.NetworkError) as exc:
                        if retry + 1 == self.max_retries:
                            return PjeResult(
                                "erro_temporario", [], attempts, last_http, str(exc), raw_pages
                            )
                        time.sleep(min(2**retry, 30))
                    except httpx.HTTPStatusError as exc:
                        return PjeResult(
                            "erro_permanente", [], attempts, exc.response.status_code,
                            str(exc), raw_pages
                        )
                else:
                    return PjeResult(
                        "erro_temporario", [], attempts, last_http,
                        "Limite de tentativas excedido", raw_pages
                    )

                if response is None:
                    return PjeResult("erro_temporario", [], attempts, last_http, "Sem resposta", raw_pages)
                payload = response.json()
                raw_pages.append(payload)
                if payload.get("status") not in (None, "success"):
                    return PjeResult(
                        "erro_permanente", [], attempts, response.status_code,
                        f"Resposta inesperada: {payload.get('status')}", raw_pages
                    )
                items = payload.get("items") or []
                if not isinstance(items, list):
                    return PjeResult(
                        "erro_permanente", [], attempts, response.status_code,
                        "Campo items nao e uma lista", raw_pages
                    )
                all_items.extend(items)
                expected = int(payload.get("count") or len(all_items))
                if not items or len(all_items) >= expected:
                    status = "encontrado" if all_items else "sem_resultado"
                    return PjeResult(status, all_items, attempts, response.status_code, None, raw_pages)
                page += 1
