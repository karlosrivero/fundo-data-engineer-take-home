from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    source_dsn: str
    warehouse_path: Path
    metadata_path: Path
    warehouse_schema_path: Path
    environment: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            source_dsn=os.getenv(
                "SOURCE_DSN", "postgresql://fundo:fundo_local_only@localhost:54329/fundo"
            ),
            warehouse_path=Path(os.getenv("WAREHOUSE_PATH", ".state/warehouse.duckdb")),
            metadata_path=Path(os.getenv("METADATA_PATH", "config/metadata.yml")),
            warehouse_schema_path=Path(
                os.getenv("WAREHOUSE_SCHEMA_PATH", "sql/warehouse/001_schema.sql")
            ),
            environment=os.getenv("PIPELINE_ENV", "local"),
        )

