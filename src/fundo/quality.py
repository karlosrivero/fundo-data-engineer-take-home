from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

import duckdb
import psycopg

from .identity import valid_email, valid_phone
from .tables import TABLES


@dataclass(frozen=True)
class DQResult:
    name: str
    dataset: str
    dimension: str
    status: str
    expected: str
    actual: str
    details: str = ""


def run_checks(
    source: psycopg.Connection,
    warehouse: duckdb.DuckDBPyConnection,
) -> list[DQResult]:
    results: list[DQResult] = []
    for spec in TABLES:
        source_keys = {row[spec.primary_key] for row in source.execute(f"SELECT {spec.primary_key} FROM {spec.source}").fetchall()}
        target_keys = {row[0] for row in warehouse.execute(f"SELECT {spec.primary_key} FROM {spec.target}").fetchall()}
        missing = source_keys - target_keys
        stale = target_keys - source_keys
        results.append(
            DQResult(
                "source_key_parity",
                spec.target,
                "completeness",
                "PASS" if not missing and not stale else "FAIL",
                f"{len(source_keys)} source keys; 0 missing; 0 stale",
                f"{len(target_keys)} warehouse keys; {len(missing)} missing; {len(stale)} stale",
                _sample_differences(missing, stale),
            )
        )
        duplicate_count = warehouse.execute(
            f"SELECT count(*) - count(DISTINCT {spec.primary_key}) FROM {spec.target}"
        ).fetchone()[0]
        results.append(
            DQResult(
                "unique_primary_key",
                spec.target,
                "uniqueness",
                "PASS" if duplicate_count == 0 else "FAIL",
                "0 duplicates",
                f"{duplicate_count} duplicates",
            )
        )

    results.extend(_relationship_checks(warehouse))
    results.extend(_identity_checks(warehouse))
    results.extend(_contact_checks(warehouse))
    return results


def _relationship_checks(con: duckdb.DuckDBPyConnection) -> list[DQResult]:
    queries = (
        ("cards_have_customer", "cards_raw", "consistency", "SELECT count(*) FROM cards_raw c LEFT JOIN customers_raw p ON p.customer_id=c.customer_id WHERE p.customer_id IS NULL"),
        ("advances_have_customer", "advances_raw", "consistency", "SELECT count(*) FROM advances_raw a LEFT JOIN customers_raw c ON c.customer_id=a.customer_id WHERE c.customer_id IS NULL"),
        ("transactions_have_advance", "transactions_raw", "consistency", "SELECT count(*) FROM transactions_raw t LEFT JOIN advances_raw a ON a.advance_id=t.advance_id WHERE a.advance_id IS NULL"),
        ("cards_have_master", "cards_master", "consistency", "SELECT count(*) FROM cards_master c LEFT JOIN customer_master m ON m.master_customer_id=c.master_customer_id WHERE m.master_customer_id IS NULL"),
    )
    results = []
    for name, dataset, dimension, query in queries:
        count = con.execute(query).fetchone()[0]
        results.append(DQResult(name, dataset, dimension, "PASS" if count == 0 else "FAIL", "0 orphans", f"{count} orphans"))
    return results


def _identity_checks(con: duckdb.DuckDBPyConnection) -> list[DQResult]:
    non_test = con.execute("SELECT count(*) FROM customers_raw WHERE NOT is_test").fetchone()[0]
    aliases = con.execute("SELECT count(*) FROM customer_alias").fetchone()[0]
    test_in_master = con.execute(
        "SELECT count(*) FROM customers_raw c JOIN customer_alias a ON a.source_customer_id=c.customer_id WHERE c.is_test"
    ).fetchone()[0]
    protected_moved = con.execute(
        """SELECT count(*) FROM (SELECT DISTINCT customer_id FROM advances_raw WHERE status IN ('funded','paid_off')) p
           JOIN customer_alias a ON a.source_customer_id=p.customer_id
           WHERE a.master_customer_id <> p.customer_id"""
    ).fetchone()[0]
    conflicts = con.execute("SELECT count(DISTINCT conflict_key) FROM identity_conflicts").fetchone()[0]
    candidates = con.execute("SELECT count(*) FROM identity_review_candidates").fetchone()[0]
    return [
        DQResult("alias_coverage", "customer_alias", "completeness", "PASS" if aliases == non_test else "FAIL", str(non_test), str(aliases)),
        DQResult("test_data_excluded", "customer_master", "validity", "PASS" if test_in_master == 0 else "FAIL", "0", str(test_in_master)),
        DQResult("protected_customer_survives", "customer_master", "business_rule", "PASS" if protected_moved == 0 else "FAIL", "0 protected customers remapped", f"{protected_moved} remapped"),
        DQResult("protected_identity_conflicts", "identity_conflicts", "business_rule", "WARN" if conflicts else "PASS", "0 preferred", str(conflicts), "conflicts are quarantined, never auto-merged"),
        DQResult("suggestive_match_candidates", "identity_review_candidates", "observability", "WARN" if candidates else "PASS", "review only", str(candidates), "suggestive evidence is deliberately not auto-merged"),
    ]


def _contact_checks(con: duckdb.DuckDBPyConnection) -> list[DQResult]:
    rows = con.execute("SELECT email, phone FROM customers_raw WHERE NOT is_test").fetchall()
    bad_emails = sum(not valid_email(row[0]) for row in rows)
    bad_phones = sum(not valid_phone(row[1]) for row in rows)
    return [
        DQResult("malformed_email_count", "customers_raw", "validity", "WARN" if bad_emails else "PASS", "tracked, not silently fixed", str(bad_emails), "raw value preserved; validity flag is exposed in master"),
        DQResult("malformed_phone_count", "customers_raw", "validity", "WARN" if bad_phones else "PASS", "tracked, not silently fixed", str(bad_phones), "raw value preserved; validity flag is exposed in master"),
    ]


def persist_results(con: duckdb.DuckDBPyConnection, run_id: str, results: list[DQResult], now: datetime) -> None:
    con.executemany(
        "INSERT INTO dq_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (str(uuid4()), run_id, result.name, result.dataset, result.dimension, result.status, result.expected, result.actual, result.details, now)
            for result in results
        ],
    )


def _sample_differences(missing: set[Any], stale: set[Any]) -> str:
    return f"missing_sample={sorted(map(str, missing))[:5]}; stale_sample={sorted(map(str, stale))[:5]}"


def print_results(results: list[DQResult]) -> None:
    print("\nDATA QUALITY")
    print(f"{'STATUS':<7} {'DATASET':<30} CHECK")
    print("-" * 82)
    for result in results:
        print(f"{result.status:<7} {result.dataset:<30} {result.name}: {result.actual}")
    failures = sum(result.status == "FAIL" for result in results)
    warnings = sum(result.status == "WARN" for result in results)
    print(f"\nSummary: {len(results) - failures - warnings} PASS, {warnings} WARN, {failures} FAIL")

