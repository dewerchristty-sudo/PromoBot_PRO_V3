from __future__ import annotations

import re
from datetime import datetime, timezone


class PromotionHunterDeliveryAdapter:
    def __init__(self, notifier, destination):
        self.notifier = notifier
        self.destination = self.validate_allowed_destination(destination)

    @staticmethod
    def validate_allowed_destination(destination):
        """Valida destino autorizado (pessoal ou grupo de revisão).

        Destinos pessoais continuam permitidos conforme o comportamento
        original. A única exceção para grupos (@g.us) é o valor exato
        configurado em WHATSAPP_REVIEW_GROUP.
        """
        import os

        value = str(destination or "").strip()
        if "," in value:
            raise ValueError(
                "Lista de destinos não é permitida. "
                "Informe um único destino."
            )

        # Exceção controlada: grupo de revisão autorizado
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

        # Destino pessoal: validação original preservada
        digits = re.sub(r"\D", "", value)
        if not 12 <= len(digits) <= 13:
            raise ValueError("Destino pessoal inválido.")
        return digits

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
        try:
            message = self.notifier.format_alert(product)
            self.notifier.send_whatsapp_message(
                message,
                queue_item["image_url"],
                self.destination,
            )
            return True, ""
        except Exception as error:
            return False, self.sanitize(error)
