import inspect

import pytest

from scripts.validate_promotion_hunter_mercado_livre import (
    build_parser,
    run_validation,
)


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def collect(self, term, limit=None):
        self.calls.append((term, limit))
        return ({
            "loja": "Mercado Livre",
            "titulo": "SSD 1TB",
            "preco": "R$ 399,90",
            "link": "https://produto.mercadolivre.com.br/MLB-123456",
            "imagem": "https://http2.mlstatic.com/teste.jpg",
            "id": "MLB123456",
        },)


def test_manual_validation_uses_fake_adapter_without_bank_or_delivery():
    output = []
    adapter = FakeAdapter()
    result = run_validation(
        "ssd 1tb",
        limit=5,
        adapter=adapter,
        output=output.append,
    )
    assert result.status == "success"
    assert adapter.calls == [("ssd 1tb", 5)]
    assert any("MLB123456" in line for line in output)
    assert any("envios=0 bancos=0" in line for line in output)


def test_cli_default_and_bounds():
    assert build_parser().parse_args(["produto"]).limit == 5
    assert build_parser().parse_args(["produto", "--limit", "10"]).limit == 10
    with pytest.raises(SystemExit):
        build_parser().parse_args(["produto", "--limit", "11"])


def test_b1_has_no_delivery_ui_scheduler_or_database_imports():
    import src.promotion_hunter.adapters.mercado_livre as adapter_module
    import src.promotion_hunter.collectors.mercado_livre_keyword as collector_module
    import src.promotion_hunter.service as service_module

    source = "\n".join((
        inspect.getsource(adapter_module),
        inspect.getsource(collector_module),
        inspect.getsource(service_module),
    )).casefold()
    forbidden = (
        "notifier",
        "deliveryservice",
        "src.ui",
        "storemanager",
        "browsermanager",
        "offerpipeline",
        "promobot.db",
    )
    assert not any(name.casefold() in source for name in forbidden)
