"""Hunter Automático — ciclo contínuo controlado via scheduler."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["PROMOTION_HUNTER_LIVE_DELIVERY"] = "false"

from src.promotion_hunter.config import (
    DEFAULT_SEARCH_TERMS,
    INTERVAL_MINUTES,
    OPERATIONAL_TIMEZONE,
)
from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.delivery import (
    DeliveryPolicy,
    PromotionHunterQueue,
)
from src.promotion_hunter.registry import CollectorRegistry
from src.promotion_hunter.repository import PromotionHunterRepository
from src.promotion_hunter.runner import PromotionHunterRunner
from src.promotion_hunter.scheduler import PromotionHunterScheduler
from src.promotion_hunter.service import PromotionHunterService
from src.promotion_hunter.adapters import MercadoLivreCollectionAdapter
from src.promotion_hunter.collectors import MercadoLivreKeywordCollector
from src.promotion_hunter.adapters.offer_pipeline import (
    build_controlled_offer_pipeline,
)
from datetime import datetime, timezone


def main():
    print("=" * 60)
    print("  PROMOTION HUNTER — CICLO AUTOMÁTICO")
    print("  Mercado Livre | análise de ofertas")
    print("=" * 60)
    now = datetime.now(OPERATIONAL_TIMEZONE)
    print(f"  Início: {now.isoformat()}")
    print()

    # Configurações
    terms = list(DEFAULT_SEARCH_TERMS)
    interval = int(os.getenv("PROMOTION_HUNTER_INTERVAL_MINUTES", INTERVAL_MINUTES))
    live_enabled = os.getenv("PROMOTION_HUNTER_LIVE_DELIVERY", "false").strip().casefold() in {
        "1", "true", "yes", "on",
    }
    mode = "live" if live_enabled else "analysis_only"

    print(f"  Modo: {mode}")
    print(f"  Intervalo: {interval}min")
    print(f"  Termos: {', '.join(terms)}")
    print(f"  Janela: 08h-22h (America/Sao_Paulo)")
    print(f"  Live delivery: {live_enabled}")
    print()

    # Construir runtime
    registry = CollectorRegistry()
    registry.register(
        "Mercado Livre", "keyword",
        MercadoLivreKeywordCollector(MercadoLivreCollectionAdapter()),
    )

    pipeline = build_controlled_offer_pipeline(
        "promotion_hunter_offer_pipeline.db"
    )
    repository = PromotionHunterRepository("promotion_hunter.db")
    repository.migrate()

    service = PromotionHunterService(registry, pipeline, repository)
    policy = DeliveryPolicy(max_products_per_keyword=5, max_messages_per_run=1)
    queue = PromotionHunterQueue(repository, policy.duplicate_window_hours)
    runner = PromotionHunterRunner(service, queue, repository, policy, delivery=None)

    # Criar fontes para cada termo
    sources = tuple(
        PromotionSource(
            f"auto-term-{index}", "keyword", "Mercado Livre", term,
            {"keyword": term}, limit=5,
        )
        for index, term in enumerate(terms, start=1)
    )

    scheduler = PromotionHunterScheduler(
        runner, sources, repository, interval, mode
    )

    try:
        print("  Ctrl+C para parar")
        print("=" * 60)
        scheduler.start()
        while scheduler.running:
            scheduler.timer.join(1)
            if not scheduler.running:
                break
    except KeyboardInterrupt:
        print("\n  Encerrando scheduler...")
    finally:
        scheduler.stop()
        runner.stop()
        pipeline.close()
        repository.close()

    print(f"  Fim: {datetime.now(OPERATIONAL_TIMEZONE).isoformat()}")
    print("  Scheduler encerrado. Nenhum processo ativo.")


if __name__ == "__main__":
    main()