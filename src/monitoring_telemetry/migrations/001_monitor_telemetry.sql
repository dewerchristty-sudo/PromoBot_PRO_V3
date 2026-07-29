CREATE TABLE IF NOT EXISTS monitor_execution_runs(
    execution_id TEXT PRIMARY KEY,
    monitor_id INTEGER NOT NULL,
    search_term TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms REAL,
    configured_stores_json TEXT NOT NULL DEFAULT '[]',
    aggregate_total INTEGER,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_monitor_execution_monitor_started
ON monitor_execution_runs(monitor_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_monitor_execution_status_started
ON monitor_execution_runs(status, started_at DESC);

CREATE TABLE IF NOT EXISTS monitor_store_runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    store_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    returned_count INTEGER,
    sanitized_count INTEGER,
    aggregate_added_count INTEGER,
    status TEXT NOT NULL,
    error_type TEXT,
    sanitized_error TEXT,
    FOREIGN KEY(execution_id)
        REFERENCES monitor_execution_runs(execution_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_monitor_store_execution
ON monitor_store_runs(execution_id, id);

CREATE INDEX IF NOT EXISTS idx_monitor_store_name_status
ON monitor_store_runs(store_name, status);
