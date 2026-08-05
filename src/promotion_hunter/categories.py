from __future__ import annotations

import unicodedata

CATEGORY_KEYWORDS = {
    "smartphones_tecnologia": ("smartphone", "celular", "notebook", "computador", "monitor", "ssd", "memoria ram", "teclado", "mouse", "fone", "smartwatch", "smart tv", "impressora", "roteador", "placa de video", "processador"),
    "casa_enxoval": ("jogo de cama", "lencol", "travesseiro", "toalha", "cortina", "tapete", "armario", "sofa", "colchao", "mesa", "cadeira", "enxoval", "movel"),
    "eletrodomesticos": ("air fryer", "fritadeira", "liquidificador", "micro ondas", "geladeira", "maquina de lavar", "cafeteira", "panela eletrica", "forno eletrico", "aspirador", "ventilador", "ferro de passar"),
    "beleza_perfumaria": ("perfume", "maquiagem", "hidratante", "protetor solar", "shampoo", "condicionador", "mascara capilar", "batom", "rimel", "blush", "skincare", "desodorante"),
    "mamae_bebe": ("fralda", "lenco umedecido", "mamadeira", "chupeta", "carrinho de bebe", "bebe conforto", "banheira infantil", "kit de higiene", "roupa de bebe", "brinquedo infantil"),
    "limpeza_utilidades": ("detergente", "sabao", "desinfetante", "amaciante", "papel higienico", "vassoura", "rodo", "balde", "organizador", "saco de lixo"),
}

def searchable(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(text.replace("-", " ").split())

def classify_category(*values: str) -> tuple[str, str]:
    text = searchable(" ".join(str(value or "") for value in values))
    for category, keywords in CATEGORY_KEYWORDS.items():
        matched = next((word for word in keywords if searchable(word) in text), "")
        if matched:
            return category, f"keyword:{matched}"
    return "", "not_detected"
