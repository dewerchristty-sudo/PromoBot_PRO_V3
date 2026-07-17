import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.browser_manager import BrowserManager
from src.stores import Americanas
from src.stores import Amazon
from src.stores import CasasBahia
from src.stores import Kabum
from src.stores import Magalu
from src.stores import MercadoLivre
from src.stores import Pichau
from src.stores import Shopee
from src.stores import Terabyte


def main():

    termo = " ".join(sys.argv[1:]).strip() or "ssd 1tb"
    stores = [
        MercadoLivre,
        Amazon,
        Kabum,
        Terabyte,
        Pichau,
        Magalu,
        CasasBahia,
        Americanas,
        Shopee,
    ]

    print(f"Validando busca real por: {termo}\n")

    for store_class in stores:

        browser = BrowserManager(headless=True)
        store = store_class(browser)

        try:

            resultados = store.search(termo)
            status = "OK" if resultados else "AVISO"

            print(f"[{status}] {store.name}: {len(resultados)} resultado(s)")

            if resultados:
                primeiro = resultados[0]
                print("     Titulo:", primeiro["titulo"][:100])
                print("     Preco :", primeiro["preco"] or "Nao informado")
                print("     Link  :", primeiro["link"][:120])

        except Exception as erro:

            print(f"[ERRO] {store.name}: {erro}")

        finally:

            browser.close()

        print()


if __name__ == "__main__":
    main()
