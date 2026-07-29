import io
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from scripts.run_single_offer_cycle import main
from src.affiliates.amazon import (
    AmazonAffiliateProvider,
    masked_associate_tag,
    validate_associate_tag,
)
from src.affiliates.config import StoreAffiliateConfig
from src.core.single_cycle_runner import (
    SingleCycleConfig,
    SingleCycleRunner,
    summarize_link,
)
from src.database import Database


FIXTURE_TAG = "fixture-unit-20"
AMAZON_URL = "https://www.amazon.com.br/dp/B0ABC12345?ref_=fixture"


class AmazonAffiliateInjectionTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tempdir.name) / "cycle.db"
        self.destination = "5511999999999"

    def tearDown(self):
        self.tempdir.cleanup()

    def config(self, stores=("amazon",), real_send=False):
        if real_send and not self.database_path.exists():
            database = Database(self.database_path)
            database.fechar()
        return SingleCycleConfig.create(
            term="produto controlado",
            stores=stores,
            destination=self.destination,
            database_path=self.database_path,
            real_send=real_send,
        )

    @staticmethod
    def product(store="Amazon", link=AMAZON_URL):
        return {
            "loja": store,
            "titulo": f"Produto {store}",
            "preco": "R$ 50,00",
            "preco_valor": 50.0,
            "preco_antigo": 100.0,
            "link": link,
            "imagem": "https://images.invalid/product.jpg",
            "estoque": 1,
            "disponivel": True,
        }

    def runner(self, *, tag=None, product=None, stores=("amazon",), **kwargs):
        item = product or self.product()
        return SingleCycleRunner(
            self.config(stores=stores),
            collector=lambda _term, _store: [dict(item)],
            amazon_associate_tag=tag,
            **kwargs,
        )

    def test_tag_absent_keeps_offer_blocked_with_sanitized_reason(self):
        transport = Mock()
        result = self.runner(transport=transport).run()
        self.assertEqual(result.final_result, "no_eligible_offer")
        self.assertEqual(
            result.affiliate_block_reasons,
            ("associate_tag_nao_configurada",),
        )
        transport.assert_not_called()

    def test_valid_tag_makes_amazon_product_eligible(self):
        transport = Mock(return_value=True)
        runner = self.runner(tag=FIXTURE_TAG, transport=transport)
        result = runner.run()
        self.assertEqual(result.final_result, "dry_run_completed")
        self.assertEqual(result.eligible_count, 1)
        self.assertEqual(runner._amazon_associate_tag, "")
        transport.assert_called_once()

    def test_invalid_tags_are_rejected_before_collection(self):
        invalid = (
            "", " tag-with-space", "tag with space", "tag\tvalue",
            "tag\nline", "tag\rline",
            "https://amazon.invalid/value", "tag=value",
            "amazon.invalid", "\"quoted\"", "x", "placeholder",
            "value&other", "value?other", "x" * 65,
        )
        collector = Mock()
        for value in invalid:
            with self.subTest(value=repr(value)):
                with self.assertRaisesRegex(ValueError, "Associate Tag"):
                    SingleCycleRunner(
                        self.config(),
                        collector=collector,
                        amazon_associate_tag=value,
                    )
        collector.assert_not_called()

    def test_tag_is_not_exposed_by_result_repr_or_exception(self):
        result = self.runner(tag=FIXTURE_TAG).run()
        self.assertNotIn(FIXTURE_TAG, repr(result))
        self.assertNotIn(FIXTURE_TAG, str(result.as_dict()))
        with self.assertRaises(ValueError) as raised:
            SingleCycleRunner(
                self.config(),
                amazon_associate_tag=f"{FIXTURE_TAG}&invalid",
            )
        self.assertNotIn(FIXTURE_TAG, str(raised.exception))

    def test_tag_is_not_logged(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            self.runner(tag=FIXTURE_TAG).run()
        finally:
            root.removeHandler(handler)
        self.assertNotIn(FIXTURE_TAG, stream.getvalue())

    def test_tag_is_not_persisted_in_temporary_database(self):
        database = Database(self.database_path)
        try:
            self.runner(tag=FIXTURE_TAG, database=database).run()
        finally:
            database.fechar()
        self.assertNotIn(
            FIXTURE_TAG.encode(),
            self.database_path.read_bytes(),
        )

    def test_only_amazon_is_enriched(self):
        for store, alias in (
            ("Mercado Livre", "mercado_livre"),
            ("Shopee", "shopee"),
        ):
            product = self.product(
                store,
                f"https://example.invalid/{alias}",
            )
            runner = self.runner(
                tag=FIXTURE_TAG,
                product=product,
                stores=(alias,),
            )
            collected, _errors = runner.collect("execution")
            self.assertNotIn("link_afiliado_salvo", collected[0])
            self.assertNotIn("link_original", collected[0])

    def test_original_link_is_preserved_only_in_temporary_product(self):
        runner = self.runner(tag=FIXTURE_TAG)
        collected, _errors = runner.collect("execution")
        product = collected[0]
        self.assertEqual(product["link"], AMAZON_URL)
        self.assertEqual(product["link_original"], AMAZON_URL)
        self.assertNotEqual(product["link_afiliado_salvo"], AMAZON_URL)
        self.assertEqual(
            parse_qs(urlparse(product["link_afiliado_salvo"]).query)["tag"],
            [FIXTURE_TAG],
        )

    def test_provider_replaces_one_tag_and_preserves_other_parameters(self):
        provider = AmazonAffiliateProvider(StoreAffiliateConfig(
            associate_tag=FIXTURE_TAG
        ))
        original = (
            "https://www.amazon.com.br/dp/B0ABC12345"
            "?tag=old-fixture&ref_=preserved&tag=duplicate"
        )
        generated, source, error = provider.generate(original)
        query = parse_qs(urlparse(generated).query)
        self.assertEqual(error, "")
        self.assertEqual(source, "associate_tag")
        self.assertEqual(query["tag"], [FIXTURE_TAG])
        self.assertEqual(query["ref_"], ["preserved"])
        self.assertIn("/dp/B0ABC12345", generated)
        self.assertTrue(provider.validate(generated, original))

    def test_provider_accepts_amazon_br_and_rejects_other_domain(self):
        provider = AmazonAffiliateProvider(StoreAffiliateConfig(
            associate_tag=FIXTURE_TAG
        ))
        generated, _source, error = provider.generate(AMAZON_URL)
        self.assertEqual(error, "")
        self.assertTrue(provider.validate(generated, AMAZON_URL))
        generated, _source, error = provider.generate(
            "https://example.invalid/dp/B0ABC12345"
        )
        self.assertEqual(generated, "")
        self.assertEqual(error, "url_original_amazon_nao_expansivel")

    def test_provider_accepts_authorized_subdomain(self):
        provider = AmazonAffiliateProvider(StoreAffiliateConfig(
            associate_tag=FIXTURE_TAG
        ))
        original = (
            "https://www.amazon.com.br/dp/B0ABC12345"
            "?ref_=preserved#customerReviews"
        )
        generated, _source, error = provider.generate(original)
        self.assertEqual(error, "")
        self.assertEqual(urlparse(generated).fragment, "customerReviews")
        self.assertEqual(
            parse_qs(urlparse(generated).query)["ref_"],
            ["preserved"],
        )

    def test_provider_rejects_similar_and_malicious_domains(self):
        provider = AmazonAffiliateProvider(StoreAffiliateConfig(
            associate_tag=FIXTURE_TAG
        ))
        for domain in (
            "amazon.com.br.evil.invalid",
            "notamazon.com.br",
            "amazon.invalid",
        ):
            with self.subTest(domain=domain):
                generated, _source, error = provider.generate(
                    f"https://{domain}/dp/B0ABC12345"
                )
                self.assertEqual(generated, "")
                self.assertEqual(
                    error,
                    "url_original_amazon_nao_expansivel",
                )

    def test_summarized_link_removes_tag_query(self):
        value = summarize_link(
            f"{AMAZON_URL}&tag={FIXTURE_TAG}"
        )
        self.assertNotIn(FIXTURE_TAG, value)
        self.assertNotIn("tag=", value)

    def test_masked_tag_never_returns_full_value(self):
        masked = masked_associate_tag(FIXTURE_TAG)
        self.assertNotEqual(masked, FIXTURE_TAG)
        self.assertNotIn(FIXTURE_TAG, masked)
        self.assertTrue(masked.endswith("-20"))

    def test_cli_without_prompt_does_not_call_getpass(self):
        fake_result = Mock()
        fake_result.as_dict.return_value = {}
        with (
            patch(
                "scripts.run_single_offer_cycle.getpass.getpass"
            ) as prompt,
            patch(
                "scripts.run_single_offer_cycle.SingleCycleRunner"
            ) as runner_class,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            runner_class.return_value.run.return_value = fake_result
            main([
                "--term", "produto",
                "--stores", "amazon",
                "--destination", self.destination,
                "--database", str(self.database_path),
            ])
        prompt.assert_not_called()
        self.assertIsNone(
            runner_class.call_args.kwargs["amazon_associate_tag"],
        )

    def test_cli_prompt_uses_getpass_without_printing_tag(self):
        fake_result = Mock()
        fake_result.as_dict.return_value = {}
        output = io.StringIO()
        with (
            patch(
                "scripts.run_single_offer_cycle.getpass.getpass",
                return_value=FIXTURE_TAG,
            ) as prompt,
            patch(
                "scripts.run_single_offer_cycle.SingleCycleRunner"
            ) as runner_class,
            patch("sys.stdout", output),
        ):
            runner_class.return_value.run.return_value = fake_result
            main([
                "--term", "produto",
                "--stores", "amazon",
                "--destination", self.destination,
                "--database", str(self.database_path),
                "--prompt-amazon-tag",
            ])
        prompt.assert_called_once()
        self.assertNotIn(FIXTURE_TAG, output.getvalue())
        self.assertEqual(
            runner_class.call_args.kwargs["amazon_associate_tag"],
            FIXTURE_TAG,
        )

    def test_cli_invalid_prompt_value_exits_without_runner(self):
        with (
            patch(
                "scripts.run_single_offer_cycle.getpass.getpass",
                return_value="tag=invalid",
            ),
            patch(
                "scripts.run_single_offer_cycle.SingleCycleRunner",
                wraps=SingleCycleRunner,
            ) as runner_class,
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            with self.assertRaises(SystemExit) as raised:
                main([
                    "--term", "produto",
                    "--stores", "amazon",
                    "--destination", self.destination,
                    "--database", str(self.database_path),
                    "--prompt-amazon-tag",
                ])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(runner_class.call_count, 1)

    def test_cli_cancelled_prompt_returns_sanitized_error(self):
        error_output = io.StringIO()
        with (
            patch(
                "scripts.run_single_offer_cycle.getpass.getpass",
                side_effect=KeyboardInterrupt,
            ),
            patch("sys.stderr", error_output),
        ):
            with self.assertRaises(SystemExit) as raised:
                main([
                    "--term", "produto",
                    "--stores", "amazon",
                    "--destination", self.destination,
                    "--database", str(self.database_path),
                    "--prompt-amazon-tag",
                ])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("cancelada", error_output.getvalue())
        self.assertNotIn(FIXTURE_TAG, error_output.getvalue())

    def test_real_failure_does_not_expose_tag(self):
        database = Database(self.database_path)
        transport = Mock(side_effect=RuntimeError("falha sanitizada"))
        try:
            runner = SingleCycleRunner(
                self.config(real_send=True),
                collector=lambda _term, _store: [self.product()],
                transport=transport,
                database=database,
                amazon_associate_tag=FIXTURE_TAG,
            )
            result = runner.run()
        finally:
            database.fechar()
        self.assertNotIn(FIXTURE_TAG, repr(result))
        self.assertNotIn(FIXTURE_TAG, str(result.as_dict()))
        self.assertEqual(runner._amazon_associate_tag, "")

    def test_real_mode_without_injection_remains_unchanged(self):
        database = Database(self.database_path)
        try:
            runner = SingleCycleRunner(
                self.config(real_send=True),
                collector=lambda _term, _store: [self.product()],
                transport=Mock(),
                database=database,
            )
            result = runner.run()
        finally:
            database.fechar()
        self.assertEqual(result.final_result, "no_eligible_offer")
        self.assertEqual(result.transport_calls, 0)


if __name__ == "__main__":
    unittest.main()
