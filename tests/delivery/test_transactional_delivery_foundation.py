from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.core.delivery_models import (
    DELIVERY_TRANSITIONS,
    DeliveryStatus,
    DestinationDelivery,
    InvalidDeliveryTransition,
    delivery_idempotency_key,
    validate_delivery_transition,
)
from src.database import Database
from src.database.delivery_repository import DeliveryRepository


class TransactionalDeliveryFoundationTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "promobot.db"
        self.now = datetime(2026, 7, 29, 12, tzinfo=timezone.utc)
        self.repository = DeliveryRepository(
            self.path,
            clock=lambda: self.now,
        )
        self.repository.migrate()

    def tearDown(self):
        self.repository.close()
        self.tempdir.cleanup()

    def delivery(self, destination="5511999999999"):
        return DestinationDelivery.create(
            "publicacao-1",
            "WhatsApp",
            destination,
            alert_id=10,
            original_link="https://example.com/produto",
            signature="loja|produto",
        )

    def test_migracao_cria_tabelas_e_indices(self):
        self.assertTrue({
            "entregas_destino",
            "tentativas_entrega",
        }.issubset(self.repository.table_names()))
        self.assertTrue({
            "idx_entregas_status_proxima",
            "idx_entregas_publicacao",
            "idx_entregas_canal_destino",
            "idx_entregas_enviado_em",
            "idx_tentativas_entrega_numero",
            "idx_tentativas_status",
        }.issubset(self.repository.index_names()))

    def test_migracao_preserva_banco_antigo(self):
        self.repository.close()
        connection = sqlite3.connect(self.path)
        connection.execute("""
            CREATE TABLE produtos(
                id INTEGER PRIMARY KEY,
                titulo TEXT NOT NULL
            )
        """)
        connection.execute("INSERT INTO produtos VALUES(1, 'Preservado')")
        connection.commit()
        connection.close()
        self.repository = DeliveryRepository(self.path)
        self.repository.migrate()
        row = self.repository.conn.execute(
            "SELECT titulo FROM produtos WHERE id=1"
        ).fetchone()
        self.assertEqual(row["titulo"], "Preservado")

    def test_migracao_preserva_schema_e_dados_do_promobot(self):
        self.repository.close()
        database = Database(self.path)
        database.salvar_produto({
            "loja": "Amazon",
            "titulo": "Produto legado",
            "preco": "99,90",
            "link": "https://example.com/legado",
            "imagem": "https://example.com/legado.jpg",
        })
        database.registrar_envio(
            "Amazon",
            "Produto legado",
            "https://example.com/legado",
            "https://example.com/afiliado",
            "promobot",
            "WhatsApp",
            "grupo@g.us",
        )
        database.fechar()
        self.repository = DeliveryRepository(self.path)
        self.repository.migrate()
        product_count = self.repository.conn.execute(
            "SELECT COUNT(*) FROM produtos"
        ).fetchone()[0]
        history_count = self.repository.conn.execute(
            "SELECT COUNT(*) FROM historico_envios"
        ).fetchone()[0]
        self.assertEqual(product_count, 1)
        self.assertEqual(history_count, 1)

    def test_migracao_e_idempotente(self):
        self.repository.migrate()
        self.repository.migrate()
        self.assertIn(
            "entregas_destino",
            self.repository.table_names(),
        )

    def test_chave_idempotente_normaliza_canal_e_destino(self):
        first = delivery_idempotency_key(
            "publicacao-1",
            "WhatsApp",
            "+55 (11) 99999-9999",
        )
        second = delivery_idempotency_key(
            "publicacao-1",
            " whatsapp ",
            "5511999999999",
        )
        different = delivery_idempotency_key(
            "publicacao-1",
            "WhatsApp",
            "5511888888888",
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, different)

    def test_insercao_repetida_retorna_a_mesma_entrega(self):
        first, created = self.repository.create(self.delivery())
        second, created_again = self.repository.create(self.delivery())
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.repository.list()), 1)

    def test_transicoes_validas(self):
        item, _ = self.repository.create(self.delivery())
        attempt = self.repository.start_attempt(item.id)
        sent = self.repository.finish_attempt(
            item.id,
            DeliveryStatus.SENT,
            external_id="evolution-123",
        )
        self.assertEqual(attempt.status, DeliveryStatus.SENDING)
        self.assertEqual(sent.status, DeliveryStatus.SENT)
        self.assertEqual(sent.external_id, "evolution-123")
        self.assertIsNotNone(sent.sent_at)

    def test_todas_as_transicoes_declaradas_sao_validas(self):
        for current, targets in DELIVERY_TRANSITIONS.items():
            for target in targets:
                with self.subTest(current=current, target=target):
                    self.assertEqual(
                        validate_delivery_transition(current, target),
                        target,
                    )

    def test_transicoes_nao_declaradas_sao_invalidas(self):
        for current in DeliveryStatus:
            for target in DeliveryStatus:
                if target in DELIVERY_TRANSITIONS[current]:
                    continue
                with self.subTest(current=current, target=target):
                    with self.assertRaises(InvalidDeliveryTransition):
                        validate_delivery_transition(current, target)

    def test_falha_pode_aguardar_tentativa_sem_iniciar_retry(self):
        item, _ = self.repository.create(self.delivery())
        self.repository.start_attempt(item.id)
        self.repository.finish_attempt(
            item.id,
            DeliveryStatus.FAILED,
            error="Falha temporaria",
            temporary_error=True,
        )
        waiting = self.repository.transition(
            item.id,
            DeliveryStatus.WAITING_RETRY,
            last_error="Falha temporaria",
            temporary_error=True,
        )
        self.assertEqual(waiting.status, DeliveryStatus.WAITING_RETRY)
        self.assertEqual(waiting.attempts, 1)

    def test_transicao_invalida_e_bloqueada(self):
        item, _ = self.repository.create(self.delivery())
        with self.assertRaises(InvalidDeliveryTransition):
            self.repository.transition(item.id, DeliveryStatus.SENT)
        self.assertEqual(
            self.repository.get(item.id).status,
            DeliveryStatus.PENDING,
        )

    def test_reinicio_move_entrega_enviando_para_revisao(self):
        item, _ = self.repository.create(self.delivery())
        self.repository.start_attempt(item.id)
        self.repository.close()
        self.repository = DeliveryRepository(self.path, clock=lambda: self.now)
        self.repository.migrate()
        recovered = self.repository.recover_inflight()
        restored = self.repository.get(item.id)
        attempts = self.repository.attempts_for(item.id)
        self.assertEqual(recovered, 1)
        self.assertEqual(restored.status, DeliveryStatus.REVIEW_REQUIRED)
        self.assertEqual(attempts[0].status, DeliveryStatus.REVIEW_REQUIRED)
        self.assertNotEqual(restored.status, DeliveryStatus.PENDING)

    def test_destinos_sao_isolados(self):
        first, _ = self.repository.create(self.delivery("5511999999999"))
        second, _ = self.repository.create(self.delivery("5511888888888"))
        self.repository.start_attempt(first.id)
        self.repository.finish_attempt(first.id, DeliveryStatus.SENT)
        self.assertEqual(
            self.repository.get(first.id).status,
            DeliveryStatus.SENT,
        )
        self.assertEqual(
            self.repository.get(second.id).status,
            DeliveryStatus.PENDING,
        )

    def test_tentativa_registra_resultado_e_erro(self):
        item, _ = self.repository.create(self.delivery())
        self.repository.start_attempt(
            item.id,
            sanitized_metadata={
                "content_type": "image/jpeg",
                "size_bytes": 1024,
                "destination_masked": "***9999",
                "base64": "conteudo-proibido",
                "token": "segredo-proibido",
            },
        )
        failed = self.repository.finish_attempt(
            item.id,
            DeliveryStatus.FAILED,
            error="HTTP 500 sanitizado",
            temporary_error=True,
        )
        attempts = self.repository.attempts_for(item.id)
        self.assertEqual(failed.attempts, 1)
        self.assertEqual(failed.status, DeliveryStatus.FAILED)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].error, "HTTP 500 sanitizado")
        self.assertTrue(attempts[0].temporary_error)
        self.assertNotIn("base64", attempts[0].sanitized_metadata)
        self.assertNotIn("segredo-proibido", attempts[0].sanitized_metadata)

    def test_historico_envios_permanece_compativel(self):
        self.repository.close()
        connection = sqlite3.connect(self.path)
        connection.execute("""
            CREATE TABLE historico_envios(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                loja TEXT,
                titulo TEXT,
                link_original TEXT,
                link_afiliado TEXT,
                etiqueta TEXT,
                canal TEXT,
                destino TEXT,
                status TEXT,
                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            INSERT INTO historico_envios(
                loja, titulo, canal, destino, status
            ) VALUES('Shopee', 'Produto', 'WhatsApp', 'grupo@g.us', 'enviado')
        """)
        connection.commit()
        connection.close()
        self.repository = DeliveryRepository(self.path)
        self.repository.migrate()
        row = self.repository.conn.execute(
            "SELECT loja, titulo, status FROM historico_envios"
        ).fetchone()
        self.assertEqual(tuple(row), ("Shopee", "Produto", "enviado"))


if __name__ == "__main__":
    unittest.main()
