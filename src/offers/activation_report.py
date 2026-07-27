import csv
import json
from pathlib import Path


class OfferActivationReport:
    def __init__(self, repository):
        self.repository = repository

    def build(self, session_id=""):
        rows = [dict(row) for row in self.repository.activation_report_rows(
            session_id
        )]
        sent = [row for row in rows if row["sent"]]
        rejected = [
            row for row in rows if row["intelligent_decision"] != "enviar"
        ]
        agreements = sum(row["difference"] == "nao" for row in rows)
        divergences = sum(row["difference"] == "sim" for row in rows)
        return {
            "session_id": session_id,
            "decisions": len(rows),
            "agreements": agreements,
            "divergences": divergences,
            "legacy_would_send_intelligent_rejected": sum(
                row["legacy_decision"] == "enviar"
                and row["intelligent_decision"] != "enviar"
                for row in rows
            ),
            "intelligent_approved_legacy_rejected": sum(
                row["legacy_decision"] != "enviar"
                and row["intelligent_decision"] == "enviar"
                for row in rows
            ),
            "average_sent_score": self.average(sent, "score"),
            "average_rejected_score": self.average(rejected, "score"),
            "rollbacks": sum(bool(row["rollback_reason"]) for row in rows),
            "failures": sum(str(row["result"]).startswith("Falha") for row in rows),
            "average_decision_ms": self.average(rows, "decision_ms"),
            "possible_duplicates": sum(
                row["reason"] == "duplicidade" for row in rows
            ),
            "transport_results": sorted({
                row["result"] for row in rows if row["result"]
            }),
            "rows": rows,
        }

    def export_json(self, path, session_id=""):
        target = Path(path)
        target.write_text(
            json.dumps(self.build(session_id), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    def export_csv(self, path, session_id=""):
        target = Path(path)
        rows = self.build(session_id)["rows"]
        fields = list(rows[0]) if rows else [
            "audit_id", "title", "store", "category", "score",
            "scheduler", "legacy_decision", "intelligent_decision",
            "difference", "reason", "result", "decision_ms", "created_at",
        ]
        with target.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return target

    @staticmethod
    def average(rows, field):
        values = [float(row[field] or 0) for row in rows]
        return round(sum(values) / len(values), 3) if values else 0
