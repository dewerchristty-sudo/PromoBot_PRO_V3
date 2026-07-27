from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path


OUTPUT = Path("reports/offer_intelligence")


def serialize(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Tipo não serializável: {type(value)!r}")


def write_intelligence_reports(analyses, output=None):
    output = Path(output or OUTPUT)
    output.mkdir(parents=True, exist_ok=True)
    payloads = [
        analysis if isinstance(analysis, dict) else asdict(analysis)
        for analysis in analyses
    ]
    overall = output / "offer_intelligence.json"
    summary = output / "offer_intelligence_summary.txt"
    overall.write_text(json.dumps(
        {"products": payloads, "count": len(payloads)},
        ensure_ascii=False, indent=2, default=serialize,
    ), encoding="utf-8")
    lines = [
        "PROMOBOT - INTELIGENCIA DE OFERTAS",
        f"Produtos analisados: {len(payloads)}",
        "Efeito operacional: NENHUM",
        "Mensagens enviadas: 0",
    ]
    for item in payloads:
        lines.extend((
            "",
            f"Produto: {item['product_key']}",
            f"Estado: {item['state']}",
            f"Observacoes: {item['observation_count']}",
            f"Preco atual: {item['current_price']}",
            f"Minimo: {item['minimum_price']}",
            f"Media: {item['average_price']}",
            f"Tendencia: {item['trend']}",
            f"Confianca: {item['confidence_index']}",
            f"Raridade: {item['rarity_index']}",
        ))
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    product_paths = []
    for item in payloads:
        path = output / (
            f"product_{item['product_key']}_intelligence.json"
        )
        path.write_text(json.dumps(
            item, ensure_ascii=False, indent=2, default=serialize
        ), encoding="utf-8")
        product_paths.append(path)
    return overall, summary, *product_paths
