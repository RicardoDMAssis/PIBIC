from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class SqliteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processos_raw (
                    numero_processo TEXT PRIMARY KEY,
                    tribunal TEXT,
                    assuntos_codigos TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_processos_raw_tribunal "
                "ON processos_raw (tribunal)"
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processos_conteudo (
                    numero_processo TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _json(documento: dict[str, Any]) -> str:
        return json.dumps(documento, ensure_ascii=False, separators=(",", ":"))

    def upsert_raw(self, documentos: Iterable[dict[str, Any]]) -> int:
        rows = []
        for documento in documentos:
            assuntos = ",".join(
                str(item.get("codigo")) for item in documento.get("assuntos", [])
            )
            rows.append(
                (
                    documento["numero_processo"],
                    documento.get("tribunal"),
                    assuntos,
                    self._json(documento),
                )
            )
        if not rows:
            return 0
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO processos_raw
                    (numero_processo, tribunal, assuntos_codigos, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(numero_processo) DO UPDATE SET
                    tribunal=excluded.tribunal,
                    assuntos_codigos=excluded.assuntos_codigos,
                    payload_json=excluded.payload_json
                """,
                rows,
            )
        return len(rows)

    def upsert_conteudo(self, documentos: Iterable[dict[str, Any]]) -> int:
        rows = [
            (documento["numero_processo"], self._json(documento))
            for documento in documentos
        ]
        if not rows:
            return 0
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO processos_conteudo (numero_processo, payload_json)
                VALUES (?, ?)
                ON CONFLICT(numero_processo) DO UPDATE SET
                    payload_json=excluded.payload_json
                """,
                rows,
            )
        return len(rows)

    def close(self) -> None:
        self.connection.close()
