from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_promotion_hunter_pilot import build_runtime, parser


ZONE = ZoneInfo("America/Sao_Paulo")
END_AT = datetime(2026, 7, 30, 8, 0, tzinfo=ZONE)
INTERVAL_SECONDS = 30 * 60
LOG_PATH = ROOT / "logs" / "promotion_hunter_overnight_20260730.log"
PROTECTED_DATABASES = (
    ROOT / "monitor_telemetry.db",
    ROOT / "promobot.db",
    ROOT / "offer_shadow.db",
)


def now():
    return datetime.now(ZONE)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_log(event, **fields):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": now().isoformat(),
        "event": event,
        **fields,
    }
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def protected_hashes():
    return {path.name: digest(path) for path in PROTECTED_DATABASES}


def table_count(repository, table):
    row = repository.conn.execute(
        f"SELECT COUNT(*) FROM {table}"
    ).fetchone()
    return int(row[0])


class ValidatingNormalizer:
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def normalize(self, product, source, collected_at):
        normalized = self.wrapped.normalize(product, source, collected_at)
        price = normalized.current_price
        if price is not None and 0 < price < 10:
            raise RuntimeError(
                "critical_invalid_normalized_price: "
                f"product={normalized.external_id or normalized.deduplication_key} "
                f"price={price}"
            )
        return normalized


class RecordingService:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.last_result = None

    def run(self, sources):
        self.last_result = self.wrapped.run(sources)
        return self.last_result


def execute_cycle(cycle_number, baseline_hashes):
    args = parser().parse_args([
        "--mode", "analysis-only",
        "--once",
        "--term", "SSD 1TB",
        "--limit", "5",
        "--max-messages", "0",
    ])
    repository = pipeline = runner = None
    started = now()
    write_log("cycle_started", cycle=cycle_number, started_at=started)
    try:
        repository, pipeline, runner, sources = build_runtime(args)
        runner.delivery = None
        runner.policy = type(runner.policy)(
            max_products_per_keyword=5,
            max_messages_per_run=0,
        )
        runner.service.normalizer = ValidatingNormalizer(
            runner.service.normalizer
        )
        recording = RecordingService(runner.service)
        runner.service = recording
        attempts_before = table_count(repository, "promotion_hunter_delivery_attempts")
        result = runner.run_once(sources, "analysis_only")
        attempts_after = table_count(repository, "promotion_hunter_delivery_attempts")
        service_result = recording.last_result
        decisions = {
            item.product_key: item for item in service_result.decisions
        }
        products = []
        for product in service_result.normalized_products:
            decision = decisions.get(product.deduplication_key)
            raw_price = (
                product.raw.get("preco_atual")
                or product.raw.get("preco")
                or product.raw.get("price")
            )
            products.append({
                "product": product.external_id or product.deduplication_key,
                "raw_price": raw_price,
                "normalized_price": product.current_price,
                "decision": decision.status.value if decision else None,
                "reason": decision.reason if decision else None,
            })
        if result.sent != 0 or attempts_after != attempts_before:
            raise RuntimeError("critical_delivery_activity_detected")
        current_hashes = protected_hashes()
        if current_hashes != baseline_hashes:
            raise RuntimeError("critical_protected_database_changed")
        finished = now()
        write_log(
            "cycle_completed",
            cycle=cycle_number,
            started_at=started,
            finished_at=finished,
            duration_seconds=(finished - started).total_seconds(),
            raw_cards=None,
            collected=result.collected,
            processed=result.unique,
            products=products,
            approved=result.approved,
            discarded=result.discarded,
            pending=result.pending,
            duplicates=result.collected - result.unique,
            queued=result.queued,
            delivery_attempts=attempts_after - attempts_before,
            delivered=result.sent,
            messages=0,
            errors=result.errors,
        )
        return True
    except Exception as exc:
        write_log(
            "cycle_failed",
            cycle=cycle_number,
            error_type=type(exc).__name__,
            error=" ".join(str(exc).split())[:300],
        )
        return False
    finally:
        if runner is not None:
            try:
                runner.stop()
            except Exception:
                pass
        if pipeline is not None:
            try:
                pipeline.close()
            except Exception:
                pass
        if repository is not None:
            try:
                repository.close()
            except Exception:
                pass


def main():
    os.environ["PROMOTION_HUNTER_LIVE_DELIVERY"] = "false"
    os.environ.pop("PROMOTION_HUNTER_PERSONAL_WHATSAPP", None)
    baseline_hashes = protected_hashes()
    write_log(
        "overnight_started",
        mode="analysis_only",
        store="Mercado Livre",
        terms=["SSD 1TB"],
        limit=5,
        interval_minutes=30,
        end_at=END_AT,
        live_delivery=False,
        destination_loaded=False,
        max_messages=0,
        protected_database_hashes=baseline_hashes,
        historical_warning=(
            "O histórico legado pode distorcer mínimos, descontos e score."
        ),
    )
    cycles = completed = failures = consecutive_failures = 0
    try:
        while now() < END_AT:
            remaining = (END_AT - now()).total_seconds()
            if remaining <= 60:
                break
            cycles += 1
            succeeded = execute_cycle(cycles, baseline_hashes)
            if succeeded:
                completed += 1
                consecutive_failures = 0
            else:
                failures += 1
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    write_log(
                        "aborted",
                        reason="three_consecutive_failures",
                    )
                    break
            sleep_for = min(INTERVAL_SECONDS, (END_AT - now()).total_seconds())
            if sleep_for <= 60:
                break
            time.sleep(sleep_for)
    finally:
        final_hashes = protected_hashes()
        write_log(
            "overnight_finished",
            finished_at=now(),
            cycles_started=cycles,
            cycles_completed=completed,
            failures=failures,
            protected_database_hashes=final_hashes,
            protected_databases_unchanged=(final_hashes == baseline_hashes),
            delivery_attempts=0,
            delivered=0,
            messages=0,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
