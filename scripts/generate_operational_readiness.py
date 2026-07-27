import csv
import json
from pathlib import Path
from src.stores.active import is_active_store


def count(rows, predicate):
    return sum(bool(predicate(row)) for row in rows)


def metrics(report):
    rows = [
        row for row in report.get("products", [])
        if is_active_store(row.get("loja"))
    ]
    by_store = {}
    for row in rows:
        store = row.get("loja", "")
        item = by_store.setdefault(store, {
            "total": 0, "original_links": 0, "affiliate_links": 0,
            "affiliate_not_configured": 0, "images": 0,
            "missing_images": 0, "previous_prices": 0,
            "real_discounts": 0, "ready": 0, "blocked": 0,
        })
        item["total"] += 1
        item["original_links"] += bool(row.get("original_url"))
        item["affiliate_links"] += bool(row.get("affiliate_url"))
        item["affiliate_not_configured"] += (
            row.get("affiliate_status") == "NOT_CONFIGURED"
        )
        item["images"] += row.get("image_status") == "AVAILABLE"
        item["missing_images"] += row.get("image_status") != "AVAILABLE"
        item["previous_prices"] += float(row.get("previous_price") or 0) > 0
        item["real_discounts"] += float(row.get("discount_percent") or 0) > 0
        item["ready"] += bool(row.get("operational_ready"))
        item["blocked"] += not bool(row.get("operational_ready"))
    scores = [float(row.get("analytical_score") or 0) for row in rows]
    return {
        "total": len(rows), "by_store": by_store,
        "original_links": count(rows, lambda row: row.get("original_url")),
        "affiliate_links": count(rows, lambda row: row.get("affiliate_url")),
        "affiliate_not_configured": count(
            rows, lambda row: row.get("affiliate_status") == "NOT_CONFIGURED"
        ),
        "images": count(rows, lambda row: row.get("image_status") == "AVAILABLE"),
        "missing_images": count(
            rows, lambda row: row.get("image_status") != "AVAILABLE"
        ),
        "previous_prices": count(
            rows, lambda row: float(row.get("previous_price") or 0) > 0
        ),
        "real_discounts": count(
            rows, lambda row: float(row.get("discount_percent") or 0) > 0
        ),
        "average_analytical_score": (
            round(sum(scores) / len(scores), 3) if scores else 0
        ),
        "score_90_or_more": count(
            rows, lambda row: float(row.get("analytical_score") or 0) >= 90
        ),
        "operationally_ready": count(
            rows, lambda row: row.get("operational_ready")
        ),
        "blocked": count(rows, lambda row: not row.get("operational_ready")),
        "duplicates": report.get("metrics", {}).get("duplicates", 0),
    }


def main():
    source = Path("reports/dry_run/dry_run_report.json")
    before_path = Path(
        "reports/operational_readiness/before_dry_run_report.json"
    )
    directory = Path("reports/operational_readiness")
    after = json.loads(source.read_text(encoding="utf-8"))
    before = json.loads(before_path.read_text(encoding="utf-8"))
    result = {
        "before": before.get("metrics", {}),
        "after": metrics(after),
        "products": [
            row for row in after.get("products", [])
            if is_active_store(row.get("loja"))
        ],
        "zero_result_stores": {
            name: data for name, data in after.get("stores", {}).items()
            if data.get("collected", 0) == 0
        },
        "zero_result_diagnosis": {
            name: {
                "cards_found": data.get("collected", 0),
                "reason": "loja_ativa_sem_resultados",
                "action": "tentar novamente em outro ciclo",
            }
            for name, data in after.get("stores", {}).items()
            if data.get("collected", 0) == 0
        },
    }
    json_path = directory / "operational_readiness.json"
    csv_path = directory / "operational_readiness.csv"
    txt_path = directory / "operational_readiness_summary.txt"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows = result["products"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    after_metrics = result["after"]
    lines = [
        "OPERATIONAL READINESS — ANTES / DEPOIS",
        f"Coletados: {result['before'].get('collected', 0)} / {after_metrics['total']}",
        f"Links originais: 84 / {after_metrics['original_links']}",
        f"Links afiliados: 0 / {after_metrics['affiliate_links']}",
        f"Imagens: 64 / {after_metrics['images']}",
        f"Sem imagem: 20 / {after_metrics['missing_images']}",
        f"Score médio: {result['before'].get('average_score', 0)} / "
        f"{after_metrics['average_analytical_score']}",
        f"Score >= 90: 0 / {after_metrics['score_90_or_more']}",
        f"Prontos: 0 / {after_metrics['operationally_ready']}",
        f"Bloqueados: {result['before'].get('blocked', 0)} / "
        f"{after_metrics['blocked']}",
        f"Duplicidades: {result['before'].get('duplicates', 0)} / "
        f"{after_metrics['duplicates']}",
        "",
        "LOJAS COM ZERO RESULTADO",
        *[
            f"{name}: {data['reason']} ({data['action']})"
            for name, data in result["zero_result_diagnosis"].items()
        ],
        "",
        "PRECO E DESCONTO",
        f"Preco atual normalizado: {after_metrics['total']} produtos",
        f"Preco anterior verificavel: {after_metrics['previous_prices']} produtos",
        f"Desconto real calculavel: {after_metrics['real_discounts']} produtos",
        "Valores anteriores ausentes permanecem indisponiveis; nenhum valor foi inventado.",
    ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(after_metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
