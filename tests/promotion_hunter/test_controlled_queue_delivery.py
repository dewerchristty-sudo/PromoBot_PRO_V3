import sqlite3

import pytest
from src.promotion_hunter.delivery.retry_classification import (
    DeliveryResult, DestinationDeliveryResult,
)
from src.promotion_hunter.controlled_delivery import CONTROLLED_CONFIRMATION

from src.promotion_hunter.controlled_delivery import (
    ControlledDeliveryError,
    ControlledQueueDelivery,
)


DESTINATION = "120363410411214947@g.us"
REVIEW = "120363411405237640@g.us"


class FakeNotifier:
    WHATSAPP_CATEGORY_KEYWORDS = {"smartphones_tecnologia": ("celular",)}

    def whatsapp_category(self, _product):
        return "smartphones_tecnologia"

    def whatsapp_category_groups(self):
        return {"smartphones_tecnologia": DESTINATION}

    def format_alert(self, product):
        return f"{product['titulo']}\n{product['link']}"


def databases(tmp_path, *, queue_id=482, status="pending", receipt=False):
    hunter = tmp_path / "hunter.db"
    connection = sqlite3.connect(hunter)
    connection.executescript("""
        CREATE TABLE promotion_hunter_delivery_queue(
          id INTEGER PRIMARY KEY, product_key TEXT, run_id TEXT, title TEXT,
          store TEXT, current_price REAL, previous_price REAL, image_url TEXT,
          product_url TEXT, source_ids_json TEXT, pipeline_status TEXT,
          status TEXT, attempts INTEGER, approved_at TEXT, last_attempt_at TEXT,
          sent_at TEXT, last_error TEXT, created_at TEXT, updated_at TEXT,
          category TEXT, search_term TEXT, breadcrumb TEXT,
          original_category TEXT, classification_source TEXT,
          promotion_signature TEXT
        );
        CREATE TABLE promotion_hunter_destination_receipts(
          id INTEGER PRIMARY KEY, queue_id INTEGER, destination TEXT, accepted INTEGER
        );
        CREATE TABLE promotion_hunter_delivery_attempts(
          id INTEGER PRIMARY KEY, queue_id INTEGER
        );
    """)
    connection.execute(
        "INSERT INTO promotion_hunter_delivery_queue VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (queue_id, "amazon:B0DZPGRMKM", "run", "Celular Samsung Galaxy A06",
         "Amazon", 663.1, 1099.0, "https://image.test/a.jpg",
         "https://amazon.com.br/dp/B0DZPGRMKM", "[]", "aprovado", status,
         0, "2026-08-02T00:00:00+00:00", None, None, None,
         "2026-08-02", "2026-08-02", "", "", "", "", "", ""),
    )
    if receipt:
        connection.execute(
            "INSERT INTO promotion_hunter_destination_receipts VALUES(1,?,?,1)",
            (queue_id, DESTINATION),
        )
    connection.commit(); connection.close()
    pipeline = tmp_path / "pipeline.db"
    connection = sqlite3.connect(pipeline)
    connection.execute("""CREATE TABLE offer_pipeline_items(
        id INTEGER PRIMARY KEY, product_id TEXT, promotion_signature TEXT,
        canonical_identity TEXT)""")
    connection.execute(
        "INSERT INTO offer_pipeline_items VALUES(1,?,?,?)",
        ("B0DZPGRMKM", "commercial-signature", "canonical-identity"),
    )
    connection.commit(); connection.close()
    return hunter, pipeline


def operation(tmp_path, monkeypatch, **kwargs):
    hunter, pipeline = databases(tmp_path, **kwargs)
    monkeypatch.setenv("AMAZON_ASSOCIATE_TAG", "official-20")
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", REVIEW)
    return ControlledQueueDelivery(hunter, pipeline, FakeNotifier), hunter


def test_pending_preview_loads_only_one_and_never_writes(tmp_path, monkeypatch):
    item, hunter = operation(tmp_path, monkeypatch)
    before = hunter.read_bytes()
    result = item.preview(482)
    assert result["selected_queue_ids"] == [482]
    assert result["loaded_queue_count"] == 1
    assert result["resolved_destinations"] == [DESTINATION]
    assert result["review_destination"] is False
    assert result["max_messages"] == 1
    assert result["accelerated_mode_ignored"] is True
    assert result["scheduler_started"] is False
    assert result["collection_started"] is False
    assert result["evolution_post_count"] == 0
    assert result["other_queue_rows_changed"] == 0
    assert hunter.read_bytes() == before


@pytest.mark.parametrize("status", ["sent", "cancelled", "failed", "sending"])
def test_non_pending_is_refused(tmp_path, monkeypatch, status):
    item, _ = operation(tmp_path, monkeypatch, status=status)
    with pytest.raises(ControlledDeliveryError, match="nao esta pending"):
        item.preview(482)


def test_missing_queue_id_is_refused(tmp_path, monkeypatch):
    item, _ = operation(tmp_path, monkeypatch)
    with pytest.raises(ControlledDeliveryError, match="inexistente"):
        item.preview(999)


def test_completed_receipt_blocks_resend(tmp_path, monkeypatch):
    item, _ = operation(tmp_path, monkeypatch, receipt=True)
    with pytest.raises(ControlledDeliveryError, match="recibo concluido"):
        item.preview(482)


def test_multiple_destinations_are_refused(tmp_path, monkeypatch):
    item, _ = operation(tmp_path, monkeypatch)
    class MultipleAdapter:
        def __init__(self, notifier, destination): pass
        def _resolve_destinations(self, product):
            return [DESTINATION, "999999999999999999@g.us"]
    item.adapter_factory = MultipleAdapter
    with pytest.raises(ControlledDeliveryError, match="exige um destino"):
        item.preview(482)


def test_review_destination_is_refused(tmp_path, monkeypatch):
    item, _ = operation(tmp_path, monkeypatch)
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", DESTINATION)
    with pytest.raises(ControlledDeliveryError, match="Review"):
        item.preview(482)


def test_real_path_is_single_attempt_and_does_not_load_backlog(tmp_path, monkeypatch):
    item, _ = operation(tmp_path, monkeypatch)
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    monkeypatch.setenv("PROMOTION_HUNTER_REAL_SEND_AUTHORIZED", "true")
    calls = []
    class Repository:
        def __init__(self, path): calls.append(("open", str(path)))
        def start_controlled_attempt(self, queue_id, destination, started):
            calls.append(("attempt", queue_id, destination)); return 7
        def record_destination_results(self, queue_id, key, attempt, results):
            calls.append(("receipt", queue_id, attempt, len(results)))
        def finish_attempt(self, queue_id, attempt, status, *args):
            calls.append(("finish", queue_id, attempt, status))
        def close(self): calls.append(("close",))
    class Adapter:
        def __init__(self, notifier, destination): pass
        def _resolve_destinations(self, product): return [DESTINATION]
        def send(self, queue_item, completed):
            calls.append(("send", queue_item["id"], tuple(completed)))
            return DeliveryResult(True, "", None, "sucesso_total", (
                DestinationDeliveryResult(
                    destination=DESTINATION, request_made=True, accepted=True
                ),
            ))
    item.repository_factory = Repository
    item.adapter_factory = Adapter
    result = item.execute(482, confirmation=CONTROLLED_CONFIRMATION)
    assert result["success"] is True
    assert [call[0] for call in calls].count("attempt") == 1
    assert [call[0] for call in calls].count("send") == 1
    assert ("send", 482, ()) in calls
    assert result["max_messages"] == 1
