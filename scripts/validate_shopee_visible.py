import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.browser_manager import BrowserManager

SHOPEE_PROFILE_PATH = ROOT / "data" / "browser_profiles" / "shopee_playwright"


def main(argv=None):

    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-login", action="store_true")
    args = parser.parse_args(argv)

    browser = BrowserManager(
        headless=False,
        user_data_dir=SHOPEE_PROFILE_PATH,
    )
    page = browser.new_page()

    try:

        page.goto(
            "https://shopee.com.br/search?keyword=ssd+1tb",
            wait_until="domcontentloaded",
            timeout=60000
        )
        if args.prepare_login:
            print(
                "Faça login e conclua manualmente qualquer verificação "
                "solicitada pela Shopee."
            )
            input("Pressione Enter somente depois de concluir o login: ")
        else:
            page.wait_for_timeout(10000)

        print("title", page.title())
        print("url", page.url)
        print(
            "links",
            page.locator(
                "a[href*='-i.'], a[href*='/product/']"
            ).count()
        )

    finally:

        browser.close()


if __name__ == "__main__":
    main()
