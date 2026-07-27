import json
import argparse
from pathlib import Path

from src.affiliates.config import AffiliateConfig
from src.affiliates.manager import AffiliateManager
from src.affiliates.validation import product_identity
from src.offers.filters import OfferFilter
from src.offers.identity import OfferIdentity
from src.offers.models import OfferCandidate
from src.offers.readiness import OfferReadinessEnricher
from src.stores.mercado_livre import MercadoLivre


DEFAULT_REPORT = Path(
    "reports/dry_run/mercado_livre/dry_run_report.json"
)
DEFAULT_OUTPUT = Path(
    "reports/affiliate_onboarding/"
    "mercado_livre_affiliate_integration.json"
)


def recent_products(path=DEFAULT_REPORT):
    if not path.exists():
        return []
    report = json.loads(path.read_text(encoding="utf-8"))
    return [
        row for row in report.get("products", [])
        if row.get("loja") == "Mercado Livre"
    ]


def validate_real_integration(config=None, products=None):
    config = config or AffiliateConfig.from_environment()
    products = list(products if products is not None else recent_products())
    manager = AffiliateManager(config)
    rows = []
    try:
        readiness = OfferReadinessEnricher(manager)
        for product in products:
            prepared = readiness.prepare(product)
            candidate = OfferCandidate.from_mapping(prepared.product)
            identity = OfferIdentity().identify(candidate)
            filtering = OfferFilter().analyze(candidate)
            rows.append({
                "title": candidate.title,
                "canonical_identity": identity.signature,
                "product_key": product_identity(
                    "Mercado Livre", candidate.product_link
                ),
                "affiliate_status": prepared.operational_readiness[
                    "affiliate_status"
                ],
                "affiliate_generated": bool(candidate.affiliate_link),
                "affiliate_url": (
                    "[oficial_e_mascarado]"
                    if candidate.affiliate_link else ""
                ),
                "operationally_ready": not filtering.operational_blocks,
                "blocks": list(filtering.operational_blocks),
                "reason": prepared.product.get("affiliate_error", ""),
                "manual_affiliate_url": "",
            })
        metrics = manager.metrics()
    finally:
        manager.close()
    return {
        "env_file_found": config.env_file_found,
        "env_path": str(config.env_path),
        "map_present": bool(config.mercado_livre.mapping),
        "template_present": bool(config.mercado_livre.template),
        "products_tested": len(rows),
        "links_generated": sum(row["affiliate_generated"] for row in rows),
        "operationally_ready": sum(
            row["operationally_ready"] for row in rows
        ),
        "failures": metrics.failures + metrics.invalid,
        "status": (
            "PASSED" if any(row["operationally_ready"] for row in rows)
            else "FAILED_NO_REAL_PRODUCT_COVERAGE"
        ),
        "products": rows,
        "manual_action": (
            "Inclua um produto real no mapa, sem remover as entradas atuais: "
            "MERCADOLIVRE_AFFILIATE_MAP="
            "<MLB_ID_REAL>=https://meli.la/<LINK_OFICIAL>"
            if rows and not any(row["affiliate_generated"] for row in rows)
            else ""
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-url", default="")
    args = parser.parse_args(argv)
    products = None
    if args.product_url:
        products = [MercadoLivre().product_from_url(args.product_url)]
    report = validate_real_integration(products=products)
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("Env encontrado:", report["env_file_found"])
    print("Caminho do env:", report["env_path"])
    print("Mapa presente:", report["map_present"])
    print("Template presente:", report["template_present"])
    print("Produtos reais testados:", report["products_tested"])
    print("Links oficiais gerados:", report["links_generated"])
    print("Produtos operacionalmente prontos:",
          report["operationally_ready"])
    print("Status:", report["status"])
    if report["manual_action"]:
        print("Acao manual:", report["manual_action"])
    print("Relatorio:", DEFAULT_OUTPUT)
    return 0 if report["status"] == "PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
