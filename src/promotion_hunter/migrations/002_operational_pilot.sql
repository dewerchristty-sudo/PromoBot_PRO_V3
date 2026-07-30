PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS promotion_hunter_delivery_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL,
    run_id TEXT NOT NULL,
    title TEXT NOT NULL,
    store TEXT NOT NULL,
    current_price REAL,
    previous_price REAL,
    image_url TEXT,
    product_url TEXT,
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    pipeline_status TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    approved_at TEXT NOT NULL,
    last_attempt_at TEXT,
    sent_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hunter_queue_status
ON promotion_hunter_delivery_queue(status, approved_at);

CREATE INDEX IF NOT EXISTS idx_hunter_queue_product_sent
ON promotion_hunter_delivery_queue(product_key, sent_at);

CREATE TABLE IF NOT EXISTS promotion_hunter_delivery_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    FOREIGN KEY(queue_id) REFERENCES promotion_hunter_delivery_queue(id)
);

CREATE INDEX IF NOT EXISTS idx_hunter_attempts_queue
ON promotion_hunter_delivery_attempts(queue_id, id);

CREATE TABLE IF NOT EXISTS promotion_hunter_scheduler_state (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    running INTEGER NOT NULL DEFAULT 0,
    last_run_at TEXT,
    next_run_at TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO promotion_hunter_scheduler_state(singleton_id)
VALUES(1);
