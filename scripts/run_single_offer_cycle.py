import argparse
import getpass
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.single_cycle_runner import SingleCycleConfig, SingleCycleRunner
from src.core.browser_manager import BrowserManager

SHOPEE_PROFILE_PATH = (
    PROJECT_ROOT / "data" / "browser_profiles" / "shopee_playwright"
)


def prompt_amazon_tag():
    try:
        return getpass.getpass("Amazon Associate Tag: ")
    except (EOFError, KeyboardInterrupt) as error:
        raise ValueError(
            "Leitura da Amazon Associate Tag cancelada."
        ) from error


def parser():
    result = argparse.ArgumentParser(
        description="Executa um unico ciclo automatico isolado do PromoBot."
    )
    result.add_argument("--term", required=True)
    result.add_argument("--stores", nargs="+", required=True)
    result.add_argument("--destination", required=True)
    result.add_argument("--max-offers", type=int, default=1)
    result.add_argument("--transport", choices=("evolution",), default="evolution")
    result.add_argument("--database", default="promobot.db")
    result.add_argument("--visible-browser", action="store_true")
    result.add_argument("--shopee-persistent-profile", action="store_true")
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--real-send", action="store_true")
    result.add_argument(
        "--prompt-amazon-tag",
        action="store_true",
        help="Solicita a Amazon Associate Tag de forma silenciosa.",
    )
    return result


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    try:
        config = SingleCycleConfig.create(
            term=args.term,
            stores=args.stores,
            destination=args.destination,
            max_offers=args.max_offers,
            transport=args.transport,
            database_path=args.database,
            real_send=args.real_send,
        )
        if args.shopee_persistent_profile:
            if not args.visible_browser:
                raise ValueError(
                    "--shopee-persistent-profile exige --visible-browser."
                )
            if config.stores != ("Shopee",):
                raise ValueError(
                    "--shopee-persistent-profile aceita somente a loja Shopee."
                )
            browser_manager = BrowserManager(
                headless=False,
                user_data_dir=SHOPEE_PROFILE_PATH,
            )
        else:
            browser_manager = BrowserManager(
                headless=not args.visible_browser
            )
        amazon_associate_tag = (
            prompt_amazon_tag()
            if args.prompt_amazon_tag else None
        )
        cycle = SingleCycleRunner(
            config,
            amazon_associate_tag=amazon_associate_tag,
            browser_manager=browser_manager,
        )
    except ValueError as error:
        argument_parser.error(str(error))
    result = cycle.run()
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    main()
