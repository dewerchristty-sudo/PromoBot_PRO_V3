import os

from src.pilot import PilotConfig, PilotManager, validate_pilot_config
from src.pilot.reports import write_diagnostic
from src.pilot.source import load_pilot_product


def transport_configured():
    return any(bool(os.getenv(name, "").strip()) for name in (
        "ZAPI_INSTANCE_ID", "WHATSAPP_WEBHOOK_URL",
        "EVOLUTION_API_URL", "EVOLUTION_INSTANCE",
    ))


def build_diagnostic(config=None):
    config = config or PilotConfig.from_environment()
    product, source_report = load_pilot_product()
    threshold = product.threshold if product else 90
    configuration = validate_pilot_config(config, threshold)
    decision = (
        PilotManager(config).evaluate(product, dry_run=True)
        if product else None
    )
    return {
        "configuration": {
            **configuration.details,
            "state": configuration.state,
            "valid": configuration.valid,
            "reasons": list(configuration.reasons),
            "masked_group": configuration.masked_group,
        },
        "product": {
            "collected": bool(product),
            "affiliate_valid": product.affiliate_valid if product else False,
            "operationally_ready":
                product.operationally_ready if product else False,
            "approved": product.approved if product else False,
            "score": product.score if product else 0,
            "threshold": threshold,
            "selected": product.selected if product else False,
            "authorized": decision.authorized if decision else False,
            "sent": False,
        },
        "pilot": {
            "state": configuration.state,
            "decision_state": decision.state if decision else "FAILED",
            "reason": (
                decision.reason if decision else "PRODUCT_NOT_AVAILABLE"
            ),
        },
        "transport": {
            "configured": transport_configured(),
            "called": False,
            "state": "NOT_CALLED",
        },
        "source_safety": source_report.get("safety", {}),
    }


def main():
    payload = build_diagnostic()
    paths = write_diagnostic(payload)
    config = payload["configuration"]
    product = payload["product"]
    print("Configuracao:")
    print("- modo piloto habilitado:", config["enabled"])
    print("- grupo configurado:", config["group_configured"])
    print("- destino:", config["masked_group"])
    print("- confirmacao manual:", config["manual_confirmation"])
    print("- limite:", config["max_messages"])
    print("- lojas:", ", ".join(config["allowed_stores"]))
    print("- Score minimo:", config["minimum_score"])
    print("- auto-stop:", config["auto_stop_on_error"])
    print("\nProduto:")
    for key in (
        "collected", "affiliate_valid", "operationally_ready",
        "approved", "score", "threshold", "selected", "authorized",
    ):
        print(f"- {key}:", product[key])
    print("- motivo:", payload["pilot"]["reason"])
    print("\nTransporte:")
    print("- configurado:", payload["transport"]["configured"])
    print("- chamado:", payload["transport"]["called"])
    print("- estado:", payload["transport"]["state"])
    print("- relatorios:", ", ".join(str(path) for path in paths))
    return payload


if __name__ == "__main__":
    main()
