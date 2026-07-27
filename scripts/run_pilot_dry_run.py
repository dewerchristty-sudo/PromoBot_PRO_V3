from src.pilot import PilotConfig, PilotManager, PilotMessageFormatter
from src.pilot.reports import write_dry_run
from src.pilot.source import load_pilot_product


class ForbiddenPilotTransport:
    called = False

    def send(self, *_args, **_kwargs):
        self.called = True
        raise AssertionError("Transporte proibido no Pilot Dry Run.")


def run(config=None, transport=None):
    product, source_report = load_pilot_product()
    if not product:
        raise RuntimeError("Produto real do Dry Run nao encontrado.")
    transport = transport or ForbiddenPilotTransport()
    manager = PilotManager(config or PilotConfig.from_environment())
    decision = manager.evaluate(product, dry_run=True)
    preview = PilotMessageFormatter().format(product, decision)
    payload = {
        "pilot_state": "DRY_RUN",
        "product": {
            "identity": product.identity,
            "store": product.store,
            "score": product.score,
            "threshold": product.threshold,
            "affiliate_valid": product.affiliate_valid,
            "operationally_ready": product.operationally_ready,
            "approved": product.approved,
            "selected": product.selected,
            "authorized": decision.authorized,
            "sent": decision.sent,
        },
        "decision": {
            "state": decision.state,
            "reason": decision.reason,
            "auto_stopped": decision.auto_stopped,
        },
        "transport": {
            "called": transport.called,
            "blocked": True,
        },
        "source_transport_called": source_report.get(
            "safety", {}
        ).get("transport_called", False),
    }
    paths = write_dry_run(payload, preview)
    if transport.called:
        raise AssertionError("Pilot Dry Run chamou transporte.")
    return payload, paths


def main():
    payload, paths = run()
    product = payload["product"]
    print("Pilot Dry Run:")
    print("- operacionalmente pronto:", product["operationally_ready"])
    print("- Score:", product["score"])
    print("- Threshold:", product["threshold"])
    print("- selecionado:", product["selected"])
    print("- autorizado:", product["authorized"])
    print("- motivo:", payload["decision"]["reason"])
    print("- transporte chamado:", payload["transport"]["called"])
    print("- relatorios:", ", ".join(str(path) for path in paths))
    return payload


if __name__ == "__main__":
    main()
