import json
from pathlib import Path

from src.affiliates.config import AffiliateConfig
from src.affiliates.shopee import ShopeeAffiliateProvider


def recent_shopee_products(
    report_path=Path("reports/dry_run/dry_run_report.json"),
):
    if not report_path.exists():
        return []
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return [
        row for row in report.get("products", [])
        if str(row.get("loja", "")).casefold() == "shopee"
    ]


def build_candidates(products, config=None):
    config = config or AffiliateConfig.from_environment()
    provider = ShopeeAffiliateProvider(config.shopee)
    candidates = []
    seen = set()
    for product in products:
        original = str(product.get("original_url") or product.get("link") or "")
        identity = str(
            product.get("identidade")
            or product.get("canonical_identity") or ""
        )
        unique = identity or original
        if not unique or unique in seen:
            continue
        seen.add(unique)
        mapped = provider.mapped(original)
        is_mapped = bool(mapped and provider.validate(mapped, original))
        candidates.append({
            "canonical_identity": identity,
            "title": str(product.get("titulo") or product.get("title") or ""),
            "original_url": original,
            "mapping_status": "MAPPED" if is_mapped else "MISSING",
            "affiliate_url": "[configurado_e_mascarado]" if is_mapped else "",
            "instruction": (
                "Ja existe link oficial no mapa."
                if is_mapped else
                "Obtenha o link no programa oficial da Shopee e preencha "
                "manualmente. Nao use link inventado."
            ),
        })
    return candidates


def write_candidates(
    candidates,
    output=Path(
        "reports/affiliate_onboarding/shopee_mapping_candidates.json"
    ),
):
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "store": "Shopee",
        "total": len(candidates),
        "mapped": sum(
            row["mapping_status"] == "MAPPED" for row in candidates
        ),
        "missing": sum(
            row["mapping_status"] == "MISSING" for row in candidates
        ),
        "warning": (
            "Preenchimento exclusivamente manual com links oficiais. "
            "Este arquivo nao altera o .env."
        ),
        "products": candidates,
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output


def main():
    candidates = build_candidates(recent_shopee_products())
    output = write_candidates(candidates)
    for row in candidates:
        print(f"\n{row['title']}")
        print("- identidade:", row["canonical_identity"])
        print("- link original:", row["original_url"])
        print("- mapeamento:", row["mapping_status"])
    print("\nArquivo gerado:", output)
    print("Mapeados:", sum(
        row["mapping_status"] == "MAPPED" for row in candidates
    ))
    print("Sem mapa:", sum(
        row["mapping_status"] == "MISSING" for row in candidates
    ))
    return candidates


if __name__ == "__main__":
    main()
