import csv
from collections import Counter
import json
from pathlib import Path
import statistics
from src.stores.active import is_active_store


DIRECTORY = Path("reports/score_calibration")
BEFORE_PATH = DIRECTORY / "before_score_report.json"
AFTER_PATH = Path("reports/dry_run/dry_run_report.json")


def band(score):
    value = float(score or 0)
    if value >= 90:
        return "90-100_excepcional"
    if value >= 75:
        return "75-89_muito_boa"
    if value >= 60:
        return "60-74_boa"
    if value >= 40:
        return "40-59_regular"
    return "0-39_fraca_sem_evidencia"


def distribution(rows, field):
    scores = [float(row.get(field) or 0) for row in rows]
    return {
        "count": len(scores),
        "average": round(statistics.fmean(scores), 3) if scores else 0,
        "median": round(statistics.median(scores), 3) if scores else 0,
        "minimum": round(min(scores), 3) if scores else 0,
        "maximum": round(max(scores), 3) if scores else 0,
        "bands": dict(Counter(band(score) for score in scores)),
    }


def missing_fields(rows):
    checks = {
        "previous_price": lambda row: float(row.get("previous_price") or 0) <= 0,
        "sufficient_history": lambda row: not row.get(
            "history_reliable_for_score"
        ),
        "verifiable_discount": lambda row: not row.get("discount_verified"),
        "rating": lambda row: float(row.get("rating") or 0) <= 0,
        "sales_count": lambda row: int(row.get("sold_count") or 0) <= 0,
        "stock": lambda row: row.get("stock_available") is None
        and not row.get("availability"),
        "shipping": lambda row: not json.loads(
            row.get("componentes_score") or "{}"
        ).get("free_shipping"),
        "seller_reputation": lambda row: not row.get("seller_reputation"),
        "popularity": lambda row: not (
            float(row.get("rating") or 0)
            or int(row.get("review_count") or 0)
            or int(row.get("sold_count") or 0)
        ),
    }
    return {
        field: sum(check(row) for row in rows)
        for field, check in checks.items()
    }


def component_audit(row):
    components = json.loads(row.get("componentes_score") or "{}")
    return {
        "score_total": row.get("analytical_score", row.get("score", 0)),
        "score_base": components.get("base", 0),
        "valid_price_points": components.get("valid_price", 0),
        "image_points": components.get("image", 0),
        "original_link_points": components.get("original_link", 0),
        "affiliate_link_points": components.get("affiliate_link", 0),
        "history_points": components.get("price_history", 0),
        "real_discount_points": components.get("discount", 0),
        "store_reliability_points": components.get("trusted_store", 0),
        "seller_reputation_points": components.get(
            "seller_reputation", 0
        ),
        "title_quality_points": components.get("title_quality", 0),
        "popularity_points": components.get("popularity", 0),
        "availability_points": components.get("availability", 0),
        "category_points": components.get("category_demand", 0),
        "bonus_points": components.get("bonus", 0),
        "penalty_points": components.get("penalties", 0),
        "promotion_confidence": row.get("promotion_confidence", 0),
        "operational_readiness": bool(row.get("operational_ready")),
        "reasons": row.get("motivos_score", ""),
    }


def simulate(rows, threshold):
    passing = [
        row for row in rows
        if float(row.get("analytical_score") or 0) >= threshold
    ]
    ready = [row for row in passing if row.get("operational_ready")]
    risk = (
        "alto: evidencia pode ser parcial"
        if threshold == 50
        else (
            "moderado: revisar confianca e desconto"
            if threshold in {60, 70}
            else (
                "baixo, mas ainda exige prontidao operacional"
                if threshold == 80
                else "muito baixo; exige evidencias excepcionais"
            )
        )
    )
    return {
        "threshold": threshold,
        "passing": len(passing),
        "operationally_ready": len(ready),
        "selected_products": [
            {
                "title": row.get("titulo"),
                "store": row.get("loja"),
                "score": row.get("analytical_score"),
                "confidence": row.get("promotion_confidence"),
            }
            for row in sorted(
                ready,
                key=lambda item: float(item.get("analytical_score") or 0),
                reverse=True,
            )
        ],
        "false_positive_risk": risk,
        "low_quality_risk": risk,
    }


def main():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    before_report = json.loads(BEFORE_PATH.read_text(encoding="utf-8"))
    after_report = json.loads(AFTER_PATH.read_text(encoding="utf-8"))
    before_rows = [
        row for row in before_report.get("products", [])
        if is_active_store(row.get("loja"))
    ]
    after_rows = [
        row for row in after_report.get("products", [])
        if is_active_store(row.get("loja"))
    ]
    before_by_key = {
        (row.get("loja"), row.get("titulo")): float(row.get("score") or 0)
        for row in before_rows
    }

    products = []
    reason_counter = Counter()
    for row in after_rows:
        audit = component_audit(row)
        reasons = [
            value.strip()
            for value in str(audit["reasons"]).split("|")
            if value.strip()
        ]
        reason_counter.update(reasons)
        products.append({
            "store": row.get("loja", ""),
            "title": row.get("titulo", ""),
            "identity": row.get("identidade", ""),
            "score_before": before_by_key.get(
                (row.get("loja"), row.get("titulo"))
            ),
            "score_after": audit["score_total"],
            "classification": row.get("classificacao", ""),
            **audit,
        })

    simulations = {
        str(threshold): simulate(after_rows, threshold)
        for threshold in (50, 60, 70, 80, 90)
    }
    result = {
        "model_before": {
            "policy_version": 1,
            "confidence_was_added_to_score": True,
            "history_minimum_samples": 3,
            "history_minimum_span_hours": 0,
        },
        "model_after": {
            "policy_version": 2,
            "analytical_score_range": [0, 100],
            "promotion_confidence_range": [0, 100],
            "operational_readiness_is_separate": True,
            "affiliate_points": 0,
            "history_minimum_span_hours": 24,
            "no_discount_no_history_cap": 39,
            "partial_evidence_cap": 74,
            "exceptional_minimum": 90,
            "exceptional_confidence_minimum": 75,
        },
        "distribution_before": distribution(before_rows, "score"),
        "distribution_after": distribution(after_rows, "analytical_score"),
        "missing_fields": missing_fields(after_rows),
        "most_frequent_reasons": reason_counter.most_common(20),
        "top_20": sorted(
            products, key=lambda row: float(row["score_after"]), reverse=True
        )[:20],
        "bottom_20": sorted(
            products, key=lambda row: float(row["score_after"])
        )[:20],
        "simulations": simulations,
        "recommendation": {
            "initial_test_threshold": 60,
            "apply_automatically": False,
            "activate_now": False,
            "reason": (
                "Usar 60 somente como piso tecnico de um futuro grupo controlado. "
                "Nao ativar enquanto os produtos nao tiverem desconto verificavel "
                "ou historico temporal confiavel e prontidao operacional."
            ),
        },
        "products": products,
        "safety": after_report.get("safety", {}),
    }

    json_path = DIRECTORY / "score_calibration.json"
    csv_path = DIRECTORY / "score_calibration.csv"
    txt_path = DIRECTORY / "score_calibration_summary.txt"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        fields = list(products[0]) if products else []
        writer = csv.DictWriter(stream, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(products)

    before = result["distribution_before"]
    after = result["distribution_after"]
    lines = [
        "PROMOBOT - CALIBRACAO DO OFFER SCORE",
        f"Produtos: {after['count']}",
        f"Antes: media {before['average']} | mediana {before['median']} | "
        f"min {before['minimum']} | max {before['maximum']}",
        f"Depois: media {after['average']} | mediana {after['median']} | "
        f"min {after['minimum']} | max {after['maximum']}",
        f"Faixas antes: {before['bands']}",
        f"Faixas depois: {after['bands']}",
        "",
        "CAMPOS AUSENTES",
        *[
            f"{name}: {value}"
            for name, value in result["missing_fields"].items()
        ],
        "",
        "SIMULACOES",
        *[
            f"Score >= {value['threshold']}: {value['passing']} passam; "
            f"{value['operationally_ready']} prontos"
            for value in simulations.values()
        ],
        "",
        "RECOMENDACAO",
        result["recommendation"]["reason"],
        "",
        "SEGURANCA",
        f"Transporte chamado: {result['safety'].get('transport_called')}",
        f"Notifier chamado: {result['safety'].get('notifier_called')}",
        f"WhatsApp chamado: {result['safety'].get('whatsapp_called')}",
        f"Evolution chamado: {result['safety'].get('evolution_called')}",
        f".env inalterado: {result['safety'].get('env_unchanged')}",
    ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "distribution_before": before,
        "distribution_after": after,
        "missing_fields": result["missing_fields"],
        "simulations": simulations,
        "recommendation": result["recommendation"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
