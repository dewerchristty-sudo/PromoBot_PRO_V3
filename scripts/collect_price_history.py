import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from uuid import uuid4

from bs4 import BeautifulSoup

from src.affiliates.validation import product_identity
from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.identity import OfferIdentity
from src.offers.models import OfferCandidate
from src.price_history import (
    PriceHistoryConfig, RealPriceHistoryService, RealPriceObservation,
)
from src.price_history.money import money
from src.stores.mercado_livre import MercadoLivre
from src.stores.mercado_livre_browser import MercadoLivrePersistentContext


OUTPUT = Path("reports/price_history")


def extract_real_product(url):
    session = MercadoLivrePersistentContext()
    page = session.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        html = page.content()
        if MercadoLivre.block_reason(page.url, page.title(), html):
            raise RuntimeError("VERIFICATION_REQUIRED")
        soup = BeautifulSoup(html, "lxml")
        title_node = soup.select_one("h1.ui-pdp-title") or soup.select_one("h1")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        candidates = []
        meta = soup.select_one('meta[itemprop="price"][content]')
        if meta:
            candidates.append(("meta_price", money(meta.get("content"))))
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(script.string or "")
                items = payload if isinstance(payload, list) else [payload]
                for item in items:
                    offers = item.get("offers", {}) if isinstance(item, dict) else {}
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    if isinstance(offers, dict) and offers.get("price"):
                        candidates.append(("json_ld", money(offers["price"])))
            except (ValueError, TypeError, AttributeError):
                continue
        amount = soup.select_one(
            ".ui-pdp-price__second-line .andes-money-amount"
        )
        if amount:
            fraction = amount.select_one(".andes-money-amount__fraction")
            cents = amount.select_one(".andes-money-amount__cents")
            if fraction:
                raw = fraction.get_text(strip=True)
                if cents:
                    raw += "," + cents.get_text(strip=True)
                candidates.append(("visible_price", money(raw)))
        candidates = [
            (source, price) for source, price in candidates
            if price is not None and price > 0
        ]
        if not candidates:
            raise ValueError("PRICE_NOT_FOUND")
        preferred = next(
            (item for item in candidates if item[0] == "meta_price"),
            candidates[0],
        )
        price = preferred[1]
        if any(
            abs(other - price) / price > Decimal("0.05")
            for _source, other in candidates
        ):
            raise ValueError("CONFLICTING_PRICE_SOURCES")
        canonical_node = soup.select_one('link[rel="canonical"][href]')
        canonical = (
            canonical_node.get("href", "").strip()
            if canonical_node else page.url
        )
        key = product_identity("Mercado Livre", canonical) or product_identity(
            "Mercado Livre", url
        )
        image = soup.select_one('meta[property="og:image"][content]')
        return {
            "product_key": key,
            "title": title,
            "price": price,
            "canonical_url": canonical,
            "original_url": url,
            "image_url": image.get("content", "") if image else "",
            "price_source": preferred[0],
        }
    finally:
        session.close()


def product_urls(product_key=""):
    if product_key:
        return [
            f"https://www.mercadolivre.com.br/p/{product_key.upper()}"
        ]
    report = Path(
        "reports/dry_run/mercado_livre/dry_run_report.json"
    )
    if not report.exists():
        return []
    payload = json.loads(report.read_text(encoding="utf-8"))
    return list(dict.fromkeys(
        row["original_url"] for row in payload.get("products", [])
        if row.get("original_url")
    ))


def collect(store, product_key="", dry_run=False, repository=None):
    if store != "mercado_livre":
        raise ValueError("Somente mercado_livre esta habilitado nesta Sprint.")
    owns_repository = repository is None
    repository = repository or OfferPipelineRepository(
        Path(os.getenv("OFFER_SHADOW_DB_PATH", "offer_shadow.db"))
    )
    repository.migrate()
    service = RealPriceHistoryService(
        repository, PriceHistoryConfig.from_environment()
    )
    run_id = uuid4().hex
    results = []
    try:
        for url in product_urls(product_key):
            observed_at = datetime.now(timezone.utc)
            try:
                raw = extract_real_product(url)
                candidate = OfferCandidate.from_mapping({
                    "loja": "Mercado Livre", "titulo": raw["title"],
                    "preco": str(raw["price"]),
                    "link": raw["canonical_url"],
                    "imagem": raw["image_url"],
                    "product_code": raw["product_key"],
                })
                identity = OfferIdentity().identify(candidate)
                observation = RealPriceObservation(
                    product_key=raw["product_key"],
                    store="Mercado Livre",
                    canonical_identity=identity.signature,
                    canonical_product_id=raw["product_key"],
                    canonical_url=raw["canonical_url"],
                    title=raw["title"], price=raw["price"],
                    currency="BRL", observed_at=observed_at,
                    source="mercado_livre_persistent_browser",
                    run_id=run_id, original_url=raw["canonical_url"],
                    image_url=raw["image_url"],
                )
                decision = service.record(observation, dry_run=dry_run)
                results.append({
                    "product_key": decision.product_key,
                    "price": str(decision.price or ""),
                    "accepted": decision.accepted,
                    "stored": decision.stored,
                    "status": decision.status,
                    "reason": decision.reason,
                    "dry_run": dry_run,
                })
            except Exception as error:
                results.append({
                    "product_key": product_key, "price": "",
                    "accepted": False, "stored": False,
                    "status": "COLLECTION_FAILED",
                    "reason": f"{type(error).__name__}: {error}",
                    "dry_run": dry_run,
                })
        analysis = service.analyze(product_key) if product_key else None
    finally:
        if owns_repository:
            repository.close()
    return results, analysis


def write_collection_reports(results, analysis):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT / "price_history_collection.json"
    csv_path = OUTPUT / "price_history_collection.csv"
    summary_path = OUTPUT / "price_history_summary.txt"
    payload = {
        "collected": len(results),
        "stored": sum(row["stored"] for row in results),
        "duplicates": sum(
            row["reason"] == "DUPLICATE_WITHIN_WINDOW" for row in results
        ),
        "invalid": sum(not row["accepted"] for row in results),
        "outliers": sum(row["reason"] == "OUTLIER_PERCENT" for row in results),
        "maturity": analysis.maturity if analysis else "",
        "distinct_days": analysis.distinct_days if analysis else 0,
        "results": results,
        "transport_called": False,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        fields = list(results[0]) if results else ["status", "reason"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)
    summary_path.write_text(
        "\n".join((
            "PROMOBOT - COLETA REAL DE HISTORICO",
            f"Coletadas: {payload['collected']}",
            f"Armazenadas: {payload['stored']}",
            f"Duplicatas: {payload['duplicates']}",
            f"Invalidas: {payload['invalid']}",
            f"Outliers: {payload['outliers']}",
            f"Maturidade: {payload['maturity']}",
            f"Dias distintos: {payload['distinct_days']}",
            "Transporte chamado: False",
        )) + "\n",
        encoding="utf-8",
    )
    return json_path, csv_path, summary_path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True, choices=["mercado_livre"])
    parser.add_argument("--product-key", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    results, analysis = collect(
        args.store, args.product_key.upper(), args.dry_run
    )
    paths = write_collection_reports(results, analysis)
    for row in results:
        print(row)
    if analysis:
        print("Maturidade:", analysis.maturity)
        print("Observacoes validas:", analysis.valid_observations)
        print("Dias distintos:", analysis.distinct_days)
        print("Proximo requisito:", analysis.next_requirement)
    print("Transportes chamados: 0")
    print("Relatorios:", ", ".join(str(path) for path in paths))


if __name__ == "__main__":
    main()
