from __future__ import annotations

import json
import re

from sqlalchemy import create_engine, event


def make_engine(url, **kwargs):
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def setup_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")

            def json_path(value, *keys):
                if value is None:
                    return None
                data = json.loads(value)
                for key in keys:
                    if not isinstance(data, dict):
                        return None
                    data = data.get(key)
                return None if data is None else str(data)

            connection.create_function("jsonb_extract_path_text", -1, json_path)
            connection.create_function(
                "regexp_replace", 4,
                lambda value, pattern, replacement, flags: None if value is None else re.sub(
                    pattern, replacement, value, count=0 if "g" in flags else 1
                ),
            )
    return engine
