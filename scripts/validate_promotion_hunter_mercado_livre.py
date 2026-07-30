from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.promotion_hunter.adapters import MercadoLivreCollectionAdapter
from src.promotion_hunter.collectors import MercadoLivreKeywordCollector
from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.normalization import ProductNormalizer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validação manual isolada do Promotion Hunter no Mercado Livre. "
            "Não envia mensagens e não acessa bancos."
        )
    )
    parser.add_argument("keyword", help="Palavra-chave da coleta")
    parser.add_argument(
        "--limit",
        type=int,
        default=MercadoLivreCollectionAdapter.DEFAULT_LIMIT,
        choices=range(
            MercadoLivreCollectionAdapter.MIN_LIMIT,
            MercadoLivreCollectionAdapter.MAX_LIMIT + 1,
        ),
        metavar="1..10",
        help="Quantidade máxima de produtos (padrão: 5)",
    )
    return parser


def run_validation(keyword, limit=5, adapter=None, output=print):
    source = PromotionSource(
        source_id="manual-mercado-livre-keyword",
        source_type="keyword",
        store="Mercado Livre",
        display_name="Validação manual por palavra-chave",
        configuration={"keyword": keyword},
        limit=limit,
    )
    collector = MercadoLivreKeywordCollector(
        adapter or MercadoLivreCollectionAdapter()
    )
    result = collector.collect(source)
    output(
        f"status={result.status} produtos={result.returned_count} "
        "envios=0 bancos=0"
    )
    normalizer = ProductNormalizer()
    for index, product in enumerate(result.products, start=1):
        normalized = normalizer.normalize(product, source, result.finished_at)
        identity = normalized.external_id or normalized.url or "(ausente)"
        output(
            f"{index}. {normalized.title} | "
            f"preço={normalized.current_price} | "
            f"url={normalized.url or '(ausente)'} | identidade={identity}"
        )
    if result.error_message:
        output(f"erro={result.error_message}")
    return result


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    result = run_validation(args.keyword, args.limit)
    return 0 if result.status in {"success", "zero_results"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
