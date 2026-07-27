import csv
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.price_history_dashboard import PriceHistoryDashboard


def main():
    output = Path("reports/price_history")
    output.mkdir(parents=True, exist_ok=True)
    repository = OfferPipelineRepository(
        Path(os.getenv("OFFER_SHADOW_DB_PATH", "offer_shadow.db"))
    )
    try:
        repository.migrate()
        dashboard = PriceHistoryDashboard(repository)
        indicators = dashboard.snapshot()
        details = dashboard.details()
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "database": "shadow",
            "indicators": indicators,
            "products": details,
        }
    finally:
        repository.close()

    json_path = output / "price_history.json"
    csv_path = output / "price_history.csv"
    txt_path = output / "price_history_summary.txt"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    rows = []
    for product in details:
        observations = product.pop("observations", [])
        product.pop("identity", None)
        for observation in observations:
            rows.append({
                **observation,
                "observed_at": str(observation["observed_at"]),
                "minimum": product["minimum"],
                "maximum": product["maximum"],
                "average": product["average"],
                "median": product["median"],
                "standard_deviation": product["standard_deviation"],
                "observed_days": product["observed_days"],
                "trend": product["trend"],
                "daily_variation_percent": product[
                    "daily_variation_percent"
                ],
                "weekly_variation_percent": product[
                    "weekly_variation_percent"
                ],
                "monthly_variation_percent": product[
                    "monthly_variation_percent"
                ],
                "temporal_confidence": product["temporal_confidence"],
                "events": " | ".join(product["events"]),
            })
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        fields = list(rows[0]) if rows else []
        writer = csv.DictWriter(stream, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(rows)

    lines = [
        "PROMOBOT - HISTORICO INTELIGENTE DE PRECOS",
        f"Gerado em: {result['generated_at']}",
        f"Produtos monitorados: {indicators['products_monitored']}",
        f"Dias de historico: {indicators['history_days']}",
        f"Menor preco: R$ {indicators['lowest_price']:.2f}",
        f"Maior preco: R$ {indicators['highest_price']:.2f}",
        f"Produtos em queda: {indicators['products_falling']}",
        f"Produtos estaveis: {indicators['products_stable']}",
        f"Novos recordes: {indicators['new_records']}",
        "Maior economia detectada: "
        f"{indicators['largest_saving_percent']:.2f}%",
        f"Pontos cronologicos: {len(rows)}",
        "",
        "Observacoes identicas do mesmo produto, dia e preco sao deduplicadas.",
        "Precos diferentes no mesmo dia permanecem no historico.",
    ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "indicators": indicators,
        "observations": len(rows),
        "files": [str(json_path), str(csv_path), str(txt_path)],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
