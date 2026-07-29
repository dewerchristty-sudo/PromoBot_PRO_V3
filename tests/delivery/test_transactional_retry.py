import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import requests

from src.core.delivery_models import DeliveryStatus, DestinationDelivery
from src.core.delivery_retry_service import (
    RetryExecution,
    TransactionalRetryService,
)
from src.core.delivery_service import DeliveryService
from src.core.monitor import MonitorRunner
from src.core.retry_policy import (
    RetryDisposition,
    TransactionalRetryPolicy,
)
from src.database.delivery_repository import DeliveryRepository


class TransactionalRetryTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "retry.db"
        self.now = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        self.repository = DeliveryRepository(
            self.path,
            clock=lambda: self.now,
        )
        self.repository.migrate()
        self.policy = TransactionalRetryPolicy(enabled=True)
        self.service = TransactionalRetryService(
            self.repository,
            self.policy,
        )

    def tearDown(self):
        self.repository.close()
        self.tempdir.cleanup()

    def delivery(
        self,
        suffix="1",
        *,
        status=DeliveryStatus.WAITING_RETRY,
        attempts=1,
        next_attempt_at=None,
        channel="WhatsApp",
    ):
        created, _ = self.repository.create(DestinationDelivery.create(
            f"publication-{suffix}",
            channel,
            f"55119999999{suffix}",
            original_link=f"https://example.com/{suffix}",
            status=status,
            attempts=attempts,
            next_attempt_at=(
                next_attempt_at
                if next_attempt_at is not None
                else self.now - timedelta(seconds=1)
            ),
        ))
        return created

    @staticmethod
    def execution(send=None, history=None):
        return RetryExecution(
            send=send or (lambda: {"id": "external-1"}),
            record_history=history,
        )

    def test_retry_desligado_nao_processa(self):
        self.delivery()
        service = TransactionalRetryService(
            self.repository,
            TransactionalRetryPolicy(enabled=False),
        )
        resolver = Mock()
        self.assertEqual(service.process_due(resolver, self.now), ())
        resolver.assert_not_called()

    def test_entrega_nao_vencida_nao_e_processada(self):
        self.delivery(next_attempt_at=self.now + timedelta(minutes=1))
        resolver = Mock()
        self.assertEqual(self.service.process_due(resolver, self.now), ())
        resolver.assert_not_called()

    def test_entrega_vencida_tem_sucesso_e_numera_tentativa(self):
        delivery = self.delivery(attempts=1)
        history = Mock()
        result = self.service.process_due(
            lambda _delivery: self.execution(history=history),
            self.now,
        )
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].sent)
        self.assertEqual(result[0].attempt_number, 2)
        stored = self.repository.get(delivery.id)
        self.assertEqual(stored.status, DeliveryStatus.SENT)
        self.assertEqual(stored.attempts, 2)
        history.assert_called_once_with()

    def test_backoff_configurado(self):
        expected = {1: 1, 2: 5, 3: 15, 4: 30}
        for attempt, minutes in expected.items():
            with self.subTest(attempt=attempt):
                self.assertEqual(
                    self.policy.delay_after_attempt(attempt),
                    minutes,
                )
                self.assertEqual(
                    self.policy.next_attempt_at(attempt, self.now),
                    self.now + timedelta(minutes=minutes),
                )

    def test_falha_temporaria_persiste_proxima_tentativa(self):
        delivery = self.delivery(attempts=1)
        result = self.service.process_due(
            lambda _delivery: self.execution(
                send=Mock(side_effect=requests.Timeout("timeout"))
            ),
            self.now,
        )
        stored = self.repository.get(delivery.id)
        self.assertEqual(result[0].status, DeliveryStatus.WAITING_RETRY)
        self.assertEqual(stored.status, DeliveryStatus.WAITING_RETRY)
        self.assertTrue(stored.temporary_error)
        self.assertEqual(
            stored.next_attempt_at,
            self.now + timedelta(minutes=5),
        )

    def test_maximo_de_tentativas_vira_falha_definitiva(self):
        delivery = self.delivery(attempts=4)
        self.service.process_due(
            lambda _delivery: self.execution(
                send=Mock(side_effect=requests.Timeout("timeout"))
            ),
            self.now,
        )
        stored = self.repository.get(delivery.id)
        self.assertEqual(stored.attempts, 5)
        self.assertEqual(stored.status, DeliveryStatus.DEFINITIVE_FAILURE)
        self.assertIsNone(stored.next_attempt_at)

    def test_falha_definitiva(self):
        delivery = self.delivery()
        self.service.process_due(
            lambda _delivery: self.execution(
                send=Mock(side_effect=ValueError("destino invalido"))
            ),
            self.now,
        )
        self.assertEqual(
            self.repository.get(delivery.id).status,
            DeliveryStatus.DEFINITIVE_FAILURE,
        )

    def test_erro_desconhecido_e_definitivo(self):
        classification = self.policy.classify(RuntimeError("inesperado"))
        self.assertEqual(
            classification.disposition,
            RetryDisposition.DEFINITIVE,
        )

    def test_resultado_incerto_vai_para_revisao(self):
        for index, message in enumerate((
            "resultado indeterminado",
            "resultado externo indeterminado",
        ), 1):
            with self.subTest(message=message):
                delivery = self.delivery(str(index))
                self.service.process_due(
                    lambda _delivery, message=message: self.execution(
                        send=Mock(side_effect=RuntimeError(message))
                    ),
                    self.now,
                )
                self.assertEqual(
                    self.repository.get(delivery.id).status,
                    DeliveryStatus.REVIEW_REQUIRED,
                )

    def test_status_http_temporarios(self):
        for status in (408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                response = requests.Response()
                response.status_code = status
                error = requests.HTTPError(response=response)
                self.assertEqual(
                    self.policy.classify(error).disposition,
                    RetryDisposition.TEMPORARY,
                )

    def test_timeout_e_conexao_recusada_sao_temporarios(self):
        errors = (
            requests.Timeout(),
            requests.ConnectionError("connection refused"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.assertEqual(
                    self.policy.classify(error).disposition,
                    RetryDisposition.TEMPORARY,
                )

    def test_erros_permanentes(self):
        for message in (
            "destino invalido",
            "autenticacao invalida",
            "credencial ausente",
            "payload invalido",
            "formato de destino nao suportado",
            "validacao local permanente",
        ):
            with self.subTest(message=message):
                self.assertEqual(
                    self.policy.classify(ValueError(message)).disposition,
                    RetryDisposition.DEFINITIVE,
                )

    def test_sucesso_apos_falha_grava_historico_uma_vez(self):
        delivery = self.delivery()
        history = Mock()
        send = Mock(return_value=True)
        first = self.service.process_due(
            lambda _delivery: self.execution(send, history),
            self.now,
        )
        second = self.service.process_due(
            lambda _delivery: self.execution(send, history),
            self.now,
        )
        self.assertTrue(first[0].sent)
        self.assertEqual(second, ())
        send.assert_called_once_with()
        history.assert_called_once_with()
        self.assertEqual(len(self.repository.attempts_for(delivery.id)), 1)

    def test_historico_existente_nao_e_duplicado(self):
        delivery = self.delivery()
        self.repository.conn.execute("""
            CREATE TABLE historico_envios(
                id INTEGER PRIMARY KEY,
                link_original TEXT,
                canal TEXT,
                destino TEXT,
                status TEXT
            )
        """)
        self.repository.conn.execute("""
            INSERT INTO historico_envios(
                link_original, canal, destino, status
            ) VALUES(?,?,?,'enviado')
        """, (
            delivery.original_link,
            delivery.channel,
            delivery.destination,
        ))
        self.repository.conn.commit()
        history = Mock()
        self.service.process_due(
            lambda _delivery: self.execution(history=history),
            self.now,
        )
        history.assert_not_called()

    def test_metadados_da_tentativa_sao_sanitizados(self):
        delivery = self.delivery()
        self.service.process_due(
            lambda _delivery: RetryExecution(
                send=lambda: True,
                sanitized_metadata={
                    "content_type": "image/bytes",
                    "destination_masked": "***9999",
                    "token": "segredo",
                    "payload": "base64",
                },
            ),
            self.now,
        )
        metadata = self.repository.attempts_for(
            delivery.id
        )[0].sanitized_metadata
        self.assertIn("content_type", metadata)
        self.assertNotIn("segredo", metadata)
        self.assertNotIn("base64", metadata)

    def test_batch_size_limita_processamento(self):
        for index in range(4):
            self.delivery(str(index + 1))
        service = TransactionalRetryService(
            self.repository,
            TransactionalRetryPolicy(enabled=True, batch_size=2),
        )
        results = service.process_due(
            lambda _delivery: self.execution(),
            self.now,
        )
        self.assertEqual(len(results), 2)

    def test_processamento_continua_apos_falha(self):
        first = self.delivery("1")
        second = self.delivery("2")
        sends = []

        def resolver(delivery):
            def send():
                sends.append(delivery.id)
                if delivery.id == first.id:
                    raise ValueError("destino invalido")
                return True
            return self.execution(send)

        results = self.service.process_due(resolver, self.now)
        self.assertEqual(len(results), 2)
        self.assertEqual(sends, [first.id, second.id])
        self.assertEqual(
            self.repository.get(second.id).status,
            DeliveryStatus.SENT,
        )

    def test_tres_destinos_ficam_isolados(self):
        service = DeliveryService(self.repository, self.policy)
        calls = {"A": 0, "B": 0, "C": 0}

        def send(name):
            calls[name] += 1
            if name == "B":
                raise requests.Timeout("timeout")
            if name == "C":
                raise ValueError("destino invalido")
            return True

        stored = {}
        for name, destination in (
            ("A", "5511999999901"),
            ("B", "5511999999902"),
            ("C", "5511999999903"),
        ):
            result = service.deliver(
                DestinationDelivery.create(
                    f"isolation-{name}",
                    "WhatsApp",
                    destination,
                ),
                lambda name=name: send(name),
            )
            stored[name] = self.repository.get(result.delivery_id)

        self.assertEqual(stored["A"].status, DeliveryStatus.SENT)
        self.assertEqual(
            stored["B"].status,
            DeliveryStatus.WAITING_RETRY,
        )
        self.assertEqual(
            stored["C"].status,
            DeliveryStatus.DEFINITIVE_FAILURE,
        )
        self.assertEqual(calls, {"A": 1, "B": 1, "C": 1})

    def test_estados_nao_elegiveis_nao_sao_processados(self):
        for index, status in enumerate((
            DeliveryStatus.SENT,
            DeliveryStatus.REVIEW_REQUIRED,
            DeliveryStatus.DEFINITIVE_FAILURE,
        ), 1):
            self.delivery(str(index), status=status)
        resolver = Mock()
        self.assertEqual(self.service.process_due(resolver, self.now), ())
        resolver.assert_not_called()

    def test_reserva_sqlite_impede_dois_workers(self):
        delivery = self.delivery()
        other = DeliveryRepository(self.path, clock=lambda: self.now)
        calls = 0
        calls_lock = threading.Lock()
        barrier = threading.Barrier(2)
        results = []

        def worker(repository):
            nonlocal calls
            service = TransactionalRetryService(repository, self.policy)
            barrier.wait()

            def send():
                nonlocal calls
                with calls_lock:
                    calls += 1
                return True

            results.append(service.process_due(
                lambda _delivery: self.execution(send),
                self.now,
            ))

        threads = [
            threading.Thread(target=worker, args=(repository,))
            for repository in (self.repository, other)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        other.close()
        self.assertEqual(calls, 1)
        self.assertEqual(
            len(self.repository.attempts_for(delivery.id)),
            1,
        )

    def test_transacao_nao_fica_aberta_durante_transporte(self):
        self.delivery()
        second = sqlite3.connect(self.path, timeout=0.2)
        second.execute(
            "CREATE TABLE IF NOT EXISTS prova_rede(id INTEGER PRIMARY KEY)"
        )
        second.commit()

        def send():
            second.execute("INSERT INTO prova_rede DEFAULT VALUES")
            second.commit()
            return True

        try:
            self.service.process_due(
                lambda _delivery: self.execution(send),
                self.now,
            )
            count = second.execute(
                "SELECT COUNT(*) FROM prova_rede"
            ).fetchone()[0]
        finally:
            second.close()
        self.assertEqual(count, 1)

    def test_reinicio_enviando_vai_para_revisao_controlada(self):
        delivery = self.delivery(
            status=DeliveryStatus.WAITING_RETRY,
            attempts=0,
        )
        self.repository.reserve_retry(delivery.id, self.now, 5)
        self.assertEqual(self.repository.recover_inflight(), 1)
        self.assertEqual(
            self.repository.get(delivery.id).status,
            DeliveryStatus.REVIEW_REQUIRED,
        )
        resolver = Mock()
        self.assertEqual(self.service.process_due(resolver, self.now), ())

    def test_retry_manual_seguro(self):
        failed = self.delivery("1", status=DeliveryStatus.FAILED)
        definitive = self.delivery(
            "2",
            status=DeliveryStatus.DEFINITIVE_FAILURE,
        )
        sent = self.delivery("3", status=DeliveryStatus.SENT)
        review = self.delivery(
            "4",
            status=DeliveryStatus.REVIEW_REQUIRED,
        )
        self.assertEqual(
            self.service.prepare_manual_retry(failed.id, now=self.now).status,
            DeliveryStatus.WAITING_RETRY,
        )
        with self.assertRaises(ValueError):
            self.service.prepare_manual_retry(definitive.id, now=self.now)
        self.assertEqual(
            self.service.prepare_manual_retry(
                definitive.id,
                confirm_definitive=True,
                now=self.now,
            ).status,
            DeliveryStatus.WAITING_RETRY,
        )
        with self.assertRaises(ValueError):
            self.service.prepare_manual_retry(sent.id, now=self.now)
        with self.assertRaises(ValueError):
            self.service.prepare_manual_retry(review.id, now=self.now)

    def test_erros_persistidos_sao_sanitizados_e_limitados(self):
        destination = "5511999999999"
        error = RuntimeError(
            "token=abc123 password=senha authorization=Bearer "
            "https://usuario:senha@example.com endpoint "
            "headers={'Authorization':'segredo'} "
            "payload={'media':'" + ("A" * 1500) + "'} "
            + destination
        )
        safe = DeliveryService.safe_error(error, destination)
        self.assertNotIn("abc123", safe)
        self.assertNotIn("usuario:senha", safe)
        self.assertNotIn("segredo", safe)
        self.assertNotIn("A" * 120, safe)
        self.assertNotIn(destination, safe)
        self.assertIn("REMOVIDO", safe)
        self.assertLessEqual(len(safe), 1000)

    def test_configuracao_invalida_usa_defaults(self):
        with patch.dict(os.environ, {
            "ENABLE_TRANSACTIONAL_RETRY": "true",
            "TRANSACTIONAL_RETRY_MAX_ATTEMPTS": "0",
            "TRANSACTIONAL_RETRY_DELAYS_MINUTES": "1,0,-2",
            "TRANSACTIONAL_RETRY_BATCH_SIZE": "-1",
        }):
            policy = TransactionalRetryPolicy.from_environment()
        self.assertTrue(policy.enabled)
        self.assertEqual(policy.max_attempts, 5)
        self.assertEqual(policy.delays_minutes, (1, 5, 15, 30))
        self.assertEqual(policy.batch_size, 10)

    def test_tentativa_inicial_ate_quinta_sem_sexta_chamada(self):
        policy = TransactionalRetryPolicy(
            enabled=True,
            max_attempts=5,
            # O valor excedente prova que ele nao e usado com maximo 5.
            delays_minutes=(1, 5, 15, 30, 60),
        )
        initial_service = DeliveryService(self.repository, policy)
        calls = 0

        def fail():
            nonlocal calls
            calls += 1
            raise requests.Timeout("timeout")

        first = initial_service.deliver(
            DestinationDelivery.create(
                "five-attempts",
                "WhatsApp",
                "5511999999999",
            ),
            fail,
        )
        delivery_id = first.delivery_id
        self.assertEqual(
            self.repository.attempts_for(delivery_id)[0].attempt_number,
            1,
        )
        retry_service = TransactionalRetryService(
            self.repository,
            policy,
        )
        for expected_attempt in range(2, 6):
            due = self.repository.get(delivery_id).next_attempt_at
            retry_service.process_due(
                lambda _delivery: self.execution(fail),
                due,
            )
            attempts = self.repository.attempts_for(delivery_id)
            self.assertEqual(attempts[-1].attempt_number, expected_attempt)
            self.assertEqual(
                self.repository.get(delivery_id).attempts,
                len(attempts),
            )

        stored = self.repository.get(delivery_id)
        self.assertEqual(calls, 5)
        self.assertEqual(stored.attempts, 5)
        self.assertEqual(len(self.repository.attempts_for(delivery_id)), 5)
        self.assertEqual(stored.status, DeliveryStatus.DEFINITIVE_FAILURE)
        self.assertIsNone(stored.next_attempt_at)
        self.assertEqual(
            retry_service.process_due(
                lambda _delivery: self.execution(fail),
                self.now + timedelta(days=1),
            ),
            (),
        )
        self.assertEqual(calls, 5)

    def test_banco_antigo_recebe_migracao_sem_perder_dados(self):
        old_path = Path(self.tempdir.name) / "old.db"
        con = sqlite3.connect(old_path)
        con.execute("CREATE TABLE legado(id INTEGER PRIMARY KEY, valor TEXT)")
        con.execute("INSERT INTO legado(valor) VALUES('preservado')")
        con.commit()
        con.close()
        repository = DeliveryRepository(old_path)
        try:
            repository.migrate()
            value = repository.conn.execute(
                "SELECT valor FROM legado"
            ).fetchone()[0]
            self.assertEqual(value, "preservado")
        finally:
            repository.close()

    def test_delivery_service_inicial_agenda_retry_quando_flag_ativa(self):
        service = DeliveryService(self.repository, self.policy)
        delivery = DestinationDelivery.create(
            "initial-publication",
            "WhatsApp",
            "5511999999999",
        )
        result = service.deliver(
            delivery,
            Mock(side_effect=requests.Timeout("timeout")),
        )
        stored = self.repository.get(result.delivery_id)
        self.assertEqual(stored.status, DeliveryStatus.WAITING_RETRY)
        self.assertEqual(stored.attempts, 1)
        self.assertEqual(
            stored.next_attempt_at,
            self.now + timedelta(minutes=1),
        )

    def test_falha_no_historico_nao_repete_transporte(self):
        delivery = self.delivery()
        send = Mock(return_value=True)
        result = self.service.process_due(
            lambda _delivery: self.execution(
                send,
                Mock(side_effect=RuntimeError("history")),
            ),
            self.now,
        )
        self.assertTrue(result[0].sent)
        self.assertTrue(result[0].history_error)
        self.assertEqual(
            self.repository.get(delivery.id).status,
            DeliveryStatus.SENT,
        )
        self.service.process_due(
            lambda _delivery: self.execution(send),
            self.now,
        )
        send.assert_called_once_with()

    def test_monitor_exige_as_duas_flags(self):
        database = Mock(db=self.path)
        runner = MonitorRunner(database)
        for delivery_flag, retry_flag, expected in (
            ("false", "false", False),
            ("true", "false", False),
            ("false", "true", False),
            ("true", "true", True),
        ):
            with self.subTest(
                delivery=delivery_flag,
                retry=retry_flag,
            ), patch.dict(os.environ, {
                "ENABLE_TRANSACTIONAL_DELIVERY": delivery_flag,
                "ENABLE_TRANSACTIONAL_RETRY": retry_flag,
            }):
                self.assertEqual(
                    runner.transactional_retry_enabled(),
                    expected,
                )

    def test_monitor_flag_desligada_nao_abre_repositorio(self):
        runner = MonitorRunner(Mock(db=self.path))
        with patch.dict(os.environ, {
            "ENABLE_TRANSACTIONAL_DELIVERY": "false",
            "ENABLE_TRANSACTIONAL_RETRY": "true",
        }), patch(
            "src.core.monitor.DeliveryRepository"
        ) as repository:
            self.assertEqual(runner.process_transactional_retries(), ())
        repository.assert_not_called()

    def test_monitor_com_duas_flags_processa_lote_e_fecha_repositorio(self):
        database = Mock(db=self.path)
        runner = MonitorRunner(database)
        repository = Mock()
        service = Mock()
        service.process_due.return_value = ("processado",)
        with patch.dict(os.environ, {
            "ENABLE_TRANSACTIONAL_DELIVERY": "true",
            "ENABLE_TRANSACTIONAL_RETRY": "true",
        }), patch(
            "src.core.monitor.DeliveryRepository",
            return_value=repository,
        ), patch(
            "src.core.monitor.TransactionalRetryService",
            return_value=service,
        ):
            result = runner.process_transactional_retries()
        self.assertEqual(result, ("processado",))
        repository.migrate.assert_called_once_with()
        service.process_due.assert_called_once_with(runner.retry_execution)
        repository.close.assert_called_once_with()

    def test_monitor_simula_whatsapp_e_telegram(self):
        database = Mock(db=self.path)
        database.buscar_produto_por_link.return_value = {
            "titulo": "Produto",
            "imagem": "https://example.com/image.jpg",
        }
        runner = MonitorRunner(database)
        runner.notifier.format_alert = Mock(return_value="mensagem")
        runner.notifier.verified_whatsapp_image = Mock(return_value=b"jpeg")
        runner.notifier.evolution_configured = Mock(return_value=True)
        runner.notifier.send_whatsapp_message = Mock(return_value=True)
        runner.notifier.send_telegram_photo = Mock(return_value=True)
        runner.notifier.record_single_delivery = Mock()
        whatsapp = self.delivery("1", channel="WhatsApp")
        telegram = self.delivery("2", channel="Telegram")
        os.environ["TELEGRAM_BOT_TOKEN"] = "fake"
        try:
            runner.retry_execution(whatsapp).send()
            runner.retry_execution(telegram).send()
        finally:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        runner.notifier.send_whatsapp_message.assert_called_once()
        runner.notifier.send_telegram_photo.assert_called_once()

    def test_nao_ha_sleep_no_fluxo_de_retry(self):
        source = (
            Path("src/core/retry_policy.py").read_text(encoding="utf-8")
            + Path("src/core/delivery_retry_service.py").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("sleep(", source)
