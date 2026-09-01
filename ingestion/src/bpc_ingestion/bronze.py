from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


class BronzeWriter:
    """Grava respostas imutaveis em NDJSON gzip para auditoria e reprocessamento."""

    def __init__(self, root: str | Path, source: str, partition: str, run_id: str):
        day = datetime.now(timezone.utc).date().isoformat()
        self.path = Path(root) / source / partition.lower() / day / f"{run_id}.ndjson.gz"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO | None = None

    def __enter__(self) -> "BronzeWriter":
        self._file = gzip.open(self.path, "at", encoding="utf-8")
        return self

    def write(self, document: dict[str, Any]) -> None:
        if self._file is None:
            raise RuntimeError("BronzeWriter precisa ser usado como context manager")
        self._file.write(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
        self._file.write("\n")
        self._file.flush()

    def write_many(self, documents: list[dict[str, Any]]) -> None:
        for document in documents:
            self.write(document)

    def __exit__(self, *_: object) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
