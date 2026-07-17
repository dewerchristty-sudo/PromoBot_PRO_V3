import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.store_manager import StoreManager


def main():

    termo = " ".join(sys.argv[1:]).strip() or "ssd 1tb"
    report = {
        "termo": termo,
        "data": datetime.now().isoformat(timespec="seconds"),
        "lojas": [],
    }

    print(f"Health check: {termo}\n")

    for loja in StoreManager.stable_store_names():

        manager = StoreManager(enabled_stores=[loja])

        try:

            resultados = manager.search_all(termo)
            status = "ok" if resultados else "sem_resultados"

            report["lojas"].append({
                "loja": loja,
                "status": status,
                "total": len(resultados),
                "primeiro": resultados[0] if resultados else None,
            })

            print(f"{loja}: {status} ({len(resultados)})")

        except Exception as erro:

            report["lojas"].append({
                "loja": loja,
                "status": "erro",
                "erro": str(erro),
            })

            print(f"{loja}: erro - {erro}")

    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    output = logs / "health_check.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\nRelatorio salvo em: {output}")


if __name__ == "__main__":
    main()
