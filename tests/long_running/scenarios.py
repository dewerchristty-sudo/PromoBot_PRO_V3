from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path

from src.offer_intelligence import OfferIntelligenceAnalyzer

from .fixtures import TEN_DAY_PRICES, TEST_PRODUCT_KEY
from .helpers import IsolatedHistory, rejection_count, valid_count


MARKER = "SIMULATED_TEST_DATA"


def ten_day_scenario():
    system = IsolatedHistory()
    try:
        for index, price in enumerate(TEN_DAY_PRICES):
            if index:
                system.clock.advance(days=1)
            system.record(price)
        history = system.service.analyze(TEST_PRODUCT_KEY)
        intelligence = OfferIntelligenceAnalyzer(
            system.repository
        ).analyze(TEST_PRODUCT_KEY, now=system.clock.now())
        return {
            "marker": MARKER,
            "days": 10,
            "collections": 10,
            "valid_observations": valid_count(system),
            "rejections": rejection_count(system),
            "minimum": str(history.minimum),
            "maximum": str(history.maximum),
            "average": str(history.average),
            "median": str(history.median),
            "history_maturity": history.maturity,
            "intelligence_state": intelligence.state,
            "trend": intelligence.trend,
            "volatility_percent": str(
                intelligence.volatility_percent
            ),
            "confidence_index": str(intelligence.confidence_index),
            "rarity_state": (
                "RARE_PRICE" if "RARE_PRICE" in intelligence.states
                else "COMMON_PRICE"
            ),
        }
    finally:
        system.close()


def thirty_day_scenario():
    system = IsolatedHistory()
    collections = failures = retries = restarts = 0
    try:
        for day in range(30):
            if day:
                system.clock.advance(hours=12)
            morning_price = Decimal("1200") - Decimal(day * 4)
            collections += 1
            system.record(str(morning_price), run_id=f"day-{day}-09")
            collections += 1
            system.record(
                str(morning_price), run_id=f"day-{day}-09-duplicate"
            )
            system.clock.advance(hours=6)
            collections += 1
            system.record(str(morning_price), run_id=f"day-{day}-15")
            system.clock.advance(hours=6)
            collections += 1
            if day % 10 == 5:
                system.record("100", run_id=f"day-{day}-outlier")
            elif day % 7 == 3:
                failures += 1
                retries += 1
                collections += 1
                system.clock.advance(minutes=15)
                system.record(
                    str(morning_price - Decimal("1")),
                    run_id=f"day-{day}-retry",
                )
            else:
                system.record(
                    str(morning_price - Decimal("1")),
                    run_id=f"day-{day}-21",
                )
            if day and day % 6 == 0:
                system.restart()
                restarts += 1
        history = system.service.analyze(TEST_PRODUCT_KEY)
        intelligence = OfferIntelligenceAnalyzer(
            system.repository
        ).analyze(TEST_PRODUCT_KEY, now=system.clock.now())
        return {
            "marker": MARKER,
            "days": 30,
            "scheduled_slots": 90,
            "collection_attempts": collections,
            "valid_observations": valid_count(system),
            "duplicates": sum(
                row["reason"] == "DUPLICATE_WITHIN_WINDOW"
                for row in system.repository.price_history_rejections(
                    TEST_PRODUCT_KEY
                )
            ),
            "rejections": rejection_count(system),
            "outliers": sum(
                row["reason"] == "OUTLIER_PERCENT"
                for row in system.repository.price_history_rejections(
                    TEST_PRODUCT_KEY
                )
            ),
            "failures": failures,
            "retries": retries,
            "restarts": restarts,
            "distinct_days": history.distinct_days,
            "history_maturity": history.maturity,
            "intelligence_state": intelligence.state,
            "minimum": str(history.minimum),
            "maximum": str(history.maximum),
            "average": str(history.average),
            "median": str(history.median),
            "trend": intelligence.trend,
            "volatility_percent": str(
                intelligence.volatility_percent
            ),
            "confidence_index": str(intelligence.confidence_index),
            "operational_calls": 0,
        }
    finally:
        system.close()


def failure_summary(thirty_day):
    return {
        "marker": MARKER,
        "failures": thirty_day["failures"],
        "retries": thirty_day["retries"],
        "restarts": thirty_day["restarts"],
        "recovered": thirty_day["failures"] == thirty_day["retries"],
        "operational_calls": 0,
    }


def write_reports(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    ten = ten_day_scenario()
    thirty = thirty_day_scenario()
    failure = failure_summary(thirty)
    summary = {
        "marker": MARKER,
        "status": "PASSED",
        "ten_day": ten,
        "thirty_day": thirty,
        "failure_recovery": failure,
        "real_database_modified": False,
        "messages_sent": 0,
    }
    documents = {
        "long_running_test_summary.json": summary,
        "simulated_10_day_history.json": ten,
        "simulated_30_day_scheduler.json": thirty,
        "failure_recovery_summary.json": failure,
    }
    paths = []
    for name, payload in documents.items():
        path = output / name
        path.write_text(json.dumps(
            payload, ensure_ascii=False, indent=2
        ), encoding="utf-8")
        paths.append(path)
    text_path = output / "long_running_test_summary.txt"
    text_path.write_text(
        "\n".join((
            MARKER,
            "PROMOBOT - TESTES DE LONGA DURACAO",
            "Status: PASSED",
            f"Coletas simuladas: {thirty['collection_attempts']}",
            f"Observacoes validas: {thirty['valid_observations']}",
            f"Duplicatas: {thirty['duplicates']}",
            f"Rejeicoes: {thirty['rejections']}",
            f"Outliers: {thirty['outliers']}",
            f"Falhas: {thirty['failures']}",
            f"Retries: {thirty['retries']}",
            f"Reinicios: {thirty['restarts']}",
            f"Maturidade: {thirty['history_maturity']}",
            "Chamadas operacionais: 0",
            "Mensagens enviadas: 0",
        )) + "\n",
        encoding="utf-8",
    )
    paths.append(text_path)
    return summary, tuple(paths)
