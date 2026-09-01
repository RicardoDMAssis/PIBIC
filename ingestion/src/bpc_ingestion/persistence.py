from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pymongo.collection import Collection


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def garantir_indices(raw: "Collection", conteudo: "Collection") -> None:
    from pymongo import ASCENDING

    raw.create_index([("numero_processo", ASCENDING)], unique=True)
    raw.create_index([("assuntos.codigo", ASCENDING)])
    raw.create_index([("tribunal", ASCENDING)])
    conteudo.create_index([("numero_processo", ASCENDING)], unique=True)


def upsert_lote(collection: "Collection", documentos: Iterable[dict[str, Any]]) -> int:
    from pymongo import ReplaceOne

    operacoes = [
        ReplaceOne({"numero_processo": doc["numero_processo"]}, doc, upsert=True)
        for doc in documentos
    ]
    if not operacoes:
        return 0
    collection.bulk_write(operacoes, ordered=False)
    return len(operacoes)


def conectar(uri: str, database: str):
    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise RuntimeError(
            "Suporte a MongoDB não instalado; execute: pip install -e .[mongo]"
        ) from exc
    client = MongoClient(uri)
    client.admin.command("ping")
    db = client[database]
    garantir_indices(db.processos_raw, db.processos_conteudo)
    return client, db
