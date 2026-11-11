-- Automated Risk Portfolio Reporting Pipeline
-- Canonical analytical schema for the local DuckDB prototype.
-- The SQL is intentionally portable in spirit; a future PostgreSQL deployment
-- would replace DuckDB-specific typing/loading code behind database/connection.py.

CREATE TABLE IF NOT EXISTS institutions (
    bank_id VARCHAR PRIMARY KEY,
    bank_name VARCHAR NOT NULL,
    region VARCHAR NOT NULL,
    peer_group VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    pipeline_run_id VARCHAR PRIMARY KEY,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status VARCHAR NOT NULL,
    environment VARCHAR NOT NULL DEFAULT 'local-duckdb',
    batches_attempted INTEGER DEFAULT 0,
    batches_completed INTEGER DEFAULT 0,
    rows_received BIGINT DEFAULT 0,
    rows_valid BIGINT DEFAULT 0,
    rows_rejected BIGINT DEFAULT 0,
    notes VARCHAR
);

CREATE TABLE IF NOT EXISTS ingestion_batches (
    batch_id VARCHAR PRIMARY KEY,
    bank_id VARCHAR NOT NULL,
    bank_name VARCHAR NOT NULL,
    reporting_date DATE,
    source_system VARCHAR NOT NULL,
    dataset_type VARCHAR NOT NULL,
    source_file VARCHAR NOT NULL,
    import_timestamp TIMESTAMP NOT NULL,
    status VARCHAR NOT NULL,
    pipeline_run_id VARCHAR,
    file_hash VARCHAR,
    raw_archive_path VARCHAR,
    rows_received BIGINT DEFAULT 0,
    rows_valid BIGINT DEFAULT 0,
    rows_rejected BIGINT DEFAULT 0,
    rows_warned BIGINT DEFAULT 0,
    quality_score DOUBLE,
    error_message VARCHAR
);

-- Staging mirrors the canonical entities but permits duplicates so that
-- uniqueness violations can be detected and quarantined rather than silently
-- overwritten. Staging rows remain available for audit.
CREATE TABLE IF NOT EXISTS staging_exposures (
    batch_id VARCHAR NOT NULL,
    staging_row_number BIGINT NOT NULL,
    exposure_id VARCHAR,
    bank_id VARCHAR,
    customer_id VARCHAR,
    snapshot_date DATE,
    product_type VARCHAR,
    industry_sector VARCHAR,
    region VARCHAR,
    rating_grade VARCHAR,
    exposure_at_default DOUBLE,
    outstanding_balance DOUBLE,
    currency VARCHAR,
    origination_date DATE,
    maturity_date DATE,
    default_flag BOOLEAN,
    default_date DATE
);

CREATE TABLE IF NOT EXISTS staging_rating_history (
    batch_id VARCHAR NOT NULL,
    staging_row_number BIGINT NOT NULL,
    exposure_id VARCHAR,
    bank_id VARCHAR,
    observation_date DATE,
    rating_grade VARCHAR
);

CREATE TABLE IF NOT EXISTS staging_collateral (
    batch_id VARCHAR NOT NULL,
    staging_row_number BIGINT NOT NULL,
    collateral_id VARCHAR,
    exposure_id VARCHAR,
    bank_id VARCHAR,
    collateral_type VARCHAR,
    collateral_value DOUBLE,
    valuation_date DATE,
    currency VARCHAR
);

CREATE TABLE IF NOT EXISTS staging_recovery_cashflows (
    batch_id VARCHAR NOT NULL,
    staging_row_number BIGINT NOT NULL,
    cashflow_id VARCHAR,
    exposure_id VARCHAR,
    bank_id VARCHAR,
    payment_date DATE,
    recovery_amount DOUBLE,
    recovery_type VARCHAR,
    adjustment_reason VARCHAR
);

CREATE TABLE IF NOT EXISTS exposures (
    exposure_id VARCHAR NOT NULL,
    bank_id VARCHAR NOT NULL,
    customer_id VARCHAR,
    snapshot_date DATE NOT NULL,
    product_type VARCHAR,
    industry_sector VARCHAR,
    region VARCHAR,
    rating_grade VARCHAR,
    exposure_at_default DOUBLE,
    outstanding_balance DOUBLE,
    currency VARCHAR,
    origination_date DATE,
    maturity_date DATE,
    default_flag BOOLEAN,
    default_date DATE,
    batch_id VARCHAR,
    PRIMARY KEY (exposure_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS rating_history (
    exposure_id VARCHAR NOT NULL,
    bank_id VARCHAR NOT NULL,
    observation_date DATE NOT NULL,
    rating_grade VARCHAR,
    batch_id VARCHAR,
    PRIMARY KEY (exposure_id, observation_date)
);

CREATE TABLE IF NOT EXISTS collateral (
    collateral_id VARCHAR NOT NULL,
    exposure_id VARCHAR NOT NULL,
    bank_id VARCHAR NOT NULL,
    collateral_type VARCHAR,
    collateral_value DOUBLE,
    valuation_date DATE NOT NULL,
    currency VARCHAR,
    batch_id VARCHAR,
    PRIMARY KEY (collateral_id, valuation_date)
);

CREATE TABLE IF NOT EXISTS recovery_cashflows (
    cashflow_id VARCHAR PRIMARY KEY,
    exposure_id VARCHAR NOT NULL,
    bank_id VARCHAR NOT NULL,
    payment_date DATE NOT NULL,
    recovery_amount DOUBLE,
    recovery_type VARCHAR,
    adjustment_reason VARCHAR,
    batch_id VARCHAR
);

CREATE TABLE IF NOT EXISTS dq_rule_catalog (
    rule_id VARCHAR PRIMARY KEY,
    rule_name VARCHAR NOT NULL,
    dataset_type VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    description VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS quality_results (
    quality_result_id VARCHAR PRIMARY KEY,
    batch_id VARCHAR NOT NULL,
    dataset_type VARCHAR NOT NULL,
    bank_id VARCHAR,
    reporting_date DATE,
    record_id VARCHAR,
    rule_id VARCHAR NOT NULL,
    rule_name VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    field_name VARCHAR,
    failed_value VARCHAR,
    reason VARCHAR NOT NULL,
    execution_timestamp TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS quarantine_records (
    quarantine_id VARCHAR PRIMARY KEY,
    batch_id VARCHAR NOT NULL,
    dataset_type VARCHAR NOT NULL,
    bank_id VARCHAR,
    reporting_date DATE,
    record_id VARCHAR,
    rule_ids VARCHAR,
    severity VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    record_json VARCHAR NOT NULL,
    quarantined_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS report_log (
    report_id VARCHAR PRIMARY KEY,
    report_type VARCHAR NOT NULL,
    module VARCHAR,
    file_format VARCHAR NOT NULL,
    bank_id VARCHAR,
    reporting_date DATE,
    file_path VARCHAR NOT NULL,
    generated_at TIMESTAMP NOT NULL,
    status VARCHAR NOT NULL,
    data_version VARCHAR,
    batch_ids VARCHAR,
    error_message VARCHAR
);

CREATE TABLE IF NOT EXISTS distribution_log (
    distribution_id VARCHAR PRIMARY KEY,
    report_id VARCHAR,
    channel VARCHAR NOT NULL,
    recipient_group VARCHAR,
    status VARCHAR NOT NULL,
    distributed_at TIMESTAMP NOT NULL,
    detail VARCHAR
);
