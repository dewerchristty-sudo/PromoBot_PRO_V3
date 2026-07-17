import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.browser_manager import BrowserManager


def main():

    browser = BrowserManager(headless=False)
    page = browser.new_page()

    try:

        page.goto(
            "https://shopee.com.br/search?keyword=ssd%201tb",
            wait_until="domcontentloaded",
            timeout=60000
        )

        print("A Shopee abriu.")
        input("Depois que os produtos aparecerem, pressione ENTER...")

        print("Titulo:", page.title())
        print("URL:", page.url)

        for seletor in [
            "a[href*='-i.']",
            "a[href*='/product/']",
            "img",
            "section",
            "div",
        ]:

            try:
                print(f"{seletor} -> {page.locator(seletor).count()}")
            except Exception as erro:
                print(f"{seletor} -> ERRO: {erro}")

    finally:

        input("Pressione ENTER para fechar o navegador...")
        browser.close()


if __name__ == "__main__":
    main()
