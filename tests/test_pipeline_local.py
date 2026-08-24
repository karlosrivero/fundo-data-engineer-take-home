from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import fundo.pipeline as pipeline_module
from fundo.config import Settings
from fundo.logging import configure_logging
from fundo.pipeline import InjectedFailure, Pipeline, warehouse_digest


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeSource:
    """Small read-only PostgreSQL-shaped adapter for local transaction tests."""

    def __init__(self):
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        self.tables = {
            "customers": [
                {"customer_id": 1, "government_id": "AR-1", "first_name": "Ana", "last_name": "Rivera", "birth_date": date(1988, 4, 10), "email": "ana@example.com", "phone": "+541155501001", "is_test": False, "created_at": ts, "updated_at": ts},
                {"customer_id": 2, "government_id": " ar 1 ", "first_name": "Ana", "last_name": "Rivera", "birth_date": date(1988, 4, 10), "email": "ANA@example.com", "phone": "+541155501002", "is_test": False, "created_at": ts, "updated_at": ts},
            ],
            "advances": [
                {"advance_id": 10, "customer_id": 2, "status": "funded", "amount_cents": 1000, "created_at": ts, "updated_at": ts}
            ],
            "cards": [
                {"card_id": "card-1", "customer_id": 1, "token": "tok", "last_four": "1111", "status": "active", "created_at": ts, "updated_at": ts}
            ],
            "transactions": [
                {"transaction_id": 100, "advance_id": 10, "transaction_type": "disbursement", "amount_cents": 1000, "occurred_at": ts, "updated_at": ts}
            ],
            "advance_status_history": [
                {"history_id": 1, "advance_id": 10, "status": "funded", "changed_at": ts}
            ],
        }

    def execute(self, query: str, params=None):
        normalized = " ".join(query.split())
        max_match = re.fullmatch(r"SELECT max\((\w+)\) AS bound FROM (\w+)", normalized)
        if max_match:
            column, table = max_match.groups()
            return Result([{"bound": max(row[column] for row in self.tables[table])}])

        select_match = re.match(r"SELECT (.+?) FROM (\w+)", normalized)
        if not select_match:
            raise AssertionError(f"unsupported fake-source query: {normalized}")
        selected, table = select_match.groups()
        rows = list(self.tables[table])
        if " WHERE " in normalized:
            cursor = re.search(r"WHERE (\w+) >", normalized).group(1)
            lower, upper = params
            rows = [row for row in rows if lower < row[cursor] <= upper]
        columns = [column.strip() for column in selected.split(",")]
        return Result([{column: row[column] for column in columns} for row in rows])


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    root = Path(__file__).parents[1]
    return Settings(
        source_dsn="fake",
        warehouse_path=tmp_path / "pipeline.duckdb",
        metadata_path=root / "config" / "metadata.yml",
        warehouse_schema_path=root / "sql" / "warehouse" / "001_schema.sql",
        environment="test",
    )


def test_full_pipeline_is_idempotent_and_atomic(monkeypatch, settings: Settings):
    source = FakeSource()

    @contextmanager
    def fake_connection(_dsn):
        yield source

    monkeypatch.setattr(pipeline_module, "source_connection", fake_connection)
    pipeline = Pipeline(settings, configure_logging())

    first = pipeline.run(check_quality=True)
    digest = warehouse_digest(settings)
    second = pipeline.run(check_quality=True)

    assert sum(item.extracted for item in first.tables.values()) == 6
    assert sum(item.extracted for item in second.tables.values()) == 0
    assert warehouse_digest(settings) == digest

    with pytest.raises(InjectedFailure):
        pipeline.run(fail_after="customers")
    assert warehouse_digest(settings) == digest

