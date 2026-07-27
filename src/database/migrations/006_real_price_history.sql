PRAGMA foreign_keys=OFF;

CREATE TABLE offer_price_history_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_identity TEXT NOT NULL,
    product_key TEXT NOT NULL DEFAULT '',
    canonical_product_id TEXT NOT NULL DEFAULT '',
    canonical_url TEXT NOT NULL DEFAULT '',
    observation_date TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    store TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    price NUMERIC NOT NULL CHECK(price > 0),
    currency TEXT NOT NULL DEFAULT 'BRL',
    original_url TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '',
    availability TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    valid INTEGER NOT NULL DEFAULT 1,
    rejection_reason TEXT NOT NULL DEFAULT '',
    observation_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

INSERT INTO offer_price_history_v2(
    id, canonical_identity, observation_date, observed_at, store, title,
    price, currency, original_url, image_url, availability, source,
    observation_hash, created_at
)
SELECT
    id, canonical_identity, observation_date, observed_at, store, title,
    price, currency, original_url, image_url, availability, source,
    'legacy:' || id, created_at
FROM offer_price_history;

DROP TABLE offer_price_history;
ALTER TABLE offer_price_history_v2 RENAME TO offer_price_history;

CREATE INDEX idx_price_history_identity_time
ON offer_price_history(canonical_identity, observed_at);
CREATE INDEX idx_price_history_product_time
ON offer_price_history(product_key, observed_at);
CREATE INDEX idx_price_history_store_time
ON offer_price_history(store, observed_at);
CREATE INDEX idx_price_history_date
ON offer_price_history(observation_date);

CREATE TABLE IF NOT EXISTS offer_price_history_rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL DEFAULT '',
    canonical_identity TEXT NOT NULL DEFAULT '',
    store TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    observed_price TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT '',
    original_url TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL,
    observation_hash TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_price_rejections_product_time
ON offer_price_history_rejections(product_key, observed_at);

PRAGMA foreign_keys=ON;
