from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import threading


class AffiliateCache:

    def __init__(self, path, ttl_hours=720, clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(hours=max(int(ttl_hours), 1))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(
            str(self.path), check_same_thread=False, timeout=30
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS affiliate_link_cache(
                store TEXT NOT NULL,
                original_url TEXT NOT NULL,
                affiliate_url TEXT NOT NULL,
                provider TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY(store, original_url)
            )
        """)
        self.conn.commit()

    def get(self, store, original_url):
        now = self.clock()
        with self.lock:
            row = self.conn.execute("""
                SELECT * FROM affiliate_link_cache
                WHERE store=? AND original_url=?
            """, (store, original_url)).fetchone()
            if not row:
                return None
            expires = datetime.fromisoformat(row["expires_at"])
            if expires <= now:
                self.conn.execute("""
                    DELETE FROM affiliate_link_cache
                    WHERE store=? AND original_url=?
                """, (store, original_url))
                self.conn.commit()
                return None
            return dict(row)

    def put(self, store, original_url, affiliate_url, provider, source):
        now = self.clock()
        with self.lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO affiliate_link_cache(
                    store, original_url, affiliate_url, provider, source,
                    created_at, expires_at
                ) VALUES(?,?,?,?,?,?,?)
            """, (
                store, original_url, affiliate_url, provider, source,
                now.isoformat(), (now + self.ttl).isoformat(),
            ))
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()
