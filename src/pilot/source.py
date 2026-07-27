import json
from pathlib import Path

from .models import PilotProduct


DEFAULT_DRY_RUN_REPORT = Path(
    "reports/dry_run/mercado_livre/dry_run_report.json"
)


def load_pilot_product(path=DEFAULT_DRY_RUN_REPORT):
    if not path.exists():
        return None, {}
    report = json.loads(path.read_text(encoding="utf-8"))
    products = report.get("products", [])
    row = next(
        (item for item in products if item.get("operational_ready")),
        products[0] if products else None,
    )
    if not row:
        return None, report
    affiliate_status = row.get("affiliate_status", "")
    threshold = float(
        report.get("limits", {}).get("minimum_score", 90)
    )
    product = PilotProduct(
        title=str(row.get("titulo", "")),
        store=str(row.get("loja", "")),
        current_price=float(row.get("current_price", 0) or 0),
        previous_price=float(row.get("previous_price", 0) or 0),
        discount_percent=float(row.get("discount_percent", 0) or 0),
        affiliate_url=str(row.get("affiliate_url", "")),
        affiliate_valid=affiliate_status in {
            "GENERATED", "CACHED", "PROVIDED"
        },
        image_available=bool(row.get("image_url")),
        score=float(row.get("score", 0) or 0),
        threshold=threshold,
        operationally_ready=bool(row.get("operational_ready")),
        selected=(
            row.get("scheduler") == "selected_shadow"
            or row.get("resultado_final") == "SERIA ENVIADA"
        ),
        approved=bool(row.get("filtro_aprovado")),
        identity=str(row.get("identidade", "")),
    )
    return product, report
