import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.browser_manager import BrowserManager
from src.stores.kabum import Kabum


def main():

    browser = BrowserManager(headless=False)
    loja = Kabum(browser)

    try:

        resultados = loja.search("ssd 1tb")

        print(f"TOTAL: {len(resultados)}")

        for indice, produto in enumerate(resultados, start=1):
            print(f"\nProduto {indice}")
            print("Loja:", produto["loja"])
            print("Titulo:", produto["titulo"])
            print("Preco:", produto["preco"])
            print("Link:", produto["link"])
            print("Imagem:", produto["imagem"])

    finally:

        browser.close()


if __name__ == "__main__":
    main()
