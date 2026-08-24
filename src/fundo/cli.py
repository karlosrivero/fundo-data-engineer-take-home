from __future__ import annotations

import argparse
import sys

from .config import Settings
from .db import source_connection, warehouse_connection
from .logging import configure_logging
from .pipeline import (
    InjectedFailure,
    Pipeline,
    QualityFailure,
    apply_demo_mutation,
    summarize,
    warehouse_digest,
)
from .quality import print_results, run_checks


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Fundo incremental pipeline")
    commands = root.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run the incremental pipeline")
    run.add_argument("--quality", action="store_true", help="gate commit on data-quality checks")
    run.add_argument("--fail-after", choices=["customers", "advances", "cards", "transactions", "advance_status_history"])

    commands.add_parser("quality", help="compare source and warehouse")
    commands.add_parser("mutate-source", help="apply one idempotent incremental change-set")
    commands.add_parser("inspect", help="show operational state")
    commands.add_parser("demo-failure", help="prove data-quality detection without leaving corruption")
    commands.add_parser("demo-recovery", help="prove rollback and replay after a mid-run failure")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = Settings.from_env()
    pipeline = Pipeline(settings, configure_logging())
    try:
        if args.command == "run":
            summary = pipeline.run(check_quality=args.quality, fail_after=args.fail_after)
            summarize(summary)
            return 0
        if args.command == "quality":
            results = pipeline.quality()
            print_results(results)
            return 2 if any(result.status == "FAIL" for result in results) else 0
        if args.command == "mutate-source":
            changed = apply_demo_mutation(settings)
            print("Applied incremental-v1 source changes." if changed else "incremental-v1 was already applied; source unchanged.")
            return 0
        if args.command == "inspect":
            inspect(settings)
            return 0
        if args.command == "demo-failure":
            return demo_failure(settings, pipeline)
        if args.command == "demo-recovery":
            return demo_recovery(settings, pipeline)
    except QualityFailure as exc:
        print_results(exc.results)
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 1


def inspect(settings: Settings) -> None:
    con = warehouse_connection(settings.warehouse_path, settings.warehouse_schema_path)
    try:
        print("\nWAREHOUSE COUNTS")
        for table in (
            "customers_raw",
            "customer_master",
            "customer_alias",
            "advances_raw",
            "transactions_raw",
            "cards_raw",
            "cards_master",
            "advance_status_history_raw",
            "identity_review_candidates",
            "identity_conflicts",
        ):
            print(f"  {table:<32} {con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]:>8}")

        print("\nLATEST PIPELINE RUNS")
        for row in con.execute(
            "SELECT run_id, status, started_at, error_message FROM pipeline_runs ORDER BY started_at DESC LIMIT 5"
        ).fetchall():
            print(f"  {row[1]:<8} {row[0]} {row[2]} {row[3] or ''}")

        print("\nCURRENT WATERMARKS")
        for row in con.execute(
            "SELECT source_table, cursor_column, cursor_value FROM watermarks ORDER BY source_table"
        ).fetchall():
            print(f"  {row[0]:<28} {row[1]}={row[2]}")

        print("\nLATEST DQ SUMMARY")
        latest = con.execute("SELECT run_id FROM dq_results ORDER BY checked_at DESC LIMIT 1").fetchone()
        if latest:
            for row in con.execute(
                "SELECT status, count(*) FROM dq_results WHERE run_id=? GROUP BY status ORDER BY status",
                [latest[0]],
            ).fetchall():
                print(f"  {row[0]:<8} {row[1]}")
        else:
            print("  no checks recorded")
    finally:
        con.close()


def demo_failure(settings: Settings, pipeline: Pipeline) -> int:
    # Ensure there is a valid baseline before demonstrating a transient corruption.
    pipeline.run(check_quality=True)
    warehouse = warehouse_connection(settings.warehouse_path, settings.warehouse_schema_path)
    try:
        warehouse.execute("BEGIN TRANSACTION")
        victim = warehouse.execute("SELECT min(transaction_id) FROM transactions_raw").fetchone()[0]
        warehouse.execute("DELETE FROM transactions_raw WHERE transaction_id=?", [victim])
        with source_connection(settings.source_dsn) as source:
            results = run_checks(source, warehouse)
        print_results(results)
        detected = any(result.status == "FAIL" for result in results)
        warehouse.execute("ROLLBACK")
    except Exception:
        warehouse.execute("ROLLBACK")
        raise
    finally:
        warehouse.close()
    if not detected:
        print("ERROR: injected corruption was not detected", file=sys.stderr)
        return 1
    print(f"\nEXPECTED FAILURE DETECTED: transaction_id={victim} was missing.")
    print("The demonstration transaction was rolled back; the warehouse remains valid.")
    return 0


def demo_recovery(settings: Settings, pipeline: Pipeline) -> int:
    pipeline.run(check_quality=True)
    changed = apply_demo_mutation(settings)
    before = warehouse_digest(settings)
    try:
        pipeline.run(check_quality=False, fail_after="customers")
    except InjectedFailure as exc:
        print(f"Expected injected failure: {exc}")
    else:
        print("ERROR: injected failure did not occur", file=sys.stderr)
        return 1
    after_failure = warehouse_digest(settings)
    if after_failure != before:
        print("ERROR: warehouse changed despite rollback", file=sys.stderr)
        return 1
    summary = pipeline.run(check_quality=True)
    after_replay = warehouse_digest(settings)
    if changed and after_replay == before:
        print("ERROR: successful replay did not apply source changes", file=sys.stderr)
        return 1
    summarize(summary)
    print("\nRECOVERY PROVED")
    print(f"  state before failure: {before}")
    print(f"  state after rollback: {after_failure} (identical)")
    print(f"  state after replay:   {after_replay}")
    return 0

