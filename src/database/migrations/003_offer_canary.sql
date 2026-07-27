CREATE TABLE IF NOT EXISTS offer_canary_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT NOT NULL UNIQUE,
    canonical_identity TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    store TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0,
    scheduler TEXT NOT NULL DEFAULT 'legado',
    legacy_decision TEXT NOT NULL DEFAULT '',
    intelligent_decision TEXT NOT NULL DEFAULT '',
    difference TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    flags_json TEXT NOT NULL DEFAULT '{}',
    canary_percent INTEGER NOT NULL DEFAULT 0,
    result TEXT NOT NULL DEFAULT '',
    sent INTEGER NOT NULL DEFAULT 0,
    rollback_reason TEXT NOT NULL DEFAULT '',
    decision_ms REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_offer_canary_created
ON offer_canary_decisions(created_at);

CREATE INDEX IF NOT EXISTS idx_offer_canary_scheduler
ON offer_canary_decisions(scheduler, created_at);

CREATE INDEX IF NOT EXISTS idx_offer_canary_identity
ON offer_canary_decisions(canonical_identity, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_offer_canary_sent_identity
ON offer_canary_decisions(canonical_identity)
WHERE sent=1;
