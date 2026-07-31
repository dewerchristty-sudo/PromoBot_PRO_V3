from __future__ import annotations

import os
import re
from datetime import datetime, timezone


class PromotionHunterDeliveryAdapter:
    """Gerencia o envio de ofertas aprovadas para grupos do WhatsApp.

    Realiza roteamento por categoria utilizando as palavras-chave já
    configuradas no Notifier (WHATSAPP_CATEGORY_KEYWORDS). O grupo de
    revisão (WHATSAPP_REVIEW_GROUP) sempre recebe uma cópia para
    conferência, independentemente da categoria detectada.
    """

    BLOCKED_DESTINATIONS: frozenset[str] = frozenset({
        "120363429738849049@g.us",  # Casa & Ofertas (bloqueado permanentemente)
    })

    def __init__(self, notifier, destination):
        self.notifier = notifier
        self.destination = self._validate_destination(destination)

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

    # ------------------------------------------------------------------
    # Roteamento por categoria
    # ------------------------------------------------------------------
    def _resolve_destinations(self, product):
        """Retorna a lista de destinos autorizados para o produto.

        A lista sempre inclui o grupo de revisão. Categorias bloqueadas
        (ex.: eletrodomesticos / Casa & Ofertas) são excluídas.
        """
        destinations = []

        # Grupo de revisão sempre incluso
        if self.destination:
            destinations.append(self.destination)

        # Grupo específico da categoria (se houver)
        category_groups = self.notifier.whatsapp_category_groups()
        if category_groups:
            category = self.notifier.whatsapp_category(product)
            if category:
                group = category_groups.get(category)
                if group and group != self.destination and group not in self.BLOCKED_DESTINATIONS:
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

    def send(self, queue_item):
        product = {
            "loja": queue_item["store"],
            "titulo": queue_item["title"],
            "preco": queue_item["current_price"],
            "preco_valor": queue_item["current_price"],
            "preco_antigo": queue_item["previous_price"],
            "imagem": queue_item["image_url"],
            "link": queue_item["product_url"],
        }
        destinations = self._resolve_destinations(product)
        message = self.notifier.format_alert(product)

        success_count = 0
        last_error = ""

        for dest in destinations:
            try:
                self.notifier.send_whatsapp_message(
                    message,
                    queue_item["image_url"],
                    dest,
                )
                success_count += 1
            except Exception as error:
                last_error = self.sanitize(error)

        return success_count > 0, last_error if not success_count else ""
