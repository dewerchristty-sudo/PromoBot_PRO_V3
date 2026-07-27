import argparse
from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path

from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.price_history import PriceHistoryConfig, RealPriceHistoryService


def serialize(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError


def inspect(product_key, repository=None):
    owns = repository is None
    repository = repository or OfferPipelineRepository(
        Path(os.getenv("OFFER_SHADOW_DB_PATH", "offer_shadow.db"))
    )
    repository.migrate()
    try:
        analysis = RealPriceHistoryService(
            repository, PriceHistoryConfig.from_environment()
        ).analyze(product_key)
        payload = asdict(analysis)
    finally:
        if owns:
            repository.close()
    return payload


def write_product_report(product_key, payload):
    output = Path("reports/price_history")
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / f"product_{product_key}_history.json"
    summary_path = output / f"product_{product_key}_summary.txt"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=serialize),
        encoding="utf-8",
    )
    summary_path.write_text(
        "\n".join((
            f"PRODUTO: {product_key}",
            f"Loja: {payload['store']}",
            f"Titulo: {payload['title']}",
            f"Observacoes validas: {payload['valid_observations']}",
            f"Observacoes ignoradas: {payload['ignored_observations']}",
            f"Dias distintos: {payload['distinct_days']}",
            f"Primeiro preco: {payload['first_price']}",
            f"Ultimo preco: {payload['last_price']}",
            f"Minimo: {payload['minimum']}",
            f"Maximo: {payload['maximum']}",
            f"Media: {payload['average']}",
            f"Mediana: {payload['median']}",
            f"Variacao anterior: "
            f"{payload['variation_from_previous_percent']}",
            f"Maturidade: {payload['maturity']}",
            f"Confianca: {payload['confidence']}%",
            f"Proximo requisito: {payload['next_requirement']}",
        )) + "\n",
        encoding="utf-8",
    )
    return json_path, summary_path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-key", required=True)
    args = parser.parse_args(argv)
    payload = inspect(args.product_key.upper())
    paths = write_product_report(args.product_key.upper(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=serialize))
    print("Relatorios:", ", ".join(str(path) for path in paths))


if __name__ == "__main__":
    main()
