from pathlib import Path

from src.affiliates.diagnostics import AffiliateDiagnostics


SAFE_TEMPLATE = """# Sugestao de configuracao - revise e copie manualmente para .env
# Nenhum valor foi gravado automaticamente no .env.
AMAZON_ASSOCIATE_TAG=
MERCADOLIVRE_AFFILIATE_ID=
MERCADOLIVRE_AFFILIATE_MAP=
MERCADOLIVRE_AFFILIATE_TEMPLATE=
SHOPEE_AFFILIATE_ID=
SHOPEE_AFFILIATE_MAP=
SHOPEE_AFFILIATE_TEMPLATE=
AFFILIATE_CACHE_TTL_HOURS=720
"""


def main(input_fn=input):
    print("PromoBot - Assistente seguro de afiliados")
    print("Lojas suportadas: Mercado Livre, Amazon e Shopee.")
    print("Valores sensiveis nunca serao exibidos por completo.")
    diagnostics = AffiliateDiagnostics()
    try:
        report = diagnostics.run()
    finally:
        diagnostics.close()
    for index, row in enumerate(report["stores"], 1):
        print(f"{index}. {row['store']}: {row['status']} - {row['reason']}")
        for name, value in row["masked_values"].items():
            print(f"   {name}: {value}")
    choice = input_fn(
        "\nDigite 1, 2 ou 3 para ver o diagnostico da loja, "
        "G para gerar sugestao, ou ENTER para sair: "
    ).strip().casefold()
    if choice in {"1", "2", "3"}:
        row = report["stores"][int(choice) - 1]
        print(f"\n{row['store']}: {row['status']}")
        print("Motivo:", row["reason"])
        print("Faltando:", ", ".join(row["missing"]) or "nada")
        if choice == "2":
            print(
                "Variavel: AMAZON_ASSOCIATE_TAG\n"
                "Formato: tag oficial do Amazon Associados, normalmente "
                "com sufixo regional, por exemplo minhavitrine-20.\n"
                "Onde obter: portal oficial Amazon Associados, na area de "
                "IDs de rastreamento.\n"
                "Depois de preencher manualmente o .env, execute:\n"
                "python -m scripts.diagnose_affiliates\n"
                "python -m scripts.run_offer_dry_run --store amazon"
            )
        return report
    if choice == "g":
        confirmation = input_fn(
            "Gerar affiliate_config.generated.example? "
            "Digite CONFIRMAR: "
        ).strip()
        if confirmation == "CONFIRMAR":
            target = Path("affiliate_config.generated.example")
            target.write_text(SAFE_TEMPLATE, encoding="utf-8")
            print("Arquivo seguro gerado:", target)
        else:
            print("Operacao cancelada. O .env nao foi alterado.")
    return report


if __name__ == "__main__":
    main()
