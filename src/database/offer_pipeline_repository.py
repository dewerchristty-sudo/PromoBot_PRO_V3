from datetime import datetime, timedelta
import hashlib
import json

from src.offers.history import OfferHistory, OfferHistoryStore
from src.offers.models import PriceObservation
from src.offers.duplicates import PreviousOffer

from .offer_repository import OfferRepository


class OfferPipelineRepository(OfferRepository, OfferHistoryStore):
    """Persistência exclusiva do pipeline sombra."""

    def __init__(
        self,
        database_path,
        pipeline_migration_path=None,
        canary_migration_path=None,
        activation_migration_path=None,
        price_history_migration_path=None,
        real_price_history_migration_path=None,
        duplicate_history_migration_path=None,
    ):
        super().__init__(database_path)
        self.pipeline_migration_path = (
            pipeline_migration_path
            or self.migration_path.with_name("002_offer_pipeline.sql")
        )
        self.canary_migration_path = (
            canary_migration_path
            or self.migration_path.with_name("003_offer_canary.sql")
        )
        self.activation_migration_path = (
            activation_migration_path
            or self.migration_path.with_name("004_offer_activation.sql")
        )
        self.price_history_migration_path = (
            price_history_migration_path
            or self.migration_path.with_name("005_price_history.sql")
        )
        self.real_price_history_migration_path = (
            real_price_history_migration_path
            or self.migration_path.with_name("006_real_price_history.sql")
        )
        self.duplicate_history_migration_path = (
            duplicate_history_migration_path
            or self.migration_path.with_name("007_duplicate_history.sql")
        )

    def migrate(self):
        super().migrate()
        script = self.pipeline_migration_path.read_text(encoding="utf-8")
        with self.lock:
            self.conn.executescript(script)
            self.conn.executescript(
                self.canary_migration_path.read_text(encoding="utf-8")
            )
            self.conn.executescript(
                self.activation_migration_path.read_text(encoding="utf-8")
            )
            self.conn.executescript(
                self.price_history_migration_path.read_text(encoding="utf-8")
            )
            columns = {
                row["name"] for row in self.conn.execute(
                    "PRAGMA table_info(offer_price_history)"
                ).fetchall()
            }
            if "product_key" not in columns:
                self.conn.executescript(
                    self.real_price_history_migration_path.read_text(
                        encoding="utf-8"
                    )
                )
            self.conn.executescript(
                self.duplicate_history_migration_path.read_text(
                    encoding="utf-8"
                )
            )
            self.conn.commit()

    def add_duplicate_offer(self, offer: PreviousOffer) -> None:
        with self.lock:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO offer_duplicate_history(
                    identity_signature, similarity_signature,
                    link_signature, promotion_signature, price, occurred_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    offer.identity_signature,
                    offer.similarity_signature,
                    offer.link_signature,
                    offer.promotion_signature,
                    float(offer.price),
                    self.iso(offer.occurred_at),
                ),
            )
            self.conn.commit()

    def recent_duplicate_offers(self, since):
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT identity_signature, similarity_signature,
                       link_signature, promotion_signature, price, occurred_at
                FROM offer_duplicate_history
                WHERE occurred_at >= ?
                ORDER BY occurred_at DESC
                """,
                (self.iso(since),),
            ).fetchall()
        return [
            PreviousOffer(
                identity_signature=row["identity_signature"],
                similarity_signature=row["similarity_signature"],
                link_signature=row["link_signature"],
                promotion_signature=row["promotion_signature"],
                price=float(row["price"]),
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
            )
            for row in rows
        ]

    def add(self, observation: PriceObservation) -> bool:
        price = float(observation.price or 0)
        if not observation.identity or price <= 0:
            return False
        with self.lock:
            observed_at = OfferHistory.normalize_datetime(
                observation.observed_at
            )
            observation_hash = hashlib.sha256(
                (
                    f"{observation.identity}|{observed_at.date()}|"
                    f"{price:.2f}"
                ).encode("utf-8")
            ).hexdigest()
            cursor = self.conn.execute("""
                INSERT OR IGNORE INTO offer_price_history(
                    canonical_identity, observation_date, observed_at,
                    store, title, price, currency, original_url,
                    image_url, availability, source, observation_hash,
                    created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                observation.identity,
                observed_at.date().isoformat(),
                self.iso(observed_at),
                observation.store,
                observation.title,
                price,
                observation.currency or "BRL",
                observation.original_url,
                observation.image_url,
                observation.availability,
                observation.source,
                observation_hash,
                self.iso(self.now()),
            ))
            self.conn.commit()
        return bool(cursor.rowcount)

    def add_real_price_observation(self, record):
        with self.lock:
            cursor = self.conn.execute("""
                INSERT OR IGNORE INTO offer_price_history(
                    canonical_identity, product_key, canonical_product_id,
                    canonical_url, observation_date, observed_at, store,
                    title, price, currency, original_url, image_url,
                    availability, source, run_id, valid, rejection_reason,
                    observation_hash, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                record["canonical_identity"], record["product_key"],
                record["canonical_product_id"], record["canonical_url"],
                record["observed_at"][:10], record["observed_at"],
                record["store"], record["title"], str(record["price"]),
                record["currency"], record["original_url"],
                record.get("image_url", ""),
                record.get("availability", ""), record["source"],
                record["run_id"], 1, "", record["observation_hash"],
                self.iso(self.now()),
            ))
            self.conn.commit()
        return bool(cursor.rowcount)

    def record_price_rejection(self, record):
        with self.lock:
            self.conn.execute("""
                INSERT INTO offer_price_history_rejections(
                    product_key, canonical_identity, store, title,
                    observed_price, currency, original_url, source, run_id,
                    reason, observation_hash, observed_at, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                record.get("product_key", ""),
                record.get("canonical_identity", ""),
                record.get("store", ""), record.get("title", ""),
                str(record.get("price", "")), record.get("currency", ""),
                record.get("original_url", ""), record.get("source", ""),
                record.get("run_id", ""), record["reason"],
                record.get("observation_hash", ""),
                record["observed_at"], self.iso(self.now()),
            ))
            self.conn.commit()

    def real_price_history(self, product_key):
        return self.read_all("""
            SELECT * FROM offer_price_history
            WHERE product_key=? AND valid=1
            ORDER BY observed_at, id
        """, (product_key,))

    def price_history_rejections(self, product_key):
        return self.read_all("""
            SELECT * FROM offer_price_history_rejections
            WHERE product_key=? ORDER BY observed_at, id
        """, (product_key,))

    def list_for(
        self,
        identity: str,
        since: datetime | None = None,
    ) -> list[PriceObservation]:
        params = [identity]
        where = "canonical_identity=?"
        if since is not None:
            where += " AND observed_at >= ?"
            params.append(self.iso(OfferHistory.normalize_datetime(since)))
        with self.lock:
            rows = self.conn.execute(f"""
                SELECT canonical_identity, price, source, observed_at,
                       store, title, currency, original_url, image_url,
                       availability
                FROM offer_price_history
                WHERE {where}
                ORDER BY observed_at, id
            """, params).fetchall()
        return [
            PriceObservation(
                identity=row["canonical_identity"],
                price=row["price"],
                source=row["source"],
                store=row["store"],
                title=row["title"],
                currency=row["currency"],
                original_url=row["original_url"],
                image_url=row["image_url"],
                availability=row["availability"],
                observed_at=self.datetime(row["observed_at"]),
            )
            for row in rows
        ]

    def record_pipeline_run(self, metrics):
        with self.lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO offer_pipeline_runs(
                    run_id, received_count, valid_count, discarded_count,
                    duplicate_count, blocked_count, approved_count,
                    queued_count, selected_shadow_count, average_score,
                    average_processing_ms, stage_timings_json, shadow_mode,
                    affects_current_flow, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,0,?)
            """, (
                metrics.run_id,
                metrics.received_count,
                metrics.valid_count,
                metrics.discarded_count,
                metrics.duplicate_count,
                metrics.blocked_count,
                metrics.approved_count,
                metrics.queued_count,
                metrics.selected_shadow_count,
                metrics.average_score,
                metrics.average_processing_ms,
                json.dumps(dict(metrics.stage_timings_ms)),
                self.iso(metrics.created_at),
            ))
            self.conn.commit()

    def record_pipeline_item(self, result):
        diagnostic = result.diagnostic
        analysis = result.analysis
        queue_item = result.queue_item
        with self.lock:
            self.conn.execute("""
                INSERT INTO offer_pipeline_items(
                    run_id, product_id, canonical_identity,
                    promotion_signature, title, store, score,
                    classification, filter_approved, duplicate_type,
                    queue_item_id, queue_status, scheduler_status,
                    diagnostic_json, processing_ms, error, shadow_mode,
                    affects_current_flow, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,?)
            """, (
                result.run_id,
                str(analysis.candidate.product_id or "") if analysis else "",
                analysis.identity.signature if analysis and analysis.identity else "",
                (
                    analysis.identity.promotion_signature
                    if analysis and analysis.identity else ""
                ),
                analysis.candidate.title if analysis else "",
                analysis.candidate.store if analysis else "",
                analysis.score.total if analysis else 0,
                analysis.score.classification if analysis else "oferta_fraca",
                int(bool(analysis and analysis.filtering.approved)),
                (
                    analysis.duplicate.duplicate_type
                    if analysis and analysis.duplicate else ""
                ),
                queue_item.id if queue_item else None,
                queue_item.status if queue_item else "",
                result.scheduler_status,
                json.dumps(diagnostic.as_dict(), ensure_ascii=False),
                result.processing_ms,
                result.error,
                self.iso(result.created_at),
            ))
            self.conn.commit()

    def latest_runs(self, limit=20):
        with self.lock:
            return self.conn.execute("""
                SELECT * FROM offer_pipeline_runs
                ORDER BY created_at DESC LIMIT ?
            """, (max(int(limit), 1),)).fetchall()

    def items_for_run(self, run_id):
        with self.lock:
            return self.conn.execute("""
                SELECT * FROM offer_pipeline_items
                WHERE run_id=? ORDER BY id
            """, (run_id,)).fetchall()

    def read_all(self, sql, params=()):
        """Executa consulta somente leitura para painéis sombra."""

        statement = str(sql or "").lstrip().casefold()
        if not statement.startswith(("select", "with", "pragma")):
            raise ValueError("O painel aceita somente consultas de leitura.")
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def read_one(self, sql, params=()):
        rows = self.read_all(sql, params)
        return rows[0] if rows else None

    def latest_offer_analysis(self, title, store="", identity=""):
        with self.lock:
            return self.conn.execute("""
                SELECT score, filter_approved, duplicate_type,
                       canonical_identity, queue_item_id, created_at
                FROM offer_pipeline_items
                WHERE title=?
                  AND (?='' OR store=?)
                ORDER BY id DESC
                LIMIT 1
            """, (str(title or ""), str(store or ""), str(store or ""))).fetchone()

    def canary_identity_was_sent(self, identity):
        with self.lock:
            return bool(self.conn.execute("""
                SELECT 1 FROM offer_canary_decisions
                WHERE canonical_identity=? AND sent=1
                LIMIT 1
            """, (str(identity or ""),)).fetchone())

    def canary_send_counts(self, now):
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        hour_start = now - timedelta(hours=1)
        with self.lock:
            hour = self.conn.execute("""
                SELECT COUNT(*) FROM offer_canary_decisions
                WHERE scheduler='inteligente' AND sent=1 AND created_at>=?
            """, (self.iso(hour_start),)).fetchone()[0]
            day = self.conn.execute("""
                SELECT COUNT(*) FROM offer_canary_decisions
                WHERE scheduler='inteligente' AND sent=1 AND created_at>=?
            """, (self.iso(day_start),)).fetchone()[0]
        return {"hour": int(hour), "day": int(day)}

    def record_canary_decisions(self, rows):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                session = self.conn.execute("""
                    SELECT id FROM offer_activation_sessions
                    WHERE status IN ('dry_run','active','paused')
                    ORDER BY created_at DESC LIMIT 1
                """).fetchone()
                for row in rows:
                    self.conn.execute("""
                        INSERT INTO offer_canary_decisions(
                            audit_id, canonical_identity, title, store,
                            category, score, scheduler, legacy_decision,
                            intelligent_decision, difference, reason,
                            flags_json, canary_percent, result, sent,
                            rollback_reason, decision_ms, created_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        row["audit_id"],
                        row["identity"],
                        row["title"],
                        row["store"],
                        row["category"],
                        row["score"],
                        row["scheduler"],
                        row["legacy_decision"],
                        row["intelligent_decision"],
                        row["difference"],
                        row["reason"],
                        row["flags_json"],
                        row["canary_percent"],
                        row["result"],
                        int(bool(row["sent"])),
                        row["rollback_reason"],
                        row["decision_ms"],
                        self.iso(row["created_at"]),
                    ))
                    if session:
                        self.conn.execute("""
                            INSERT OR IGNORE INTO offer_activation_decisions(
                                session_id, audit_id, created_at
                            ) VALUES(?,?,?)
                        """, (
                            session["id"], row["audit_id"],
                            self.iso(row["created_at"]),
                        ))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def canary_metrics(self):
        row = self.read_one("""
            SELECT
                COUNT(*) AS comparisons,
                COALESCE(SUM(CASE WHEN scheduler='legado' AND sent=1
                    THEN 1 ELSE 0 END), 0) AS legacy_sends,
                COALESCE(SUM(CASE WHEN scheduler='inteligente' AND sent=1
                    THEN 1 ELSE 0 END), 0) AS intelligent_sends,
                COALESCE(SUM(CASE WHEN rollback_reason<>''
                    THEN 1 ELSE 0 END), 0) AS rollbacks,
                COALESCE(SUM(CASE WHEN difference='sim'
                    THEN 1 ELSE 0 END), 0) AS differences
            FROM offer_canary_decisions
        """)
        return dict(row) if row else {
            "comparisons": 0,
            "legacy_sends": 0,
            "intelligent_sends": 0,
            "rollbacks": 0,
            "differences": 0,
        }

    def activation_health(self):
        now = self.now()
        hour = self.iso(now - timedelta(hours=1))
        with self.lock:
            rollbacks = self.conn.execute("""
                SELECT COUNT(*) FROM offer_canary_decisions
                WHERE rollback_reason<>'' AND created_at>=?
            """, (hour,)).fetchone()[0]
            critical = self.conn.execute("""
                SELECT COUNT(*) FROM offer_activation_events
                WHERE event_type IN ('critical_error','audit_failure')
                  AND created_at>=?
            """, (hour,)).fetchone()[0]
            invalid = self.conn.execute("""
                SELECT COUNT(*) FROM offer_queue
                WHERE status='reserved'
                  AND (reserved_by='' OR reservation_expires_at IS NULL)
            """).fetchone()[0]
            duplicates = self.conn.execute("""
                SELECT COUNT(*) FROM offer_pipeline_items
                WHERE duplicate_type NOT IN ('','novo_produto','nova_promocao')
                  AND queue_status IN ('queued','reserved')
            """).fetchone()[0]
        return {
            "recent_rollbacks": int(rollbacks),
            "critical_errors": int(critical),
            "invalid_reservations": int(invalid),
            "pending_duplicates": int(duplicates),
        }

    def canary_safety_metrics(self):
        hour = self.iso(self.now() - timedelta(hours=1))
        rows = self.read_all("""
            SELECT result, rollback_reason, reason, decision_ms, sent
            FROM offer_canary_decisions
            WHERE created_at>=? ORDER BY id DESC
        """, (hour,))
        errors = [
            row for row in rows
            if str(row["result"]).startswith("Falha")
        ]
        consecutive = 0
        for row in rows:
            if str(row["result"]).startswith("Falha"):
                consecutive += 1
            else:
                break
        total = len(rows)
        return {
            "consecutive_errors": consecutive,
            "rollbacks_hour": sum(bool(row["rollback_reason"]) for row in rows),
            "error_rate_percent": (
                len(errors) * 100 / total if total else 0
            ),
            "average_decision_ms": (
                sum(float(row["decision_ms"] or 0) for row in rows) / total
                if total else 0
            ),
            "duplicates": sum(row["reason"] == "duplicidade" for row in rows),
            "audit_failures": self.read_one("""
                SELECT COUNT(*) AS total FROM offer_activation_events
                WHERE event_type='audit_failure' AND created_at>=?
            """, (hour,))["total"],
            "limit_violations": 0,
        }

    def record_activation_checks(self, session_id, checks):
        with self.lock:
            for check in checks:
                self.conn.execute("""
                    INSERT INTO offer_activation_checks(
                        session_id, check_name, passed, critical, detail,
                        created_at
                    ) VALUES(?,?,?,?,?,?)
                """, (
                    session_id, check.name, int(check.passed),
                    int(check.critical), check.detail, self.iso(self.now()),
                ))
            self.conn.commit()

    def record_activation_event(
        self, session_id, event_type, actor, reason, before, after
    ):
        with self.lock:
            self.conn.execute("""
                INSERT INTO offer_activation_events(
                    session_id, event_type, actor, reason,
                    before_json, after_json, created_at
                ) VALUES(?,?,?,?,?,?,?)
            """, (
                session_id, event_type, actor, reason,
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                self.iso(self.now()),
            ))
            self.conn.commit()

    def create_activation_session(
        self, session_id, status, actor, dry_run, config, stage, created_at
    ):
        with self.lock:
            self.conn.execute("""
                INSERT INTO offer_activation_sessions(
                    id, status, stage, actor, dry_run, config_json,
                    started_at, created_at
                ) VALUES(?,?,?,?,?,?,?,?)
            """, (
                session_id, status, stage, actor, int(dry_run),
                json.dumps(config, ensure_ascii=False),
                self.iso(created_at), self.iso(created_at),
            ))
            self.conn.commit()

    def finish_activation_session(self, session_id, status, result, ended_at):
        if not session_id:
            return
        with self.lock:
            self.conn.execute("""
                UPDATE offer_activation_sessions
                SET status=?, final_result=?, ended_at=?
                WHERE id=?
            """, (status, result, self.iso(ended_at), session_id))
            self.conn.commit()

    def current_activation_session(self):
        return self.read_one("""
            SELECT * FROM offer_activation_sessions
            WHERE status IN ('dry_run','active','paused')
            ORDER BY created_at DESC LIMIT 1
        """)

    def latest_activation_session(self):
        return self.read_one("""
            SELECT * FROM offer_activation_sessions
            ORDER BY created_at DESC LIMIT 1
        """)

    def activation_sessions(self, limit=100):
        return self.read_all("""
            SELECT * FROM offer_activation_sessions
            ORDER BY created_at DESC LIMIT ?
        """, (max(int(limit), 1),))

    def record_auto_stop(self, session_id, reason, metrics, created_at):
        with self.lock:
            self.conn.execute("""
                INSERT INTO offer_canary_auto_stops(
                    session_id, reason, metrics_json, created_at
                ) VALUES(?,?,?,?)
            """, (
                session_id, reason,
                json.dumps(metrics, ensure_ascii=False),
                self.iso(created_at),
            ))
            self.conn.commit()

    def activation_report_rows(self, session_id=""):
        join = """
            JOIN offer_activation_decisions d ON d.audit_id=c.audit_id
        """ if session_id else ""
        where = "WHERE d.session_id=?" if session_id else ""
        params = (session_id,) if session_id else ()
        return self.read_all(f"""
            SELECT c.* FROM offer_canary_decisions c
            {join}
            {where}
            ORDER BY c.created_at
        """, params)
