import argparse

from src.collector_scheduler import (
    PriceCollectionSchedulerConfig,
    PriceCollectionSchedulerRunner,
)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once", action="store_true",
        help="Executa uma coleta imediata e encerra.",
    )
    args = parser.parse_args(argv)
    config = PriceCollectionSchedulerConfig.from_environment()
    runner = PriceCollectionSchedulerRunner(config)
    try:
        if args.once:
            print("Modo: execucao unica")
            result = runner.run_once()
            print("Status:", result.status)
            print("Produtos:", result.products)
            print("Observacoes validas:", result.valid_observations)
            print("Duplicatas:", result.duplicates)
            print("Falhas:", result.failures)
            print("Retries:", result.retries)
            print("Proxima execucao:", result.next_run)
            print("Mensagens enviadas: 0")
            return result
        next_run = (
            runner.schedule.next_run(runner.clock())
            if config.enabled else None
        )
        print("Agendador de coleta de precos")
        print("Habilitado:", config.enabled)
        print("Proximo horario:", next_run)
        print("Pressione Ctrl+C para parar com seguranca.")
        results = runner.run_scheduled()
        print("Ciclos executados:", len(results))
        print("Mensagens enviadas: 0")
        return results
    except KeyboardInterrupt:
        print("\nAgendador interrompido pelo usuario. Nenhum envio realizado.")
        return []


if __name__ == "__main__":
    main()
