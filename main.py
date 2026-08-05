from __future__ import annotations

import argparse
import json
import sys
import os
import threading
import multiprocessing
from pathlib import Path

from dotenv import load_dotenv

from src.affiliates.config import runtime_env_path
from src.core.desktop_shortcut import ensure_desktop_shortcut
from src.version import __version__
from src.startup_diagnostics import install_exception_logging, startup_log


# Ponto de injecao preservado para testes; a GUI continua com import tardio.
PromoBot = None


def main() -> None:
    global PromoBot
    # Obrigatório no executável congelado: impede subprocessos de bibliotecas
    # (incluindo Playwright) de reexecutarem o entrypoint da interface.
    multiprocessing.freeze_support()
    install_exception_logging()
    startup_log("01 processo iniciado")
    startup_log("02 sys.frozen detectado", f"frozen={bool(getattr(sys, 'frozen', False))}")
    startup_log(
        "03 caminhos resolvidos",
        f"executable={sys.executable} meipass={getattr(sys, '_MEIPASS', '')} cwd={Path.cwd()}",
    )
    if _startup_probe_cli(sys.argv[1:]):
        startup_log("19 processo finalizado")
        return
    load_dotenv(runtime_env_path(), override=True)
    if _operational_cli(sys.argv[1:]):
        return
    if PromoBot is None:
        from src.app import PromoBot as PromoBotClass
        PromoBot = PromoBotClass
    ensure_desktop_shortcut()
    sistema = PromoBot()
    sistema.run()


def _startup_probe_cli(argv):
    if not argv or argv[0] != "--startup-probe":
        return False
    parser = argparse.ArgumentParser(description="PromoBot startup probe")
    parser.add_argument("--startup-probe", action="store_true")
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    env_path = runtime_env_path()
    startup_log("04 .env localizado", str(env_path))
    load_dotenv(env_path, override=True)
    startup_log("05 .env carregado", f"exists={env_path.is_file()}")
    startup_log("06 bancos localizados", f"database={Path(args.database).resolve()}")
    os.environ["PROMOTION_HUNTER_LIVE_DELIVERY"] = "false"
    os.environ["PROMOTION_HUNTER_REAL_SEND_AUTHORIZED"] = "false"
    from src.app import PromoBot
    _write_result(args.output, {"probe_stage": "constructing_app", "version": __version__})
    app = PromoBot(db_path=args.database, startup_probe=True)
    _write_result(args.output, {"probe_stage": "app_constructed", "version": __version__})
    startup_log("10 mainloop iniciado")
    app.run()
    startup_log("18 mainloop encerrado")
    residual = [
        {"name": item.name, "daemon": item.daemon}
        for item in threading.enumerate()
        if item is not threading.current_thread() and item.is_alive()
    ]
    payload = {
        "version": __version__,
        "frozen": bool(getattr(sys, "frozen", False)),
        "dashboard_loaded": app.app.current_page == "dashboard",
        "shutdown_clean": app.app.shutdown_clean,
        "residual_threads": residual,
        "scheduler_started": False,
        "hunter_started": False,
        "evolution_post_count": 0,
    }
    _write_result(args.output, payload)
    return True


def _write_result(path, payload):
    text = json.dumps(payload, ensure_ascii=True, indent=2, default=str)
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        print(text)


def _operational_cli(argv):
    if not argv or argv[0] not in {
        "--hunter-runtime-probe", "--controlled-queue-id",
        "--amazon-collection-test",
    }:
        return False
    parser = argparse.ArgumentParser(description="PromoBot operational CLI")
    parser.add_argument("--hunter-runtime-probe", action="store_true")
    parser.add_argument("--controlled-queue-id", type=int)
    parser.add_argument("--amazon-collection-test", type=str, default="")
    parser.add_argument("--database", default="promotion_hunter.db")
    parser.add_argument(
        "--pipeline-database", default="promotion_hunter_offer_pipeline.db"
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    load_dotenv(runtime_env_path(), override=True)
    if args.amazon_collection_test:
        os.environ["PROMOTION_HUNTER_LIVE_DELIVERY"] = "false"
        os.environ["PROMOTION_HUNTER_REAL_SEND_AUTHORIZED"] = "false"
        keyword = args.amazon_collection_test.strip()
        if not keyword:
            _write_result(args.output, {"error": "keyword vazia"})
            return True
        from src.promotion_hunter.adapters.amazon import (
            AmazonCollectionAdapter,
        )
        adapter = AmazonCollectionAdapter()
        try:
            products = adapter.collect(keyword, limit=5)
            normalized = [
                p for p in products
                if p.get("titulo") and p.get("preco") and p.get("link")
            ]
            payload = {
                "version": __version__,
                "frozen": bool(getattr(sys, "frozen", False)),
                "keyword": keyword,
                "products_found": len(products),
                "products_normalized": len(normalized),
                "status": "success" if products else "zero_results",
                "sample": [
                    {
                        "titulo": p.get("titulo", "")[:80],
                        "preco": p.get("preco", ""),
                        "link": p.get("link", "")[:80],
                        "categoria": p.get(
                            "categoria_original",
                            p.get("categoria_manual", ""),
                        ),
                    }
                    for p in products[:3]
                ],
            }
        except Exception as error:
            payload = {
                "version": __version__,
                "frozen": bool(getattr(sys, "frozen", False)),
                "keyword": keyword,
                "products_found": 0,
                "products_normalized": 0,
                "status": "error",
                "error_type": type(error).__name__,
                "error_message": str(error)[:500],
            }
        _write_result(args.output, payload)
        return True
    if args.hunter_runtime_probe:
        from src.promotion_hunter.official_runtime import OfficialHunterController
        from src.promotion_hunter.process_lock import HunterProcessLock
        controller = OfficialHunterController()
        started = controller.start(mode="analysis_only")
        running_before_stop = controller.running
        controller.stop()
        payload = {
            "version": __version__,
            "frozen": bool(getattr(sys, "frozen", False)),
            "started": bool(started),
            "running_before_stop": running_before_stop,
            "running_after_stop": controller.running,
            "mutex_released": not HunterProcessLock.is_locked(),
            "mode": "analysis_only",
            "scheduler_started": True,
            "collection_started": False,
            "evolution_post_count": 0,
            "external_script_used": False,
            "sys_executable_used_as_python": False,
        }
    else:
        from src.promotion_hunter.controlled_delivery import (
            ControlledQueueDelivery,
        )
        operation = ControlledQueueDelivery(
            args.database, args.pipeline_database
        )
        result = operation.preview(args.controlled_queue_id)
        payload = {
            key: value for key, value in result.items()
            if not key.startswith("_")
        }
        payload["version"] = __version__
        payload["frozen"] = bool(getattr(sys, "frozen", False))
    _write_result(args.output, payload)
    return True


if __name__ == "__main__":
    main()
