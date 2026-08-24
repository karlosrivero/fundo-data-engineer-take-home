# Solution

## Executive decision

I solved all three requested problems with one transactional Python process, visible SQL, PostgreSQL as the local source, and DuckDB as the warehouse. The design deliberately does not include Airflow, dbt, Kafka, Debezium, or a catalog server: none is required to prove incremental movement, identity safety, correctness, or replay in a 4–8 hour exercise. The important control is atomicity: raw changes, deletes, derived identity tables, watermarks, metrics, quality results, and the SUCCESS state commit together. A crash cannot publish a partial new state.

PostgreSQL is the one material environment trade-off. SQL Server would better match Fundo, but its local image is heavier and less portable across ARM laptops. The extraction contract uses standard indexed timestamps and keys, so moving to SQL Server would mainly replace the connector and later enable Change Tracking/CDC; this submission does not pretend PostgreSQL proves SQL Server-specific behavior.

## What was implemented

### Incremental movement and recovery

Each run captures a source upper bound, then extracts `previous_watermark < updated_at <= upper_bound`. Capturing the bound prevents a moving target: later changes remain eligible for the next run. Rows are upserted by stable source key. For mutable tables, a current-key-only source scan detects hard deletes without retransferring full rows. The append-only history table uses its monotonic `history_id` and does not pay for delete reconciliation.

`pipeline_runs` is written RUNNING before the data transaction. All data changes and new watermarks are committed together; exceptions roll them back and mark the run FAILED separately. `make demo-recovery` hashes the business rows and watermarks before the injected crash, after rollback, and after replay. This proves rollback rather than relying on an explanation. Re-running unchanged input extracts zero payload rows and produces the same business-state hash.

Per-table decisions:

| Table | Strategy | Reason and trade-off |
|---|---|---|
| Customers | timestamp watermark + upsert + key reconciliation | Updates and hard deletes matter. Key scan costs one narrow column but avoids missing deletes. |
| Advances | timestamp watermark + upsert + key reconciliation | Status changes affect protected identity; correctness beats a small key scan. |
| Cards | timestamp watermark + upsert + key reconciliation | Ownership and status change; stale cards are unsafe. Tokens stay in restricted raw/master tables. |
| Transactions | append-optimized timestamp + upsert + key reconciliation | Mostly insert-only and largest table. Payload is incremental; a key scan proves hard deletes. At higher scale this becomes CDC or partition reconciliation. |
| Advance status history | monotonic append-only sequence | The contract forbids mutation. Cheapest path; a source contract violation would need a separate audit. |
| Scratch export | skipped | Measured as 8 rows but has no owner or consumer. Copying it would perpetuate the stated governance problem. |

### Customer identity

Only a normalized government identifier is treated as proof and auto-merged. Normalization removes formatting characters and case, but does not invent missing values. Email, phone, name, and birth date are suggestive: the implementation records `email + birth_date` pairs in `identity_review_candidates` and never auto-merges them. This is intentionally more conservative than a weighted matching score, because a high score is still not proof.

Within a proven group, a customer with a funded or paid-off advance is the survivor. Its source ID stays the master ID and every alias and card points to it. If two protected customers share the same proven identity, both remain separate and are written to `identity_conflicts`; the pipeline does not guess. Without a protected record, the deterministic order is data completeness, oldest creation time, then smallest ID. Raw records are retained and `customer_alias` makes every decision reversible.

Test data is excluded using the explicit `is_test` source flag. I did not use name fragments or `@fundo.com`: the fixture includes the real surname `Testerman` and real staff activity on the company domain specifically to catch that unsafe shortcut. Malformed contacts are preserved in raw, counted as WARN, and exposed through validity flags on the master. Silent repair could create false identities. Cards from merged aliases are remapped to the surviving master in `cards_master`; leaving them on a discarded ID would break payment ownership and downstream referential integrity.

The warehouse prevents a repeated source duplicate from becoming a second master: every run resolves proven identity through the same deterministic alias mapping. Preventing the duplicate at the operational write path would additionally require an application/API uniqueness policy and a reviewed exception workflow; changing that source system is outside this pipeline's authority.

### Correctness, governance, and observability

Checks compare current source and warehouse key sets for completeness, missing rows, and stale rows. They also check uniqueness, raw relationships, card-to-master relationships, alias coverage, explicit test exclusion, protected-survivor behavior, identity conflicts, review candidates, and malformed contacts. FAIL blocks a pipeline commit; WARN exposes a controlled data issue without claiming it was fixed. `make demo-failure` deletes a warehouse transaction in a temporary transaction, proves the normal parity check fails, then rolls back the demo damage.

Governance is operational metadata, not a decorative catalog. `config/metadata.yml` declares owner, source, classification, PII/masking requirements, criticality, retention, strategy, primary key, checks, exclusions, and lightweight lineage; each run materializes the controlled version in `dataset_metadata`. Observability is queryable through run status/error, per-table extracted/upserted/deleted/key-scan/payload-byte metrics, watermarks, identity metrics, and check results. Logs are structured JSON with run and table context. A git commit field is recorded when available.

## Measurements, estimates, and cost

**Measured from the deterministic fixture and acceptance flow:** the initial source has 8 customers, 6 advances, 1,000 transactions, 4 cards, 6 history rows, and 8 excluded scratch rows. The pipeline therefore transfers 1,024 payload rows on the initial load. It produces 6 masters from 7 non-test customers, one proven duplicate merge, one suggestive review pair, one excluded test account, and one malformed email plus phone. The unchanged second run transfers 0 payload rows. The `incremental-v1` scenario changes five warehouse facts—four extracted rows (two customers, one card, one inserted transaction) and one reconciled transaction delete—about 0.49% of the initial 1,024-row payload. Each run also records serialized payload bytes (protocol overhead excluded) rather than fabricating a network measurement.

**Estimated production impact:** today a daily full copy processes 100% of payload to find roughly 1% change. Incremental payload extraction should reduce source read/transfer bytes toward the change rate, approximately 99% before fixed overhead. The current hard-delete proof still scans primary keys for four mutable tables, so it is not a claim of 99% fewer source rows touched. BigQuery cost would depend on ingestion method, storage retention, transformations, and downstream query scans; no dollar saving is claimed without Fundo volumes, compression, and pricing. The durable levers are fewer transferred payload bytes, dropping unowned scratch data, explicit retention, and partition/cluster-aware downstream models.

## Risks and deliberately skipped scope

- Timestamp correctness depends on every mutation advancing `updated_at`. Production should prefer SQL Server Change Tracking or CDC with a log sequence number and retention-gap detection.
- Key reconciliation is safe and simple locally but becomes expensive at billions of rows. Partition manifests, source tombstones, or CDC delete events would replace it.
- Schema drift is fail-fast, not auto-applied. Silent widening or coercion is riskier than an explicit migration.
- No fuzzy auto-merge, contact “repair,” destructive source cleanup, token masking engine, RBAC, alert delivery, scheduler, dashboard, or cloud cost benchmark is claimed.
- The bad unbounded card identifier is preserved to demonstrate detection; production remediation would add a bounded validated column, backfill, dual-write, verify, then cut over.
- Retention is declared but not executed in the take-home because deleting regulated financial history without approved policy would violate the safety criterion.

## Production evolution

The first delivery would still be incremental Customers and Advances with the protected-identity rules, data contract, and reconciliation checks. That removes material transfer waste while protecting the highest-risk business relationship. The one-time work would profile/backfill identity keys, resolve the quarantined duplicate backlog with Operations, classify scratch tables, and migrate the unbounded identifier. Permanent components would be incremental ingestion, data contracts, DQ gates, lineage/run metrics, retention enforcement, and alerting.

For SQL Server I would choose Change Tracking when current-state changes and deletes are sufficient, or CDC when ordered before/after history is required. I would land immutable changes in object storage, orchestrate with the company's existing scheduler (Airflow only if already operated), transform/test with dbt, and load partitioned/clustered BigQuery tables. OpenLineage/OpenTelemetry would feed the existing observability stack; a managed data-quality layer is justified only if multiple teams need shared ownership and incident workflows. I would add service-level objectives—freshness, completeness, failed-run recovery time, bytes transferred per changed row—and alert on breach. The business identity policy remains deterministic and versioned; probabilistic candidates go to human review, never directly into an irreversible merge.

