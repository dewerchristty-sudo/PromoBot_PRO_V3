import csv
import json
from pathlib import Path
import sqlite3


def main():
    directory = Path("reports/dry_run")
    json_path = directory / "dry_run_report.json"
    report = json.loads(json_path.read_text(encoding="utf-8"))
    connection = sqlite3.connect("offer_shadow.db")
    try:
        blocks = {
            row[0]: row[1]
            for row in connection.execute("""
                SELECT canonical_identity, blocked_reason
                FROM offer_queue
            """)
        }
    finally:
        connection.close()

    def enrich(row):
        row["bloqueios_operacionais"] = blocks.get(
            row.get("identidade", ""), ""
        )
        row.setdefault("motivos_filtro", "")
        return row

    for key in (
        "products", "top_20_scores", "top_20_approved",
        "top_20_rejected", "would_send", "scheduler_rejected",
    ):
        report[key] = [enrich(row) for row in report.get(key, [])]
    report["operational_block_summary"] = {}
    for row in report["products"]:
        reason = row["bloqueios_operacionais"] or "sem_bloqueio"
        report["operational_block_summary"][reason] = (
            report["operational_block_summary"].get(reason, 0) + 1
        )
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rows = report["products"]
    with (directory / "dry_run_report.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (directory / "dry_run_summary.txt").open(
        "a", encoding="utf-8"
    ) as stream:
        stream.write("\nBLOQUEIOS OPERACIONAIS\n")
        for reason, total in report["operational_block_summary"].items():
            stream.write(f"{reason}: {total}\n")
    print(report["operational_block_summary"])


if __name__ == "__main__":
    main()
