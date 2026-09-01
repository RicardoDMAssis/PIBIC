from __future__ import annotations

from typing import Any


def _texto_movimentacoes(movimentacoes: list[dict[str, Any]]) -> str:
    linhas: list[str] = []
    for movimento in movimentacoes:
        linha = f"{movimento.get('data_hora') or ''} | {movimento.get('codigo')} | {movimento.get('nome') or ''}"
        complementos = movimento.get("complementos") or []
        if complementos:
            detalhes = "; ".join(
                f"{item.get('descricao') or item.get('codigo')}: {item.get('nome') or item.get('valor')}"
                for item in complementos
            )
            linha += f" | {detalhes}"
        linhas.append(linha)
    return "\n".join(linhas)


def criar_conteudo_de_movimentacoes(
    processo: dict[str, Any], coletado_em: str
) -> dict[str, Any]:
    movimentacoes = processo.get("movimentacoes") or []
    datas = [m["data_hora"] for m in movimentacoes if m.get("data_hora")]
    return {
        "numero_processo": processo["numero_processo"],
        "fonte": "datajud_movimentacoes",
        "peca": {
            "tipo": "movimentacoes",
            "texto_bruto": _texto_movimentacoes(movimentacoes),
            "url_documento": None,
            "data": max(datas) if datas else processo.get("data_ultima_atualizacao"),
        },
        "coletado_em": coletado_em,
    }

