from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .contracts import PromotionSource
from .models import HunterDecision


class PromotionHunterRepository:
    def __init__(
        self,
        database_path: str | Path = "promotion_hunter.db",
        migration_path: str | Path | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.migration_path = Path(migration_path) if migration_path else (
            Path(__file__).with_name("migrations") / "001_promotion_hunter.sql"
        )
        self.conn = sqlite3.connect(self.database_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()

    def migrate(self) -> None:
        with self.lock:
            migration_dir = self.migration_path.parent
            migrations = sorted(migration_dir.glob("*.sql"))
            for migration in migrations:
                self.conn.executescript(migration.read_text(encoding="utf-8"))
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert_source(self, source: PromotionSource) -> None:
        configuration = json.dumps(
            dict(source.configuration),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO promotion_hunter_sources(
                    source_id, source_type, store, display_name,
                    configuration_json, enabled, item_limit
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_type=excluded.source_type,
                    store=excluded.store,
                    display_name=excluded.display_name,
                    configuration_json=excluded.configuration_json,
                    enabled=excluded.enabled,
                    item_limit=excluded.item_limit,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    source.source_id,
                    source.source_type,
                    source.store,
                    source.display_name,
                    configuration,
                    int(source.enabled),
                    source.limit,
                ),
            )
            self.conn.commit()

    def start_run(self, run_id: str, started_at: str) -> None:
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO promotion_hunter_runs(run_id, status, started_at)
                VALUES(?, 'running', ?)
                """,
                (run_id, started_at),
            )
            self.conn.commit()

    def finish_run(
        self,
        run_id: str,
        status: str,
        collected_count: int,
        unique_count: int,
        finished_at: str,
    ) -> None:
        with self.lock:
            self.conn.execute(
                """
                UPDATE promotion_hunter_runs
                SET status=?, collected_count=?, unique_count=?, finished_at=?
                WHERE run_id=?
                """,
                (
                    status,
                    collected_count,
                    unique_count,
                    finished_at,
                    run_id,
                ),
            )
            self.conn.commit()

    def record_source_run(
        self,
        run_id: str,
        source_id: str,
        status: str,
        returned_count: int,
        normalized_count: int,
        added_count: int,
        error_type: str | None,
        error_message: str | None,
        started_at: str,
        finished_at: str,
    ) -> None:
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO promotion_hunter_source_runs(
                    run_id, source_id, status, returned_count,
                    normalized_count, added_count, error_type, error_message,
                    started_at, finished_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    source_id,
                    status,
                    returned_count,
                    normalized_count,
                    added_count,
                    error_type,
                    error_message,
                    started_at,
                    finished_at,
                ),
            )
            self.conn.commit()

    def record_decisions(
        self,
        run_id: str,
        decisions: Iterable[HunterDecision],
    ) -> None:
        rows = [
            (
                run_id,
                decision.product_key,
                decision.status.value,
                decision.reason,
                decision.score,
                decision.classification,
                decision.pipeline_run_id,
                json.dumps(decision.source_ids, ensure_ascii=False),
                decision.created_at.isoformat(),
            )
            for decision in decisions
        ]
        if not rows:
            return
        with self.lock:
            self.conn.executemany(
                """
                INSERT INTO promotion_hunter_decisions(
                    run_id, product_key, decision_status, reason, score,
                    classification, pipeline_run_id, source_ids_json, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
            self.conn.commit()

    def enqueue_approved(self, run_id, product, decision):
        now = datetime.now(timezone.utc).isoformat()
        payload = dict(decision.delivery_payload or {})
        with self.lock:
            cursor = self.conn.execute(
                """
                INSERT INTO promotion_hunter_delivery_queue(
                    product_key, run_id, title, store, current_price,
                    previous_price, image_url, product_url, source_ids_json,
                    pipeline_status, approved_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    product.deduplication_key, run_id,
                    payload.get("title") or product.title,
                    payload.get("store") or product.store,
                    payload.get("current_price", product.current_price),
                    payload.get("previous_price", product.previous_price),
                    payload.get("image_url") or product.image_url,
                    payload.get("product_url") or product.url,
                    json.dumps(product.source_ids, ensure_ascii=False),
                    decision.status.value, now,
                ),
            )
            self.conn.commit()
            return int(cursor.lastrowid)

    def queue_items(self, statuses=("pending",), limit=100):
        placeholders = ",".join("?" for _ in statuses)
        with self.lock:
            return tuple(self.conn.execute(
                f"""
                SELECT * FROM promotion_hunter_delivery_queue
                WHERE status IN ({placeholders})
                ORDER BY approved_at, id
                LIMIT ?
                """,
                (*statuses, int(limit)),
            ).fetchall())

    def recently_sent(self, product_key, since):
        with self.lock:
            return self.conn.execute(
                """
                SELECT * FROM promotion_hunter_delivery_queue
                WHERE product_key=? AND status='sent' AND sent_at>=?
                ORDER BY sent_at DESC LIMIT 1
                """,
                (product_key, since),
            ).fetchone()

    def start_attempt(self, queue_id, started_at):
        with self.lock:
            self.conn.execute(
                """
                UPDATE promotion_hunter_delivery_queue
                SET status='sending', attempts=attempts+1,
                    last_attempt_at=?, updated_at=?
                WHERE id=? AND status IN ('pending','failed')
                """,
                (started_at, started_at, queue_id),
            )
            cursor = self.conn.execute(
                """
                INSERT INTO promotion_hunter_delivery_attempts(
                    queue_id, started_at, status
                ) VALUES(?,?,'sending')
                """,
                (queue_id, started_at),
            )
            self.conn.commit()
            return int(cursor.lastrowid)

    def finish_attempt(self, queue_id, attempt_id, status, finished_at, error=""):
        queue_status = "sent" if status == "sent" else "failed"
        with self.lock:
            self.conn.execute(
                """
                UPDATE promotion_hunter_delivery_attempts
                SET status=?, finished_at=?, error_message=?
                WHERE id=? AND queue_id=?
                """,
                (status, finished_at, error, attempt_id, queue_id),
            )
            self.conn.execute(
                """
                UPDATE promotion_hunter_delivery_queue
                SET status=?, sent_at=CASE WHEN ?='sent' THEN ? ELSE sent_at END,
                    last_error=?, updated_at=?
                WHERE id=?
                """,
                (
                    queue_status, status, finished_at, error,
                    finished_at, queue_id,
                ),
            )
            self.conn.commit()

    def recover_sending(self):
        with self.lock:
            cursor = self.conn.execute(
                """
                UPDATE promotion_hunter_delivery_queue
                SET status='failed',
                    last_error='resultado anterior indeterminado; revisão necessária',
                    updated_at=CURRENT_TIMESTAMP
                WHERE status='sending'
                """
            )
            self.conn.commit()
            return cursor.rowcount

    def sent_count_since(self, since):
        with self.lock:
            return int(self.conn.execute(
                """
                SELECT COUNT(*) FROM promotion_hunter_delivery_queue
                WHERE status='sent' AND sent_at>=?
                """,
                (since,),
            ).fetchone()[0])

    def last_sent_at(self):
        with self.lock:
            row = self.conn.execute(
                """
                SELECT MAX(sent_at) FROM promotion_hunter_delivery_queue
                WHERE status='sent'
                """
            ).fetchone()
        return row[0] if row else None

    def update_scheduler_state(self, running, last_run_at=None,
                               next_run_at=None, last_error=""):
        with self.lock:
            self.conn.execute(
                """
                UPDATE promotion_hunter_scheduler_state
                SET running=?, last_run_at=?, next_run_at=?, last_error=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE singleton_id=1
                """,
                (
                    int(bool(running)), last_run_at, next_run_at,
                    str(last_error or "")[:300],
                ),
            )
            self.conn.commit()

    def scheduler_state(self):
        with self.lock:
            return self.conn.execute(
                """
                SELECT * FROM promotion_hunter_scheduler_state
                WHERE singleton_id=1
                """
            ).fetchone()
