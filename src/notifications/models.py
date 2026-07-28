from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional


class MessageStyle(str, Enum):
    SHORT = "short"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class NotificationOffer:
    """Dados já analisados necessários para compor uma notificação."""

    title: str = ""
    store: str = ""
    current_price: Optional[Any] = None
    previous_price: Optional[Any] = None
    savings: Optional[Any] = None
    discount_percent: Optional[Any] = None
    classification: Any = ""
    product_link: str = ""
    image_link: str = ""

    @classmethod
    def from_mapping(cls, offer: Mapping[str, Any]) -> "NotificationOffer":
        return cls(
            title=offer.get("title", offer.get("titulo", "")),
            store=offer.get("store", offer.get("loja", "")),
            current_price=offer.get(
                "current_price",
                offer.get("preco_valor", offer.get("preco")),
            ),
            previous_price=offer.get(
                "previous_price",
                offer.get("preco_antigo"),
            ),
            savings=offer.get(
                "savings",
                offer.get("saving_amount", offer.get("economia")),
            ),
            discount_percent=offer.get(
                "discount_percent",
                offer.get("percentual_desconto", offer.get("desconto")),
            ),
            classification=offer.get(
                "classification",
                offer.get("classificacao", offer.get("rating", "")),
            ),
            product_link=offer.get(
                "product_link",
                offer.get(
                    "affiliate_link",
                    offer.get("link_afiliado", offer.get("link", "")),
                ),
            ),
            image_link=offer.get(
                "image_link",
                offer.get("image_url", offer.get("imagem", "")),
            ),
        )


@dataclass(frozen=True, slots=True)
class PreparedNotification:
    """Resultado sem efeitos colaterais, pronto para um canal futuro."""

    message: str
    style: MessageStyle
    product_link: str = ""
    image_link: str = ""

