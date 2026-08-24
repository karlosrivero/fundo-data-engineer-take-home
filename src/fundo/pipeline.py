from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import duckdb
import psycopg
import yaml

from . import __version__
from .config import Settings
from .db import source_connection, warehouse_connection
from .identity import rebuild_customer_master
from .logging import log
from .quality import DQResult, persist_results, print_results, run_checks
from .tables import TABLES, TableSpec


class PipelineError(RuntimeError):
    pass


class InjectedFailure(PipelineError):
    pass


class QualityFailure(PipelineError):
    def __init__(self, results: list[DQResult]):
        self.results = results
        super().__init__("one or more blocking data-quality checks failed")


@dataclass(frozen=True)
class TableMetrics:
    extracted: int
    upserted: int
    deleted: int
    bytes_read_estimate: int
    source_keys_scanned: int
    upper_bound: str


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    tables: dict[str, TableMetrics]
    identity: dict[str, int]
    quality: list[DQResult]


class Pipeline:
    def __init__(self, settings: Settings, logger: logging.Logger):
        self.settings = settings
        self.logger = logger

    def run(self, *, check_quality: bool = False, fail_after: str | None = None) -> RunSummary:
        run_id = str(uuid4())
        started = _now()
        warehouse = warehouse_connection(self.settings.warehouse_path, self.settings.warehouse_schema_path)
        self._record_run_start(warehouse, run_id, started)
        metrics: dict[str, TableMetrics] = {}
        identity_metrics: dict[str, int] = {}
        quality_results: list[DQResult] = []
        log(self.logger, logging.INFO, "pipeline_started", run_id=run_id, version=__version__)
        try:
            with source_connection(self.settings.source_dsn) as source:
                warehouse.execute("BEGIN TRANSACTION")
                self._load_governance_metadata(warehouse, started)
                for spec in TABLES:
                    table_metrics = self._sync_table(source, warehouse, spec, run_id, started)
                    metrics[spec.source] = table_metrics
                    self._record_table_metrics(warehouse, run_id, spec, table_metrics, started)
                    log(
                        self.logger,
                        logging.INFO,
                        "table_loaded",
                        run_id=run_id,
                        table=spec.source,
                        extracted=table_metrics.extracted,
                        deleted=table_metrics.deleted,
                        source_keys_scanned=table_metrics.source_keys_scanned,
                        strategy=spec.strategy,
                    )
                    if fail_after == spec.source:
                        raise InjectedFailure(f"deliberate failure after {spec.source}")

                identity_metrics = rebuild_customer_master(warehouse, run_id, started)
                self._record_identity_metrics(warehouse, run_id, identity_metrics, started)
                if check_quality:
                    quality_results = run_checks(source, warehouse)
                    persist_results(warehouse, run_id, quality_results, started)
                    if any(result.status == "FAIL" for result in quality_results):
                        raise QualityFailure(quality_results)

                finished = _now()
                warehouse.execute(
                    "UPDATE pipeline_runs SET status='SUCCESS', finished_at=? WHERE run_id=?",
                    [finished, run_id],
                )
                warehouse.execute("COMMIT")
        except Exception as exc:
            try:
                warehouse.execute("ROLLBACK")
            except duckdb.TransactionException:
                pass
            if isinstance(exc, QualityFailure):
                # Keep the evidence even though the candidate data state was rejected.
                persist_results(warehouse, run_id, exc.results, _now())
            self._record_run_failure(warehouse, run_id, exc)
            log(self.logger, logging.ERROR, "pipeline_failed", run_id=run_id, error=str(exc))
            raise
        finally:
            warehouse.close()

        log(self.logger, logging.INFO, "pipeline_succeeded", run_id=run_id, tables=len(metrics))
        return RunSummary(run_id, "SUCCESS", metrics, identity_metrics, quality_results)

    def quality(self, run_id: str | None = None, *, persist: bool = True) -> list[DQResult]:
        check_id = run_id or f"quality-{uuid4()}"
        warehouse = warehouse_connection(self.settings.warehouse_path, self.settings.warehouse_schema_path)
        try:
            with source_connection(self.settings.source_dsn) as source:
                results = run_checks(source, warehouse)
            if persist:
                persist_results(warehouse, check_id, results, _now())
            return results
        finally:
            warehouse.close()

    def _sync_table(
        self,
        source: psycopg.Connection,
        warehouse: duckdb.DuckDBPyConnection,
        spec: TableSpec,
        run_id: str,
        loaded_at: datetime,
    ) -> TableMetrics:
        watermark = self._watermark(warehouse, spec)
        bound_row = source.execute(f"SELECT max({spec.cursor_column}) AS bound FROM {spec.source}").fetchone()
        upper_bound = bound_row["bound"]
        if upper_bound is None:
            upper_bound = 0 if spec.cursor_type == "integer" else datetime(1970, 1, 1, tzinfo=timezone.utc)

        select_columns = ", ".join(spec.columns)
        rows = source.execute(
            f"SELECT {select_columns} FROM {spec.source} WHERE {spec.cursor_column} > %s AND {spec.cursor_column} <= %s ORDER BY {spec.cursor_column}, {spec.primary_key}",
            [watermark, upper_bound],
        ).fetchall()
        if rows:
            placeholders = ", ".join("?" for _ in range(len(spec.columns) + 2))
            warehouse.executemany(
                f"INSERT OR REPLACE INTO {spec.target} VALUES ({placeholders})",
                [[row[column] for column in spec.columns] + [loaded_at, run_id] for row in rows],
            )

        deleted = 0
        keys_scanned = 0
        if spec.reconcile_deletes:
            source_keys = [row[spec.primary_key] for row in source.execute(f"SELECT {spec.primary_key} FROM {spec.source}").fetchall()]
            keys_scanned = len(source_keys)
            target_keys = [row[0] for row in warehouse.execute(f"SELECT {spec.primary_key} FROM {spec.target}").fetchall()]
            stale_keys = sorted(set(target_keys) - set(source_keys), key=str)
            if stale_keys:
                warehouse.executemany(
                    f"DELETE FROM {spec.target} WHERE {spec.primary_key} = ?",
                    [[key] for key in stale_keys],
                )
                deleted = len(stale_keys)

        cursor_value = str(upper_bound.isoformat() if hasattr(upper_bound, "isoformat") else upper_bound)
        warehouse.execute(
            """INSERT OR REPLACE INTO watermarks
               VALUES (?, ?, ?, ?, ?)""",
            [spec.source, spec.cursor_column, cursor_value, loaded_at, run_id],
        )
        estimated_bytes = sum(sum(len(str(value).encode("utf-8")) for value in row.values()) for row in rows)
        return TableMetrics(len(rows), len(rows), deleted, estimated_bytes, keys_scanned, cursor_value)

    def _watermark(self, warehouse: duckdb.DuckDBPyConnection, spec: TableSpec) -> Any:
        row = warehouse.execute(
            "SELECT cursor_value FROM watermarks WHERE source_table = ?", [spec.source]
        ).fetchone()
        if not row:
            return 0 if spec.cursor_type == "integer" else datetime(1970, 1, 1, tzinfo=timezone.utc)
        return int(row[0]) if spec.cursor_type == "integer" else datetime.fromisoformat(row[0])

    def _record_run_start(self, con: duckdb.DuckDBPyConnection, run_id: str, started: datetime) -> None:
        con.execute(
            "INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, NULL, 'RUNNING', NULL)",
            [run_id, "fundo_incremental", __version__, _git_commit(), self.settings.environment, started],
        )

    def _record_run_failure(self, con: duckdb.DuckDBPyConnection, run_id: str, exc: Exception) -> None:
        con.execute(
            "UPDATE pipeline_runs SET status='FAILED', finished_at=?, error_message=? WHERE run_id=?",
            [_now(), str(exc)[:1000], run_id],
        )

    def _record_table_metrics(
        self,
        con: duckdb.DuckDBPyConnection,
        run_id: str,
        spec: TableSpec,
        metrics: TableMetrics,
        now: datetime,
    ) -> None:
        values = (
            ("rows_extracted", metrics.extracted, "rows"),
            ("rows_upserted", metrics.upserted, "rows"),
            ("rows_deleted", metrics.deleted, "rows"),
            ("payload_bytes_estimated", metrics.bytes_read_estimate, "bytes"),
            ("source_keys_scanned", metrics.source_keys_scanned, "keys"),
        )
        con.executemany(
            "INSERT INTO pipeline_metrics VALUES (?, ?, ?, ?, ?, ?)",
            [(run_id, spec.source, name, value, unit, now) for name, value, unit in values],
        )

    def _record_identity_metrics(
        self,
        con: duckdb.DuckDBPyConnection,
        run_id: str,
        metrics: dict[str, int],
        now: datetime,
    ) -> None:
        con.executemany(
            "INSERT INTO pipeline_metrics VALUES (?, 'identity_resolution', ?, ?, 'rows', ?)",
            [(run_id, name, value, now) for name, value in metrics.items()],
        )

    def _load_governance_metadata(self, con: duckdb.DuckDBPyConnection, now: datetime) -> None:
        metadata = yaml.safe_load(self.settings.metadata_path.read_text(encoding="utf-8"))
        version = int(metadata["version"])
        for dataset, values in metadata["datasets"].items():
            con.execute(
                """INSERT OR REPLACE INTO dataset_metadata
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    dataset,
                    values["owner"],
                    values["source"],
                    values["classification"],
                    values["contains_pii"],
                    values["masking_required"],
                    values["criticality"],
                    values["refresh"],
                    values["retention_days"],
                    values["strategy"],
                    values["primary_key"],
                    ",".join(values["dq_checks"]),
                    version,
                    now,
                ],
            )


def apply_demo_mutation(settings: Settings) -> bool:
    with source_connection(settings.source_dsn) as source:
        already_applied = source.execute(
            "SELECT 1 FROM demo_mutations WHERE mutation_name='incremental-v1'"
        ).fetchone()
        if already_applied:
            return False
        source.execute("INSERT INTO demo_mutations(mutation_name) VALUES ('incremental-v1')")
        source.execute(
            "UPDATE customers SET phone='+541155509999', updated_at='2025-03-01 00:00:00+00' WHERE customer_id=3"
        )
        source.execute("DELETE FROM transactions WHERE transaction_id=100001")
        source.execute(
            """INSERT INTO transactions VALUES
               (200001, 103, 'repayment', 2500, '2025-03-01 00:01:00+00', '2025-03-01 00:01:00+00')"""
        )
        source.execute(
            """INSERT INTO customers VALUES
               (9, 'AR-400', 'Sol', 'Vega', '1995-05-05', 'sol@example.com', '+541155501009', FALSE,
                '2025-03-01 00:02:00+00', '2025-03-01 00:02:00+00')"""
        )
        source.execute(
            """INSERT INTO cards VALUES
               ('card-5', 9, 'tok_005', '5555', 'active', '2025-03-01 00:03:00+00', '2025-03-01 00:03:00+00')"""
        )
        source.commit()
        return True


def warehouse_digest(settings: Settings) -> str:
    con = warehouse_connection(settings.warehouse_path, settings.warehouse_schema_path)
    try:
        parts: list[str] = []
        for spec in TABLES:
            rows = con.execute(f"SELECT * EXCLUDE (_loaded_at, _run_id) FROM {spec.target} ORDER BY {spec.primary_key}").fetchall()
            parts.append(repr(rows))
        parts.append(
            repr(
                con.execute(
                    "SELECT * EXCLUDE (resolved_at, _run_id) FROM customer_master ORDER BY master_customer_id"
                ).fetchall()
            )
        )
        parts.append(
            repr(
                con.execute(
                    "SELECT * EXCLUDE (resolved_at, _run_id) FROM customer_alias ORDER BY source_customer_id"
                ).fetchall()
            )
        )
        parts.append(
            repr(
                con.execute(
                    "SELECT * EXCLUDE (resolved_at, _run_id) FROM cards_master ORDER BY card_id"
                ).fetchall()
            )
        )
        parts.append(repr(con.execute("SELECT source_table, cursor_value FROM watermarks ORDER BY source_table").fetchall()))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()
    finally:
        con.close()


def _git_commit() -> str:
    value = os.getenv("GIT_COMMIT")
    if value:
        return value
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unavailable"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def summarize(summary: RunSummary) -> None:
    print(f"\nPipeline {summary.status}: run_id={summary.run_id}")
    print(f"{'TABLE':<28} {'EXTRACTED':>10} {'DELETED':>8} {'KEYS':>8} {'BYTES*':>10}")
    print("-" * 72)
    for table, metrics in summary.tables.items():
        print(f"{table:<28} {metrics.extracted:>10} {metrics.deleted:>8} {metrics.source_keys_scanned:>8} {metrics.bytes_read_estimate:>10}")
    print("* Payload bytes are measured from serialized extracted values; protocol overhead excluded.")
    if summary.identity:
        print("Identity:", ", ".join(f"{key}={value}" for key, value in summary.identity.items()))
    if summary.quality:
        print_results(summary.quality)
