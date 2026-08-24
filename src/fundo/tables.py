from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSpec:
    source: str
    target: str
    primary_key: str
    cursor_column: str
    cursor_type: str
    columns: tuple[str, ...]
    reconcile_deletes: bool
    strategy: str


TABLES = (
    TableSpec(
        "customers",
        "customers_raw",
        "customer_id",
        "updated_at",
        "timestamp",
        (
            "customer_id",
            "government_id",
            "first_name",
            "last_name",
            "birth_date",
            "email",
            "phone",
            "is_test",
            "created_at",
            "updated_at",
        ),
        True,
        "watermark-upsert-plus-key-reconciliation",
    ),
    TableSpec(
        "advances",
        "advances_raw",
        "advance_id",
        "updated_at",
        "timestamp",
        ("advance_id", "customer_id", "status", "amount_cents", "created_at", "updated_at"),
        True,
        "watermark-upsert-plus-key-reconciliation",
    ),
    TableSpec(
        "cards",
        "cards_raw",
        "card_id",
        "updated_at",
        "timestamp",
        ("card_id", "customer_id", "token", "last_four", "status", "created_at", "updated_at"),
        True,
        "watermark-upsert-plus-key-reconciliation",
    ),
    TableSpec(
        "transactions",
        "transactions_raw",
        "transaction_id",
        "updated_at",
        "timestamp",
        ("transaction_id", "advance_id", "transaction_type", "amount_cents", "occurred_at", "updated_at"),
        True,
        "append-optimized-watermark-plus-key-reconciliation",
    ),
    TableSpec(
        "advance_status_history",
        "advance_status_history_raw",
        "history_id",
        "history_id",
        "integer",
        ("history_id", "advance_id", "status", "changed_at"),
        False,
        "append-only-sequence",
    ),
)

