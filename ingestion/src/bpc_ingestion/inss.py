from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class InssCatalogClient:
    """Cliente do catalogo CKAN oficial de dados abertos do INSS."""

    def __init__(self, base_url: str, timeout: float = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def search(self, query: str = "beneficios", rows: int = 100) -> list[dict[str, Any]]:
        url = f"{self.base_url}/package_search?{urlencode({'q': query, 'rows': rows})}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "bpc-jud/0.4"})
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.load(response)
        if not payload.get("success"):
            raise RuntimeError("Catalogo do INSS retornou uma resposta sem sucesso")
        return list((payload.get("result") or {}).get("results") or [])

    @staticmethod
    def resources(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for package in packages:
            package_id = str(package.get("id") or package.get("name") or "")
            for resource in package.get("resources") or []:
                resource_id = str(resource.get("id") or resource.get("url") or "")
                if not package_id or not resource_id or not resource.get("url"):
                    continue
                output.append(
                    {
                        "fonte": "inss",
                        "conjunto_id": package_id,
                        "conjunto_nome": package.get("title") or package.get("name"),
                        "recurso_id": resource_id,
                        "nome": resource.get("name") or resource.get("description"),
                        "formato": resource.get("format"),
                        "url": resource["url"],
                        "metadata": {"conjunto": package, "recurso": resource},
                    }
                )
        return output
