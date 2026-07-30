PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS promotion_hunter_sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    store TEXT NOT NULL,
    display_name TEXT NOT NULL,
    configuration_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    item_limit INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS promotion_hunter_runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    collected_count INTEGER NOT NULL DEFAULT 0,
    unique_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS promotion_hunter_source_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL,
    returned_count INTEGER,
    normalized_count INTEGER,
    added_count INTEGER,
    error_type TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY(run_id) REFERENCES promotion_hunter_runs(run_id),
    FOREIGN KEY(source_id) REFERENCES promotion_hunter_sources(source_id)
);

CREATE TABLE IF NOT EXISTS promotion_hunter_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    product_key TEXT NOT NULL,
    decision_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    score REAL,
    classification TEXT,
    pipeline_run_id TEXT,
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES promotion_hunter_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_hunter_source_runs_run
ON promotion_hunter_source_runs(run_id);

CREATE INDEX IF NOT EXISTS idx_hunter_source_runs_source
ON promotion_hunter_source_runs(source_id);

CREATE INDEX IF NOT EXISTS idx_hunter_decisions_run
ON promotion_hunter_decisions(run_id);

CREATE INDEX IF NOT EXISTS idx_hunter_decisions_status
ON promotion_hunter_decisions(decision_status);

CREATE INDEX IF NOT EXISTS idx_hunter_decisions_product
ON promotion_hunter_decisions(product_key);
