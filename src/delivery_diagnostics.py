"""Diagnóstico somente leitura do funil operacional de entrega."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class FunnelStage:
    name: str
    total: int | None
    percentage: float | None
    main_reason: str = ""


@dataclass(frozen=True)
class DeliveryTrace:
    queue_id: int
    store: str
    title: str
    stage: str
    status: str
    attempts: int
    reason: str
    product_url: str
    image_url: str


@dataclass(frozen=True)
class DeliveryDiagnosticSnapshot:
    funnel: tuple[FunnelStage, ...]
    top_losses: tuple[tuple[str, int], ...]
    image_failures_by_store: tuple[tuple[str, int], ...]
    affiliate_failures: tuple[tuple[str, int], ...]
    sqlite_failures: tuple[tuple[str, int, str], ...]
    evolution_failures: tuple[tuple[str, int], ...]
    destinations: tuple[tuple[str, int], ...]
    traces: tuple[DeliveryTrace, ...]
    limitations: tuple[str, ...]
    generated_at: datetime


class DeliveryDiagnosticsRepository:
    """Deriva evidências existentes sem escrever ou migrar bancos."""

    def __init__(self, hunter_path, main_path):
        self.hunter = self._open_hunter(hunter_path)
        self.main = self._open(main_path)
        self.closed = False

    @classmethod
    def _open_hunter(cls, path):
        resolved = Path(path).resolve()
        if resolved.exists():
            return cls._open(resolved)
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE promotion_hunter_runs (
                status TEXT, collected_count INTEGER, unique_count INTEGER
            );
            CREATE TABLE promotion_hunter_decisions (
                decision_status TEXT, reason TEXT, created_at TEXT
            );
            CREATE TABLE promotion_hunter_delivery_queue (
                id INTEGER, store TEXT, title TEXT, status TEXT,
                attempts INTEGER, last_error TEXT, product_url TEXT,
                image_url TEXT, updated_at TEXT
            );
            CREATE TABLE promotion_hunter_delivery_attempts (
                status TEXT, error_message TEXT
            );
        """)
        return connection

    @staticmethod
    def _open(path):
        resolved = Path(path).resolve()
        connection = sqlite3.connect(
            f"file:{resolved.as_posix()}?mode=ro", uri=True
        )
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _scalar(connection, query, parameters=()):
        row = connection.execute(query, parameters).fetchone()
        return int(row[0] or 0) if row else 0

    def _decision_count(self, status=None, reason_like=None):
        clauses = []
        parameters = []
        if status:
            clauses.append("decision_status=?")
            parameters.append(status)
        if reason_like:
            clauses.append("lower(reason) LIKE ?")
            parameters.append(f"%{reason_like.casefold()}%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return self._scalar(
            self.hunter,
            "SELECT COUNT(*) FROM promotion_hunter_decisions" + where,
            parameters,
        )

    @staticmethod
    def _stage(name, total, collected, reason=""):
        percentage = (total / collected * 100.0) if collected else 0.0
        return FunnelStage(name, total, percentage, reason)

    def snapshot(self):
        collected = self._scalar(
            self.hunter,
            "SELECT COALESCE(SUM(collected_count),0) "
            "FROM promotion_hunter_runs WHERE status!='running'",
        )
        normalized = self._scalar(
            self.hunter,
            "SELECT COALESCE(SUM(unique_count),0) "
            "FROM promotion_hunter_runs WHERE status!='running'",
        )
        approved = self._decision_count("aprovado")
        duplicates = self._decision_count(reason_like="duplicidade")
        affiliates = self._decision_count(reason_like="afiliado")
        score = self._decision_count(reason_like="score")
        pending = self._decision_count("pendente")
        image_blocked = self._scalar(
            self.hunter,
            "SELECT COUNT(*) FROM promotion_hunter_delivery_queue "
            "WHERE lower(COALESCE(last_error,'')) LIKE '%imagem possui%' "
            "OR lower(COALESCE(last_error,'')) LIKE '%resolu%'",
        )
        queued = self._scalar(
            self.hunter,
            "SELECT COUNT(*) FROM promotion_hunter_delivery_queue",
        )
        awaiting_attempt = self._scalar(
            self.hunter,
            "SELECT COUNT(*) FROM promotion_hunter_delivery_queue "
            "WHERE status='pending' AND attempts=0",
        )
        temporary_retry = self._scalar(
            self.hunter,
            "SELECT COUNT(*) FROM promotion_hunter_delivery_queue "
            "WHERE status='failed'",
        )
        permanent_cancelled = self._scalar(
            self.hunter,
            "SELECT COUNT(*) FROM promotion_hunter_delivery_queue "
            "WHERE status='cancelled'",
        )
        partial = self._scalar(
            self.hunter,
            "SELECT COUNT(*) FROM promotion_hunter_delivery_queue "
            "WHERE lower(COALESCE(last_error,'')) "
            "LIKE '%sucesso_parcial_destinos%'",
        )
        evolution_attempts = self._scalar(
            self.hunter,
            "SELECT COUNT(*) FROM promotion_hunter_delivery_attempts "
            "WHERE status='sent' "
            "OR lower(COALESCE(error_message,'')) LIKE '%evolution%' "
            "OR lower(COALESCE(error_message,'')) LIKE '%http%' "
            "OR lower(COALESCE(error_message,'')) LIKE '%status_code%'",
        )
        evolution_accepted = self._scalar(
            self.hunter,
            "SELECT COUNT(*) FROM promotion_hunter_delivery_attempts "
            "WHERE status='sent'",
        )

        funnel = (
            self._stage("Produtos coletados", collected, collected),
            self._stage("Produtos normalizados", normalized, collected),
            self._stage("Produtos aprovados", approved, collected),
            self._stage("Bloqueados por duplicidade", duplicates, collected,
                        "duplicidade_ativa"),
            self._stage("Bloqueados por afiliado", affiliates, collected,
                        "link_afiliado_ausente"),
            self._stage("Bloqueados por imagem", image_blocked, collected,
                        "resolução inferior ao mínimo"),
            self._stage("Bloqueados por score", score, collected),
            self._stage("Pendentes", pending, collected),
            self._stage("Em fila", queued, collected),
            self._stage("Aguardando tentativa", awaiting_attempt, collected),
            self._stage("Em retry temporário", temporary_retry, collected),
            self._stage(
                "Cancelados por erro permanente", permanent_cancelled,
                collected,
            ),
            self._stage("Enviados para Evolution", evolution_attempts, collected),
            self._stage("Aceitos pela Evolution", evolution_accepted, collected),
            self._stage("Sucesso parcial por destino", partial, collected),
            FunnelStage(
                "Entrega final confirmada", None, None,
                "confirmação final não é persistida pelo fluxo atual",
            ),
        )

        losses = tuple(
            (str(row["reason"] or "sem motivo"), int(row["total"]))
            for row in self.hunter.execute(
                "SELECT reason,COUNT(*) total FROM promotion_hunter_decisions "
                "WHERE decision_status!='aprovado' GROUP BY reason "
                "ORDER BY total DESC LIMIT 10"
            )
        )
        image_by_store = tuple(
            (str(row["store"] or "Não informada"), int(row["total"]))
            for row in self.hunter.execute(
                "SELECT store,COUNT(*) total "
                "FROM promotion_hunter_delivery_queue "
                "WHERE lower(COALESCE(last_error,'')) LIKE '%imagem possui%' "
                "OR lower(COALESCE(last_error,'')) LIKE '%resolu%' "
                "GROUP BY store ORDER BY total DESC"
            )
        )
        affiliate_failures = tuple(
            (str(row["reason"] or "link afiliado ausente"), int(row["total"]))
            for row in self.hunter.execute(
                "SELECT reason,COUNT(*) total FROM promotion_hunter_decisions "
                "WHERE lower(reason) LIKE '%afiliado%' GROUP BY reason "
                "ORDER BY total DESC LIMIT 10"
            )
        )
        sqlite_failures = tuple(
            (
                str(row["reason"] or ""), int(row["total"]),
                str(row["latest"] or ""),
            )
            for row in self.hunter.execute(
                "SELECT reason,COUNT(*) total,MAX(created_at) latest "
                "FROM promotion_hunter_decisions "
                "WHERE lower(reason) LIKE '%sqlite objects created in a thread%' "
                "GROUP BY reason ORDER BY latest DESC LIMIT 10"
            )
        )
        evolution_failures = tuple(
            (str(row["error"] or "sem mensagem"), int(row["total"]))
            for row in self.hunter.execute(
                "SELECT error_message error,COUNT(*) total "
                "FROM promotion_hunter_delivery_attempts WHERE status='failed' "
                "GROUP BY error_message ORDER BY total DESC LIMIT 10"
            )
        )
        destinations = tuple(
            (str(row["canal"] or "Não informado"), int(row["total"]))
            for row in self.main.execute(
                "SELECT canal,COUNT(*) total FROM historico_envios "
                "GROUP BY canal ORDER BY total DESC"
            )
        )
        traces = tuple(
            DeliveryTrace(
                queue_id=int(row["id"]),
                store=str(row["store"] or ""),
                title=str(row["title"] or ""),
                stage=self._trace_stage(row),
                status=str(row["status"] or ""),
                attempts=int(row["attempts"] or 0),
                reason=str(row["last_error"] or ""),
                product_url=str(row["product_url"] or ""),
                image_url=str(row["image_url"] or ""),
            )
            for row in self.hunter.execute(
                "SELECT * FROM promotion_hunter_delivery_queue "
                "ORDER BY updated_at DESC,id DESC LIMIT 50"
            )
        )
        return DeliveryDiagnosticSnapshot(
            funnel=funnel,
            top_losses=losses,
            image_failures_by_store=image_by_store,
            affiliate_failures=affiliate_failures,
            sqlite_failures=sqlite_failures,
            evolution_failures=evolution_failures,
            destinations=destinations,
            traces=traces,
            limitations=(
                "Parser e origem da imagem não são persistidos no histórico atual.",
                "O link afiliado final não é persistido na fila operacional.",
                "PENDING/entrega final do WhatsApp não possui confirmação persistida.",
            ),
            generated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _trace_stage(row):
        status = str(row["status"] or "")
        error = str(row["last_error"] or "").casefold()
        if "imagem" in error or "resolu" in error:
            return "IMAGEM"
        if "afiliado" in error:
            return "LINK AFILIADO"
        if status == "sent":
            if "sucesso_parcial_destinos" in error:
                return "EVOLUTION ACEITOU PARCIALMENTE"
            return "EVOLUTION ACEITOU"
        if status in {"failed", "cancelled"}:
            return "DELIVERY"
        return "FILA"

    def close(self):
        if not self.closed:
            self.hunter.close()
            self.main.close()
            self.closed = True
