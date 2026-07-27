CREATE TABLE IF NOT EXISTS offer_activation_sessions (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    stage INTEGER NOT NULL DEFAULT 0,
    actor TEXT NOT NULL DEFAULT '',
    dry_run INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT,
    ended_at TEXT,
    final_result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offer_activation_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT '',
    check_name TEXT NOT NULL,
    passed INTEGER NOT NULL,
    critical INTEGER NOT NULL DEFAULT 1,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offer_activation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offer_canary_auto_stops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offer_activation_decisions (
    session_id TEXT NOT NULL,
    audit_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_activation_sessions_created
ON offer_activation_sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_activation_checks_session
ON offer_activation_checks(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_activation_events_session
ON offer_activation_events(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_auto_stops_created
ON offer_canary_auto_stops(created_at);
CREATE INDEX IF NOT EXISTS idx_activation_decisions_session
ON offer_activation_decisions(session_id, created_at);
