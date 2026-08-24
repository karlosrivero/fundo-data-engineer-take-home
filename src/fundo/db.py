from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb
import psycopg
from psycopg.rows import dict_row


@contextmanager
def source_connection(dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        yield connection


def warehouse_connection(path: Path, schema_path: Path) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path))
    connection.execute(schema_path.read_text(encoding="utf-8"))
    return connection

