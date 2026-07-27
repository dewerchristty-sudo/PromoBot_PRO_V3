CREATE TABLE IF NOT EXISTS offer_price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_identity TEXT NOT NULL,
    observation_date TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    store TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    price REAL NOT NULL CHECK(price > 0),
    currency TEXT NOT NULL DEFAULT 'BRL',
    original_url TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '',
    availability TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(canonical_identity, observation_date, price)
);

CREATE INDEX IF NOT EXISTS idx_price_history_identity_time
ON offer_price_history(canonical_identity, observed_at);

CREATE INDEX IF NOT EXISTS idx_price_history_store_time
ON offer_price_history(store, observed_at);

CREATE INDEX IF NOT EXISTS idx_price_history_date
ON offer_price_history(observation_date);

INSERT OR IGNORE INTO offer_price_history(
    canonical_identity, observation_date, observed_at, store, title,
    price, currency, original_url, image_url, availability, source,
    created_at
)
SELECT
    canonical_identity,
    substr(observed_at, 1, 10),
    observed_at,
    source,
    '',
    price,
    'BRL',
    '',
    '',
    '',
    source,
    observed_at
FROM offer_price_observations
WHERE price > 0;
