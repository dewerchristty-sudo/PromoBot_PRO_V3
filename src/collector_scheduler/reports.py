from dataclasses import asdict
import json
from pathlib import Path


OUTPUT = Path("reports/collector_scheduler")


def write_status(status):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "scheduler_status.json"
    path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def write_run(result):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = asdict(result)
    json_path = OUTPUT / "scheduler_last_run.json"
    summary_path = OUTPUT / "scheduler_summary.txt"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    summary_path.write_text(
        "\n".join((
            "PROMOBOT - AGENDADOR DE COLETA DE PRECOS",
            f"Status: {result.status}",
            f"Ultima execucao: {result.ended_at.isoformat()}",
            f"Proxima execucao: {result.next_run}",
            f"Produtos: {result.products}",
            f"Observacoes validas: {result.valid_observations}",
            f"Duplicatas: {result.duplicates}",
            f"Falhas: {result.failures}",
            f"Retries: {result.retries}",
            f"Duracao: {result.duration_seconds}s",
            "Mensagens enviadas: 0",
        )) + "\n",
        encoding="utf-8",
    )
    return json_path, summary_path
