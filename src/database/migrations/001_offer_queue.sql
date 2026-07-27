CREATE TABLE IF NOT EXISTS offer_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id TEXT NOT NULL,
    product_id TEXT NOT NULL DEFAULT '',
    canonical_identity TEXT NOT NULL,
    promotion_signature TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL DEFAULT '',
    store TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    current_price REAL NOT NULL DEFAULT 0,
    previous_price REAL NOT NULL DEFAULT 0,
    discount_percent REAL NOT NULL DEFAULT 0,
    saving_amount REAL NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    classification TEXT NOT NULL DEFAULT 'oferta_fraca',
    confidence REAL NOT NULL DEFAULT 0,
    score_components_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued' CHECK (
        status IN (
            'queued', 'blocked', 'reserved', 'selected_shadow', 'sent',
            'expired', 'discarded', 'failed', 'cancelled'
        )
    ),
    priority REAL NOT NULL DEFAULT 0,
    available_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    reserved_at TEXT,
    reserved_by TEXT NOT NULL DEFAULT '',
    reservation_expires_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    blocked_reason TEXT NOT NULL DEFAULT '',
    blocked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sent_at TEXT
);

CREATE TABLE IF NOT EXISTS offer_scheduler_runs (
    run_id TEXT PRIMARY KEY,
    selected_count INTEGER NOT NULL DEFAULT 0,
    hourly_remaining INTEGER NOT NULL DEFAULT 0,
    daily_remaining INTEGER NOT NULL DEFAULT 0,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    shadow_mode INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offer_queue_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduler_run_id TEXT NOT NULL DEFAULT '',
    queue_item_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    previous_status TEXT NOT NULL DEFAULT '',
    new_status TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    shadow_mode INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(queue_item_id) REFERENCES offer_queue(id)
);

CREATE INDEX IF NOT EXISTS idx_offer_queue_status
ON offer_queue(status);

CREATE INDEX IF NOT EXISTS idx_offer_queue_score
ON offer_queue(score DESC);

CREATE INDEX IF NOT EXISTS idx_offer_queue_priority
ON offer_queue(priority DESC);

CREATE INDEX IF NOT EXISTS idx_offer_queue_available_at
ON offer_queue(available_at);

CREATE INDEX IF NOT EXISTS idx_offer_queue_expires_at
ON offer_queue(expires_at);

CREATE INDEX IF NOT EXISTS idx_offer_queue_identity
ON offer_queue(canonical_identity);

CREATE UNIQUE INDEX IF NOT EXISTS idx_offer_queue_promotion
ON offer_queue(promotion_signature);

CREATE INDEX IF NOT EXISTS idx_offer_queue_reserved_by
ON offer_queue(reserved_by);

CREATE INDEX IF NOT EXISTS idx_offer_queue_reservation_expires
ON offer_queue(reservation_expires_at);

CREATE INDEX IF NOT EXISTS idx_offer_queue_created_at
ON offer_queue(created_at);

CREATE INDEX IF NOT EXISTS idx_offer_decisions_item_created
ON offer_queue_decisions(queue_item_id, created_at);

CREATE INDEX IF NOT EXISTS idx_offer_decisions_run
ON offer_queue_decisions(scheduler_run_id);
