from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Iterable

from src.offers.models import QueueOffer


class OfferRepository:
    """Repositório SQLite independente das tabelas atuais do PromoBot."""

    def __init__(self, database_path, migration_path=None):
        self.database_path = str(database_path)
        self.migration_path = Path(migration_path or (
            Path(__file__).resolve().parent
            / "migrations"
            / "001_offer_queue.sql"
        ))
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
            timeout=30,
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")

    def migrate(self):
        script = self.migration_path.read_text(encoding="utf-8")
        with self.lock:
            self.conn.executescript(script)
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()

    def enqueue(self, offer: QueueOffer) -> tuple[QueueOffer, bool]:
        now = self.iso(offer.created_at or self.now())
        available = self.iso(offer.available_at or self.now())
        expires = self.iso(offer.expires_at)
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self.conn.execute(
                    "SELECT id FROM offer_queue WHERE promotion_signature=?",
                    (offer.promotion_signature,),
                ).fetchone()
                if existing:
                    self.conn.execute("""
                        UPDATE offer_queue SET
                            evaluation_id=?, product_id=?, title=?, store=?,
                            category=?, current_price=?, previous_price=?,
                            discount_percent=?, saving_amount=?, score=?,
                            classification=?, confidence=?,
                            score_components_json=?, priority=?,
                            available_at=?, expires_at=?, updated_at=?
                        WHERE id=?
                    """, (
                        offer.evaluation_id,
                        offer.product_id,
                        offer.title,
                        offer.store,
                        offer.category,
                        offer.current_price,
                        offer.previous_price,
                        offer.discount_percent,
                        offer.saving_amount,
                        offer.score,
                        offer.classification,
                        offer.confidence,
                        json.dumps(dict(offer.score_components)),
                        offer.priority,
                        available,
                        expires,
                        now,
                        existing["id"],
                    ))
                    item_id = existing["id"]
                    created = False
                else:
                    cursor = self.conn.execute("""
                        INSERT INTO offer_queue(
                            evaluation_id, product_id, canonical_identity,
                            promotion_signature, title, store, category,
                            current_price, previous_price, discount_percent,
                            saving_amount, score, classification, confidence,
                            score_components_json, status, priority,
                            available_at, expires_at, blocked_reason, blocked_at,
                            created_at, updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        offer.evaluation_id,
                        offer.product_id,
                        offer.canonical_identity,
                        offer.promotion_signature,
                        offer.title,
                        offer.store,
                        offer.category,
                        offer.current_price,
                        offer.previous_price,
                        offer.discount_percent,
                        offer.saving_amount,
                        offer.score,
                        offer.classification,
                        offer.confidence,
                        json.dumps(dict(offer.score_components)),
                        offer.status,
                        offer.priority,
                        available,
                        expires,
                        offer.blocked_reason,
                        self.iso(offer.blocked_at),
                        now,
                        now,
                    ))
                    item_id = cursor.lastrowid
                    created = True
                    self._audit(
                        item_id,
                        "enqueue",
                        "",
                        offer.status,
                        "Oferta inserida na fila.",
                    )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self.get(item_id), created

    def get(self, item_id: int) -> QueueOffer | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM offer_queue WHERE id=?",
                (int(item_id),),
            ).fetchone()
            return self.to_offer(row) if row else None

    def list_by_status(
        self,
        statuses: Iterable[str] | None = None,
        limit: int = 500,
    ) -> list[QueueOffer]:
        statuses = tuple(statuses or ())
        params: list = []
        where = ""
        if statuses:
            marks = ",".join("?" for _ in statuses)
            where = f"WHERE status IN ({marks})"
            params.extend(statuses)
        params.append(max(int(limit), 1))
        with self.lock:
            rows = self.conn.execute(f"""
                SELECT * FROM offer_queue
                {where}
                ORDER BY priority DESC, score DESC, confidence DESC,
                         created_at ASC, id ASC
                LIMIT ?
            """, params).fetchall()
            return [self.to_offer(row) for row in rows]

    def transition(
        self,
        item_id: int,
        allowed_from: Iterable[str],
        new_status: str,
        reason: str = "",
        run_id: str = "",
        fields: dict | None = None,
    ) -> QueueOffer:
        allowed = tuple(allowed_from)
        fields = dict(fields or {})
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute(
                    "SELECT status FROM offer_queue WHERE id=?",
                    (int(item_id),),
                ).fetchone()
                if not row:
                    raise KeyError(f"Oferta {item_id} não encontrada.")
                previous = row["status"]
                if previous not in allowed:
                    raise ValueError(
                        f"Transição inválida: {previous} -> {new_status}."
                    )
                assignments = ["status=?", "updated_at=?"]
                params = [new_status, self.iso(self.now())]
                for name, value in fields.items():
                    assignments.append(f"{name}=?")
                    params.append(
                        self.iso(value)
                        if isinstance(value, datetime)
                        else value
                    )
                params.append(int(item_id))
                self.conn.execute(
                    f"UPDATE offer_queue SET {', '.join(assignments)} WHERE id=?",
                    params,
                )
                self._audit(
                    item_id,
                    "transition",
                    previous,
                    new_status,
                    reason,
                    run_id,
                )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self.get(item_id)

    def reserve_ids(
        self,
        item_ids: Iterable[int],
        reserved_by: str,
        reserved_at: datetime,
        reservation_expires_at: datetime,
        run_id: str,
    ) -> list[QueueOffer]:
        ids = [int(item_id) for item_id in item_ids]
        if not ids:
            return []
        reserved = []
        now_text = self.iso(reserved_at)
        reservation_text = self.iso(reservation_expires_at)
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                for item_id in ids:
                    row = self.conn.execute("""
                        SELECT status, expires_at FROM offer_queue
                        WHERE id=? AND status='queued'
                          AND available_at <= ? AND expires_at > ?
                    """, (item_id, now_text, now_text)).fetchone()
                    if not row:
                        continue
                    effective_expiration = min(
                        self.datetime(row["expires_at"]),
                        reservation_expires_at,
                    )
                    cursor = self.conn.execute("""
                        UPDATE offer_queue SET
                            status='reserved', reserved_by=?, reserved_at=?,
                            reservation_expires_at=?, attempts=attempts+1,
                            updated_at=?
                        WHERE id=? AND status='queued'
                    """, (
                        reserved_by,
                        now_text,
                        self.iso(effective_expiration),
                        now_text,
                        item_id,
                    ))
                    if cursor.rowcount:
                        reserved.append(item_id)
                        self._audit(
                            item_id,
                            "reserve",
                            "queued",
                            "reserved",
                            f"Reservada por {reserved_by}.",
                            run_id,
                        )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return [self.get(item_id) for item_id in reserved]

    def release_expired_reservations(self, now: datetime) -> int:
        now_text = self.iso(now)
        with self.lock:
            rows = self.conn.execute("""
                SELECT id FROM offer_queue
                WHERE status='reserved' AND reservation_expires_at <= ?
                  AND expires_at > ?
            """, (now_text, now_text)).fetchall()
            for row in rows:
                self.transition(
                    row["id"],
                    ("reserved",),
                    "queued",
                    "Reserva vencida liberada.",
                    fields={
                        "reserved_by": "",
                        "reserved_at": None,
                        "reservation_expires_at": None,
                    },
                )
            return len(rows)

    def expire_due(self, now: datetime) -> int:
        now_text = self.iso(now)
        with self.lock:
            rows = self.conn.execute("""
                SELECT id, status FROM offer_queue
                WHERE expires_at <= ?
                  AND status IN ('queued','blocked','reserved')
            """, (now_text,)).fetchall()
            for row in rows:
                self.transition(
                    row["id"],
                    (row["status"],),
                    "expired",
                    "Prazo da oferta encerrado.",
                )
            return len(rows)

    def count_selected_since(self, since: datetime) -> int:
        with self.lock:
            return int(self.conn.execute("""
                SELECT COUNT(*) FROM offer_queue_decisions
                WHERE new_status='selected_shadow' AND created_at >= ?
            """, (self.iso(since),)).fetchone()[0])

    def last_selected_at(self) -> datetime | None:
        with self.lock:
            value = self.conn.execute("""
                SELECT MAX(created_at) FROM offer_scheduler_runs
                WHERE selected_count > 0
            """).fetchone()[0]
            return self.datetime(value) if value else None

    def record_scheduler_run(
        self,
        run_id: str,
        selected_count: int,
        hourly_remaining: int,
        daily_remaining: int,
        reasons: Iterable[str],
        created_at: datetime,
    ):
        with self.lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO offer_scheduler_runs(
                    run_id, selected_count, hourly_remaining, daily_remaining,
                    reasons_json, shadow_mode, created_at
                ) VALUES(?,?,?,?,?,1,?)
            """, (
                run_id,
                selected_count,
                hourly_remaining,
                daily_remaining,
                json.dumps(list(reasons), ensure_ascii=False),
                self.iso(created_at),
            ))
            self.conn.commit()

    def decisions(self, item_id=None):
        with self.lock:
            if item_id is None:
                return self.conn.execute(
                    "SELECT * FROM offer_queue_decisions ORDER BY id"
                ).fetchall()
            return self.conn.execute("""
                SELECT * FROM offer_queue_decisions
                WHERE queue_item_id=? ORDER BY id
            """, (int(item_id),)).fetchall()

    def record_decision(
        self,
        item_id: int,
        action: str,
        reason: str,
        run_id: str = "",
    ):
        with self.lock:
            row = self.conn.execute(
                "SELECT status FROM offer_queue WHERE id=?",
                (int(item_id),),
            ).fetchone()
            if not row:
                return
            self._audit(
                item_id,
                action,
                row["status"],
                row["status"],
                reason,
                run_id,
            )
            self.conn.commit()

    def table_names(self):
        with self.lock:
            return {
                row[0] for row in self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

    def index_names(self):
        with self.lock:
            return {
                row[0] for row in self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }

    def _audit(
        self,
        item_id,
        action,
        previous_status,
        new_status,
        reason,
        run_id="",
    ):
        self.conn.execute("""
            INSERT INTO offer_queue_decisions(
                scheduler_run_id, queue_item_id, action, previous_status,
                new_status, reason, shadow_mode, created_at
            ) VALUES(?,?,?,?,?,?,1,?)
        """, (
            run_id,
            int(item_id),
            action,
            previous_status,
            new_status,
            reason,
            self.iso(self.now()),
        ))

    @classmethod
    def to_offer(cls, row) -> QueueOffer:
        return QueueOffer(
            id=row["id"],
            evaluation_id=row["evaluation_id"],
            product_id=row["product_id"],
            canonical_identity=row["canonical_identity"],
            promotion_signature=row["promotion_signature"],
            title=row["title"],
            store=row["store"],
            category=row["category"],
            current_price=row["current_price"],
            previous_price=row["previous_price"],
            discount_percent=row["discount_percent"],
            saving_amount=row["saving_amount"],
            score=row["score"],
            classification=row["classification"],
            confidence=row["confidence"],
            score_components=json.loads(row["score_components_json"] or "{}"),
            status=row["status"],
            priority=row["priority"],
            available_at=cls.datetime(row["available_at"]),
            expires_at=cls.datetime(row["expires_at"]),
            reserved_at=cls.datetime(row["reserved_at"]),
            reserved_by=row["reserved_by"],
            reservation_expires_at=cls.datetime(
                row["reservation_expires_at"]
            ),
            attempts=row["attempts"],
            last_error=row["last_error"],
            blocked_reason=row["blocked_reason"],
            blocked_at=cls.datetime(row["blocked_at"]),
            created_at=cls.datetime(row["created_at"]),
            updated_at=cls.datetime(row["updated_at"]),
            sent_at=cls.datetime(row["sent_at"]),
        )

    @staticmethod
    def now():
        return datetime.now(timezone.utc)

    @staticmethod
    def iso(value):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def datetime(value):
        if not value:
            return None
        result = datetime.fromisoformat(str(value))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
