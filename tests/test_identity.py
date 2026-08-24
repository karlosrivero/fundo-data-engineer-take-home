from datetime import datetime, timezone

from fundo.identity import (
    normalize_email,
    normalize_government_id,
    resolve_group,
    valid_email,
    valid_phone,
)


def customer(customer_id: int, *, complete: bool = True) -> dict:
    return {
        "customer_id": customer_id,
        "government_id": "AR-1",
        "first_name": "Ana",
        "last_name": "Rivera",
        "birth_date": "1988-04-10" if complete else None,
        "email": "ana@example.com" if complete else None,
        "phone": "+541155501001" if complete else None,
        "created_at": datetime(2025, 1, customer_id, tzinfo=timezone.utc),
    }


def test_normalization_is_conservative_and_deterministic():
    assert normalize_government_id(" ar 100-2 ") == "AR1002"
    assert normalize_email(" ANA@Example.COM ") == "ana@example.com"
    assert valid_email("ana@example.com")
    assert not valid_email("not-an-email")
    assert valid_phone("+54 11 5550-1001")
    assert not valid_phone("000")


def test_funded_customer_always_survives_proven_merge():
    resolutions, conflicts = resolve_group([customer(1), customer(2, complete=False)], {2})
    assert not conflicts
    assert {resolution.master_customer_id for resolution in resolutions} == {2}


def test_two_protected_customers_are_not_merged():
    resolutions, conflicts = resolve_group([customer(1), customer(2)], {1, 2})
    assert conflicts == [1, 2]
    assert all(item.source_customer_id == item.master_customer_id for item in resolutions)


def test_completeness_then_age_breaks_unprotected_ties():
    resolutions, _ = resolve_group([customer(1, complete=False), customer(2)], set())
    assert {resolution.master_customer_id for resolution in resolutions} == {2}

