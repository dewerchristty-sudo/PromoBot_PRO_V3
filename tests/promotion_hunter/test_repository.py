import sqlite3

from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.repository import PromotionHunterRepository


EXPECTED_TABLES = {
    "promotion_hunter_sources",
    "promotion_hunter_runs",
    "promotion_hunter_source_runs",
    "promotion_hunter_decisions",
}


def test_migration_is_idempotent_and_uses_only_temporary_database(tmp_path):
    database = tmp_path / "hunter.db"
    repository = PromotionHunterRepository(database)
    repository.migrate()
    repository.migrate()
    tables = {
        row[0] for row in repository.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    repository.close()
    assert EXPECTED_TABLES <= tables
    assert database.exists()


def test_repository_records_generic_source_without_other_databases(tmp_path):
    database = tmp_path / "hunter.db"
    repository = PromotionHunterRepository(database)
    repository.migrate()
    repository.upsert_source(PromotionSource(
        "source", "keyword", "Mercado Livre", "Fonte",
        {"terms": ["produto"]},
    ))
    repository.close()
    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT source_type, store FROM promotion_hunter_sources"
        ).fetchone() == ("keyword", "Mercado Livre")
    assert {path.name for path in tmp_path.iterdir()} == {"hunter.db"}
