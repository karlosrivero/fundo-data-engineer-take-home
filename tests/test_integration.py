from pathlib import Path

import pytest

from fundo.config import Settings
from fundo.logging import configure_logging
from fundo.pipeline import InjectedFailure, Pipeline, warehouse_digest


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    base = Settings.from_env()
    return Settings(
        source_dsn=base.source_dsn,
        warehouse_path=tmp_path / "test.duckdb",
        metadata_path=base.metadata_path,
        warehouse_schema_path=base.warehouse_schema_path,
        environment="test",
    )


@pytest.mark.integration
def test_second_run_is_idempotent_and_extracts_nothing(settings: Settings):
    pipeline = Pipeline(settings, configure_logging())
    first = pipeline.run(check_quality=True)
    first_digest = warehouse_digest(settings)
    second = pipeline.run(check_quality=True)
    second_digest = warehouse_digest(settings)

    assert sum(metric.extracted for metric in first.tables.values()) > 0
    assert sum(metric.extracted for metric in second.tables.values()) == 0
    assert first_digest == second_digest


@pytest.mark.integration
def test_failure_rolls_back_data_and_watermarks(settings: Settings):
    pipeline = Pipeline(settings, configure_logging())
    pipeline.run(check_quality=True)
    before = warehouse_digest(settings)

    with pytest.raises(InjectedFailure):
        pipeline.run(fail_after="customers")

    assert warehouse_digest(settings) == before

