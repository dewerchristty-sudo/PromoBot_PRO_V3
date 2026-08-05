"""Entrega controlada de exatamente um registro da fila, sem coleta."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.core.notifier import Notifier
from src.database.offer_repository import OfferRepository
from src.offers.queue import OfferQueue

from .delivery.authorization import require_real_delivery_authorized
from .delivery.notifier_adapter import PromotionHunterDeliveryAdapter
from .repository import PromotionHunterRepository


CONTROLLED_CONFIRMATION = "AUTORIZO_ENVIO_REAL_CONTROLADO_DE_UM_QUEUE_ID"


class ControlledDeliveryError(RuntimeError):
    pass


class ControlledQueueDelivery:
    def __init__(self, database_path="promotion_hunter.db",
                 pipeline_path="promotion_hunter_offer_pipeline.db",
                 notifier_factory=Notifier, repository_factory=PromotionHunterRepository,
                 adapter_factory=PromotionHunterDeliveryAdapter, clock=None):
        self.database_path = Path(database_path)
        self.pipeline_path = Path(pipeline_path)
        self.notifier_factory = notifier_factory
        self.repository_factory = repository_factory
        self.adapter_factory = adapter_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _readonly(path):
        connection = sqlite3.connect(
            f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True
        )
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _asin(row):
        product_key = str(row["product_key"] or "")
        match = re.fullmatch(r"amazon:([A-Z0-9]{10})", product_key, re.I)
        if not match:
            raise ControlledDeliveryError("Product Key Amazon invalido.")
        return match.group(1).upper()

    def _signature(self, asin):
        if not self.pipeline_path.exists():
            return "", ""
        with self._readonly(self.pipeline_path) as connection:
            row = connection.execute(
                """SELECT promotion_signature, canonical_identity
                   FROM offer_pipeline_items WHERE upper(product_id)=?
                   AND promotion_signature<>'' ORDER BY id DESC LIMIT 1""",
                (asin,),
            ).fetchone()
            return (
                (str(row["promotion_signature"]), str(row["canonical_identity"]))
                if row else ("", "")
            )

    def preview(self, queue_id):
        queue_id = int(queue_id)
        with self._readonly(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM promotion_hunter_delivery_queue WHERE id=?",
                (queue_id,),
            ).fetchone()
            if row is None:
                raise ControlledDeliveryError(f"Queue ID inexistente: {queue_id}")
            item = dict(row)
            if item["status"] != "pending":
                raise ControlledDeliveryError(
                    f"Queue ID {queue_id} nao esta pending: {item['status']}"
                )
            if str(item["store"]).strip().casefold() != "amazon":
                raise ControlledDeliveryError("Modo controlado aceita somente Amazon.")
            accepted = connection.execute(
                """SELECT destination FROM promotion_hunter_destination_receipts
                   WHERE queue_id=? AND accepted=1""", (queue_id,)
            ).fetchall()
            if accepted:
                raise ControlledDeliveryError("Queue ID ja possui recibo concluido.")
            receipt_count = connection.execute(
                "SELECT COUNT(*) FROM promotion_hunter_destination_receipts WHERE queue_id=?",
                (queue_id,),
            ).fetchone()[0]
            attempt_count = connection.execute(
                "SELECT COUNT(*) FROM promotion_hunter_delivery_attempts WHERE queue_id=?",
                (queue_id,),
            ).fetchone()[0]
            same_active = connection.execute(
                """SELECT COUNT(*) FROM promotion_hunter_delivery_queue
                   WHERE product_key=? AND status IN ('pending','sending','failed')""",
                (item["product_key"],),
            ).fetchone()[0]

        asin = self._asin(item)
        signature = str(item.get("promotion_signature") or "")
        canonical_identity = ""
        if not signature:
            signature, canonical_identity = self._signature(asin)
        if not signature:
            raise ControlledDeliveryError("Assinatura comercial ausente.")
        tag = os.getenv("AMAZON_ASSOCIATE_TAG", "").strip()
        if not tag:
            raise ControlledDeliveryError("AMAZON_ASSOCIATE_TAG ausente.")
        canonical_url = f"https://www.amazon.com.br/dp/{asin}?tag={tag}"
        item["product_url"] = canonical_url

        notifier = self.notifier_factory()
        adapter = self.adapter_factory(notifier, "")
        product = {
            "loja": item["store"], "titulo": item["title"],
            "preco": item["current_price"], "preco_valor": item["current_price"],
            "preco_antigo": item["previous_price"], "imagem": item["image_url"],
            "link": canonical_url, "categoria_manual": item.get("category", ""),
            "termo": item.get("search_term", ""),
            "breadcrumb": item.get("breadcrumb", ""),
            "categoria_original": item.get("original_category", ""),
        }
        category = notifier.whatsapp_category(product)
        destinations = adapter._resolve_destinations(product)
        review = os.getenv("WHATSAPP_REVIEW_GROUP", "").strip()
        if len(destinations) != 1:
            raise ControlledDeliveryError(
                f"Modo controlado exige um destino; encontrados={len(destinations)}"
            )
        if destinations[0] == review:
            raise ControlledDeliveryError("Destino Review proibido.")
        if not item.get("image_url"):
            raise ControlledDeliveryError("Imagem ausente.")
        message = notifier.format_alert(product)
        if not message:
            raise ControlledDeliveryError("Mensagem nao foi formatada.")
        if same_active != 1:
            raise ControlledDeliveryError(
                f"Deduplicacao ambigua: registros ativos={same_active}"
            )
        return {
            "mode": "controlled_single_delivery_preview",
            "selected_queue_ids": [queue_id],
            "loaded_queue_count": 1,
            "queue_id": queue_id,
            "status": item["status"],
            "product_key": item["product_key"],
            "asin": asin,
            "title": item["title"],
            "price": item["current_price"],
            "category": category,
            "resolved_destinations": destinations,
            "review_destination": False,
            "canonical_affiliate_url": canonical_url,
            "commercial_signature": signature,
            "canonical_identity": canonical_identity,
            "receipt_count": int(receipt_count),
            "attempt_count": int(attempt_count),
            "active_product_key_count": int(same_active),
            "image_available": True,
            "message_formatted": True,
            "message_preview": message,
            "max_messages": 1,
            "accelerated_mode_ignored": True,
            "scheduler_started": False,
            "collection_started": False,
            "evolution_post_count": 0,
            "other_queue_rows_loaded": 0,
            "other_queue_rows_changed": 0,
            "_queue_item": item,
        }

    def execute(self, queue_id, *, confirmation):
        if confirmation != CONTROLLED_CONFIRMATION:
            raise ControlledDeliveryError("Confirmacao real controlada ausente.")
        require_real_delivery_authorized(boundary="controlled_single.initialize")
        preview = self.preview(queue_id)
        destination = preview["resolved_destinations"][0]
        repository = self.repository_factory(self.database_path)
        attempt_id = None
        offer_repo = None
        offer_queue = None
        offer_item_id = None
        send_attempted = False  # protege contra rollback apos POST
        try:
            # ------------------------------------------------------------------
            # Integracao com offer_queue (maquina de estados explicita)
            # ------------------------------------------------------------------
            promotion_signature = str(
                preview["_queue_item"].get("promotion_signature") or ""
            )
            if promotion_signature:
                offer_repo = OfferRepository(self.pipeline_path)
                offer_repo.migrate()
                offer_queue = OfferQueue(offer_repo)
                offer_row = offer_repo.conn.execute(
                    "SELECT id, status FROM offer_queue WHERE promotion_signature=?",
                    (promotion_signature,),
                ).fetchone()
                if offer_row:
                    offer_item_id = int(offer_row["id"])
                    current_offer_status = str(offer_row["status"])
                    if current_offer_status == "queued":
                        offer_queue.transition(
                            offer_item_id,
                            "reserved",
                            "Reservado para envio controlado.",
                            run_id="controlled",
                        )
                        offer_queue.select_shadow(
                            offer_item_id,
                            "controlled",
                            "Selecionado para envio controlado.",
                        )
                    elif current_offer_status == "reserved":
                        offer_queue.select_shadow(
                            offer_item_id,
                            "controlled",
                            "Selecionado para envio controlado (ja reservado).",
                        )
            # ------------------------------------------------------------------
            started = self.clock().isoformat()
            attempt_id = repository.start_controlled_attempt(
                queue_id, destination, started
            )
            adapter = self.adapter_factory(self.notifier_factory(), "")
            send_attempted = True  # POST sera executado a seguir
            result = adapter.send(preview["_queue_item"], ())
            finished = self.clock().isoformat()
            if result.destination_results:
                repository.record_destination_results(
                    queue_id, preview["product_key"], attempt_id,
                    result.destination_results,
                )
            repository.finish_attempt(
                queue_id, attempt_id, "sent" if result.success else "failed",
                finished, result.error, bool(result.permanent),
            )
            # ------------------------------------------------------------------
            # Atualiza offer_queue apos o envio
            # ------------------------------------------------------------------
            if offer_item_id is not None and offer_queue is not None:
                if result.success:
                    receipt_msg_id = ""
                    for dr in result.destination_results:
                        if dr.evolution_status and "message_id:" in dr.evolution_status:
                            receipt_msg_id = dr.evolution_status.split(
                                "message_id:"
                            )[-1].split("|")[0]
                            break
                    sent_fields = {"sent_at": finished, "attempts": 1}
                    reason = "Enviado com sucesso via Evolution API."
                    if receipt_msg_id:
                        reason += f" message_id={receipt_msg_id}"
                    offer_queue.transition(
                        offer_item_id,
                        "sent",
                        reason,
                        run_id="controlled",
                        fields=sent_fields,
                    )
                else:
                    error_msg = str(result.error or "falha_desconhecida")[:200]
                    try:
                        offer_queue.transition(
                            offer_item_id,
                            "cancelled",
                            f"Falha no envio controlado: {error_msg}",
                            run_id="controlled",
                            fields={"last_error": error_msg},
                        )
                    except ValueError:
                        pass
            return {
                **{k: v for k, v in preview.items() if not k.startswith("_")},
                "mode": "controlled_single_delivery_real",
                "success": bool(result.success),
                "evolution_post_count": sum(
                    int(item.request_made) for item in result.destination_results
                ),
            }
        except Exception:
            # So desfaz reserved/selected_shadow se o POST NAO foi tentado
            if not send_attempted and offer_item_id is not None and offer_queue is not None:
                try:
                    current = offer_repo.get(offer_item_id)
                    if current and current.status in ("reserved", "selected_shadow"):
                        offer_queue.transition(
                            offer_item_id,
                            "queued",
                            "Envio abortado por excecao antes do POST.",
                            run_id="controlled",
                            fields={
                                "reserved_at": None,
                                "reserved_by": "",
                                "reservation_expires_at": None,
                            },
                        )
                except Exception:
                    pass
            raise
        finally:
            repository.close()
            if offer_repo is not None:
                try:
                    offer_repo.close()
                except Exception:
                    pass


def safe_json(result):
    return json.dumps(
        {key: value for key, value in result.items() if not key.startswith("_")},
        ensure_ascii=True, indent=2, default=str,
    )
