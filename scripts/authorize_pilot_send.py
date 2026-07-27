from src.pilot import (
    CONFIRMATION_PHRASE, PilotConfig, PilotManager, PilotMessageFormatter,
)
from src.pilot.source import load_pilot_product


def main(input_fn=input):
    product, _report = load_pilot_product()
    if not product:
        raise SystemExit("Produto selecionado nao encontrado.")
    manager = PilotManager(PilotConfig.from_environment())
    decision = manager.evaluate(product, dry_run=False)
    print(PilotMessageFormatter().format(product, decision))
    if decision.state != "AWAITING_CONFIRMATION":
        print("Autorizacao bloqueada:", decision.reason)
        print("Nenhum transporte foi chamado.")
        return decision
    print("Destino:", "(configurado e mascarado)")
    phrase = input_fn(
        f"Digite exatamente '{CONFIRMATION_PHRASE}' para autorizar: "
    )
    authorization, result = manager.authorize(product, phrase)
    print("Estado:", result.state)
    print("Transporte chamado: False")
    if authorization:
        print("Autorizacao temporaria criada e ainda nao consumida.")
    return result


if __name__ == "__main__":
    main()
