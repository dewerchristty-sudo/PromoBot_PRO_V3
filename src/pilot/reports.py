import csv
import json
from pathlib import Path


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def write_diagnostic(payload, directory=Path("reports/pilot")):
    directory.mkdir(parents=True, exist_ok=True)
    json_path = write_json(directory / "pilot_diagnostic.json", payload)
    csv_path = directory / "pilot_diagnostic.csv"
    row = {
        "pilot_state": payload["pilot"]["state"],
        "enabled": payload["configuration"]["enabled"],
        "group_configured": payload["configuration"]["group_configured"],
        "manual_confirmation":
            payload["configuration"]["manual_confirmation"],
        "score": payload["product"].get("score", 0),
        "threshold": payload["product"].get("threshold", 0),
        "operationally_ready":
            payload["product"].get("operationally_ready", False),
        "selected": payload["product"].get("selected", False),
        "authorized": payload["product"].get("authorized", False),
        "reason": payload["pilot"]["reason"],
        "transport_called": payload["transport"]["called"],
    }
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    summary_path = directory / "pilot_diagnostic_summary.txt"
    summary_path.write_text(
        "\n".join((
            "PROMOBOT - DIAGNOSTICO DO PILOTO",
            f"Estado: {row['pilot_state']}",
            f"Grupo configurado: {row['group_configured']}",
            f"Score: {row['score']}",
            f"Threshold: {row['threshold']}",
            f"Operacionalmente pronto: {row['operationally_ready']}",
            f"Selecionado: {row['selected']}",
            f"Autorizado: {row['authorized']}",
            f"Motivo: {row['reason']}",
            f"Transporte chamado: {row['transport_called']}",
        )) + "\n",
        encoding="utf-8",
    )
    return json_path, csv_path, summary_path


def write_dry_run(payload, preview, directory=Path("reports/pilot")):
    json_path = write_json(directory / "pilot_dry_run.json", payload)
    preview_path = directory / "pilot_message_preview.txt"
    preview_path.write_text(preview, encoding="utf-8")
    return json_path, preview_path
