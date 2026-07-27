import csv
from datetime import datetime, timezone
import json
from pathlib import Path

from src.affiliates.diagnostics import AffiliateDiagnostics
from scripts.prepare_shopee_affiliate_mapping import (
    build_candidates, recent_shopee_products, write_candidates,
)


def dry_run_report(path=Path("reports/dry_run/dry_run_report.json")):
    report = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists() else {"stores": {}, "affiliate_by_store": {}}
    )
    for key, store in (
        ("mercado_livre", "Mercado Livre"),
        ("amazon", "Amazon"),
        ("shopee", "Shopee"),
    ):
        isolated = path.parent / key / "dry_run_report.json"
        if not isolated.exists():
            continue
        value = json.loads(isolated.read_text(encoding="utf-8"))
        if store in value.get("stores", {}):
            report.setdefault("stores", {})[store] = value["stores"][store]
        if store in value.get("affiliate_by_store", {}):
            report.setdefault("affiliate_by_store", {})[store] = (
                value["affiliate_by_store"][store]
            )
    return report


def build_onboarding(diagnostic, dry_report, candidates):
    dry_stores = dry_report.get("stores", {})
    affiliate = dry_report.get("affiliate_by_store", {})
    candidate_counts = {
        "mapped": sum(row["mapping_status"] == "MAPPED"
                      for row in candidates),
        "missing": sum(row["mapping_status"] == "MISSING"
                       for row in candidates),
    }
    rows = []
    for status in diagnostic["stores"]:
        store = status["store"]
        collection = dry_stores.get(store, {})
        operation = affiliate.get(store, {})
        next_step = {
            "Mercado Livre": (
                "Execute python -m scripts.recover_mercado_livre_session"
                if status.get("session_status") != "SESSION_READY"
                else "Execute o Dry Run isolado do Mercado Livre."
            ),
            "Amazon": (
                "Preencha manualmente AMAZON_ASSOCIATE_TAG com a tag "
                "obtida no portal Amazon Associados e execute o diagnostico."
                if status["status"] != "VALIDATED"
                else "Execute o Dry Run isolado da Amazon."
            ),
            "Shopee": (
                "Preencha manualmente os candidatos com links oficiais "
                "da Shopee e atualize o mapa."
                if candidate_counts["missing"]
                else "Execute o Dry Run isolado da Shopee."
            ),
        }[store]
        rows.append({
            "store": store,
            "configuration_status": status["status"],
            "session_status": status.get("session_status", ""),
            "collection_status": (
                "FAILED" if collection.get("error") else "READY"
            ),
            "products": collection.get("collected", 0),
            "mapped_products": (
                candidate_counts["mapped"] if store == "Shopee" else 0
            ),
            "unmapped_products": (
                candidate_counts["missing"] if store == "Shopee" else 0
            ),
            "links_generated": operation.get("links_generated", 0),
            "links_blocked": operation.get("failures", 0),
            "operationally_ready": operation.get("operationally_ready", 0),
            "reasons": operation.get("block_reasons", {}),
            "next_step": next_step,
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stores": rows,
        "safety": {
            "env_modified": False, "messages_sent": False,
            "secrets_included": False,
        },
    }


def write_onboarding(report, directory=Path("reports/affiliate_onboarding")):
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "affiliate_onboarding.json"
    csv_path = directory / "affiliate_onboarding.csv"
    summary_path = directory / "affiliate_onboarding_summary.txt"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    csv_rows = [{
        **{key: value for key, value in row.items() if key != "reasons"},
        "reasons": json.dumps(row["reasons"], ensure_ascii=False),
    } for row in report["stores"]]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    lines = ["PROMOBOT - ONBOARDING DE AFILIADOS", ""]
    for row in report["stores"]:
        lines.extend((
            row["store"],
            f"- configuracao: {row['configuration_status']}",
            f"- sessao: {row['session_status'] or 'nao aplicavel'}",
            f"- produtos: {row['products']}",
            f"- mapeados: {row['mapped_products']}",
            f"- links gerados: {row['links_generated']}",
            f"- prontos: {row['operationally_ready']}",
            f"- proximo passo: {row['next_step']}", "",
        ))
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, csv_path, summary_path


def main():
    diagnostics = AffiliateDiagnostics()
    try:
        diagnostic = diagnostics.run()
    finally:
        diagnostics.close()
    candidates = build_candidates(recent_shopee_products())
    write_candidates(candidates)
    report = build_onboarding(diagnostic, dry_run_report(), candidates)
    paths = write_onboarding(report)
    for row in report["stores"]:
        print(f"\n{row['store']}")
        print("- configuracao:", row["configuration_status"])
        if row["session_status"]:
            print("- sessao:", row["session_status"])
        print("- geracao disponivel:",
              row["configuration_status"] == "VALIDATED")
        if row["store"] == "Shopee":
            print("- produtos mapeados:", row["mapped_products"])
            print("- produtos sem mapa:", row["unmapped_products"])
        print("- proximo passo:", row["next_step"])
    print("\nRelatorios:", ", ".join(str(path) for path in paths))
    return report


if __name__ == "__main__":
    main()
