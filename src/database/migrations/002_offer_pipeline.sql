CREATE TABLE IF NOT EXISTS offer_price_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_identity TEXT NOT NULL,
    price REAL NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offer_pipeline_runs (
    run_id TEXT PRIMARY KEY,
    received_count INTEGER NOT NULL DEFAULT 0,
    valid_count INTEGER NOT NULL DEFAULT 0,
    discarded_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    blocked_count INTEGER NOT NULL DEFAULT 0,
    approved_count INTEGER NOT NULL DEFAULT 0,
    queued_count INTEGER NOT NULL DEFAULT 0,
    selected_shadow_count INTEGER NOT NULL DEFAULT 0,
    average_score REAL NOT NULL DEFAULT 0,
    average_processing_ms REAL NOT NULL DEFAULT 0,
    stage_timings_json TEXT NOT NULL DEFAULT '{}',
    shadow_mode INTEGER NOT NULL DEFAULT 1,
    affects_current_flow INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offer_pipeline_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    product_id TEXT NOT NULL DEFAULT '',
    canonical_identity TEXT NOT NULL DEFAULT '',
    promotion_signature TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    store TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0,
    classification TEXT NOT NULL DEFAULT 'oferta_fraca',
    filter_approved INTEGER NOT NULL DEFAULT 0,
    duplicate_type TEXT NOT NULL DEFAULT '',
    queue_item_id INTEGER,
    queue_status TEXT NOT NULL DEFAULT '',
    scheduler_status TEXT NOT NULL DEFAULT '',
    diagnostic_json TEXT NOT NULL DEFAULT '{}',
    processing_ms REAL NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    shadow_mode INTEGER NOT NULL DEFAULT 1,
    affects_current_flow INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES offer_pipeline_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_offer_observations_identity_time
ON offer_price_observations(canonical_identity, observed_at);

CREATE INDEX IF NOT EXISTS idx_offer_pipeline_runs_created
ON offer_pipeline_runs(created_at);

CREATE INDEX IF NOT EXISTS idx_offer_pipeline_items_run
ON offer_pipeline_items(run_id);

CREATE INDEX IF NOT EXISTS idx_offer_pipeline_items_identity
ON offer_pipeline_items(canonical_identity);

CREATE INDEX IF NOT EXISTS idx_offer_pipeline_items_score
ON offer_pipeline_items(score DESC);

CREATE INDEX IF NOT EXISTS idx_offer_pipeline_items_queue_status
ON offer_pipeline_items(queue_status);
