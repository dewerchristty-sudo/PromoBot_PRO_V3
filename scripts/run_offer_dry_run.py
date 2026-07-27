import csv
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import tracemalloc
from urllib.parse import urlparse

from src.core.store_manager import StoreManager
from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.activation import OfferActivationFlags
from src.offers.canary import OfferCanaryController
from src.offers.pipeline import OfferPipeline


TEMPORARY_FLAGS = {
    "OFFER_INTELLIGENT_SCHEDULER_ENABLED": "True",
    "OFFER_COMPARE_WITH_LEGACY": "True",
    "OFFER_CANARY_PERCENT": "5",
    "OFFER_MIN_SCORE_TO_SEND": "90",
    "OFFER_MAX_SEND_PER_HOUR": "1",
    "OFFER_MAX_SEND_PER_DAY": "3",
    "OFFER_ENABLE_ROLLBACK": "True",
    "OFFER_DRY_RUN_TRANSPORT": "True",
    # Políticas internas do Scheduler sombra.
    "OFFER_MAX_PER_HOUR": "1",
    "OFFER_MAX_PER_DAY": "3",
    "OFFER_MIN_SCORE": "90",
    "OFFER_EXCELLENT_SCORE": "90",
    "OFFER_SHADOW_PIPELINE_ENABLED": "False",
}


def masked_affiliate_url(url):
    if not url:
        return ""
    parsed = urlparse(str(url))
    return f"{parsed.scheme}://{parsed.hostname}/[mascarado]"


def sha256(path):
    target = Path(path)
    return hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else ""


STORE_NAMES = {
    "mercado_livre": "Mercado Livre",
    "mercadolivre": "Mercado Livre",
    "amazon": "Amazon",
    "shopee": "Shopee",
}


def normalize_store_argument(value):
    if not value:
        return ""
    key = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    if key not in STORE_NAMES:
        raise argparse.ArgumentTypeError(
            "Loja invalida. Use mercado_livre, amazon ou shopee."
        )
    return key


def collect_all(query, store_key=""):
    enabled = (
        [STORE_NAMES[store_key]]
        if store_key else ["Mercado Livre", "Amazon", "Shopee"]
    )
    manager = StoreManager(enabled_stores=enabled)
    products = []
    stores = {}
    for store in manager.stores:
        started = time.perf_counter()
        error = ""
        try:
            found = manager.sanitize_results(store.search(query))
            found = manager.filter_by_requested_capacity(query, found)
            found = manager.filter_by_requested_product_type(query, found)
            found = manager.filter_by_requested_model_codes(query, found)
            found = manager.filter_by_query_relevance(query, found)
        except Exception as exc:
            found = []
            error = f"{type(exc).__name__}: {exc}"
        elapsed = round(time.perf_counter() - started, 3)
        stores[store.name] = {
            "collected": len(found), "seconds": elapsed, "error": error
        }
        products.extend(found)
        print(
            f"{store.name}: {len(found)} produto(s), {elapsed:.3f}s"
            + (f", erro={error}" if error else "")
        )
    return products, stores


def item_row(item):
    analysis = item.analysis
    candidate = analysis.candidate if analysis else None
    history = analysis.history if analysis else None
    duplicate = analysis.duplicate if analysis else None
    score = analysis.score if analysis else None
    filtering = analysis.filtering if analysis else None
    queue = item.queue_item
    signals = dict(candidate.future_signals or {}) if candidate else {}
    return {
        "loja": candidate.store if candidate else "",
        "categoria": candidate.category if candidate else "",
        "titulo": candidate.title if candidate else "",
        "preco": candidate.current_price if candidate else 0,
        "preco_anterior": candidate.previous_price if candidate else 0,
        "identidade": analysis.identity.signature if analysis else "",
        "historico_amostras": history.sample_count if history else 0,
        "historico_minimo": history.minimum if history else 0,
        "duplicidade": bool(duplicate and duplicate.is_duplicate),
        "tipo_duplicidade": duplicate.duplicate_type if duplicate else "",
        "score": score.total if score else 0,
        "classificacao": score.classification if score else "",
        "motivos_score": " | ".join(score.reasons) if score else "",
        "componentes_score": json.dumps(
            dict(score.components) if score else {}, ensure_ascii=False
        ),
        "analytical_score": score.total if score else 0,
        "promotion_confidence": score.confidence if score else 0,
        "score_policy_version": score.policy_version if score else 0,
        "original_url": signals.get("original_url", ""),
        "affiliate_url": masked_affiliate_url(
            signals.get("affiliate_url", "")
        ),
        "affiliate_provider": signals.get("affiliate_provider", ""),
        "affiliate_status": signals.get("affiliate_status", ""),
        "affiliate_error": signals.get("affiliate_error", ""),
        "affiliate_source": signals.get("affiliate_source", ""),
        "affiliate_cache_hit": signals.get("affiliate_cache_hit", False),
        "affiliate_elapsed_ms": signals.get("affiliate_elapsed_ms", 0),
        "image_url": signals.get("image_url", ""),
        "image_source": signals.get("image_source", ""),
        "image_status": signals.get("image_status", ""),
        "image_error": signals.get("image_error", ""),
        "current_price": signals.get("current_price", 0),
        "previous_price": signals.get("previous_price", 0),
        "discount_percent": signals.get("discount_percent", 0),
        "discount_source": signals.get("discount_source", ""),
        "price_status": signals.get("price_status", ""),
        "title_quality": signals.get("title_quality", ""),
        "history_span_hours": signals.get("history_span_hours", 0),
        "history_reliable_for_score": signals.get(
            "history_reliable_for_score", False
        ),
        "discount_verified": signals.get("discount_verified", False),
        "rating": candidate.rating if candidate else None,
        "review_count": candidate.review_count if candidate else 0,
        "sold_count": candidate.sold_count if candidate else 0,
        "stock_available": candidate.stock_available if candidate else None,
        "availability": candidate.availability if candidate else "",
        "seller_reputation": (
            candidate.seller_reputation if candidate else ""
        ),
        "category_demand": candidate.category_demand if candidate else "",
        "operational_ready": bool(
            queue and queue.status not in {"blocked", "discarded", "failed"}
        ),
        "filtro_aprovado": bool(filtering and filtering.approved),
        "fila": queue.status if queue else "",
        "bloqueios_operacionais": (
            queue.blocked_reason if queue else ""
        ),
        "motivos_filtro": (
            " | ".join(filtering.reasons) if filtering else ""
        ),
        "ranking": queue.priority if queue else 0,
        "scheduler": item.scheduler_status,
        "resultado_final": (
            "SERIA ENVIADA"
            if item.scheduler_status == "selected_shadow"
            else "NÃO SERIA ENVIADA"
        ),
        "motivo_final": item.diagnostic.reason,
        "tempo_ms": item.processing_ms,
        "erro": item.error,
    }


def write_reports(report, rows, directory):
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "dry_run_report.json"
    csv_path = directory / "dry_run_report.csv"
    summary_path = directory / "dry_run_summary.txt"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [
            "loja", "titulo", "score", "resultado_final"
        ])
        writer.writeheader()
        writer.writerows(rows)
    metrics = report["metrics"]
    affiliate = report.get("affiliate_metrics", {})
    lines = [
        "PROMOBOT — DRY RUN OPERACIONAL",
        f"Executado em: {report['executed_at']}",
        f"Consulta: {report['query']}",
        f"Total coletado: {metrics['collected']}",
        f"Total analisado: {metrics['analyzed']}",
        f"Descartados: {metrics['discarded']}",
        f"Duplicados: {metrics['duplicates']}",
        f"Bloqueados: {metrics['blocked']}",
        f"Aprovados: {metrics['approved']}",
        f"Excelentes: {metrics['excellent']}",
        f"Boas: {metrics['good']}",
        f"Na fila: {metrics['queued']}",
        f"Selecionados: {metrics['selected']}",
        f"Rejeitados: {metrics['rejected']}",
        f"Score médio: {metrics['average_score']}",
        f"Canary: 5% | Score mínimo: 90 | Limites: 1/h e 3/dia",
        f"Transporte chamado: {report['safety']['transport_called']}",
        f"Auto-Stop: {report['safety']['auto_stop']}",
        f"Tempo total: {report['performance']['total_seconds']}s",
        f"Memória aproximada de pico: {report['performance']['peak_memory_mb']} MB",
        "",
        "POR LOJA",
        *[
            f"{name}: {data['collected']} em {data['seconds']}s"
            + (f" | {data['error']}" if data["error"] else "")
            for name, data in report["stores"].items()
        ],
        "",
        "PRODUTOS QUE SERIAM ENVIADOS",
        *[
            f"{row['score']:.1f} | {row['loja']} | {row['titulo']}"
            for row in rows if row["resultado_final"] == "SERIA ENVIADA"
        ],
    ]
    lines[lines.index("POR LOJA"):lines.index("POR LOJA")] = [
        "AFILIADOS",
        f"Gerados: {affiliate.get('generated', 0)}",
        f"Cache: {affiliate.get('cache_hits', 0)}",
        f"Falhas: {affiliate.get('failures', 0)}",
        f"URLs invalidas: {affiliate.get('invalid', 0)}",
        f"Tempo medio: {affiliate.get('average_ms', 0)} ms",
        "",
    ]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [str(json_path), str(csv_path), str(summary_path)]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Dry Run protegido do PromoBot."
    )
    parser.add_argument(
        "--store", type=normalize_store_argument, default="",
        help="mercado_livre, amazon ou shopee",
    )
    parser.add_argument("--query", default="")
    args = parser.parse_args(argv)
    query = os.getenv("DRY_RUN_QUERY", "ssd 1tb")
    if args.query:
        query = args.query
    default_output = (
        f"reports/dry_run/{args.store}" if args.store else "reports/dry_run"
    )
    output = Path(os.getenv("DRY_RUN_REPORT_PATH", default_output))
    env_hash_before = sha256(".env")
    original = {name: os.environ.get(name) for name in TEMPORARY_FLAGS}
    transport_called = False
    started_total = time.perf_counter()
    tracemalloc.start()
    pipeline = None
    repository = None
    try:
        os.environ.update(TEMPORARY_FLAGS)
        products, stores = collect_all(query, args.store)
        repository = OfferPipelineRepository(
            Path(os.getenv("OFFER_SHADOW_DB_PATH", "offer_shadow.db"))
        )
        repository.migrate()
        pipeline = OfferPipeline(repository)
        pipeline_started = time.perf_counter()
        result = pipeline.process_batch(products)
        pipeline_seconds = round(time.perf_counter() - pipeline_started, 3)

        def forbidden_transport(_alerts):
            nonlocal transport_called
            transport_called = True
            raise AssertionError("Transporte proibido no Dry Run.")

        canary_result = OfferCanaryController(
            repository, OfferActivationFlags.from_environment()
        ).execute(products, forbidden_transport)
        rows = [item_row(item) for item in result.items]
        selected = [
            row for row in rows if row["resultado_final"] == "SERIA ENVIADA"
        ]
        rejected = [
            row for row in rows if row["resultado_final"] != "SERIA ENVIADA"
        ]
        excellent = sum(
            row["classificacao"] in {
                "oferta_excepcional", "oferta_excelente"
            } for row in rows
        )
        good = sum(row["classificacao"] in {
            "oferta_muito_boa", "oferta_boa", "boa_oferta"
        } for row in rows)
        metrics = result.metrics
        affiliate_metrics = asdict(pipeline.affiliate_manager.metrics())
        affiliate_by_store = {}
        for store_name, store_data in stores.items():
            store_rows = [
                row for row in rows if row["loja"] == store_name
            ]
            counters = affiliate_metrics["by_store"].get(store_name, {})
            blockers = {}
            for row in store_rows:
                reason = row["affiliate_error"] or row["affiliate_status"]
                if not row["operational_ready"] and reason:
                    blockers[reason] = blockers.get(reason, 0) + 1
            affiliate_by_store[store_name] = {
                "products_collected": store_data["collected"],
                "link_requests": counters.get("requests", 0),
                "links_generated": counters.get("generated", 0),
                "cache_hits": counters.get("cache_hits", 0),
                "failures": counters.get("failures", 0)
                            + counters.get("invalid", 0),
                "block_reasons": blockers,
                "operationally_ready": sum(
                    row["operational_ready"] for row in store_rows
                ),
            }
        peak = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
        report = {
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "requested_store": (
                STORE_NAMES.get(args.store, "Todas") if args.store else "Todas"
            ),
            "temporary_flags": TEMPORARY_FLAGS,
            "stores": stores,
            "metrics": {
                "collected": len(products),
                "analyzed": metrics.received_count,
                "discarded": metrics.discarded_count,
                "duplicates": metrics.duplicate_count,
                "blocked": metrics.blocked_count,
                "approved": metrics.approved_count,
                "excellent": excellent,
                "good": good,
                "queued": metrics.queued_count,
                "selected": metrics.selected_shadow_count,
                "rejected": len(rows) - metrics.selected_shadow_count,
                "average_score": metrics.average_score,
            },
            "affiliate_metrics": affiliate_metrics,
            "affiliate_by_store": affiliate_by_store,
            "comparison": {
                "legacy_would_send": len(rows),
                "intelligent_would_send": len(selected),
                "same": len(selected),
                "different": len(rejected),
                "difference_reasons": {
                    reason: sum(row["motivo_final"] == reason for row in rejected)
                    for reason in sorted({
                        row["motivo_final"] for row in rejected
                    })
                },
            },
            "limits": {
                "canary_percent": 5, "minimum_score": 90,
                "max_per_hour": 1, "max_per_day": 3,
            },
            "safety": {
                "dry_run_result": canary_result,
                "transport_called": transport_called,
                "notifier_called": False,
                "whatsapp_called": False,
                "evolution_called": False,
                "auto_stop": "nenhum",
                "env_unchanged": env_hash_before == sha256(".env"),
            },
            "performance": {
                "pipeline_seconds": pipeline_seconds,
                "score_ms": metrics.stage_timings_ms.get("analysis", 0),
                "queue_ms": metrics.stage_timings_ms.get("queue", 0),
                "scheduler_ms": metrics.stage_timings_ms.get("scheduler", 0),
                "total_seconds": round(time.perf_counter() - started_total, 3),
                "peak_memory_mb": round(peak, 3),
            },
            "top_20_scores": sorted(
                rows, key=lambda row: row["score"], reverse=True
            )[:20],
            "top_20_approved": sorted(
                [row for row in rows if row["filtro_aprovado"]],
                key=lambda row: row["score"], reverse=True,
            )[:20],
            "top_20_rejected": sorted(
                rejected, key=lambda row: row["score"], reverse=True
            )[:20],
            "would_send": selected,
            "scheduler_rejected": rejected,
            "products": rows,
        }
        files = write_reports(report, rows, output)
        print(json.dumps({
            "metrics": report["metrics"],
            "performance": report["performance"],
            "safety": report["safety"],
            "reports": files,
        }, ensure_ascii=False, indent=2))
        if transport_called:
            raise AssertionError("Dry Run tentou chamar transporte.")
        if env_hash_before != sha256(".env"):
            raise AssertionError("O arquivo .env foi alterado.")
    finally:
        tracemalloc.stop()
        if pipeline is not None:
            # O repositório pertence ao executor e é fechado uma única vez.
            pipeline.close()
            repository = None
        elif repository is not None:
            repository.close()
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    main()
