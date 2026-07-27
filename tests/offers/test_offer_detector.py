"""Testes completos para o módulo independente de detecção de ofertas."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import logging
import unittest

from src.offers.detector import (
    OfferDetection,
    OfferDetector,
    OfferDetectorConfig,
    OfferRating,
)


class OfferDetectorConfigTest(unittest.TestCase):
    """Testes para a configuração do detector de ofertas."""

    def test_config_padrao(self):
        """Configuração padrão deve ter 10% para good e 25% para excellent."""
        config = OfferDetectorConfig()
        self.assertEqual(config.good_discount_percent, 10.0)
        self.assertEqual(config.excellent_discount_percent, 25.0)

    def test_config_personalizado(self):
        """Deve aceitar limites personalizados."""
        config = OfferDetectorConfig(
            good_discount_percent=5.0,
            excellent_discount_percent=15.0,
        )
        self.assertEqual(config.good_discount_percent, 5.0)
        self.assertEqual(config.excellent_discount_percent, 15.0)

    def test_config_good_negativo_levanta_erro(self):
        """good_discount_percent negativo deve levantar ValueError."""
        with self.assertRaises(ValueError) as ctx:
            OfferDetectorConfig(good_discount_percent=-1.0)
        self.assertIn("good_discount_percent", str(ctx.exception))

    def test_config_excellent_negativo_levanta_erro(self):
        """excellent_discount_percent negativo deve levantar ValueError."""
        with self.assertRaises(ValueError) as ctx:
            OfferDetectorConfig(excellent_discount_percent=-5.0)
        self.assertIn("excellent_discount_percent", str(ctx.exception))

    def test_config_good_maior_que_excellent_levanta_erro(self):
        """good > excellent deve levantar ValueError."""
        with self.assertRaises(ValueError) as ctx:
            OfferDetectorConfig(
                good_discount_percent=30.0,
                excellent_discount_percent=20.0,
            )
        self.assertIn("good_discount_percent", str(ctx.exception))
        self.assertIn("excellent_discount_percent", str(ctx.exception))

    def test_config_good_igual_excellent_valido(self):
        """good igual a excellent é válido (ambos 20%)."""
        config = OfferDetectorConfig(
            good_discount_percent=20.0,
            excellent_discount_percent=20.0,
        )
        config.validate()  # não deve levantar exceção

    def test_config_zero_valido(self):
        """good_discount_percent = 0 é válido."""
        config = OfferDetectorConfig(good_discount_percent=0.0)
        config.validate()

    def test_config_to_dict(self):
        """to_dict deve retornar os limites como dicionário."""
        config = OfferDetectorConfig(
            good_discount_percent=5.0,
            excellent_discount_percent=15.0,
        )
        d = config.to_dict()
        self.assertEqual(d["good_discount_percent"], 5.0)
        self.assertEqual(d["excellent_discount_percent"], 15.0)


class OfferDetectorAnalyzeTest(unittest.TestCase):
    """Testes para o método analyze do OfferDetector."""

    def setUp(self):
        self.detector = OfferDetector()
        self.fixed_now = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

    # --- Cálculo de desconto ---

    def test_desconto_calculado_corretamente(self):
        """Desconto de 50% deve ser calculado corretamente."""
        result = self.detector.analyze(
            current_price=50.0,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertEqual(result.discount_percent, 50.0)
        self.assertEqual(result.savings, 50.0)
        self.assertTrue(result.is_price_drop)
        self.assertEqual(result.rating, OfferRating.EXCELLENT)

    def test_desconto_25_porcento(self):
        """Desconto de exatamente 25% deve ser EXCELLENT."""
        result = self.detector.analyze(
            current_price=75.0,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertEqual(result.discount_percent, 25.0)
        self.assertEqual(result.rating, OfferRating.EXCELLENT)

    def test_desconto_10_porcento(self):
        """Desconto de exatamente 10% deve ser GOOD."""
        result = self.detector.analyze(
            current_price=90.0,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertEqual(result.discount_percent, 10.0)
        self.assertEqual(result.rating, OfferRating.GOOD)

    def test_desconto_5_porcento(self):
        """Desconto de 5% (abaixo de 10%) deve ser COMMON."""
        result = self.detector.analyze(
            current_price=95.0,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertEqual(result.discount_percent, 5.0)
        self.assertEqual(result.rating, OfferRating.COMMON)

    # --- Cálculo de economia ---

    def test_economia_em_reais(self):
        """Economia de R$ 30,00 em um produto de R$ 100,00 para R$ 70,00."""
        result = self.detector.analyze(
            current_price=70.0,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertEqual(result.savings, 30.0)
        self.assertEqual(result.discount_percent, 30.0)

    def test_economia_com_centavos(self):
        """Economia com centavos deve ser arredondada para 2 casas."""
        result = self.detector.analyze(
            current_price=89.97,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertEqual(result.savings, 10.03)
        self.assertAlmostEqual(result.discount_percent, 10.03, places=2)

    def test_economia_zero_quando_preco_maior(self):
        """Quando preço atual é maior, economia deve ser 0 (não negativa)."""
        result = self.detector.analyze(
            current_price=120.0,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertEqual(result.savings, 0.0)
        self.assertEqual(result.discount_percent, 0.0)
        self.assertFalse(result.is_price_drop)
        self.assertEqual(result.rating, OfferRating.NONE)

    # --- Sem preço anterior ---

    def test_sem_preco_anterior(self):
        """Sem preço anterior, deve retornar rating NONE e savings/discount None."""
        result = self.detector.analyze(
            current_price=100.0,
            previous_price=None,
            analyzed_at=self.fixed_now,
        )
        self.assertIsNone(result.previous_price)
        self.assertIsNone(result.savings)
        self.assertIsNone(result.discount_percent)
        self.assertFalse(result.has_previous_price)
        self.assertFalse(result.is_price_drop)
        self.assertEqual(result.rating, OfferRating.NONE)
        self.assertEqual(result.current_price, 100.0)

    # --- Preço maior ---

    def test_preco_maior_que_anterior(self):
        """Preço atual maior que anterior não é queda de preço."""
        result = self.detector.analyze(
            current_price=150.0,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertFalse(result.is_price_drop)
        self.assertEqual(result.savings, 0.0)
        self.assertEqual(result.discount_percent, 0.0)
        self.assertEqual(result.rating, OfferRating.NONE)

    # --- Preço igual ---

    def test_preco_igual_ao_anterior(self):
        """Preço igual ao anterior não é queda de preço."""
        result = self.detector.analyze(
            current_price=100.0,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertFalse(result.is_price_drop)
        self.assertEqual(result.savings, 0.0)
        self.assertEqual(result.discount_percent, 0.0)
        self.assertEqual(result.rating, OfferRating.NONE)

    # --- Desconto extremo ---

    def test_desconto_extremo_99_porcento(self):
        """Desconto de 99% deve ser EXCELLENT."""
        result = self.detector.analyze(
            current_price=1.0,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertEqual(result.discount_percent, 99.0)
        self.assertEqual(result.rating, OfferRating.EXCELLENT)

    def test_desconto_extremo_100_porcento(self):
        """Desconto de 100% (produto grátis) deve ser EXCELLENT."""
        result = self.detector.analyze(
            current_price=0.0,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertEqual(result.discount_percent, 100.0)
        self.assertEqual(result.rating, OfferRating.EXCELLENT)

    def test_desconto_extremo_99_99_porcento(self):
        """Desconto de 99.99% deve ser EXCELLENT."""
        result = self.detector.analyze(
            current_price=0.01,
            previous_price=100.0,
            analyzed_at=self.fixed_now,
        )
        self.assertAlmostEqual(result.discount_percent, 99.99, places=2)
        self.assertEqual(result.rating, OfferRating.EXCELLENT)

    # --- Classificação correta ---

    def test_classificacao_none_sem_preco_anterior(self):
        """Sem preço anterior, classificação deve ser NONE."""
        result = self.detector.analyze(
            current_price=50.0,
            previous_price=None,
        )
        self.assertEqual(result.rating, OfferRating.NONE)

    def test_classificacao_none_preco_maior(self):
        """Preço maior, classificação deve ser NONE."""
        result = self.detector.analyze(
            current_price=200.0,
            previous_price=100.0,
        )
        self.assertEqual(result.rating, OfferRating.NONE)

    def test_classificacao_none_preco_igual(self):
        """Preço igual, classificação deve ser NONE."""
        result = self.detector.analyze(
            current_price=100.0,
            previous_price=100.0,
        )
        self.assertEqual(result.rating, OfferRating.NONE)

    def test_classificacao_common(self):
        """Desconto entre 0% e 10% deve ser COMMON."""
        result = self.detector.analyze(
            current_price=95.0,
            previous_price=100.0,
        )
        self.assertEqual(result.rating, OfferRating.COMMON)

    def test_classificacao_good(self):
        """Desconto entre 10% e 25% deve ser GOOD."""
        result = self.detector.analyze(
            current_price=80.0,
            previous_price=100.0,
        )
        self.assertEqual(result.rating, OfferRating.GOOD)

    def test_classificacao_excellent(self):
        """Desconto >= 25% deve ser EXCELLENT."""
        result = self.detector.analyze(
            current_price=70.0,
            previous_price=100.0,
        )
        self.assertEqual(result.rating, OfferRating.EXCELLENT)

    def test_classificacao_excellent_25_porcento_exato(self):
        """Desconto de exatamente 25% deve ser EXCELLENT."""
        result = self.detector.analyze(
            current_price=75.0,
            previous_price=100.0,
        )
        self.assertEqual(result.rating, OfferRating.EXCELLENT)

    def test_classificacao_good_10_porcento_exato(self):
        """Desconto de exatamente 10% deve ser GOOD."""
        result = self.detector.analyze(
            current_price=90.0,
            previous_price=100.0,
        )
        self.assertEqual(result.rating, OfferRating.GOOD)

    # --- Limites configuráveis ---

    def test_limites_personalizados_good_5_excellent_15(self):
        """Com good=5% e excellent=15%, 12% deve ser EXCELLENT."""
        detector = OfferDetector(
            config=OfferDetectorConfig(
                good_discount_percent=5.0,
                excellent_discount_percent=15.0,
            )
        )
        result = detector.analyze(
            current_price=88.0,
            previous_price=100.0,
        )
        self.assertEqual(result.discount_percent, 12.0)
        self.assertEqual(result.rating, OfferRating.GOOD)

    def test_limites_personalizados_7_porcento_good(self):
        """Com good=7%, 7% de desconto deve ser GOOD."""
        detector = OfferDetector(
            config=OfferDetectorConfig(
                good_discount_percent=7.0,
                excellent_discount_percent=20.0,
            )
        )
        result = detector.analyze(
            current_price=93.0,
            previous_price=100.0,
        )
        self.assertEqual(result.discount_percent, 7.0)
        self.assertEqual(result.rating, OfferRating.GOOD)

    def test_limites_personalizados_6_porcento_common(self):
        """Com good=7%, 6% de desconto deve ser COMMON."""
        detector = OfferDetector(
            config=OfferDetectorConfig(
                good_discount_percent=7.0,
                excellent_discount_percent=20.0,
            )
        )
        result = detector.analyze(
            current_price=94.0,
            previous_price=100.0,
        )
        self.assertEqual(result.discount_percent, 6.0)
        self.assertEqual(result.rating, OfferRating.COMMON)

    def test_limites_com_good_zero(self):
        """Com good=0%, qualquer desconto > 0% deve ser GOOD."""
        detector = OfferDetector(
            config=OfferDetectorConfig(
                good_discount_percent=0.0,
                excellent_discount_percent=10.0,
            )
        )
        result = detector.analyze(
            current_price=99.0,
            previous_price=100.0,
        )
        self.assertEqual(result.discount_percent, 1.0)
        self.assertEqual(result.rating, OfferRating.GOOD)

    # --- Erros ---

    def test_current_price_negativo_levanta_erro(self):
        """Preço atual negativo deve levantar ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.detector.analyze(current_price=-10.0, previous_price=100.0)
        self.assertIn("current_price", str(ctx.exception))

    def test_previous_price_negativo_tratado_como_ausente(self):
        """Preço anterior negativo deve ser tratado como ausente (NONE)."""
        result = self.detector.analyze(
            current_price=50.0,
            previous_price=-10.0,
            analyzed_at=self.fixed_now,
        )
        self.assertIsNone(result.previous_price)
        self.assertIsNone(result.savings)
        self.assertIsNone(result.discount_percent)
        self.assertFalse(result.has_previous_price)
        self.assertEqual(result.rating, OfferRating.NONE)

    def test_previous_price_zero_tratado_como_ausente(self):
        """Preço anterior zero deve ser tratado como ausente (NONE)."""
        result = self.detector.analyze(
            current_price=50.0,
            previous_price=0.0,
            analyzed_at=self.fixed_now,
        )
        self.assertIsNone(result.previous_price)
        self.assertIsNone(result.savings)
        self.assertIsNone(result.discount_percent)
        self.assertFalse(result.has_previous_price)
        self.assertEqual(result.rating, OfferRating.NONE)

    def test_current_price_invalido_levanta_erro(self):
        """Tipo inválido para current_price deve levantar ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.detector.analyze(current_price="cem", previous_price=100.0)  # type: ignore
        self.assertIn("current_price", str(ctx.exception))

    # --- Casos extremos ---

    def test_preco_muito_alto(self):
        """Preços muito altos devem funcionar sem erro."""
        result = self.detector.analyze(
            current_price=1_000_000.0,
            previous_price=2_000_000.0,
        )
        self.assertEqual(result.discount_percent, 50.0)
        self.assertEqual(result.savings, 1_000_000.0)
        self.assertEqual(result.rating, OfferRating.EXCELLENT)

    def test_preco_muito_baixo_centavos(self):
        """Preços em centavos devem funcionar."""
        result = self.detector.analyze(
            current_price=0.50,
            previous_price=1.00,
        )
        self.assertEqual(result.discount_percent, 50.0)
        self.assertEqual(result.savings, 0.50)
        self.assertEqual(result.rating, OfferRating.EXCELLENT)

    def test_preco_com_muitas_casas_decimais(self):
        """Preços com muitas casas decimais devem ser arredondados."""
        result = self.detector.analyze(
            current_price=74.9999,
            previous_price=100.0,
        )
        self.assertAlmostEqual(result.discount_percent, 25.00, places=2)
        self.assertAlmostEqual(result.savings, 25.00, places=2)

    def test_current_price_zero_valido(self):
        """Preço atual zero é válido (produto grátis/promocional)."""
        result = self.detector.analyze(
            current_price=0.0,
            previous_price=100.0,
        )
        self.assertEqual(result.discount_percent, 100.0)
        self.assertEqual(result.savings, 100.0)
        self.assertEqual(result.rating, OfferRating.EXCELLENT)

    def test_analyzed_at_padrao_utc(self):
        """Se analyzed_at não for fornecido, deve usar UTC now."""
        before = datetime.now(timezone.utc)
        result = self.detector.analyze(
            current_price=50.0,
            previous_price=100.0,
        )
        after = datetime.now(timezone.utc)
        self.assertTrue(before <= result.analyzed_at <= after)
        self.assertIsNotNone(result.analyzed_at.tzinfo)

    def test_analyzed_at_personalizado(self):
        """analyzed_at personalizado deve ser preservado."""
        custom_time = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = self.detector.analyze(
            current_price=50.0,
            previous_price=100.0,
            analyzed_at=custom_time,
        )
        self.assertEqual(result.analyzed_at, custom_time)

    def test_has_previous_price_true_quando_fornecido(self):
        """has_previous_price deve ser True quando previous_price é fornecido."""
        result = self.detector.analyze(
            current_price=50.0,
            previous_price=100.0,
        )
        self.assertTrue(result.has_previous_price)

    def test_has_previous_price_false_quando_ausente(self):
        """has_previous_price deve ser False quando previous_price é None."""
        result = self.detector.analyze(
            current_price=50.0,
            previous_price=None,
        )
        self.assertFalse(result.has_previous_price)

    def test_thresholds_used_no_resultado(self):
        """O resultado deve conter os thresholds usados na análise."""
        config = OfferDetectorConfig(
            good_discount_percent=5.0,
            excellent_discount_percent=15.0,
        )
        detector = OfferDetector(config=config)
        result = detector.analyze(
            current_price=50.0,
            previous_price=100.0,
        )
        self.assertEqual(
            result.thresholds_used["good_discount_percent"], 5.0
        )
        self.assertEqual(
            result.thresholds_used["excellent_discount_percent"], 15.0
        )


class OfferDetectorAnalyzeFromMappingTest(unittest.TestCase):
    """Testes para o método analyze_from_mapping."""

    def setUp(self):
        self.detector = OfferDetector()

    def test_mapping_com_chaves_em_ingles(self):
        """Deve extrair current_price e previous_price de chaves em inglês."""
        data = {
            "current_price": 50.0,
            "previous_price": 100.0,
        }
        result = self.detector.analyze_from_mapping(data)
        self.assertEqual(result.current_price, 50.0)
        self.assertEqual(result.previous_price, 100.0)
        self.assertEqual(result.discount_percent, 50.0)

    def test_mapping_com_chaves_em_portugues(self):
        """Deve extrair preco_valor e preco_antigo de chaves em português."""
        data = {
            "preco_valor": 75.0,
            "preco_antigo": 100.0,
        }
        result = self.detector.analyze_from_mapping(data)
        self.assertEqual(result.current_price, 75.0)
        self.assertEqual(result.previous_price, 100.0)
        self.assertEqual(result.discount_percent, 25.0)

    def test_mapping_sem_preco_anterior(self):
        """Mapping sem preço anterior deve resultar em NONE."""
        data = {
            "current_price": 50.0,
        }
        result = self.detector.analyze_from_mapping(data)
        self.assertEqual(result.current_price, 50.0)
        self.assertIsNone(result.previous_price)
        self.assertEqual(result.rating, OfferRating.NONE)

    def test_mapping_com_preco_antigo_zero(self):
        """Mapping com preco_antigo = 0 deve tratar como ausente."""
        data = {
            "current_price": 50.0,
            "preco_antigo": 0,
        }
        result = self.detector.analyze_from_mapping(data)
        self.assertIsNone(result.previous_price)
        self.assertEqual(result.rating, OfferRating.NONE)

    def test_mapping_com_analyzed_at(self):
        """Deve extrair analyzed_at do mapping se fornecido."""
        custom_time = datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        data = {
            "current_price": 50.0,
            "previous_price": 100.0,
            "analyzed_at": custom_time,
        }
        result = self.detector.analyze_from_mapping(data)
        self.assertEqual(result.analyzed_at, custom_time)

    def test_mapping_com_valores_string_numericos(self):
        """Deve converter strings numéricas para float."""
        data = {
            "current_price": "50.0",
            "previous_price": "100.0",
        }
        result = self.detector.analyze_from_mapping(data)
        self.assertEqual(result.current_price, 50.0)
        self.assertEqual(result.previous_price, 100.0)
        self.assertEqual(result.discount_percent, 50.0)

    def test_mapping_com_valores_decimal(self):
        """Deve converter Decimal para float."""
        data = {
            "current_price": Decimal("50.0"),
            "previous_price": Decimal("100.0"),
        }
        result = self.detector.analyze_from_mapping(data)
        self.assertEqual(result.current_price, 50.0)
        self.assertEqual(result.previous_price, 100.0)

    def test_mapping_sem_chaves_de_preco(self):
        """Mapping sem chaves de preço deve resultar em erro (current_price obrigatório)."""
        data = {"title": "Produto teste"}
        with self.assertRaises(ValueError):
            self.detector.analyze_from_mapping(data)


class OfferDetectionToDictTest(unittest.TestCase):
    """Testes para o método to_dict do OfferDetection."""

    def test_to_dict_com_preco_anterior(self):
        """to_dict deve conter todos os campos esperados."""
        result = OfferDetection(
            current_price=50.0,
            previous_price=100.0,
            savings=50.0,
            discount_percent=50.0,
            rating=OfferRating.EXCELLENT,
            has_previous_price=True,
            is_price_drop=True,
            analyzed_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc),
            thresholds_used={"good_discount_percent": 10.0, "excellent_discount_percent": 25.0},
        )
        d = result.to_dict()
        self.assertEqual(d["current_price"], 50.0)
        self.assertEqual(d["previous_price"], 100.0)
        self.assertEqual(d["savings"], 50.0)
        self.assertEqual(d["discount_percent"], 50.0)
        self.assertEqual(d["rating"], "excellent")
        self.assertTrue(d["has_previous_price"])
        self.assertTrue(d["is_price_drop"])
        self.assertIn("analyzed_at", d)
        self.assertIn("thresholds_used", d)

    def test_to_dict_sem_preco_anterior(self):
        """to_dict sem preço anterior deve ter campos None."""
        result = OfferDetection(
            current_price=50.0,
            previous_price=None,
            savings=None,
            discount_percent=None,
            rating=OfferRating.NONE,
            has_previous_price=False,
            is_price_drop=False,
            analyzed_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc),
            thresholds_used={"good_discount_percent": 10.0, "excellent_discount_percent": 25.0},
        )
        d = result.to_dict()
        self.assertIsNone(d["previous_price"])
        self.assertIsNone(d["savings"])
        self.assertIsNone(d["discount_percent"])
        self.assertEqual(d["rating"], "none")
        self.assertFalse(d["has_previous_price"])

    def test_to_dict_rating_common(self):
        """to_dict com rating COMMON."""
        result = OfferDetection(
            current_price=95.0,
            previous_price=100.0,
            savings=5.0,
            discount_percent=5.0,
            rating=OfferRating.COMMON,
            has_previous_price=True,
            is_price_drop=True,
            analyzed_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc),
            thresholds_used={"good_discount_percent": 10.0, "excellent_discount_percent": 25.0},
        )
        d = result.to_dict()
        self.assertEqual(d["rating"], "common")

    def test_to_dict_rating_good(self):
        """to_dict com rating GOOD."""
        result = OfferDetection(
            current_price=85.0,
            previous_price=100.0,
            savings=15.0,
            discount_percent=15.0,
            rating=OfferRating.GOOD,
            has_previous_price=True,
            is_price_drop=True,
            analyzed_at=datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc),
            thresholds_used={"good_discount_percent": 10.0, "excellent_discount_percent": 25.0},
        )
        d = result.to_dict()
        self.assertEqual(d["rating"], "good")


class OfferDetectorLoggingTest(unittest.TestCase):
    """Testes de logging do OfferDetector."""

    def test_logging_nao_quebra_analise(self):
        """Logging não deve interferir no resultado da análise."""
        detector = OfferDetector(logger=logging.getLogger("test"))
        result = detector.analyze(
            current_price=50.0,
            previous_price=100.0,
        )
        self.assertEqual(result.rating, OfferRating.EXCELLENT)

    def test_logging_sem_preco_anterior(self):
        """Logging sem preço anterior não deve quebrar."""
        detector = OfferDetector(logger=logging.getLogger("test"))
        result = detector.analyze(
            current_price=50.0,
            previous_price=None,
        )
        self.assertEqual(result.rating, OfferRating.NONE)


class OfferRatingTest(unittest.TestCase):
    """Testes para o enum OfferRating."""

    def test_rating_values(self):
        """OfferRating deve ter os valores corretos."""
        self.assertEqual(OfferRating.NONE.value, "none")
        self.assertEqual(OfferRating.COMMON.value, "common")
        self.assertEqual(OfferRating.GOOD.value, "good")
        self.assertEqual(OfferRating.EXCELLENT.value, "excellent")

    def test_rating_str(self):
        """str(OfferRating) deve retornar o valor."""
        self.assertEqual(str(OfferRating.NONE), "none")
        self.assertEqual(str(OfferRating.COMMON), "common")
        self.assertEqual(str(OfferRating.GOOD), "good")
        self.assertEqual(str(OfferRating.EXCELLENT), "excellent")


if __name__ == "__main__":
    unittest.main()