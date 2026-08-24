# Fundo Data Engineer Take-Home

A small, reliable local pipeline that moves synthetic operational data incrementally into a warehouse, resolves only proven duplicate identities, and makes correctness visible. It favors deterministic code and SQL over infrastructure.

## Quick start

Prerequisite: Docker Desktop (or Docker Engine with Compose v2) and `make`. No cloud credentials are used.

From a clean checkout, run exactly:

```bash
docker compose up --build --abort-on-container-exit --exit-code-from pipeline
```

Compose starts PostgreSQL, seeds the synthetic source, builds the Python image, runs the initial load, runs all quality checks, and exits when the pipeline completes. The expected final lines include:

```text
Pipeline SUCCESS: run_id=...
customers                         8
transactions                   1000
Summary: 18 PASS, 3 WARN, 0 FAIL
```

Warnings are expected: the seed deliberately contains malformed contact data and a suggestive identity match that is not safe to auto-merge. Exact PASS/WARN counts are printed by the current code and may change when checks are added; the acceptance condition is `0 FAIL` and exit code `0`.

The equivalent convenience command is:

```bash
make up
```

Docker volumes preserve both databases between commands. Local credentials and the host port are documented in `.env.example`; they are intentionally not production secrets.

## Operate and verify

Every command below is copy-pasteable and starts the source dependency if it is stopped.

```bash
make load
```

Runs the pipeline again without changing the source. Expected: every table reports `EXTRACTED 0`, `DELETED 0`, quality has `0 FAIL`, and the warehouse business state is unchanged. This is the simplest idempotency demonstration.

```bash
make incremental
```

Applies the named source mutation `incremental-v1` once, then loads it. It updates one customer, inserts one customer and card, inserts one transaction, and hard-deletes one transaction. Expected: four payload rows extracted, one stale transaction deleted, and `0 FAIL`. Re-running the command prints that the mutation was already applied and extracts zero rows.

```bash
make quality
```

Compares source and warehouse keys, relationships, customer aliases, protected-customer rules, test exclusion, and contact validity. Exit code is `0` for PASS/WARN and `2` if any blocking check fails.

```bash
make inspect
```

Prints warehouse counts, the last five pipeline runs, current watermarks, and the latest quality summary. Operational records are also queryable in `pipeline_runs`, `pipeline_metrics`, `dq_results`, `watermarks`, and `dataset_metadata`.

## Reproduce a failing check

```bash
make demo-failure
```

The command removes one warehouse transaction inside a temporary transaction, runs the normal source-to-warehouse checks, and must print:

```text
FAIL    transactions_raw               source_key_parity: ... 1 missing ...
EXPECTED FAILURE DETECTED
```

It then rolls the demonstration transaction back. This proves detection without leaving the repository in a broken state. A following `make quality` must pass.

## Prove failure recovery

```bash
make demo-recovery
```

This command:

1. establishes a valid baseline;
2. applies the repeatable incremental source change-set if needed;
3. injects an exception after the customer table is written but before commit;
4. proves the warehouse data and watermarks have the same SHA-256 digest as before the failed run;
5. replays normally and runs quality checks.

Expected output ends with `RECOVERY PROVED`, identical pre-failure/rollback digests, and a successful replay digest. The failed attempt remains visible in `pipeline_runs`; partial data and advanced watermarks do not.

## Tests and static checks

```bash
make test
make lint
```

`make test` runs pure identity-rule tests plus integration tests against the seeded source. The integration tests prove a second run extracts no payload rows and an injected failure rolls back data plus watermarks. `make lint` compiles all Python modules and tests.

To remove all take-home containers and both local data volumes:

```bash
make reset
```

This is intentionally destructive to local demo data only. It is the recovery path to a truly clean seed.

## Architecture

```text
PostgreSQL source
  | bounded watermarks + current-key reconciliation
  v
DuckDB raw tables ----> source/warehouse data-quality comparisons
  |
  +--> protected-advance lookup
  +--> conservative identity resolution
          |--> customer_master + customer_alias
          |--> identity_review_candidates / identity_conflicts
          `--> cards_master

Control plane: pipeline_runs | pipeline_metrics | watermarks | dq_results
Governance:    config/metadata.yml -> dataset_metadata
```

The source is PostgreSQL rather than SQL Server. PostgreSQL has a small multi-architecture image that starts reliably on Intel and ARM laptops; the pipeline is evaluated, not local DBA setup. SQL Server-specific CDC and `rowversion` semantics are therefore not claimed. Production choices are in [SOLUTION.md](SOLUTION.md).

## Project map

```text
config/metadata.yml              ownership, classification, retention, checks, lineage
sql/source/001_schema.sql        operational schema and deliberate bad choices
sql/source/002_seed.sql          deterministic synthetic cases and 1,000 transactions
sql/warehouse/001_schema.sql     raw, master, governance, quality, and audit tables
src/fundo/pipeline.py            bounded incremental load and atomic recovery
src/fundo/identity.py            conservative deterministic identity rules
src/fundo/quality.py             source-to-warehouse checks
src/fundo/cli.py                 runnable commands and demonstrations
tests/                           unit and integration acceptance tests
SOLUTION.md                      decisions, measurements, cost, risks, production path
```

## Important operating semantics

- A watermark is advanced only in the same DuckDB transaction as all table writes, identity outputs, metrics, and the successful run state.
- Each incremental query has a captured upper bound (`old < cursor <= run bound`), so rows arriving during a run are deferred rather than missed.
- Mutable tables use watermark upserts plus a narrow current-key scan to detect hard deletes. The append-only history table uses a monotonic sequence and deliberately does not scan for deletes.
- Raw tables preserve source values and identifiers. Identity resolution is reversible through `customer_alias`; contact defects are flagged, never silently corrected.
- Test exclusion uses the explicit source `is_test` flag. Names containing “test” and real company-domain accounts are not classified as tests.

See [SOLUTION.md](SOLUTION.md) before reading the implementation; it states the boundaries and unimplemented production concerns explicitly.
