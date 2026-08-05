from pathlib import Path
import sys

import pytest

from src.affiliates.amazon import AmazonAffiliateProvider
from src.affiliates.config import (
    AffiliateConfig,
    StoreAffiliateConfig,
    runtime_env_path,
)
from src.affiliates.manager import AffiliateManager
from src.offers.readiness import OfferReadinessEnricher
from src.promotion_hunter import official_runtime


TAG = "miguelchristt-20"
ASIN = "B0DZPGRMKM"
ORIGINAL = f"https://www.amazon.com.br/dp/{ASIN}?ref_=automatic"
EXPECTED = f"https://www.amazon.com.br/dp/{ASIN}?tag={TAG}"


def config(tag=TAG, env_path=Path(".env")):
    empty = StoreAffiliateConfig()
    return AffiliateConfig(
        mercado_livre=empty,
        amazon=StoreAffiliateConfig(associate_tag=tag),
        shopee=empty,
        cache_path=Path(":memory:"),
        env_path=env_path,
        env_file_found=True,
    )


def test_canonical_generation_preserves_asin_and_exact_tag():
    url, source, error = AmazonAffiliateProvider(config().amazon).generate(ORIGINAL)
    assert error == ""
    assert source == "associate_tag"
    assert url == EXPECTED


@pytest.mark.parametrize("tag", ["", "tag=wrong-20", "bad tag-20"])
def test_automatic_runtime_rejects_missing_or_invalid_tag(monkeypatch, tag):
    monkeypatch.setattr(
        official_runtime.AffiliateConfig,
        "from_environment",
        classmethod(lambda cls: config(tag)),
    )
    with pytest.raises(RuntimeError, match="Promotion Hunter Amazon indisponivel"):
        official_runtime.build_official_runtime()


def test_frozen_runtime_uses_external_env_beside_executable(monkeypatch, tmp_path):
    executable = tmp_path / "PromoBot_PRO_V3.exe"
    env_file = tmp_path / ".env"
    env_file.write_text(f"AMAZON_ASSOCIATE_TAG={TAG}\n", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.delenv("PROMOBOT_ENV_PATH", raising=False)
    monkeypatch.delenv("AMAZON_ASSOCIATE_TAG", raising=False)
    assert runtime_env_path() == env_file
    loaded = AffiliateConfig.from_environment()
    assert loaded.env_path == env_file
    assert loaded.amazon.associate_tag == TAG


def test_automatic_runtime_injects_validated_config(monkeypatch):
    loaded = config()
    captured = {}
    monkeypatch.setattr(
        official_runtime.AffiliateConfig,
        "from_environment",
        classmethod(lambda cls: loaded),
    )
    import scripts.run_promotion_hunter_pilot as pilot

    def fake_build(args, affiliate_config=None):
        captured["config"] = affiliate_config
        return object(), object(), object(), ()

    monkeypatch.setattr(pilot, "build_runtime", fake_build)
    result = official_runtime.build_official_runtime()
    assert result[:3]
    assert captured["config"] is loaded


def test_amazon_product_reaches_readiness_with_affiliate_url():
    manager = AffiliateManager(config=config())
    try:
        prepared = OfferReadinessEnricher(manager).prepare({
            "loja": "Amazon",
            "titulo": "Produto real",
            "link": ORIGINAL,
            "preco_atual": 199.90,
            "imagem": "https://images.example/product.jpg",
        })
        assert prepared.product["affiliate_url"] == EXPECTED
        assert "link_afiliado_ausente" not in prepared.operational_readiness["blocks"]
    finally:
        manager.close()
