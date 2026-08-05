"""Testes automatizados para o fluxo de pos-envio controlado.

ETAPA 6 — PROMOBOT PRO V3.3.0
Testes A a G conforme especificacao.
Usa banco temporario e Notifier/Evolution simulados. NUNCA realiza POST real.
"""

import sqlite3
from datetime import datetime, timezone
import pytest

from src.promotion_hunter.controlled_delivery import (
    CONTROLLED_CONFIRMATION,
    ControlledDeliveryError,
    ControlledQueueDelivery,
)
from src.database.offer_repository import OfferRepository
from src.offers.queue import OfferQueue

DESTINATION = "120363410411214947@g.us"
REVIEW = "120363411405237640@g.us"
PROMOTION_SIGNATURE = "38992db80742a86c1983223afdfb68d691b2d0df149124eeb213f4501c4dc3d6"
CANONICAL_IDENTITY = "38b9fc41d60dbda294e951fe445fbaf3bd97bb113dd2901339737d10f6c22ff7"


def _now():
    return datetime(2026, 8, 4, 20, 14, 35, 124168, tzinfo=timezone.utc)


class FakeNotifier:
    WHATSAPP_CATEGORY_KEYWORDS = {"eletrodomesticos": ("liquidificador",)}
    def whatsapp_category(self, _product):
        return "eletrodomesticos"
    def whatsapp_category_groups(self):
        return {"eletrodomesticos": DESTINATION}
    def format_alert(self, product):
        return f"{product.get("titulo", "")}\n{product.get("link", "")}"


class FakeNotifierWithReceipt(FakeNotifier):
    def __init__(self, should_succeed=True, http_status=201, message_id=""):
        super().__init__()
        self._message_id = message_id
        self.should_succeed = should_succeed
        self.http_status = http_status
    def send_whatsapp_message(self, *args, **kwargs):
        self.last_delivery_receipt = {
            "http_status": self.http_status, "status": "PENDING",
            "message_id": self._message_id,
            "evolution_status": "aceito_pela_evolution",
            "delivery_confirmed": False,
            "timestamp": _now().isoformat(), "destino": DESTINATION,
            "response_summary": {"status": "PENDING"},
        }
        if not self.should_succeed:
            raise RuntimeError(f"HTTP {self.http_status} simulado")
        return True


class Http500Notifier(FakeNotifier):
    def send_whatsapp_message(self, *args, **kwargs):
        raise ConnectionError("HTTP 500 Internal Server Error simulado")


class PreSendErrorNotifier(FakeNotifier):
    def format_alert(self, product):
        raise ValueError("Erro na formatacao da mensagem")


def _make_databases(tmp_path, offer_status="queued", queue_status="pending",
                    queue_id=482, offer_id=871):
    hunter_path = tmp_path / "hunter.db"
    c = sqlite3.connect(hunter_path)
    c.executescript("""
        CREATE TABLE promotion_hunter_delivery_queue(
          id INTEGER PRIMARY KEY, product_key TEXT, run_id TEXT, title TEXT,
          store TEXT, current_price REAL, previous_price REAL, image_url TEXT,
          product_url TEXT, source_ids_json TEXT, pipeline_status TEXT,
          status TEXT, attempts INTEGER, approved_at TEXT, last_attempt_at TEXT,
          sent_at TEXT, last_error TEXT, created_at TEXT, updated_at TEXT,
          category TEXT, search_term TEXT, breadcrumb TEXT,
          original_category TEXT, classification_source TEXT,
          promotion_signature TEXT, profile_id TEXT
        );
        CREATE TABLE promotion_hunter_destination_receipts(
          id INTEGER PRIMARY KEY, queue_id INTEGER,
          product_key TEXT, destination TEXT,
          attempt_id INTEGER, attempted_at TEXT,
          request_made INTEGER, http_status INTEGER,
          returned_status TEXT, evolution_status TEXT,
          accepted INTEGER, error_message TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE promotion_hunter_delivery_attempts(
          id INTEGER PRIMARY KEY, queue_id INTEGER,
          started_at TEXT, finished_at TEXT,
          status TEXT, error_message TEXT
        );
    """)
    c.execute(
        "INSERT INTO promotion_hunter_delivery_queue VALUES("
        "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (queue_id, "amazon:B08DFJRCJB", "run-test",
         "Liquidificador 1400 Full Oster Preto 3,2L - 220V",
         "Amazon", 156.66, 319.9, "https://image.test/img.jpg",
         "https://amazon.com.br/dp/B08DFJRCJB",
         "[]", "aprovado", queue_status,
         0, "2026-08-04T20:14:35+00:00", None, None, None,
         "2026-08-04", "2026-08-04",
         "eletrodomesticos", "", "", "", "",
         PROMOTION_SIGNATURE, ""),
    )
    c.commit(); c.close()

    pipeline_path = tmp_path / "pipeline.db"
    c = sqlite3.connect(pipeline_path)
    c.executescript("""
        CREATE TABLE offer_pipeline_items(
            id INTEGER PRIMARY KEY, product_id TEXT,
            promotion_signature TEXT, canonical_identity TEXT,
            run_id TEXT, title TEXT, store TEXT
        );
        CREATE TABLE IF NOT EXISTS offer_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluation_id TEXT NOT NULL, product_id TEXT NOT NULL DEFAULT '',
            canonical_identity TEXT NOT NULL,
            promotion_signature TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '', store TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            current_price REAL NOT NULL DEFAULT 0,
            previous_price REAL NOT NULL DEFAULT 0,
            discount_percent REAL NOT NULL DEFAULT 0,
            saving_amount REAL NOT NULL DEFAULT 0,
            score REAL NOT NULL DEFAULT 0,
            classification TEXT NOT NULL DEFAULT 'oferta_fraca',
            confidence REAL NOT NULL DEFAULT 0,
            score_components_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'queued' CHECK (
                status IN ('queued','blocked','reserved','selected_shadow',
                'sent','expired','discarded','failed','cancelled')
            ),
            priority REAL NOT NULL DEFAULT 0,
            available_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            reserved_at TEXT, reserved_by TEXT NOT NULL DEFAULT '',
            reservation_expires_at TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            blocked_reason TEXT NOT NULL DEFAULT '',
            blocked_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            sent_at TEXT
        );
        CREATE TABLE IF NOT EXISTS offer_queue_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scheduler_run_id TEXT NOT NULL DEFAULT '',
            queue_item_id INTEGER NOT NULL,
            action TEXT NOT NULL, previous_status TEXT NOT NULL DEFAULT '',
            new_status TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            shadow_mode INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY(queue_item_id) REFERENCES offer_queue(id)
        );
    """)
    c.execute("INSERT INTO offer_pipeline_items VALUES(1,?,?,?,?,?,?)",
              ("B08DFJRCJB", PROMOTION_SIGNATURE, CANONICAL_IDENTITY,
               "run-pipe", "Liquidificador 1400 Full Oster", "Amazon"))
    c.execute(
        "INSERT INTO offer_queue(id,evaluation_id,product_id,canonical_identity,"
        "promotion_signature,title,store,category,current_price,previous_price,"
        "discount_percent,saving_amount,score,classification,confidence,"
        "score_components_json,status,priority,available_at,expires_at,"
        "attempts,created_at,updated_at,sent_at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (offer_id, "eval-871", "B08DFJRCJB", CANONICAL_IDENTITY, PROMOTION_SIGNATURE,
         "Liquidificador 1400 Full Oster Preto 3,2L - 220V",
         "Amazon", "eletrodomesticos", 156.66, 319.9, 51.03,
         163.24, 39.0, "oferta_fraca_sem_evidencia", 30.0, "{}",
         offer_status, 3930.0,
         "2026-08-04T20:14:35+00:00", "2026-08-05T08:14:35+00:00",
         0, "2026-08-04T20:14:35+00:00", "2026-08-04T20:14:35+00:00", None),
    )
    c.commit(); c.close()
    return hunter_path, pipeline_path


def _make_delivery(tmp_path, monkeypatch, notifier_class=None, **db_kwargs):
    hunter_path, pipeline_path = _make_databases(tmp_path, **db_kwargs)
    if notifier_class is None:
        notifier_class = FakeNotifier
    monkeypatch.setenv("AMAZON_ASSOCIATE_TAG", "official-20")
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", REVIEW)
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    monkeypatch.setenv("PROMOTION_HUNTER_REAL_SEND_AUTHORIZED", "true")
    return ControlledQueueDelivery(
        database_path=hunter_path, pipeline_path=pipeline_path,
        notifier_factory=notifier_class, clock=_now,
    ), hunter_path, pipeline_path




# ================================================================
# Teste A ? sucesso: queued -> reserved -> selected_shadow -> sent
# ================================================================

def test_a_success_flow(tmp_path, monkeypatch):
    delivery, hunter_path, pipeline_path = _make_delivery(
        tmp_path, monkeypatch,
        notifier_class=FakeNotifierWithReceipt,
        offer_status="queued", queue_status="pending",
    )
    result = delivery.execute(482, confirmation=CONTROLLED_CONFIRMATION)
    assert result["success"] is True
    assert result["evolution_post_count"] == 1

    offer_repo = OfferRepository(pipeline_path)
    offer_repo.migrate()
    item = offer_repo.get(871)
    assert item is not None
    assert item.status == "sent", f"Esperado sent, obtido {item.status}"
    assert item.sent_at is not None
    assert item.attempts == 1, f"Esperado attempts=1, obtido {item.attempts}"
    offer_repo.close()

    c = sqlite3.connect(hunter_path)
    c.row_factory = sqlite3.Row
    row = c.execute(
        "SELECT status, attempts, sent_at FROM promotion_hunter_delivery_queue WHERE id=482"
    ).fetchone()
    assert row["status"] == "sent"
    assert row["attempts"] == 1
    c.close()


# ================================================================
# Teste A.2 ? receipt com message_id
# ================================================================

def test_a2_receipt_with_message_id(tmp_path, monkeypatch):
    msg_id = "3EB0517C463ABB8262D789005F941C34484719BD"
    delivery, _, pipeline_path = _make_delivery(
        tmp_path, monkeypatch,
        notifier_class=lambda: FakeNotifierWithReceipt(message_id=msg_id),
        offer_status="queued",
    )
    result = delivery.execute(482, confirmation=CONTROLLED_CONFIRMATION)
    assert result["success"] is True

    c = sqlite3.connect(pipeline_path)
    c.row_factory = sqlite3.Row
    decisions = c.execute(
        "SELECT * FROM offer_queue_decisions WHERE queue_item_id=871 ORDER BY id DESC"
    ).fetchall()
    c.close()
    sent_decision = None
    for d in decisions:
        if d["new_status"] == "sent":
            sent_decision = d; break
    assert sent_decision is not None, "Decisao 'sent' nao encontrada"
    assert msg_id in sent_decision["reason"], (
        f"message_id {msg_id} ausente: {sent_decision['reason']}"
    )


# ================================================================
# Teste B ? HTTP 500: nao marca sent
# ================================================================

def test_b_http500_failure(tmp_path, monkeypatch):
    delivery, _, pipeline_path = _make_delivery(
        tmp_path, monkeypatch,
        notifier_class=Http500Notifier,
        offer_status="queued",
    )
    result = delivery.execute(482, confirmation=CONTROLLED_CONFIRMATION)
    assert result["success"] is False

    offer_repo = OfferRepository(pipeline_path)
    offer_repo.migrate()
    item = offer_repo.get(871)
    assert item is not None
    assert item.status != "sent", f"Nao deveria estar sent: {item.status}"
    assert item.sent_at is None
    offer_repo.close()


# ================================================================
# Teste C ? excecao antes do POST
# ================================================================

def test_c_exception_before_post(tmp_path, monkeypatch):
    delivery, _, pipeline_path = _make_delivery(
        tmp_path, monkeypatch,
        notifier_class=PreSendErrorNotifier,
        offer_status="queued",
    )
    with pytest.raises(ValueError):
        delivery.execute(482, confirmation=CONTROLLED_CONFIRMATION)

    offer_repo = OfferRepository(pipeline_path)
    offer_repo.migrate()
    item = offer_repo.get(871)
    assert item is not None
    assert item.status == "queued", f"Esperado queued, obtido {item.status}"
    assert item.reserved_at is None
    assert item.reserved_by == ""
    offer_repo.close()


# ================================================================
# Teste D ? restart apos sucesso (item sent nao volta)
# ================================================================

def test_d_idempotency_after_sent(tmp_path, monkeypatch):
    delivery, _, pipeline_path = _make_delivery(
        tmp_path, monkeypatch,
        notifier_class=FakeNotifierWithReceipt,
        offer_status="queued", queue_status="pending",
    )
    result = delivery.execute(482, confirmation=CONTROLLED_CONFIRMATION)
    assert result["success"] is True

    offer_repo = OfferRepository(pipeline_path)
    offer_repo.migrate()
    assert offer_repo.get(871).status == "sent"
    offer_repo.close()

    with pytest.raises(ControlledDeliveryError, match="nao esta pending"):
        delivery.execute(482, confirmation=CONTROLLED_CONFIRMATION)


# ================================================================
# Teste E ? restart com queued (preview sem envio)
# ================================================================

def test_e_restart_with_queued_only_preview(tmp_path, monkeypatch):
    delivery, hunter_path, _ = _make_delivery(
        tmp_path, monkeypatch, offer_status="queued", queue_status="pending",
    )
    before = hunter_path.read_bytes()
    preview = delivery.preview(482)
    assert preview["queue_id"] == 482
    assert preview["status"] == "pending"
    assert hunter_path.read_bytes() == before


# ================================================================
# Teste F ? receipt sem message_id ainda envia como sent
# ================================================================

def test_f_success_without_message_id(tmp_path, monkeypatch):
    delivery, _, pipeline_path = _make_delivery(
        tmp_path, monkeypatch,
        notifier_class=FakeNotifierWithReceipt,
        offer_status="queued",
    )
    result = delivery.execute(482, confirmation=CONTROLLED_CONFIRMATION)
    assert result["success"] is True

    offer_repo = OfferRepository(pipeline_path)
    offer_repo.migrate()
    item = offer_repo.get(871)
    assert item.status == "sent"
    assert item.sent_at is not None
    offer_repo.close()


# ================================================================
# Teste G ? outros Queue IDs inalterados
# ================================================================

def test_g_other_queue_ids_unchanged(tmp_path, monkeypatch):
    delivery, _, pipeline_path = _make_delivery(
        tmp_path, monkeypatch,
        notifier_class=FakeNotifierWithReceipt,
        offer_status="queued", queue_status="pending",
    )
    c = sqlite3.connect(pipeline_path)
    # Insere outro item com id=999 para verificar que nao e alterado
    c.execute(
        "INSERT INTO offer_queue(id,evaluation_id,product_id,canonical_identity,"
        "promotion_signature,title,store,category,current_price,previous_price,"
        "discount_percent,saving_amount,score,classification,confidence,"
        "score_components_json,status,priority,available_at,expires_at,"
        "attempts,created_at,updated_at,sent_at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (999, "eval-999", "B0XYZ", "canonical-999", "signature-999",
         "Outro Produto", "Amazon", "eletrodomesticos",
         100.0, 200.0, 50.0, 100.0, 50.0, "boa_oferta", 80.0, "{}",
         "queued", 5000.0,
         "2026-08-04T20:14:35+00:00", "2026-08-05T08:14:35+00:00",
         0, "2026-08-04", "2026-08-04", None),
    )
    c.commit(); c.close()

    result = delivery.execute(482, confirmation=CONTROLLED_CONFIRMATION)
    assert result["success"] is True

    offer_repo = OfferRepository(pipeline_path)
    offer_repo.migrate()
    assert offer_repo.get(871).status == "sent"
    assert offer_repo.get(999).status == "queued", "Outro QID alterado!"
    offer_repo.close()


# ================================================================
# Teste H ? nao permite transicao direta queued -> sent
# ================================================================

def test_h_no_direct_queued_to_sent():
    assert "sent" not in OfferQueue.VALID_TRANSITIONS["queued"]


# ================================================================
# Teste I ? selected_shadow abandonado: recuperacao
# ================================================================

def test_i_selected_shadow_abandoned_recovery(tmp_path):
    assert OfferQueue.VALID_TRANSITIONS["selected_shadow"] == {"sent", "cancelled"}
    _, pipeline_path = _make_databases(
        tmp_path, offer_status="selected_shadow", queue_status="sent",
    )
    offer_repo = OfferRepository(pipeline_path)
    offer_repo.migrate()
    oq = OfferQueue(offer_repo)
    # Encontra o item pela promotion_signature (ID pode variar)
    row = offer_repo.conn.execute(
        "SELECT id, status FROM offer_queue WHERE promotion_signature=?",
        (PROMOTION_SIGNATURE,),
    ).fetchone()
    assert row is not None, "Item nao encontrado no offer_queue"
    offer_id = int(row["id"])
    assert row["status"] == "selected_shadow"
    oq.transition(offer_id, "cancelled", "selected_shadow recuperado sem evidencia")
    assert offer_repo.get(offer_id).status == "cancelled"
    offer_repo.close()


# ================================================================
# Teste J ? POST aceito + processo encerrado = nao reenviar
# ================================================================

def test_j_post_accepted_no_duplicate(tmp_path):
    _, pipeline_path = _make_databases(
        tmp_path, offer_status="selected_shadow", queue_status="sent",
    )
    offer_repo = OfferRepository(pipeline_path)
    offer_repo.migrate()
    oq = OfferQueue(offer_repo)
    row = offer_repo.conn.execute(
        "SELECT id, status FROM offer_queue WHERE promotion_signature=?",
        (PROMOTION_SIGNATURE,),
    ).fetchone()
    assert row is not None, "Item nao encontrado no offer_queue"
    offer_id = int(row["id"])
    assert row["status"] == "selected_shadow"
    oq.transition(
        offer_id, "sent",
        "Reconciliado: envio ja confirmado no hunter.",
        run_id="recovery",
        fields={"sent_at": _now(), "attempts": 1},
    )
    item = offer_repo.get(offer_id)
    assert item.status == "sent"
    assert item.sent_at is not None
    offer_repo.close()
