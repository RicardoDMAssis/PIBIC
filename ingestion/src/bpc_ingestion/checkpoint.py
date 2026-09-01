from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class CheckpointStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Checkpoint inválido em {self.path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Checkpoint inválido em {self.path}")
        return value

    @staticmethod
    def _key(tribunal: str, query_id: str | None) -> str:
        return f"{query_id}:{tribunal.upper()}" if query_id else tribunal.upper()

    def get(self, tribunal: str, query_id: str | None = None) -> list[Any] | None:
        value = self._read().get(self._key(tribunal, query_id))
        if value is None:
            return None
        if not isinstance(value, list):
            raise RuntimeError(f"Cursor inválido para {tribunal} em {self.path}")
        return value

    def save(
        self, tribunal: str, search_after: list[Any], query_id: str | None = None
    ) -> None:
        state = self._read()
        state[self._key(tribunal, query_id)] = search_after
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, self.path)

    def clear(self, tribunal: str, query_id: str | None = None) -> None:
        state = self._read()
        if state.pop(self._key(tribunal, query_id), None) is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, self.path)
