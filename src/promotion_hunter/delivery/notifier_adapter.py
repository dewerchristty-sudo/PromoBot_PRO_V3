from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from .retry_classification import (
    DestinationDeliveryResult,
    DeliveryFailureKind,
    DeliveryResult,
    classify_delivery_failure,
)
from .authorization import require_real_delivery_authorized


class PromotionHunterDeliveryAdapter:
    """Gerencia o envio de ofertas aprovadas para grupos do WhatsApp.

    Realiza roteamento por categoria utilizando as palavras-chave já
    configuradas no Notifier (WHATSAPP_CATEGORY_KEYWORDS). O grupo de
    revisão pertence somente ao fluxo manual e não recebe cópia automática.
    """

    BLOCKED_DESTINATIONS: frozenset[str] = frozenset({
        "120363429738849049@g.us",  # Casa & Ofertas (bloqueado permanentemente)
    })

    def __init__(self, notifier, destination):
        self.notifier = notifier
        # O destino de revisão é exclusivo do fluxo manual. O argumento é
        # mantido apenas para compatibilidade com chamadas antigas.
        self.destination = (
            self._validate_destination(destination) if destination else ""
        )

    @property
    def has_destination(self):
        return bool(self.notifier.whatsapp_category_groups())

    # ------------------------------------------------------------------
    # Validação de destino
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_destination(destination):
        """Valida o destino configurado como grupo de revisão."""
        value = str(destination or "").strip()
        if "," in value:
            raise ValueError(
                "Lista de destinos não é permitida. "
                "Informe um único destino."
            )
        if value.endswith("@g.us"):
            review_group = os.getenv("WHATSAPP_REVIEW_GROUP", "").strip()
            if not review_group:
                raise ValueError("Grupo de revisão não está configurado.")
            if not review_group.endswith("@g.us"):
                raise ValueError(
                    "WHATSAPP_REVIEW_GROUP deve terminar em @g.us."
                )
            if value != review_group:
                raise ValueError(
                    "Grupo não autorizado. "
                    "Apenas o grupo de revisão configurado é permitido."
                )
            return value
        digits = re.sub(r"\D", "", value)
        if not 12 <= len(digits) <= 13:
            raise ValueError("Destino pessoal inválido.")
        return digits

    # Nome público preservado para telas/testes que já usam esta validação.
    validate_allowed_destination = _validate_destination

    # ------------------------------------------------------------------
    # Roteamento por categoria
    # ------------------------------------------------------------------
    def _resolve_destinations(self, product):
        """Retorna a lista de destinos autorizados para o produto.

        Somente o grupo específico da categoria é elegível. Destinos
        bloqueados explicitamente são excluídos.
        """
        destinations = []

        # Grupo específico da categoria (se houver)
        category_groups = self.notifier.whatsapp_category_groups()
        if category_groups:
            category = self.notifier.whatsapp_category(product)
            if category:
                group = category_groups.get(category)
                if group and group not in self.BLOCKED_DESTINATIONS:
                    destinations.append(group)

        # Preservar ordem e remover duplicatas
        seen = set()
        return [d for d in destinations if not (d in seen or seen.add(d))]

    # ------------------------------------------------------------------
    # Envio
    # ------------------------------------------------------------------
    @staticmethod
    def sanitize(error):
        return " ".join(str(error).split())[:300]

    def send(self, queue_item, completed_destinations=()):
        def value(name, default=""):
            try:
                return queue_item[name]
            except (KeyError, IndexError, TypeError):
                return default
        product = {
            "loja": queue_item["store"],
            "titulo": queue_item["title"],
            "preco": queue_item["current_price"],
            "preco_valor": queue_item["current_price"],
            "preco_antigo": queue_item["previous_price"],
            "imagem": queue_item["image_url"],
            "link": queue_item["product_url"],
            "categoria_manual": value("category"),
            "termo": value("search_term"),
            "breadcrumb": value("breadcrumb"),
            "categoria_original": value("original_category"),
            "profile_id": value("profile_id"),
        }
        completed = set(completed_destinations or ())
        destinations = [
            item for item in self._resolve_destinations(product)
            if item not in completed
        ]
        if not destinations:
            if completed:
                return DeliveryResult(True, "", None, "ja_concluido", ())
            return DeliveryResult(
                False,
                "categoria_sem_destino_autorizado",
                DeliveryFailureKind.PERMANENT,
                "bloqueado_categoria",
                (),
            )
        message = self.notifier.format_alert(product)

        results = []
        last_error = ""
        failure_kinds = []

        for dest in destinations:
            try:
                require_real_delivery_authorized(
                    boundary="PromotionHunterDeliveryAdapter.send"
                )
                # Impede que um recibo de uma chamada anterior seja associado
                # ao destino atual. Notifiers legados continuam compatíveis.
                if hasattr(self.notifier, "last_delivery_receipt"):
                    self.notifier.last_delivery_receipt = None
                returned = self.notifier.send_whatsapp_message(
                    message,
                    queue_item["image_url"],
                    dest,
                )
                receipt = getattr(
                    self.notifier, "last_delivery_receipt", None
                )
                if not isinstance(receipt, dict) and isinstance(returned, dict):
                    receipt = returned
                receipt = receipt if isinstance(receipt, dict) else {}
                http_status = receipt.get("http_status")
                returned_status = str(receipt.get("status") or "")
                evolution_status = str(
                    receipt.get("evolution_status")
                    or "aceito_pela_evolution"
                )
                # Extrai message_id de forma defensiva
                message_id = str(receipt.get("message_id") or "")
                # Enriquece evolution_status com message_id para auditoria
                if message_id:
                    evolution_status = f"{evolution_status}|message_id:{message_id}"
                results.append(DestinationDeliveryResult(
                    destination=dest,
                    channel="WhatsApp",
                    request_made=True,
                    http_status=(int(http_status) if http_status else None),
                    returned_status=returned_status,
                    evolution_status=evolution_status,
                    accepted=True,
                ))
            except Exception as error:
                if type(error).__name__ == "LowResolutionImageError":
                    last_error = self.sanitize(
                        "imagem_resolucao_insuficiente_permanente: "
                        f"url={getattr(error, 'image_url', '')};"
                        f"resolucao={getattr(error, 'width', 0)}x"
                        f"{getattr(error, 'height', 0)}"
                    )
                else:
                    last_error = self.sanitize(error)
                failure_kind = classify_delivery_failure(error)
                failure_kinds.append(failure_kind)
                results.append(DestinationDeliveryResult(
                    destination=dest,
                    channel="WhatsApp",
                    request_made=not isinstance(error, ValueError),
                    evolution_status=(
                        "rejeitado_antes_da_evolution"
                        if isinstance(error, ValueError)
                        else "falhou"
                    ),
                    error=last_error,
                ))

        success_count = sum(result.accepted for result in results)
        if success_count:
            aggregate = (
                "sucesso_total"
                if success_count == len(results)
                else "sucesso_parcial"
            )
            summary = ""
            if aggregate == "sucesso_parcial":
                summary = (
                    "sucesso_parcial_destinos: "
                    f"aceitos={success_count};falhos={len(results)-success_count}"
                )
            # A fila encerra a tentativa após qualquer aceite. Isso preserva a
            # proteção existente contra duplicar o destino que já aceitou.
            return DeliveryResult(
                True, summary, None, aggregate, tuple(results)
            )
        failure_kind = (
            DeliveryFailureKind.PERMANENT
            if failure_kinds
            and all(kind is DeliveryFailureKind.PERMANENT for kind in failure_kinds)
            else DeliveryFailureKind.TEMPORARY
        )
        return DeliveryResult(
            False, last_error, failure_kind, "falha_total", tuple(results)
        )
