CREATE TABLE IF NOT EXISTS offer_duplicate_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_signature TEXT NOT NULL,
    similarity_signature TEXT NOT NULL DEFAULT '',
    link_signature TEXT NOT NULL DEFAULT '',
    promotion_signature TEXT NOT NULL,
    price REAL NOT NULL,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(identity_signature, promotion_signature, occurred_at)
);

CREATE INDEX IF NOT EXISTS idx_offer_duplicate_history_identity_time
ON offer_duplicate_history(identity_signature, occurred_at);

CREATE INDEX IF NOT EXISTS idx_offer_duplicate_history_link_time
ON offer_duplicate_history(link_signature, occurred_at);

-- Reidrata o histórico já conhecido sem apagar ou alterar a fila existente.
INSERT OR IGNORE INTO offer_duplicate_history(
    identity_signature, similarity_signature, link_signature,
    promotion_signature, price, occurred_at
)
SELECT canonical_identity, '', '', promotion_signature,
       current_price, created_at
FROM offer_queue
WHERE canonical_identity <> '' AND promotion_signature <> '';
