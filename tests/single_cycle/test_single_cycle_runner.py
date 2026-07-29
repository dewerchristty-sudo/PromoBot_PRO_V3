import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import ANY, Mock, patch

from scripts.run_single_offer_cycle import main, parser
from src.core.single_cycle_runner import (
    SingleCycleConfig,
    SingleCycleMode,
    SingleCycleResult,
    SingleCycleRunner,
    result_mask,
)
from src.core.store_manager import StoreManager
from src.database import Database


class SingleCycleRunnerTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tempdir.name) / "promobot.db"
        self.database = Database(self.database_path)
        self.destination = "5511999999999"
        self.products = {
            "Mercado Livre": [self.product(
                "Mercado Livre", "Produto ML", 80, 160, "ml"
            )],
            "Amazon": [self.product(
                "Amazon", "Produto Amazon", 70, 100, "amazon"
            )],
            "Shopee": [self.product(
                "Shopee", "Produto Shopee", 60, 100, "shopee"
            )],
        }

    def tearDown(self):
        self.database.fechar()
        self.tempdir.cleanup()

    @staticmethod
    def product(store, title, current, previous, slug):
        return {
            "loja": store,
            "titulo": title,
            "preco": f"R$ {current:.2f}",
            "preco_valor": float(current),
            "preco_antigo": float(previous),
            "link": f"https://example.invalid/{slug}",
            "link_afiliado_salvo": f"https://affiliate.invalid/{slug}",
            "imagem": f"https://example.invalid/{slug}.jpg",
            "estoque": 1,
            "disponivel": True,
        }

    def config(self, **fields):
        values = {
            "term": "produto controlado",
            "stores": ["mercado_livre", "amazon", "shopee"],
            "destination": self.destination,
            "database_path": self.database_path,
        }
        values.update(fields)
        return SingleCycleConfig.create(**values)

    def collector(self, term, store):
        self.assertEqual(term, "produto controlado")
        return list(self.products.get(store, ()))

    def runner(self, *, config=None, collector=None, transport=None, database=None):
        return SingleCycleRunner(
            config or self.config(),
            collector=collector or self.collector,
            transport=transport,
            database=database,
        )

    def test_01_default_mode_is_dry_run(self):
        self.assertEqual(self.config().mode, SingleCycleMode.DRY_RUN)
        args = parser().parse_args([
            "--term", "produto", "--stores", "amazon",
            "--destination", self.destination,
        ])
        self.assertFalse(args.real_send)
        self.assertFalse(args.visible_browser)
        self.assertFalse(args.shopee_persistent_profile)

    @patch("scripts.run_single_offer_cycle.SingleCycleRunner")
    @patch("scripts.run_single_offer_cycle.BrowserManager")
    def test_cli_uses_headless_browser_by_default(
        self,
        browser_manager_class,
        runner_class,
    ):
        runner_class.return_value.run.return_value.as_dict.return_value = {}
        main([
            "--term", "produto", "--stores", "amazon",
            "--destination", self.destination,
        ])
        browser_manager_class.assert_called_once_with(headless=True)
        self.assertIs(
            runner_class.call_args.kwargs["browser_manager"],
            browser_manager_class.return_value,
        )

    @patch("scripts.run_single_offer_cycle.SingleCycleRunner")
    @patch("scripts.run_single_offer_cycle.BrowserManager")
    def test_cli_visible_browser_disables_headless(
        self,
        browser_manager_class,
        runner_class,
    ):
        runner_class.return_value.run.return_value.as_dict.return_value = {}
        main([
            "--term", "produto", "--stores", "amazon",
            "--destination", self.destination, "--visible-browser",
        ])
        browser_manager_class.assert_called_once_with(headless=False)
        self.assertIs(
            runner_class.call_args.kwargs["browser_manager"],
            browser_manager_class.return_value,
        )

    @patch(
        "scripts.run_single_offer_cycle.prompt_amazon_tag",
        return_value="fixture-unit-20",
    )
    @patch(
        "scripts.run_single_offer_cycle.SingleCycleRunner",
        wraps=SingleCycleRunner,
    )
    @patch("scripts.run_single_offer_cycle.BrowserManager")
    @patch("src.core.single_cycle_runner.StoreManager")
    def test_cli_visible_browser_with_amazon_tag_keeps_visible_and_closes(
        self,
        manager_class,
        browser_manager_class,
        runner_class,
        prompt,
    ):
        manager_class.return_value.stores = [Mock()]
        manager_class.return_value.search_all.return_value = []
        main([
            "--term", "produto", "--stores", "amazon",
            "--destination", self.destination,
            "--visible-browser", "--prompt-amazon-tag",
        ])
        prompt.assert_called_once_with()
        browser_manager_class.assert_called_once_with(headless=False)
        self.assertEqual(
            runner_class.call_args.kwargs["amazon_associate_tag"],
            "fixture-unit-20",
        )
        self.assertIs(
            runner_class.call_args.kwargs["browser_manager"],
            browser_manager_class.return_value,
        )
        browser_manager_class.return_value.close.assert_called_once_with()

    @patch("scripts.run_single_offer_cycle.SingleCycleRunner")
    @patch("scripts.run_single_offer_cycle.BrowserManager")
    def test_cli_shopee_persistent_profile_is_explicit_and_exclusive(
        self,
        browser_manager_class,
        runner_class,
    ):
        runner_class.return_value.run.return_value.as_dict.return_value = {}
        main([
            "--term", "produto", "--stores", "shopee",
            "--destination", self.destination,
            "--visible-browser", "--shopee-persistent-profile",
        ])
        call = browser_manager_class.call_args
        self.assertFalse(call.kwargs["headless"])
        self.assertEqual(
            call.kwargs["user_data_dir"].as_posix().rsplit("/", 3)[-3:],
            ["data", "browser_profiles", "shopee_playwright"],
        )

    def test_cli_shopee_persistent_profile_requires_visible_browser(self):
        with self.assertRaises(SystemExit):
            main([
                "--term", "produto", "--stores", "shopee",
                "--destination", self.destination,
                "--shopee-persistent-profile",
            ])

    def test_cli_shopee_persistent_profile_rejects_other_stores(self):
        with self.assertRaises(SystemExit):
            main([
                "--term", "produto", "--stores", "shopee", "amazon",
                "--destination", self.destination,
                "--visible-browser", "--shopee-persistent-profile",
            ])

    def test_02_destination_is_required(self):
        with self.assertRaisesRegex(ValueError, "obrigatorio"):
            self.config(destination="")

    def test_03_invalid_destination_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalido"):
            self.config(destination="destino-invalido")

    def test_04_multiple_destinations_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "exatamente um"):
            self.config(destination=f"{self.destination},5511888888888")

    def test_05_only_allowed_stores_are_normalized(self):
        config = self.config(stores=["mercado_livre", "amazon", "shopee"])
        self.assertEqual(config.stores, (
            "Mercado Livre", "Amazon", "Shopee",
        ))

    def test_06_invalid_store_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "nao autorizada"):
            self.config(stores=["kabum"])

    def test_07_store_error_does_not_block_other_stores(self):
        def collector(_term, store):
            if store == "Amazon":
                raise RuntimeError("falha simulada")
            return self.products[store]
        result = self.runner(collector=collector).run()
        self.assertIn("Amazon", result.stores_with_error)
        self.assertTrue(result.selected_offer)

    def test_08_only_current_execution_products_are_considered(self):
        foreign = self.product("Amazon", "Antigo", 1, 100, "old")
        foreign["_single_cycle_execution_id"] = "outra-execucao"
        runner = self.runner()
        eligible = runner.eligible_products(
            [foreign], runner.notifier or Mock(), self.database, "atual"
        )
        self.assertEqual(eligible, [])

    def test_09_old_database_product_is_ignored(self):
        old = self.product("Amazon", "Produto antigo", 1, 100, "old-db")
        self.database.salvar_produto(old)
        result = self.runner(database=self.database).run()
        self.assertNotEqual(result.title, old["titulo"])
        self.assertEqual(result.collected_count, 3)

    def test_10_no_eligible_offer_is_normal_result(self):
        invalid = self.product("Amazon", "Sem imagem", 10, 100, "invalid")
        invalid["imagem"] = ""
        result = self.runner(
            collector=lambda _term, _store: [invalid]
        ).run()
        self.assertEqual(result.final_result, "no_eligible_offer")
        self.assertEqual(result.transport_calls, 0)

    def test_11_selects_at_most_one_offer(self):
        transport = Mock(return_value=True)
        result = self.runner(transport=transport).run()
        self.assertTrue(result.selected_offer)
        self.assertEqual(result.transport_calls, 1)
        transport.assert_called_once()

    def test_12_uses_current_priority_order(self):
        result = self.runner().run()
        self.assertEqual(result.title, "Produto ML")
        self.assertEqual(result.discount_percent, 50)

    def test_13_dry_run_uses_fake_transport(self):
        transport = Mock(return_value={"id": "fake"})
        result = self.runner(transport=transport).run()
        self.assertEqual(result.final_result, "dry_run_completed")
        transport.assert_called_once()

    def test_14_dry_run_never_uses_notifier_external_transport(self):
        result = self.runner().run()
        self.assertEqual(result.mode, "dry-run")
        self.assertEqual(result.transport_calls, 1)

    def test_15_real_mode_allows_only_one_fake_transport_call(self):
        transport = Mock(return_value={"id": "fake-real"})
        config = self.config(real_send=True)
        result = self.runner(
            config=config, transport=transport, database=self.database
        ).run()
        self.assertEqual(result.transport_calls, 1)
        transport.assert_called_once()

    def test_16_transport_failure_has_no_second_attempt(self):
        transport = Mock(side_effect=RuntimeError("falha definitiva"))
        result = self.runner(
            config=self.config(real_send=True),
            transport=transport,
            database=self.database,
        ).run()
        self.assertEqual(result.transport_calls, 1)
        self.assertEqual(result.final_result, "delivery_failed")
        transport.assert_called_once()

    def test_17_uncertain_result_requires_review_without_resend(self):
        transport = Mock(
            side_effect=RuntimeError("resultado externo indeterminado")
        )
        result = self.runner(
            config=self.config(real_send=True),
            transport=transport,
            database=self.database,
        ).run()
        self.assertEqual(result.transport_calls, 1)
        self.assertEqual(result.delivery_status, "revisao_necessaria")
        self.assertEqual(result.attempt_status, "revisao_necessaria")
        transport.assert_called_once()

    def test_18_retry_is_never_scheduled(self):
        transport = Mock(side_effect=TimeoutError("timeout"))
        result = self.runner(
            config=self.config(real_send=True),
            transport=transport,
            database=self.database,
        ).run()
        self.assertNotEqual(
            result.delivery_status, "aguardando_nova_tentativa"
        )
        transport.assert_called_once()

    def test_19_global_queue_is_not_processed(self):
        self.database.listar_fila_notificacoes = Mock(
            side_effect=AssertionError("fila consultada")
        )
        self.runner(database=self.database).run()
        self.database.listar_fila_notificacoes.assert_not_called()

    def test_20_global_pending_alerts_are_not_processed(self):
        self.database.alertas_pendentes = Mock(
            side_effect=AssertionError("pendencias consultadas")
        )
        self.runner(database=self.database).run()
        self.database.alertas_pendentes.assert_not_called()

    def test_21_monitor_is_not_started(self):
        with patch.dict("sys.modules", {"src.core.monitor": None}):
            result = self.runner().run()
        self.assertEqual(result.final_result, "dry_run_completed")

    def test_22_supervisor_is_not_started(self):
        database = self.database
        database.registrar_evento_sistema = Mock()
        self.runner(database=database).run()
        database.registrar_evento_sistema.assert_not_called()

    def test_23_shopee_detector_is_not_started(self):
        collector = Mock(side_effect=self.collector)
        self.runner(collector=collector).run()
        self.assertEqual(collector.call_count, 3)

    def test_24_intelligent_scheduler_is_not_started(self):
        with patch.dict(os.environ, {
            "OFFER_INTELLIGENT_SCHEDULER_ENABLED": "true",
            "OFFER_CANARY_PERCENT": "100",
        }):
            result = self.runner().run()
        self.assertEqual(result.final_result, "dry_run_completed")

    def test_25_environment_groups_are_ignored(self):
        transport = Mock(return_value=True)
        with patch.dict(os.environ, {
            "WHATSAPP_GROUPS": "120363000000000000@g.us",
            "WHATSAPP_GROUP_MAMAE_BEBE": "120363111111111111@g.us",
        }):
            self.runner(transport=transport).run()
        self.assertEqual(transport.call_args.args[2], self.destination)

    def test_26_environment_destination_is_ignored(self):
        transport = Mock(return_value=True)
        with patch.dict(os.environ, {
            "WHATSAPP_PHONES": "5511888888888",
        }):
            self.runner(transport=transport).run()
        self.assertEqual(transport.call_args.args[2], self.destination)

    def test_27_result_and_logs_mask_destination(self):
        result = self.runner().run()
        self.assertEqual(result.masked_destination, "5511*****9999")
        self.assertNotIn(self.destination, str(result.as_dict()))

    def test_28_dry_run_uses_temporary_database(self):
        before = self.database.conn.execute(
            "SELECT COUNT(*) FROM historico_envios"
        ).fetchone()[0]
        self.runner().run()
        after = self.database.conn.execute(
            "SELECT COUNT(*) FROM historico_envios"
        ).fetchone()[0]
        self.assertEqual(before, after)

    def test_29_real_delivery_is_idempotent(self):
        transport = Mock(return_value=True)
        config = self.config(real_send=True)
        first = self.runner(
            config=config, transport=transport, database=self.database
        ).run()
        second = self.runner(
            config=config, transport=transport, database=self.database
        ).run()
        self.assertEqual(first.final_result, "sent")
        self.assertEqual(second.final_result, "already_processed")
        transport.assert_called_once()

    def test_30_returns_structured_result(self):
        result = self.runner().run()
        self.assertIsInstance(result, SingleCycleResult)
        required = {
            "execution_id", "term", "stores_consulted", "stores_with_error",
            "collected_count", "eligible_count", "selected_offer", "store",
            "title", "current_price", "previous_price", "discount_percent",
            "summarized_link", "masked_destination", "mode",
            "transport_calls", "delivery_status", "attempt_status",
            "final_result", "shadow_pipeline_enabled",
            "shadow_database_touched", "temporary_database_used",
            "affiliate_block_reasons", "duration_seconds",
        }
        self.assertEqual(set(result.as_dict()), required)

    def test_dry_run_disables_shadow_pipeline_without_touching_environment(self):
        original = os.environ.get("OFFER_SHADOW_PIPELINE_ENABLED")
        with patch.dict(
            os.environ,
            {"OFFER_SHADOW_PIPELINE_ENABLED": "True"},
            clear=False,
        ):
            result = self.runner().run()
            self.assertEqual(
                os.environ["OFFER_SHADOW_PIPELINE_ENABLED"],
                "True",
            )
        self.assertEqual(
            os.environ.get("OFFER_SHADOW_PIPELINE_ENABLED"),
            original,
        )
        self.assertFalse(result.shadow_pipeline_enabled)
        self.assertFalse(result.shadow_database_touched)
        self.assertTrue(result.temporary_database_used)

    def test_dry_run_does_not_create_or_touch_shadow_database(self):
        shadow = Path(self.tempdir.name) / "offer_shadow.db"
        shadow.write_bytes(b"sentinel")
        before = shadow.read_bytes()
        with patch.dict(
            os.environ,
            {
                "OFFER_SHADOW_PIPELINE_ENABLED": "True",
                "OFFER_SHADOW_DB_PATH": str(shadow),
            },
            clear=False,
        ):
            self.runner().run()
        self.assertEqual(shadow.read_bytes(), before)
        self.assertFalse(Path(f"{shadow}-wal").exists())
        self.assertFalse(Path(f"{shadow}-shm").exists())

    def test_collection_exception_preserves_shadow_configuration(self):
        with patch.dict(
            os.environ,
            {"OFFER_SHADOW_PIPELINE_ENABLED": "True"},
            clear=False,
        ):
            result = self.runner(
                collector=Mock(side_effect=RuntimeError("falha simulada"))
            ).run()
            self.assertEqual(
                os.environ["OFFER_SHADOW_PIPELINE_ENABLED"],
                "True",
            )
        self.assertEqual(result.final_result, "no_eligible_offer")
        self.assertFalse(result.shadow_pipeline_enabled)

    def test_real_mode_keeps_shadow_pipeline_configuration(self):
        with patch.dict(
            os.environ,
            {"OFFER_SHADOW_PIPELINE_ENABLED": "True"},
            clear=False,
        ):
            result = self.runner(
                config=self.config(real_send=True),
                transport=Mock(return_value=True),
                database=self.database,
            ).run()
        self.assertTrue(result.shadow_pipeline_enabled)
        self.assertFalse(result.temporary_database_used)

    @patch("src.core.single_cycle_runner.StoreManager")
    def test_dry_run_injects_shadow_pipeline_disabled(self, manager_class):
        manager_class.return_value.search_all.return_value = []
        self.runner().collect_store("produto controlado", "Amazon")
        manager_class.assert_called_once_with(
            progress_callback=ANY,
            enabled_stores=["Amazon"],
            offer_shadow_enabled=False,
        )

    @patch("src.core.single_cycle_runner.StoreManager")
    def test_real_mode_preserves_store_manager_shadow_behavior(
        self,
        manager_class,
    ):
        manager_class.return_value.search_all.return_value = []
        runner = self.runner(config=self.config(real_send=True))
        runner.collect_store("produto controlado", "Amazon")
        manager_class.assert_called_once_with(
            progress_callback=ANY,
            enabled_stores=["Amazon"],
            offer_shadow_enabled=None,
        )

    @patch("src.core.single_cycle_runner.StoreManager")
    def test_shared_browser_is_provided_and_closed(self, manager_class):
        browser_manager = Mock()
        store = Mock()
        manager_class.return_value.stores = [store]
        manager_class.return_value.search_all.return_value = []
        runner = SingleCycleRunner(
            self.config(),
            browser_manager=browser_manager,
        )
        runner.run()
        self.assertIs(store.browser_manager, browser_manager)
        browser_manager.close.assert_called_once_with()

    def test_shared_browser_is_closed_when_cycle_raises(self):
        browser_manager = Mock()
        notifier = Mock()
        notifier.float_env.side_effect = RuntimeError("falha simulada")
        with self.assertRaisesRegex(RuntimeError, "falha simulada"):
            SingleCycleRunner(
                self.config(),
                collector=self.collector,
                database=self.database,
                notifier=notifier,
                browser_manager=browser_manager,
            ).run()
        browser_manager.close.assert_called_once_with()

    def test_shared_browser_is_closed_when_database_open_raises(self):
        browser_manager = Mock()
        runner = SingleCycleRunner(
            self.config(),
            browser_manager=browser_manager,
        )
        runner.open_database = Mock(
            side_effect=RuntimeError("falha ao abrir banco")
        )
        with self.assertRaisesRegex(RuntimeError, "falha ao abrir banco"):
            runner.run()
        browser_manager.close.assert_called_once_with()

    def test_store_manager_none_preserves_environment_shadow_flag(self):
        pipeline = Mock()
        pipeline.process_batch.return_value.metrics = type(
            "Metrics",
            (),
            {
                "received_count": 1,
                "queued_count": 1,
                "selected_shadow_count": 0,
            },
        )()
        with patch.dict(
            os.environ,
            {"OFFER_SHADOW_PIPELINE_ENABLED": "True"},
            clear=False,
        ):
            manager = StoreManager(
                enabled_stores=[],
                offer_pipeline=pipeline,
                offer_shadow_enabled=None,
            )
            result = manager.observe_offer_shadow([{"titulo": "Produto"}])
        pipeline.process_batch.assert_called_once()
        self.assertIs(result, pipeline.process_batch.return_value)

    def test_31_runner_ends_after_one_cycle(self):
        collector = Mock(side_effect=self.collector)
        self.runner(collector=collector).run()
        self.assertEqual(collector.call_count, 3)

    def test_32_mercado_livre_compatibility(self):
        result = self.runner(
            config=self.config(stores=["mercado_livre"])
        ).run()
        self.assertEqual(result.store, "Mercado Livre")

    def test_33_amazon_compatibility(self):
        result = self.runner(
            config=self.config(stores=["amazon"])
        ).run()
        self.assertEqual(result.store, "Amazon")

    def test_34_shopee_compatibility(self):
        result = self.runner(
            config=self.config(stores=["shopee"])
        ).run()
        self.assertEqual(result.store, "Shopee")

    def test_35_normal_flow_modules_are_not_mutated(self):
        result = self.runner().run()
        self.assertEqual(result.final_result, "dry_run_completed")
        self.assertEqual(result.stores_consulted, (
            "Mercado Livre", "Amazon", "Shopee",
        ))

    def test_destination_mask_supports_group_without_full_identifier(self):
        masked = result_mask("120363000000000000@g.us")
        self.assertEqual(masked, "1203*****0000@g.us")
        self.assertNotIn("120363000000000000", masked)

    def run_cli(self, *arguments):
        return subprocess.run(
            [
                sys.executable,
                "scripts/run_single_offer_cycle.py",
                *arguments,
            ],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_cli_help_works_directly(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--real-send", result.stdout)

    def test_cli_missing_destination_returns_nonzero(self):
        result = self.run_cli(
            "--term", "produto", "--stores", "amazon"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--destination", result.stderr)

    def test_cli_rejects_conflicting_modes(self):
        result = self.run_cli(
            "--term", "produto", "--stores", "amazon",
            "--destination", self.destination,
            "--dry-run", "--real-send",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowed with argument", result.stderr)

    def test_cli_rejects_max_offers_above_one(self):
        result = self.run_cli(
            "--term", "produto", "--stores", "amazon",
            "--destination", self.destination,
            "--max-offers", "2",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("max_offers=1", result.stderr)
        self.assertNotIn(self.destination, result.stderr)

    def test_cli_rejects_invalid_database_path(self):
        result = self.run_cli(
            "--term", "produto", "--stores", "amazon",
            "--destination", self.destination,
            "--database", str(Path(self.tempdir.name)),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("arquivo", result.stderr)
        self.assertNotIn(self.destination, result.stderr)

    def test_real_mode_requires_existing_database(self):
        missing = Path(self.tempdir.name) / "missing.db"
        with self.assertRaisesRegex(ValueError, "existente"):
            self.config(database_path=missing, real_send=True)


if __name__ == "__main__":
    unittest.main()
