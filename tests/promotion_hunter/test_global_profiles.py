import sqlite3

from src.promotion_hunter.profiles import (
    AUTHORIZED_PROFILE_IDS,
    PROFILE_BY_ID,
    RotatingProfileSources,
    build_profile_sources,
)
from src.promotion_hunter.normalization import ProductNormalizer
from src.promotion_hunter.repository import PromotionHunterRepository
from src.promotion_hunter.delivery.queue import PromotionHunterQueue


def test_catalog_has_only_three_profiles_and_no_store_term_duplicates():
    sources = build_profile_sources(
        stores=("Amazon", "Mercado Livre", "Shopee"), limit=2
    )
    assert set(AUTHORIZED_PROFILE_IDS) == {
        "tecnologia_acessorios", "cosmeticos", "eletrodomesticos"
    }
    pairs = [(item.store.casefold(), item.display_name.casefold()) for item in sources]
    assert len(pairs) == len(set(pairs))
    forbidden = {"fralda", "detergente", "jogo de cama", "móvel", "brinquedo"}
    assert forbidden.isdisjoint({item.display_name.casefold() for item in sources})


def test_profile_category_is_authoritative_from_source_to_product():
    normalizer = ProductNormalizer()
    examples = {
        "tecnologia_acessorios": ("notebook", "smartphones_tecnologia"),
        "cosmeticos": ("shampoo", "beleza_perfumaria"),
        "eletrodomesticos": ("air fryer", "eletrodomesticos"),
    }
    for profile_id, (term, category) in examples.items():
        source = next(item for item in build_profile_sources(stores=("Amazon",))
                      if item.configuration["profile_id"] == profile_id
                      and item.display_name == term)
        product = normalizer.normalize(
            {"id": profile_id, "titulo": "Título sem pista", "preco": 10}, source
        )
        assert product.profile_id == profile_id
        assert product.category == category
        assert product.classification_source == "profile"


def test_rotation_is_fair_and_skips_disabled_profile():
    sources = build_profile_sources(stores=("Amazon",), limit=1)
    rotating = RotatingProfileSources(sources, per_store=1)
    observed = [next(iter(rotating)).configuration["profile_id"] for _ in range(6)]
    assert observed == list(AUTHORIZED_PROFILE_IDS) * 2
    limited = build_profile_sources(
        stores=("Amazon",), enabled_profiles=("cosmeticos", "eletrodomesticos")
    )
    rotating = RotatingProfileSources(limited, per_store=1)
    assert [next(iter(rotating)).configuration["profile_id"] for _ in range(4)] == [
        "cosmeticos", "eletrodomesticos", "cosmeticos", "eletrodomesticos"
    ]


def test_legacy_database_migration_adds_profile_without_rewriting_queue(tmp_path):
    path = tmp_path / "legacy.db"
    repository = PromotionHunterRepository(path)
    repository.migrate()
    repository.conn.execute(
        "INSERT INTO promotion_hunter_delivery_queue("
        "product_key,run_id,title,store,pipeline_status,approved_at) "
        "VALUES('legacy','run','Legacy','Amazon','aprovado','2026-01-01')"
    )
    repository.conn.commit()
    original_id = repository.conn.execute(
        "SELECT id FROM promotion_hunter_delivery_queue WHERE product_key='legacy'"
    ).fetchone()[0]
    repository.migrate()
    row = repository.conn.execute(
        "SELECT id,profile_id FROM promotion_hunter_delivery_queue "
        "WHERE product_key='legacy'"
    ).fetchone()
    assert (row[0], row[1]) == (original_id, "")
    assert repository.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert repository.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    repository.close()


def test_delivery_queue_rotates_profiles_with_one_global_limit():
    class Rows:
        def queue_items(self, *_args, **_kwargs):
            return [
                {"id": 1, "profile_id": "tecnologia_acessorios", "category": "smartphones_tecnologia", "store": "Amazon", "title": "n", "search_term": "n"},
                {"id": 2, "profile_id": "cosmeticos", "category": "beleza_perfumaria", "store": "Amazon", "title": "p", "search_term": "p"},
                {"id": 3, "profile_id": "eletrodomesticos", "category": "eletrodomesticos", "store": "Amazon", "title": "a", "search_term": "a"},
            ]

        def recover_sending(self):
            return 0

    queue = PromotionHunterQueue(Rows())
    assert [queue.pending(limit=1)[0]["id"] for _ in range(6)] == [1, 2, 3, 1, 2, 3]
