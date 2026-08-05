from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.duplicates import DuplicateChecker, PersistentDuplicateHistoryStore
from src.offers.identity import OfferIdentity
from src.offers.models import OfferCandidate
from src.promotion_hunter.categories import classify_category
from src.promotion_hunter.delivery.notifier_adapter import PromotionHunterDeliveryAdapter
from src.promotion_hunter.delivery.queue import PromotionHunterQueue
from src.promotion_hunter.models import HunterDecision, NormalizedProduct, DecisionStatus
from src.promotion_hunter.repository import PromotionHunterRepository
from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.official_runtime import RotatingSources


def candidate(url="https://www.amazon.com.br/produto/dp/B012345678?ref=x", price=100):
    return OfferCandidate.from_mapping({
        "id": "B012345678", "loja": "Amazon", "titulo": "Notebook teste",
        "url": url, "preco_atual": price, "imagem": "https://img/test.jpg",
    })


def test_duplicate_history_survives_repository_restart(tmp_path):
    path = tmp_path / "pipeline.db"
    first = OfferPipelineRepository(path)
    first.migrate()
    identity = OfferIdentity().identify(candidate())
    DuplicateChecker(PersistentDuplicateHistoryStore(first)).remember(
        identity, 100, datetime.now(timezone.utc)
    )
    first.close()

    second = OfferPipelineRepository(path)
    second.migrate()
    result = DuplicateChecker(PersistentDuplicateHistoryStore(second)).check(
        identity, 100, datetime.now(timezone.utc)
    )
    second.close()
    assert result.is_duplicate


def test_active_pending_prevents_second_queue_row(tmp_path):
    repository = PromotionHunterRepository(tmp_path / "hunter.db")
    repository.migrate()
    queue = PromotionHunterQueue(repository)
    product = NormalizedProduct(
        "amazon:B012345678", "Amazon", "Notebook teste",
        external_id="B012345678", current_price=100,
        category="smartphones_tecnologia",
    )
    decision = HunterDecision(
        product.deduplication_key, DecisionStatus.APPROVED, "oferta_aprovada",
        50, "oferta_regular", "pipeline", (),
        delivery_payload={"category": "smartphones_tecnologia"},
    )
    assert queue.enqueue("run-1", product, decision)
    assert queue.enqueue("run-2", product, decision) is None
    assert len(repository.queue_items(("pending",), 10)) == 1
    repository.close()


def test_category_examples_are_canonical():
    expected = {
        "notebook": "smartphones_tecnologia",
        "air fryer": "eletrodomesticos",
        "micro-ondas": "eletrodomesticos",
        "perfume": "beleza_perfumaria",
        "fralda": "mamae_bebe",
        "jogo de cama": "casa_enxoval",
        "detergente": "limpeza_utilidades",
    }
    assert {term: classify_category(term)[0] for term in expected} == expected


def test_automatic_adapter_uses_only_category_group(monkeypatch):
    review = "120000000000000001@g.us"
    technology = "120000000000000002@g.us"
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", review)
    notifier = MagicMock()
    notifier.whatsapp_category_groups.return_value = {
        "smartphones_tecnologia": technology
    }
    notifier.whatsapp_category.return_value = "smartphones_tecnologia"
    notifier.send_whatsapp_message.return_value = True
    adapter = PromotionHunterDeliveryAdapter(notifier, review)
    item = {
        "store": "Amazon", "title": "Notebook", "current_price": 100,
        "previous_price": 120, "image_url": "https://img/test.jpg",
        "product_url": "https://amazon.com.br/dp/B012345678?tag=x-20",
        "category": "smartphones_tecnologia", "search_term": "notebook",
        "breadcrumb": "", "original_category": "",
    }
    result = adapter.send(item)
    assert result.success
    notifier.send_whatsapp_message.assert_called_once()
    assert notifier.send_whatsapp_message.call_args.args[2] == technology


def test_fair_queue_interleaves_categories_and_stores():
    rows = [
        {"category": "smartphones_tecnologia", "store": "Amazon", "title": "N1", "search_term": ""},
        {"category": "smartphones_tecnologia", "store": "Amazon", "title": "N2", "search_term": ""},
        {"category": "eletrodomesticos", "store": "Mercado Livre", "title": "A1", "search_term": ""},
        {"category": "beleza_perfumaria", "store": "Shopee", "title": "P1", "search_term": ""},
    ]
    ordered = PromotionHunterQueue._fair_order(rows)
    assert [row["title"] for row in ordered[:3]] == ["N1", "A1", "P1"]


def test_source_catalog_rotates_without_starvation():
    sources = [
        PromotionSource(f"a-{index}", "keyword", "Amazon", str(index))
        for index in range(5)
    ]
    rotating = RotatingSources(sources, per_store=2)
    cycles = [[item.source_id for item in rotating] for _ in range(3)]
    assert cycles == [["a-0", "a-1"], ["a-2", "a-3"], ["a-4", "a-0"]]
