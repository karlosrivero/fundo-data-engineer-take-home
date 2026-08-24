from datetime import datetime, timezone
from pathlib import Path

from fundo.config import Settings
from fundo.db import warehouse_connection
from fundo.identity import rebuild_customer_master
from fundo.logging import configure_logging
from fundo.pipeline import Pipeline


def test_schema_metadata_and_identity_materialization(tmp_path: Path):
    root = Path(__file__).parents[1]
    settings = Settings(
        source_dsn="unused",
        warehouse_path=tmp_path / "warehouse.duckdb",
        metadata_path=root / "config" / "metadata.yml",
        warehouse_schema_path=root / "sql" / "warehouse" / "001_schema.sql",
        environment="test",
    )
    con = warehouse_connection(settings.warehouse_path, settings.warehouse_schema_path)
    now = datetime.now(timezone.utc)
    Pipeline(settings, configure_logging())._load_governance_metadata(con, now)
    assert con.execute("SELECT count(*) FROM dataset_metadata").fetchone()[0] == 6

    customer_rows = [
        (1, "AR-1", "Ana", "Rivera", "1988-04-10", "ana@example.com", "+541155501001", False, now, now, now, "run"),
        (2, " ar 1 ", "Ana", "Rivera", "1988-04-10", "ANA@example.com", "123", False, now, now, now, "run"),
        (3, None, "Demo", "Account", None, "test@fundo.com", "000", True, now, now, now, "run"),
    ]
    con.executemany("INSERT INTO customers_raw VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", customer_rows)
    con.execute("INSERT INTO advances_raw VALUES (10, 2, 'funded', 1000, ?, ?, ?, 'run')", [now, now, now])
    con.execute("INSERT INTO cards_raw VALUES ('card-1', 1, 'tok', '1111', 'active', ?, ?, ?, 'run')", [now, now, now])

    metrics = rebuild_customer_master(con, "run", now)
    assert metrics["master_customers"] == 1
    assert metrics["proven_merges"] == 1
    assert con.execute("SELECT master_customer_id FROM customer_alias WHERE source_customer_id=1").fetchone()[0] == 2
    assert con.execute("SELECT master_customer_id FROM cards_master WHERE card_id='card-1'").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM customer_alias WHERE source_customer_id=3").fetchone()[0] == 0
    con.close()

