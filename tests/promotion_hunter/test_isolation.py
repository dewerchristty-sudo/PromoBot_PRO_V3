from pathlib import Path


AUTHORIZED_IMPORTS = {
    "src.promotion_hunter",
}


def test_module_has_no_operational_integration_or_transport_access():
    root = Path("src/promotion_hunter")
    general_content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*.py")
        if not (
            path.name == "notifier_adapter.py"
            or path.name == "circuit_breaker.py"
            or (path.name == "__init__.py" and path.parent.name == "delivery")
        )
    ).casefold()
    forbidden = (
        "playwright",
        "selenium",
        "browsermanager",
        "storemanager",
        "notifier",
        "deliveryservice",
        "whatsapp",
        "telegram",
        "requests.",
        "httpx.",
        "promobot.db",
        "offer_shadow.db",
        "monitor_telemetry.db",
    )
    assert not [token for token in forbidden if token in general_content]

    delivery_adapter = (
        root / "delivery" / "notifier_adapter.py"
    ).read_text(encoding="utf-8").casefold()
    assert "src.core.notifier" not in delivery_adapter
    assert "whatsapp_groups" not in delivery_adapter
    assert "whatsapp_category_groups" not in delivery_adapter


def test_automated_tests_do_not_open_real_promotion_hunter_database():
    test_root = Path("tests/promotion_hunter")
    references = []
    for path in test_root.rglob("*.py"):
        if path.resolve() == Path(__file__).resolve():
            continue
        content = path.read_text(encoding="utf-8")
        if '"promotion_hunter.db"' in content or "'promotion_hunter.db'" in content:
            references.append(str(path))
    assert references == []
