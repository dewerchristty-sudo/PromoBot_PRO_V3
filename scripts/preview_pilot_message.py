from src.pilot import PilotConfig, PilotManager, PilotMessageFormatter
from src.pilot.reports import write_dry_run
from src.pilot.source import load_pilot_product


def generate_preview(config=None):
    product, _report = load_pilot_product()
    if not product:
        raise RuntimeError("Nenhum produto de Dry Run disponivel.")
    decision = PilotManager(
        config or PilotConfig.from_environment()
    ).evaluate(product, dry_run=True)
    return product, decision, PilotMessageFormatter().format(
        product, decision
    )


def main():
    product, decision, preview = generate_preview()
    payload = {
        "state": decision.state,
        "score": product.score,
        "threshold": product.threshold,
        "operationally_ready": product.operationally_ready,
        "selected": product.selected,
        "authorized": decision.authorized,
        "reason": decision.reason,
        "transport_called": False,
    }
    _json, path = write_dry_run(payload, preview)
    print(preview)
    print("Previa salva em:", path)
    return preview


if __name__ == "__main__":
    main()
