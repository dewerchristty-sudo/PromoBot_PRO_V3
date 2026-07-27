import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offer_intelligence import (
    OfferIntelligenceAnalyzer, write_intelligence_reports,
)
from src.offer_intelligence.reports import serialize


def inspect(product_key, repository=None, now=None):
    owns_repository = repository is None
    repository = repository or OfferPipelineRepository(
        Path(os.getenv("OFFER_SHADOW_DB_PATH", "offer_shadow.db"))
    )
    repository.migrate()
    try:
        analysis = OfferIntelligenceAnalyzer(repository).analyze(
            product_key, now=now
        )
    finally:
        if owns_repository:
            repository.close()
    return analysis


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Inspeciona indicadores históricos sem efeito operacional."
    )
    parser.add_argument("--product-key", required=True)
    args = parser.parse_args(argv)
    product_key = args.product_key.strip().upper()
    analysis = inspect(product_key)
    payload = asdict(analysis)
    paths = write_intelligence_reports([analysis])
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=serialize))
    print("Histórico:", payload["observation_count"], "observações")
    print("Mínimo:", payload["minimum_price"])
    print("Máximo:", payload["maximum_price"])
    print("Média:", payload["average_price"])
    print("Mediana:", payload["median_price"])
    print("Volatilidade:", payload["volatility_percent"])
    print("Confiança:", payload["confidence_index"])
    print("Raridade:", payload["rarity_index"])
    print("Tendência:", payload["trend"])
    print("Estado:", payload["state"])
    print("Relatórios:", ", ".join(str(path) for path in paths))
    print("Mensagens enviadas: 0")


if __name__ == "__main__":
    main()
