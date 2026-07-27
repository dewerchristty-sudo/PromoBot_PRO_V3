from urllib.parse import urlparse


def masked_url(url):
    if not url:
        return "(ausente)"
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.hostname}/[mascarado]"


class PilotMessageFormatter:

    def format(self, product, decision):
        lines = [
            "PREVIA - NENHUMA MENSAGEM SERA ENVIADA",
            f"Produto: {product.title}",
            f"Loja: {product.store}",
            f"Preco atual: R$ {product.current_price:.2f}",
        ]
        if product.previous_price > product.current_price > 0:
            saving = product.previous_price - product.current_price
            lines.extend((
                f"Preco anterior: R$ {product.previous_price:.2f}",
                f"Economia: R$ {saving:.2f}",
                f"Desconto: {product.discount_percent:.2f}%",
            ))
        lines.extend((
            f"Link oficial: {masked_url(product.affiliate_url)}",
            "Imagem disponivel: "
            + ("sim" if product.image_available else "nao"),
            f"Score: {product.score:.2f}",
            f"Threshold: {product.threshold:.2f}",
            "Prontidao: " + (
                "OPERATIONALLY_READY"
                if product.operationally_ready
                else "NOT_OPERATIONALLY_READY"
            ),
            "Selecao: " + (
                "SELECTED" if product.selected else "NOT_SELECTED"
            ),
            "Autorizacao: " + (
                "AUTHORIZED" if decision.authorized
                else "NOT_AUTHORIZED_FOR_PILOT"
            ),
            f"Motivo: {decision.reason}",
        ))
        return "\n".join(lines) + "\n"
