import hashlib
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.statistics.repository import StatisticsRepository


class StatisticsRepositoryTest(unittest.TestCase):

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "statistics.db"
        connection = sqlite3.connect(self.database_path)
        connection.executescript("""
            CREATE TABLE produtos(
                id INTEGER PRIMARY KEY,
                loja TEXT,
                titulo TEXT,
                preco_valor REAL,
                preco_antigo REAL,
                link TEXT,
                categoria_manual TEXT,
                categoria_original TEXT,
                data TEXT
            );
            CREATE TABLE historico_envios(
                id INTEGER PRIMARY KEY,
                loja TEXT,
                titulo TEXT,
                link_original TEXT,
                canal TEXT,
                status TEXT,
                data TEXT
            );
            CREATE TABLE pendencias_revisao(
                id INTEGER PRIMARY KEY,
                status TEXT
            );
            CREATE TABLE alertas(id INTEGER PRIMARY KEY, ativo INTEGER);
            CREATE TABLE entregas_destino(
                id INTEGER PRIMARY KEY,
                status TEXT
            );
            CREATE TABLE tentativas_entrega(
                id INTEGER PRIMARY KEY,
                entrega_id INTEGER,
                status TEXT
            );
        """)
        connection.executemany("""
            INSERT INTO produtos VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            (
                1, "Shopee", "Produto A", 80, 100, "link-a",
                "Casa", "", "2026-07-28 10:00:00",
            ),
            (
                2, "Amazon", "Produto B", 50, 0, "link-b",
                "", "", "2026-07-29 10:00:00",
            ),
            (
                3, "Shopee", "Produto C", 40, 50, "link-c",
                "", "Beleza", "2026-07-29 11:00:00",
            ),
        ))
        connection.executemany("""
            INSERT INTO historico_envios VALUES(?,?,?,?,?,?,?)
        """, (
            (
                1, "Shopee", "Produto A", "link-a", "WhatsApp",
                "enviado", "2026-07-28 12:00:00",
            ),
            (
                2, "Shopee", "Produto A", "link-a", "Telegram",
                "enviado", "2026-07-29 12:00:00",
            ),
            (
                3, "Amazon", "Produto B", "link-b", "WhatsApp",
                "falhou", "2026-07-29 13:00:00",
            ),
        ))
        connection.executemany(
            "INSERT INTO pendencias_revisao VALUES(?,?)",
            ((1, "pendente"), (2, "resolvida")),
        )
        connection.executemany(
            "INSERT INTO alertas VALUES(?,?)",
            ((1, 1), (2, 0)),
        )
        connection.executemany(
            "INSERT INTO entregas_destino VALUES(?,?)",
            (
                (1, "enviado"),
                (2, "falhou"),
                (3, "aguardando_nova_tentativa"),
                (4, "falha_definitiva"),
                (5, "revisao_necessaria"),
            ),
        )
        connection.executemany(
            "INSERT INTO tentativas_entrega VALUES(?,?,?)",
            ((1, 2, "falhou"), (2, 2, "falhou")),
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def test_snapshot_aggregates_only_authorized_indicators(self):
        repository = StatisticsRepository(self.database_path)
        snapshot = repository.snapshot()
        repository.close()

        self.assertEqual(snapshot.total_products, 3)
        self.assertEqual(snapshot.total_sends, 2)
        self.assertEqual(snapshot.pending_reviews, 1)
        self.assertEqual(snapshot.active_alerts, 1)
        self.assertEqual(snapshot.failed_deliveries, 4)
        self.assertEqual(
            [(item.label, item.total) for item in snapshot.products_by_store],
            [("Shopee", 2), ("Amazon", 1)],
        )
        self.assertEqual(
            {item.label: item.total for item in snapshot.sends_by_channel},
            {"Telegram": 1, "WhatsApp": 1},
        )

    def test_failures_count_current_deliveries_not_attempts_or_reviews(self):
        repository = StatisticsRepository(self.database_path)
        snapshot = repository.snapshot()
        repository.close()
        self.assertEqual(snapshot.failed_deliveries, 4)

    def test_coverage_and_commercial_averages_are_explicit(self):
        repository = StatisticsRepository(self.database_path)
        snapshot = repository.snapshot()
        repository.close()

        self.assertEqual(snapshot.products_by_category.covered, 2)
        self.assertEqual(snapshot.products_by_category.total, 3)
        self.assertEqual(snapshot.sent_categories.covered, 2)
        self.assertEqual(snapshot.sent_categories.total, 2)
        self.assertEqual(snapshot.average_discount.covered, 2)
        self.assertEqual(snapshot.average_discount.total, 3)
        self.assertAlmostEqual(snapshot.average_discount.average, 20.0)
        self.assertAlmostEqual(snapshot.average_savings.average, 15.0)

    def test_rankings_recent_sends_and_time_series(self):
        repository = StatisticsRepository(self.database_path)
        snapshot = repository.snapshot()
        repository.close()

        self.assertEqual(snapshot.most_sent_products[0].label, "Produto A")
        self.assertEqual(snapshot.most_sent_products[0].total, 2)
        self.assertEqual(len(snapshot.recent_sends), 2)
        self.assertEqual(snapshot.recent_sends[0].channel, "Telegram")
        self.assertEqual(
            [(point.period, point.total) for point in snapshot.daily_sends],
            [("2026-07-28", 1), ("2026-07-29", 1)],
        )
        self.assertEqual(sum(p.total for p in snapshot.weekly_collections), 3)

    def test_empty_old_database_without_optional_tables(self):
        old_path = Path(self.temporary.name) / "old.db"
        connection = sqlite3.connect(old_path)
        connection.execute(
            "CREATE TABLE produtos(id INTEGER PRIMARY KEY, titulo TEXT)"
        )
        connection.commit()
        connection.close()

        repository = StatisticsRepository(old_path)
        snapshot = repository.snapshot()
        repository.close()

        self.assertEqual(snapshot.total_products, 0)
        self.assertEqual(snapshot.total_sends, 0)
        self.assertEqual(snapshot.failed_deliveries, 0)
        self.assertEqual(snapshot.products_by_store, ())
        self.assertEqual(snapshot.products_by_category.total, 0)

    def test_read_only_connection_rejects_writes(self):
        repository = StatisticsRepository(self.database_path)
        with self.assertRaises(sqlite3.OperationalError):
            repository.connection.execute(
                "INSERT INTO alertas(id, ativo) VALUES(99, 1)"
            )
        repository.close()

    def test_snapshot_and_close_do_not_modify_database(self):
        before = self.digest(self.database_path)
        repository = StatisticsRepository(self.database_path)
        repository.snapshot()
        repository.close()
        after = self.digest(self.database_path)
        self.assertEqual(before, after)

    def test_close_is_idempotent(self):
        repository = StatisticsRepository(self.database_path)
        repository.close()
        repository.close()
        self.assertTrue(repository.closed)


if __name__ == "__main__":
    unittest.main()
