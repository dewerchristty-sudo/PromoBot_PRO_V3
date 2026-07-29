from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading

from src.core.delivery_models import (
    DeliveryAttempt,
    DeliveryStatus,
    DestinationDelivery,
    validate_delivery_transition,
)
from src.core.retry_policy import RetryDisposition


class DeliveryRepository:
    """Persistencia isolada; nao participa do envio ativo nesta etapa."""

    SAFE_METADATA_FIELDS = frozenset({
        "status_http",
        "endpoint",
        "content_type",
        "file_name",
        "size_bytes",
        "format",
        "width",
        "height",
        "destination_masked",
    })

    def __init__(self, database_path, migration_path=None, clock=None):
        self.database_path = str(database_path)
        self.migration_path = Path(migration_path or (
            Path(__file__).resolve().parent
            / "main_migrations"
            / "001_transactional_deliveries.sql"
        ))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
            timeout=30,
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def migrate(self):
        script = self.migration_path.read_text(encoding="utf-8")
        with self.lock:
            self.conn.executescript(script)
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()

    def create(self, delivery):
        if not isinstance(delivery, DestinationDelivery):
            raise TypeError("delivery deve ser DestinationDelivery.")
        now = self.iso(delivery.created_at or self.clock())
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = self.conn.execute("""
                    INSERT OR IGNORE INTO entregas_destino(
                        chave_entrega, chave_publicacao, alerta_id,
                        link_original, assinatura, canal, destino,
                        origem_decisao, status, tentativas, proxima_tentativa,
                        ultimo_erro, erro_temporario, identificador_externo,
                        criado_em, atualizado_em, enviado_em
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    delivery.delivery_key,
                    delivery.publication_key,
                    delivery.alert_id,
                    delivery.original_link,
                    delivery.signature,
                    delivery.channel,
                    delivery.destination,
                    delivery.decision_origin,
                    DeliveryStatus(delivery.status).value,
                    max(int(delivery.attempts), 0),
                    self.iso(delivery.next_attempt_at),
                    delivery.last_error,
                    self.boolean(delivery.temporary_error),
                    delivery.external_id,
                    now,
                    self.iso(delivery.updated_at) or now,
                    self.iso(delivery.sent_at),
                ))
                row = self.conn.execute(
                    "SELECT id FROM entregas_destino WHERE chave_entrega=?",
                    (delivery.delivery_key,),
                ).fetchone()
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self.get(row["id"]), cursor.rowcount == 1

    def get(self, delivery_id):
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM entregas_destino WHERE id=?",
                (int(delivery_id),),
            ).fetchone()
        return self.to_delivery(row) if row else None

    def get_by_key(self, delivery_key):
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM entregas_destino WHERE chave_entrega=?",
                (str(delivery_key),),
            ).fetchone()
        return self.to_delivery(row) if row else None

    def list(self, statuses=None, limit=500):
        statuses = tuple(DeliveryStatus(item).value for item in (statuses or ()))
        params = []
        where = ""
        if statuses:
            marks = ",".join("?" for _ in statuses)
            where = f"WHERE status IN ({marks})"
            params.extend(statuses)
        params.append(max(int(limit), 1))
        with self.lock:
            rows = self.conn.execute(f"""
                SELECT * FROM entregas_destino
                {where}
                ORDER BY criado_em, id
                LIMIT ?
            """, params).fetchall()
        return [self.to_delivery(row) for row in rows]

    def list_due_retries(self, now=None, max_attempts=5, limit=10):
        now = self.iso(now or self.clock())
        max_attempts = max(int(max_attempts), 1)
        limit = max(int(limit), 1)
        with self.lock:
            rows = self.conn.execute("""
                SELECT * FROM entregas_destino
                WHERE status=?
                  AND proxima_tentativa IS NOT NULL
                  AND proxima_tentativa<=?
                  AND tentativas<?
                ORDER BY proxima_tentativa, id
                LIMIT ?
            """, (
                DeliveryStatus.WAITING_RETRY.value,
                now,
                max_attempts,
                limit,
            )).fetchall()
        return [self.to_delivery(row) for row in rows]

    def reserve_retry(self, delivery_id, now=None, max_attempts=5):
        now = self.iso(now or self.clock())
        max_attempts = max(int(max_attempts), 1)
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute("""
                    SELECT tentativas FROM entregas_destino
                    WHERE id=? AND status=?
                      AND proxima_tentativa IS NOT NULL
                      AND proxima_tentativa<=?
                      AND tentativas<?
                """, (
                    int(delivery_id),
                    DeliveryStatus.WAITING_RETRY.value,
                    now,
                    max_attempts,
                )).fetchone()
                if row is None:
                    self.conn.rollback()
                    return None
                attempt_number = int(row["tentativas"]) + 1
                updated = self.conn.execute("""
                    UPDATE entregas_destino
                    SET status=?, tentativas=?, atualizado_em=?,
                        proxima_tentativa=NULL, ultimo_erro='',
                        erro_temporario=NULL
                    WHERE id=? AND status=?
                """, (
                    DeliveryStatus.SENDING.value,
                    attempt_number,
                    now,
                    int(delivery_id),
                    DeliveryStatus.WAITING_RETRY.value,
                ))
                if updated.rowcount != 1:
                    self.conn.rollback()
                    return None
                cursor = self.conn.execute("""
                    INSERT INTO tentativas_entrega(
                        entrega_id, numero_tentativa, iniciada_em, status,
                        metadados_sanitizados
                    ) VALUES(?,?,?,?,?)
                """, (
                    int(delivery_id),
                    attempt_number,
                    now,
                    DeliveryStatus.SENDING.value,
                    "",
                ))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self.get_attempt(cursor.lastrowid)

    def update_attempt_metadata(self, attempt_id, metadata):
        with self.lock:
            self.conn.execute("""
                UPDATE tentativas_entrega
                SET metadados_sanitizados=?
                WHERE id=? AND status=?
            """, (
                self.safe_metadata(metadata),
                int(attempt_id),
                DeliveryStatus.SENDING.value,
            ))
            self.conn.commit()

    def history_exists(self, delivery):
        with self.lock:
            table = self.conn.execute("""
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='historico_envios'
            """).fetchone()
            if not table:
                return False
            row = self.conn.execute("""
                SELECT 1 FROM historico_envios
                WHERE link_original=? AND canal=? AND destino=?
                  AND status='enviado'
                LIMIT 1
            """, (
                delivery.original_link,
                delivery.channel,
                delivery.destination,
            )).fetchone()
        return row is not None

    def finish_reserved_failure(
        self,
        delivery_id,
        disposition,
        error,
        policy,
        now=None,
    ):
        disposition = RetryDisposition(disposition)
        now_value = now or self.clock()
        now_iso = self.iso(now_value)
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                delivery = self.conn.execute("""
                    SELECT status, tentativas FROM entregas_destino
                    WHERE id=?
                """, (int(delivery_id),)).fetchone()
                if not delivery:
                    raise KeyError(f"Entrega {delivery_id} nao encontrada.")
                if delivery["status"] != DeliveryStatus.SENDING.value:
                    raise RuntimeError("Entrega nao esta reservada para envio.")
                attempt = self.conn.execute("""
                    SELECT id FROM tentativas_entrega
                    WHERE entrega_id=? AND numero_tentativa=? AND status=?
                """, (
                    int(delivery_id),
                    int(delivery["tentativas"]),
                    DeliveryStatus.SENDING.value,
                )).fetchone()
                if not attempt:
                    raise RuntimeError("Tentativa reservada nao encontrada.")

                attempts = int(delivery["tentativas"])
                if disposition == RetryDisposition.UNCERTAIN:
                    delivery_status = DeliveryStatus.REVIEW_REQUIRED
                    attempt_status = DeliveryStatus.REVIEW_REQUIRED
                    temporary = None
                    next_attempt = None
                elif (
                    disposition == RetryDisposition.TEMPORARY
                    and policy.can_retry(attempts)
                ):
                    delivery_status = DeliveryStatus.WAITING_RETRY
                    attempt_status = DeliveryStatus.FAILED
                    temporary = True
                    next_attempt = self.iso(
                        policy.next_attempt_at(attempts, now_value)
                    )
                else:
                    delivery_status = DeliveryStatus.DEFINITIVE_FAILURE
                    attempt_status = DeliveryStatus.FAILED
                    temporary = (
                        disposition == RetryDisposition.TEMPORARY
                    )
                    next_attempt = None

                self.conn.execute("""
                    UPDATE tentativas_entrega
                    SET finalizada_em=?, status=?, erro=?,
                        erro_temporario=?
                    WHERE id=?
                """, (
                    now_iso,
                    attempt_status.value,
                    str(error or ""),
                    self.boolean(temporary),
                    attempt["id"],
                ))
                self.conn.execute("""
                    UPDATE entregas_destino
                    SET status=?, atualizado_em=?, proxima_tentativa=?,
                        ultimo_erro=?, erro_temporario=?
                    WHERE id=?
                """, (
                    delivery_status.value,
                    now_iso,
                    next_attempt,
                    str(error or ""),
                    self.boolean(temporary),
                    int(delivery_id),
                ))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self.get(delivery_id)

    def prepare_manual_retry(
        self,
        delivery_id,
        *,
        confirm_definitive=False,
        now=None,
    ):
        now = self.iso(now or self.clock())
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute(
                    "SELECT status FROM entregas_destino WHERE id=?",
                    (int(delivery_id),),
                ).fetchone()
                if not row:
                    raise KeyError(f"Entrega {delivery_id} nao encontrada.")
                status = DeliveryStatus(row["status"])
                allowed = {
                    DeliveryStatus.FAILED,
                    DeliveryStatus.WAITING_RETRY,
                }
                if (
                    status == DeliveryStatus.DEFINITIVE_FAILURE
                    and confirm_definitive
                ):
                    allowed.add(DeliveryStatus.DEFINITIVE_FAILURE)
                if status not in allowed:
                    raise ValueError(
                        f"Retry manual nao permitido para {status.value}."
                    )
                self.conn.execute("""
                    UPDATE entregas_destino
                    SET status=?, proxima_tentativa=?, atualizado_em=?,
                        erro_temporario=1
                    WHERE id=?
                """, (
                    DeliveryStatus.WAITING_RETRY.value,
                    now,
                    now,
                    int(delivery_id),
                ))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self.get(delivery_id)

    def transition(self, delivery_id, target, **fields):
        target = DeliveryStatus(target)
        allowed_fields = {
            "next_attempt_at": "proxima_tentativa",
            "last_error": "ultimo_erro",
            "temporary_error": "erro_temporario",
            "external_id": "identificador_externo",
            "sent_at": "enviado_em",
        }
        unknown = set(fields) - set(allowed_fields)
        if unknown:
            raise ValueError(
                "Campos de transicao desconhecidos: " + ", ".join(sorted(unknown))
            )
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute(
                    "SELECT status FROM entregas_destino WHERE id=?",
                    (int(delivery_id),),
                ).fetchone()
                if not row:
                    raise KeyError(f"Entrega {delivery_id} nao encontrada.")
                validate_delivery_transition(row["status"], target)
                assignments = ["status=?", "atualizado_em=?"]
                params = [target.value, self.iso(self.clock())]
                for field, value in fields.items():
                    assignments.append(f"{allowed_fields[field]}=?")
                    if field in {"next_attempt_at", "sent_at"}:
                        value = self.iso(value)
                    elif field == "temporary_error":
                        value = self.boolean(value)
                    params.append(value)
                params.append(int(delivery_id))
                self.conn.execute(
                    f"UPDATE entregas_destino SET {', '.join(assignments)} "
                    "WHERE id=?",
                    params,
                )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self.get(delivery_id)

    def start_attempt(self, delivery_id, sanitized_metadata=None):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute(
                    "SELECT status, tentativas FROM entregas_destino WHERE id=?",
                    (int(delivery_id),),
                ).fetchone()
                if not row:
                    raise KeyError(f"Entrega {delivery_id} nao encontrada.")
                validate_delivery_transition(
                    row["status"],
                    DeliveryStatus.SENDING,
                )
                attempt_number = int(row["tentativas"]) + 1
                now = self.iso(self.clock())
                self.conn.execute("""
                    UPDATE entregas_destino
                    SET status=?, tentativas=?, atualizado_em=?,
                        proxima_tentativa=NULL, ultimo_erro='',
                        erro_temporario=NULL
                    WHERE id=?
                """, (
                    DeliveryStatus.SENDING.value,
                    attempt_number,
                    now,
                    int(delivery_id),
                ))
                cursor = self.conn.execute("""
                    INSERT INTO tentativas_entrega(
                        entrega_id, numero_tentativa, iniciada_em, status,
                        metadados_sanitizados
                    ) VALUES(?,?,?,?,?)
                """, (
                    int(delivery_id),
                    attempt_number,
                    now,
                    DeliveryStatus.SENDING.value,
                    self.safe_metadata(sanitized_metadata),
                ))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self.get_attempt(cursor.lastrowid)

    def finish_attempt(
        self,
        delivery_id,
        target,
        error="",
        temporary_error=None,
        external_id="",
    ):
        target = DeliveryStatus(target)
        if target not in {
            DeliveryStatus.SENT,
            DeliveryStatus.FAILED,
            DeliveryStatus.REVIEW_REQUIRED,
        }:
            raise ValueError("Resultado de tentativa invalido.")
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                delivery = self.conn.execute(
                    "SELECT status, tentativas FROM entregas_destino WHERE id=?",
                    (int(delivery_id),),
                ).fetchone()
                if not delivery:
                    raise KeyError(f"Entrega {delivery_id} nao encontrada.")
                validate_delivery_transition(delivery["status"], target)
                attempt = self.conn.execute("""
                    SELECT id FROM tentativas_entrega
                    WHERE entrega_id=? AND numero_tentativa=? AND status=?
                """, (
                    int(delivery_id),
                    int(delivery["tentativas"]),
                    DeliveryStatus.SENDING.value,
                )).fetchone()
                if not attempt:
                    raise RuntimeError("Tentativa ativa nao encontrada.")
                now = self.iso(self.clock())
                sent_at = now if target == DeliveryStatus.SENT else None
                self.conn.execute("""
                    UPDATE tentativas_entrega
                    SET finalizada_em=?, status=?, erro=?,
                        erro_temporario=?, identificador_externo=?
                    WHERE id=?
                """, (
                    now,
                    target.value,
                    str(error or ""),
                    self.boolean(temporary_error),
                    str(external_id or ""),
                    attempt["id"],
                ))
                self.conn.execute("""
                    UPDATE entregas_destino
                    SET status=?, atualizado_em=?, ultimo_erro=?,
                        erro_temporario=?, identificador_externo=?,
                        enviado_em=?
                    WHERE id=?
                """, (
                    target.value,
                    now,
                    str(error or ""),
                    self.boolean(temporary_error),
                    str(external_id or ""),
                    sent_at,
                    int(delivery_id),
                ))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return self.get(delivery_id)

    def recover_inflight(self, reason="Estado indeterminado apos reinicio."):
        now = self.iso(self.clock())
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self.conn.execute("""
                    SELECT id, tentativas FROM entregas_destino
                    WHERE status=?
                """, (DeliveryStatus.SENDING.value,)).fetchall()
                for row in rows:
                    self.conn.execute("""
                        UPDATE entregas_destino
                        SET status=?, atualizado_em=?, ultimo_erro=?,
                            erro_temporario=NULL
                        WHERE id=?
                    """, (
                        DeliveryStatus.REVIEW_REQUIRED.value,
                        now,
                        str(reason),
                        row["id"],
                    ))
                    self.conn.execute("""
                        UPDATE tentativas_entrega
                        SET status=?, finalizada_em=?, erro=?,
                            erro_temporario=NULL
                        WHERE entrega_id=? AND numero_tentativa=? AND status=?
                    """, (
                        DeliveryStatus.REVIEW_REQUIRED.value,
                        now,
                        str(reason),
                        row["id"],
                        row["tentativas"],
                        DeliveryStatus.SENDING.value,
                    ))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return len(rows)

    def attempts_for(self, delivery_id):
        with self.lock:
            rows = self.conn.execute("""
                SELECT * FROM tentativas_entrega
                WHERE entrega_id=?
                ORDER BY numero_tentativa
            """, (int(delivery_id),)).fetchall()
        return [self.to_attempt(row) for row in rows]

    def get_attempt(self, attempt_id):
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM tentativas_entrega WHERE id=?",
                (int(attempt_id),),
            ).fetchone()
        return self.to_attempt(row) if row else None

    def table_names(self):
        with self.lock:
            rows = self.conn.execute("""
                SELECT name FROM sqlite_master WHERE type='table'
            """).fetchall()
        return {row["name"] for row in rows}

    def index_names(self):
        with self.lock:
            rows = self.conn.execute("""
                SELECT name FROM sqlite_master WHERE type='index'
            """).fetchall()
        return {row["name"] for row in rows}

    @classmethod
    def to_delivery(cls, row):
        return DestinationDelivery(
            id=row["id"],
            delivery_key=row["chave_entrega"],
            publication_key=row["chave_publicacao"],
            alert_id=row["alerta_id"],
            original_link=row["link_original"],
            signature=row["assinatura"],
            channel=row["canal"],
            destination=row["destino"],
            decision_origin=row["origem_decisao"],
            status=DeliveryStatus(row["status"]),
            attempts=row["tentativas"],
            next_attempt_at=cls.datetime(row["proxima_tentativa"]),
            last_error=row["ultimo_erro"],
            temporary_error=cls.optional_boolean(row["erro_temporario"]),
            external_id=row["identificador_externo"],
            created_at=cls.datetime(row["criado_em"]),
            updated_at=cls.datetime(row["atualizado_em"]),
            sent_at=cls.datetime(row["enviado_em"]),
        )

    @classmethod
    def to_attempt(cls, row):
        return DeliveryAttempt(
            id=row["id"],
            delivery_id=row["entrega_id"],
            attempt_number=row["numero_tentativa"],
            started_at=cls.datetime(row["iniciada_em"]),
            finished_at=cls.datetime(row["finalizada_em"]),
            status=DeliveryStatus(row["status"]),
            error=row["erro"],
            temporary_error=cls.optional_boolean(row["erro_temporario"]),
            external_id=row["identificador_externo"],
            sanitized_metadata=row["metadados_sanitizados"],
        )

    @staticmethod
    def boolean(value):
        return None if value is None else int(bool(value))

    @classmethod
    def safe_metadata(cls, metadata):
        if metadata is None:
            return ""
        if not isinstance(metadata, dict):
            raise TypeError("Metadados sanitizados devem ser um dicionario.")
        safe = {
            key: metadata[key]
            for key in cls.SAFE_METADATA_FIELDS
            if key in metadata
        }
        return json.dumps(safe, ensure_ascii=False, sort_keys=True)[:2000]

    @staticmethod
    def optional_boolean(value):
        return None if value is None else bool(value)

    @staticmethod
    def iso(value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def datetime(value):
        return datetime.fromisoformat(value) if value else None
