CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id VARCHAR PRIMARY KEY,
    pipeline_name VARCHAR NOT NULL,
    pipeline_version VARCHAR NOT NULL,
    git_commit VARCHAR,
    environment VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    error_message VARCHAR
);

CREATE TABLE IF NOT EXISTS pipeline_metrics (
    run_id VARCHAR NOT NULL,
    table_name VARCHAR NOT NULL,
    metric_name VARCHAR NOT NULL,
    metric_value DOUBLE NOT NULL,
    unit VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, table_name, metric_name)
);

CREATE TABLE IF NOT EXISTS dq_results (
    result_id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL,
    check_name VARCHAR NOT NULL,
    dataset VARCHAR NOT NULL,
    dimension VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    expected VARCHAR NOT NULL,
    actual VARCHAR NOT NULL,
    details VARCHAR,
    checked_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS watermarks (
    source_table VARCHAR PRIMARY KEY,
    cursor_column VARCHAR NOT NULL,
    cursor_value VARCHAR NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    run_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_metadata (
    dataset VARCHAR PRIMARY KEY,
    owner VARCHAR NOT NULL,
    source_system VARCHAR NOT NULL,
    classification VARCHAR NOT NULL,
    contains_pii BOOLEAN NOT NULL,
    masking_required BOOLEAN NOT NULL,
    criticality VARCHAR NOT NULL,
    refresh VARCHAR NOT NULL,
    retention_days INTEGER NOT NULL,
    load_strategy VARCHAR NOT NULL,
    primary_key VARCHAR NOT NULL,
    dq_checks VARCHAR NOT NULL,
    metadata_version INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS customers_raw (
    customer_id BIGINT PRIMARY KEY,
    government_id VARCHAR,
    first_name VARCHAR NOT NULL,
    last_name VARCHAR NOT NULL,
    birth_date DATE,
    email VARCHAR,
    phone VARCHAR,
    is_test BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL,
    _run_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS advances_raw (
    advance_id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    status VARCHAR NOT NULL,
    amount_cents BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL,
    _run_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions_raw (
    transaction_id BIGINT PRIMARY KEY,
    advance_id BIGINT NOT NULL,
    transaction_type VARCHAR NOT NULL,
    amount_cents BIGINT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL,
    _run_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS cards_raw (
    card_id VARCHAR PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    token VARCHAR NOT NULL,
    last_four VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL,
    _run_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS advance_status_history_raw (
    history_id BIGINT PRIMARY KEY,
    advance_id BIGINT NOT NULL,
    status VARCHAR NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL,
    _run_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_master (
    master_customer_id BIGINT PRIMARY KEY,
    government_id VARCHAR,
    first_name VARCHAR NOT NULL,
    last_name VARCHAR NOT NULL,
    birth_date DATE,
    email VARCHAR,
    phone VARCHAR,
    email_valid BOOLEAN NOT NULL,
    phone_valid BOOLEAN NOT NULL,
    protected_by_advance BOOLEAN NOT NULL,
    source_record_count INTEGER NOT NULL,
    resolved_at TIMESTAMPTZ NOT NULL,
    _run_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_alias (
    source_customer_id BIGINT PRIMARY KEY,
    master_customer_id BIGINT NOT NULL,
    resolution_rule VARCHAR NOT NULL,
    resolved_at TIMESTAMPTZ NOT NULL,
    _run_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_review_candidates (
    customer_id_a BIGINT NOT NULL,
    customer_id_b BIGINT NOT NULL,
    evidence VARCHAR NOT NULL,
    reason_not_merged VARCHAR NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    _run_id VARCHAR NOT NULL,
    PRIMARY KEY (customer_id_a, customer_id_b, evidence)
);

CREATE TABLE IF NOT EXISTS identity_conflicts (
    conflict_key VARCHAR NOT NULL,
    customer_id BIGINT NOT NULL,
    reason VARCHAR NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    _run_id VARCHAR NOT NULL,
    PRIMARY KEY (conflict_key, customer_id)
);

CREATE TABLE IF NOT EXISTS cards_master (
    card_id VARCHAR PRIMARY KEY,
    master_customer_id BIGINT NOT NULL,
    source_customer_id BIGINT NOT NULL,
    token VARCHAR NOT NULL,
    last_four VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    resolved_at TIMESTAMPTZ NOT NULL,
    _run_id VARCHAR NOT NULL
);

