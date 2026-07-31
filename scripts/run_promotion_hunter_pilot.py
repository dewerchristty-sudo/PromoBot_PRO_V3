from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.notifier import Notifier
from src.promotion_hunter.adapters import (
    MercadoLivreCollectionAdapter,
    AmazonCollectionAdapter,
    ShopeeCollectionAdapter,
    ProductUrlCollectionAdapter,
)
from src.promotion_hunter.adapters.offer_pipeline import (
    build_controlled_offer_pipeline,
)
from src.promotion_hunter.collectors import (
    MercadoLivreKeywordCollector,
    AmazonKeywordCollector,
    ShopeeKeywordCollector,
    ProductUrlCollector,
)
from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.delivery import (
    DeliveryPolicy,
    PromotionHunterDeliveryAdapter,
    PromotionHunterQueue,
)
from src.promotion_hunter.registry import CollectorRegistry
from src.promotion_hunter.repository import PromotionHunterRepository
from src.promotion_hunter.runner import PromotionHunterRunner
from src.promotion_hunter.scheduler import PromotionHunterScheduler
from src.promotion_hunter.service import PromotionHunterService
from src.promotion_hunter.models import HunterRunResult
from src.stores.active import normalize_store_name
from datetime import datetime, timezone


STORE_DOMAINS = {
    "mercado livre": ("mercadolivre.com.br", "mercadolivre.com"),
    "amazon": ("amazon.com.br", "amzn.to"),
    "shopee": ("shopee.com.br", "s.shopee.com.br", "br.shp.ee"),
}

STORE_FACTORIES = {
    "mercado livre": (
        lambda: MercadoLivreCollectionAdapter(),
        lambda adapter: MercadoLivreKeywordCollector(adapter),
    ),
    "amazon": (
        lambda: AmazonCollectionAdapter(),
        lambda adapter: AmazonKeywordCollector(adapter),
    ),
    "shopee": (
        lambda: ShopeeCollectionAdapter(),
        lambda adapter: ShopeeKeywordCollector(adapter),
    ),
}


def parser():
    value = argparse.ArgumentParser(description="Piloto isolado do Promotion Hunter")
    value.add_argument(
        "--mode", choices=("dry-run", "analysis-only", "live"),
        default="analysis-only",
    )
    value.add_argument("--term", action="append", default=None)
    value.add_argument("--limit", type=int, choices=range(1, 11), default=5)
    value.add_argument("--max-messages", type=int, default=3)
    group = value.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", default=True)
    group.add_argument("--schedule", action="store_true")
    value.add_argument("--interval", type=int, default=30)
    value.add_argument(
        "--store",
        choices=("Mercado Livre", "Amazon", "Shopee"),
        default=None,
    )
    value.add_argument("--product-url", default=None)
    return value


def validate_product_url_args(args):
    if args.product_url:
        if not args.store:
            raise SystemExit(
                "--store é obrigatório com --product-url. "
                "Opções: Mercado Livre, Amazon, Shopee"
            )
        if args.term:
            raise SystemExit(
                "--product-url e --term são mutuamente exclusivos. "
                "Use apenas um deles."
            )
        if args.schedule:
            raise SystemExit(
                "--schedule não é compatível com --product-url. "
                "Use --once."
            )
        if args.limit != 1 and args.limit != 5:
            raise SystemExit(
                "--limit deve ser 1 no modo --product-url."
            )
        if args.max_messages > 1:
            raise SystemExit(
                "--max-messages deve ser 1 no modo --product-url."
            )
    else:
        if not args.term:
            raise SystemExit(
                "Informe --term ou --product-url. Use --help para detalhes."
            )
        if args.store:
            raise SystemExit(
                "--store só pode ser usado com --product-url. "
                "Para busca por termo, a loja é selecionada pelo coletor."
            )


def mask_destination(value):
    text = str(value or "")
    return f"***{text[-4:]}" if len(text) >= 4 else "(não configurado)"


def build_runtime(args):
    repository = PromotionHunterRepository("promotion_hunter.db")
    repository.migrate()
    registry = CollectorRegistry()

    # Registrar keyword collectors (fluxo existente)
    registry.register(
        "Mercado Livre", "keyword",
        MercadoLivreKeywordCollector(MercadoLivreCollectionAdapter()),
    )
    registry.register(
        "Amazon", "keyword",
        AmazonKeywordCollector(AmazonCollectionAdapter()),
    )
    registry.register(
        "Shopee", "keyword",
        ShopeeKeywordCollector(ShopeeCollectionAdapter()),
    )

    # Registrar product_url collectors
    for store_name, domains in STORE_DOMAINS.items():
        adapter = ProductUrlCollectionAdapter(
            scraper_factory=lambda sn=store_name: _store_factory(sn),
            allowed_domains=domains,
        )
        registry.register(store_name, "product_url", ProductUrlCollector(adapter))

    pipeline = build_controlled_offer_pipeline(
        "promotion_hunter_offer_pipeline.db"
    )
    if args.mode == "dry-run":
        class DryRunService:
            def run(self, sources):
                now = datetime.now(timezone.utc)
                return HunterRunResult(
                    "dry-run", "zero_results", (), 0, 0, (), (), now, now
                )
        service = DryRunService()
    else:
        service = PromotionHunterService(registry, pipeline, repository)
    policy = DeliveryPolicy(
        max_products_per_keyword=args.limit,
        max_messages_per_run=args.max_messages,
    )
    queue = PromotionHunterQueue(repository, policy.duplicate_window_hours)
    destination = os.getenv("PROMOTION_HUNTER_PERSONAL_WHATSAPP", "")
    delivery = (
        PromotionHunterDeliveryAdapter(Notifier(), destination)
        if destination else None
    )
    runner = PromotionHunterRunner(
        service, queue, repository, policy, delivery
    )

    if args.product_url:
        # Modo product_url: uma única fonte
        store_key = normalize_store_name(args.store)
        if args.limit == 5:
            args.limit = 1  # forçar para 1
        sources = (
            PromotionSource(
                "product-url-1", "product_url", args.store, args.product_url,
                {"product_url": args.product_url}, limit=1,
            ),
        )
    else:
        sources = tuple(
            PromotionSource(
                f"keyword-{index}", "keyword", "Mercado Livre", term,
                {"keyword": term}, limit=args.limit,
            )
            for index, term in enumerate(args.term, start=1)
        )
    return repository, pipeline, runner, sources


def _store_factory(store_name):
    if store_name == "mercado livre":
        from src.stores.mercado_livre import MercadoLivre
        return MercadoLivre()
    elif store_name == "amazon":
        from src.stores.amazon import Amazon
        return Amazon()
    elif store_name == "shopee":
        from src.stores.shopee import Shopee
        return Shopee()
    raise ValueError(f"Loja não suportada: {store_name}")


def main(argv=None):
    args = parser().parse_args(argv)
    validate_product_url_args(args)
    repository, pipeline, runner, sources = build_runtime(args)
    mode = args.mode.replace("-", "_")
    print(f"modo={mode} fontes={len(sources)} limite={args.limit}")
    print(
        "destino="
        + mask_destination(os.getenv("PROMOTION_HUNTER_PERSONAL_WHATSAPP"))
    )
    try:
        if args.schedule:
            scheduler = PromotionHunterScheduler(
                runner, sources, repository, interval=args.interval, mode=mode
            )
            scheduler.start()
            print("scheduler iniciado; Ctrl+C para parar")
            try:
                while scheduler.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                scheduler.stop()
            return 0
        result = runner.run_once(sources, mode)
        print(
            f"coletados={result.collected} únicos={result.unique} "
            f"aprovados={result.approved} enfileirados={result.queued} "
            f"enviados={result.sent} bloqueados={result.blocked}"
        )
        return 0
    finally:
        runner.stop()
        pipeline.close()
        repository.close()


if __name__ == "__main__":
    raise SystemExit(main())