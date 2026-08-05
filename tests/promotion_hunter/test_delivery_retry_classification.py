from datetime import datetime, timezone

import pytest
import requests
from unittest.mock import MagicMock

from src.core.notifier import LowResolutionImageError
from src.promotion_hunter.delivery import (
    DeliveryFailureKind,
    PromotionHunterDeliveryAdapter,
    PromotionHunterQueue,
    classify_delivery_failure,
)
from src.promotion_hunter.repository import PromotionHunterRepository


def repository_with_item(tmp_path, *, attempts=0, status="pending", approved_at=None):
    repository = PromotionHunterRepository(tmp_path / "hunter.db")
    repository.migrate()
    approved_at = approved_at or "2026-08-01T12:00:00+00:00"
    cursor = repository.conn.execute("""
        INSERT INTO promotion_hunter_delivery_queue(
            product_key, run_id, title, store, source_ids_json,
            pipeline_status, status, attempts, approved_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        f"amazon:item-{attempts}-{approved_at}", "run", "Produto", "Amazon",
        "[]", "aprovado", status, attempts, approved_at,
    ))
    repository.conn.commit()
    return repository, int(cursor.lastrowid)


def finish_failure(repository, queue_id, error, permanent):
    started = datetime.now(timezone.utc).isoformat()
    attempt_id = repository.start_attempt(queue_id, started)
    repository.finish_attempt(
        queue_id, attempt_id, "failed", started, error, permanent
    )
    return attempt_id


def test_low_resolution_is_permanent():
    error = LowResolutionImageError("imagem pequena", "https://image", 320, 200)
    assert classify_delivery_failure(error) is DeliveryFailureKind.PERMANENT


def adapter_raising(error):
    notifier = MagicMock()
    notifier.whatsapp_category_groups.return_value = {
        "smartphones_tecnologia": "120000000000000001@g.us"
    }
    notifier.whatsapp_category.return_value = "smartphones_tecnologia"
    notifier.format_alert.return_value = "mensagem"
    notifier.send_whatsapp_message.side_effect = error
    return PromotionHunterDeliveryAdapter(notifier, "5511999999999"), notifier


def test_adapter_marks_low_resolution_permanent_and_calls_once():
    error = LowResolutionImageError("imagem pequena", "https://image", 320, 200)
    adapter, notifier = adapter_raising(error)
    result = adapter.send({
        "store": "Amazon", "title": "Produto", "current_price": 10,
        "previous_price": 20, "image_url": "https://image",
        "product_url": "https://product",
        "category": "smartphones_tecnologia",
    })
    assert not result.success and result.permanent
    assert "imagem_resolucao_insuficiente_permanente" in result.error
    assert "https://image" in result.error
    assert "320x200" in result.error
    notifier.send_whatsapp_message.assert_called_once()


def test_adapter_keeps_timeout_temporary_without_real_send():
    adapter, notifier = adapter_raising(requests.Timeout("timeout controlado"))
    result = adapter.send({
        "store": "Amazon", "title": "Produto", "current_price": 10,
        "previous_price": 20, "image_url": "https://image",
        "product_url": "https://product",
        "category": "smartphones_tecnologia",
    })
    assert not result.success and not result.permanent
    assert "timeout controlado" in result.error
    notifier.send_whatsapp_message.assert_called_once()


@pytest.mark.parametrize("error", [
    requests.Timeout("timeout"),
    "Evolution API temporariamente indisponivel HTTP 503",
    "HTTP 500",
    "HTTP 429 rate limit",
])
def test_temporary_failures_remain_temporary(error):
    assert classify_delivery_failure(error) is DeliveryFailureKind.TEMPORARY


@pytest.mark.parametrize("error", [
    "HTTP 404 imagem inexistente",
    "HTTP 415 formato invalido",
    "O arquivo recebido nao e uma imagem valida.",
    "O arquivo recebido não é uma imagem válida.",
])
def test_permanent_4xx_and_invalid_format_are_permanent(error):
    assert classify_delivery_failure(error) is DeliveryFailureKind.PERMANENT


def test_permanent_failure_is_terminal_after_one_attempt(tmp_path):
    repository, queue_id = repository_with_item(tmp_path)
    finish_failure(repository, queue_id, "imagem definitivamente pequena", True)
    stored = repository.conn.execute(
        "SELECT status, attempts, last_error FROM promotion_hunter_delivery_queue WHERE id=?",
        (queue_id,),
    ).fetchone()
    attempts = repository.conn.execute(
        "SELECT status, error_message FROM promotion_hunter_delivery_attempts WHERE queue_id=?",
        (queue_id,),
    ).fetchall()
    pending = PromotionHunterQueue(repository).pending()
    repository.close()
    assert stored["status"] == "cancelled"
    assert stored["attempts"] == 1
    assert stored["last_error"] == "imagem definitivamente pequena"
    assert [(row["status"], row["error_message"]) for row in attempts] == [
        ("failed", "imagem definitivamente pequena")
    ]
    assert pending == ()


def test_temporary_failure_remains_eligible_and_preserves_attempt(tmp_path):
    repository, queue_id = repository_with_item(tmp_path)
    finish_failure(repository, queue_id, "HTTP 503", False)
    stored = repository.conn.execute(
        "SELECT status, attempts, last_error FROM promotion_hunter_delivery_queue WHERE id=?",
        (queue_id,),
    ).fetchone()
    pending_ids = [row["id"] for row in PromotionHunterQueue(repository).pending()]
    repository.close()
    assert tuple(stored) == ("failed", 1, "HTTP 503")
    assert pending_ids == [queue_id]


def test_old_over_limit_item_does_not_starve_new_item(tmp_path):
    repository, old_id = repository_with_item(
        tmp_path, attempts=19, status="failed", approved_at="2026-07-01T00:00:00+00:00"
    )
    cursor = repository.conn.execute("""
        INSERT INTO promotion_hunter_delivery_queue(
            product_key, run_id, title, store, source_ids_json,
            pipeline_status, status, attempts, approved_at
        ) VALUES('amazon:new','run','Novo','Amazon','[]','aprovado','pending',0,?)
    """, ("2026-08-01T00:00:00+00:00",))
    new_id = int(cursor.lastrowid)
    repository.conn.commit()
    pending_ids = [row["id"] for row in PromotionHunterQueue(repository).pending(limit=1)]
    old = repository.conn.execute(
        "SELECT status, attempts FROM promotion_hunter_delivery_queue WHERE id=?",
        (old_id,),
    ).fetchone()
    repository.close()
    assert pending_ids == [new_id]
    assert tuple(old) == ("failed", 19)
