from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

import duckdb


EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)


def normalize_government_id(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", value.upper())
    return normalized or None


def normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower() or None


def valid_email(value: str | None) -> bool:
    normalized = normalize_email(value)
    return bool(normalized and EMAIL_PATTERN.fullmatch(normalized))


def valid_phone(value: str | None) -> bool:
    if not value:
        return False
    digits = re.sub(r"\D", "", value)
    return 8 <= len(digits) <= 15 and len(set(digits)) > 1


def completeness_score(row: dict[str, Any]) -> int:
    fields = ("government_id", "first_name", "last_name", "birth_date", "email", "phone")
    return sum(row.get(field) not in (None, "") for field in fields)


@dataclass(frozen=True)
class Resolution:
    source_customer_id: int
    master_customer_id: int
    rule: str


def resolve_group(rows: list[dict[str, Any]], protected_ids: set[int]) -> tuple[list[Resolution], list[int]]:
    """Resolve one proven-identity group; multiple protected records are quarantined."""
    protected = sorted(int(row["customer_id"]) for row in rows if row["customer_id"] in protected_ids)
    if len(protected) > 1:
        return (
            [Resolution(int(row["customer_id"]), int(row["customer_id"]), "protected_conflict") for row in rows],
            protected,
        )
    if len(protected) == 1:
        master_id = protected[0]
        rule = "government_id+protected_advance"
    else:
        survivor = min(
            rows,
            key=lambda row: (
                -completeness_score(row),
                row["created_at"],
                int(row["customer_id"]),
            ),
        )
        master_id = int(survivor["customer_id"])
        rule = "government_id+deterministic_survivor"
    return ([Resolution(int(row["customer_id"]), master_id, rule) for row in rows], [])


def rebuild_customer_master(con: duckdb.DuckDBPyConnection, run_id: str, now: datetime) -> dict[str, int]:
    columns = [description[0] for description in con.execute("SELECT * FROM customers_raw LIMIT 0").description]
    customers = [dict(zip(columns, row, strict=True)) for row in con.execute("SELECT * FROM customers_raw WHERE NOT is_test").fetchall()]
    protected_ids = {
        int(row[0])
        for row in con.execute(
            "SELECT DISTINCT customer_id FROM advances_raw WHERE status IN ('funded', 'paid_off')"
        ).fetchall()
    }

    proven_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unproven: list[dict[str, Any]] = []
    for customer in customers:
        key = normalize_government_id(customer["government_id"])
        (proven_groups[key] if key else unproven).append(customer)

    resolutions: list[Resolution] = []
    conflicts: list[tuple[str, int, str]] = []
    for key, rows in proven_groups.items():
        group_resolutions, protected_conflicts = resolve_group(rows, protected_ids)
        resolutions.extend(group_resolutions)
        conflicts.extend((key, customer_id, "multiple protected customers share proven identity") for customer_id in protected_conflicts)
    resolutions.extend(Resolution(int(row["customer_id"]), int(row["customer_id"]), "no_proven_identity") for row in unproven)

    by_id = {int(row["customer_id"]): row for row in customers}
    aliases_by_master: dict[int, list[int]] = defaultdict(list)
    for resolution in resolutions:
        aliases_by_master[resolution.master_customer_id].append(resolution.source_customer_id)

    con.execute("DELETE FROM cards_master")
    con.execute("DELETE FROM identity_review_candidates")
    con.execute("DELETE FROM identity_conflicts")
    con.execute("DELETE FROM customer_alias")
    con.execute("DELETE FROM customer_master")

    for master_id, alias_ids in sorted(aliases_by_master.items()):
        canonical = by_id[master_id]
        group = [by_id[customer_id] for customer_id in alias_ids]
        # Enrich only missing canonical values; a protected survivor is never overwritten.
        merged = dict(canonical)
        for field in ("government_id", "birth_date", "email", "phone"):
            if merged.get(field) in (None, ""):
                merged[field] = next((row[field] for row in group if row.get(field) not in (None, "")), None)
        con.execute(
            """INSERT INTO customer_master VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                master_id,
                merged.get("government_id"),
                merged["first_name"],
                merged["last_name"],
                merged.get("birth_date"),
                merged.get("email"),
                merged.get("phone"),
                valid_email(merged.get("email")),
                valid_phone(merged.get("phone")),
                master_id in protected_ids,
                len(alias_ids),
                now,
                run_id,
            ],
        )

    con.executemany(
        "INSERT INTO customer_alias VALUES (?, ?, ?, ?, ?)",
        [(r.source_customer_id, r.master_customer_id, r.rule, now, run_id) for r in resolutions],
    )
    if conflicts:
        con.executemany(
            "INSERT INTO identity_conflicts VALUES (?, ?, ?, ?, ?)",
            [(key, customer_id, reason, now, run_id) for key, customer_id, reason in conflicts],
        )

    _insert_review_candidates(con, customers, resolutions, run_id, now)
    con.execute(
        """INSERT INTO cards_master
           SELECT c.card_id, a.master_customer_id, c.customer_id, c.token, c.last_four,
                  c.status, ?, ?
           FROM cards_raw c JOIN customer_alias a ON a.source_customer_id = c.customer_id""",
        [now, run_id],
    )
    return {
        "master_customers": len(aliases_by_master),
        "aliases": len(resolutions),
        "proven_merges": sum(1 for r in resolutions if r.source_customer_id != r.master_customer_id),
        "identity_conflicts": len(conflicts),
    }


def _insert_review_candidates(
    con: duckdb.DuckDBPyConnection,
    customers: Iterable[dict[str, Any]],
    resolutions: list[Resolution],
    run_id: str,
    now: datetime,
) -> None:
    master_by_source = {r.source_customer_id: r.master_customer_id for r in resolutions}
    groups: dict[tuple[str, Any], list[int]] = defaultdict(list)
    for row in customers:
        email = normalize_email(row.get("email"))
        birth_date = row.get("birth_date")
        if email and valid_email(email) and birth_date:
            groups[(email, birth_date)].append(int(row["customer_id"]))
    candidates: list[tuple[int, int, str, str, datetime, str]] = []
    for ids in groups.values():
        for index, left in enumerate(sorted(ids)):
            for right in sorted(ids)[index + 1 :]:
                if master_by_source[left] != master_by_source[right]:
                    candidates.append((left, right, "email+birth_date", "suggestive evidence is not proof", now, run_id))
    if candidates:
        con.executemany("INSERT INTO identity_review_candidates VALUES (?, ?, ?, ?, ?, ?)", candidates)
