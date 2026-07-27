from urllib.parse import quote

from bs4 import BeautifulSoup

from src.stores.mercado_livre import MercadoLivre
from src.stores.mercado_livre_browser import MercadoLivrePersistentContext


def main():
    term = input("Termo [ssd 1tb]: ").strip() or "ssd 1tb"
    manager = MercadoLivrePersistentContext(headless=False)
    page = manager.new_page()
    try:
        url = "https://lista.mercadolivre.com.br/" + quote(
            term.replace(" ", "-"), safe="-"
        )
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        print("URL aberta:", page.url)
        input(
            "Se aparecer a verificação, conclua manualmente no navegador. "
            "Depois pressione ENTER aqui..."
        )
        page.wait_for_timeout(2000)
        store = MercadoLivre.__new__(MercadoLivre)
        html = page.content()
        cards, counts = store.find_cards(BeautifulSoup(html, "lxml"))
        products = store.parse_cards(cards)
        print("URL final:", page.url)
        print("Seletores:", counts)
        print("Cards brutos:", len(cards))
        print("Produtos válidos:", len(products))
        for product in products[:10]:
            print(
                product["titulo"], "|", product["preco"], "|",
                product["link"], "| imagem:", bool(product["imagem"])
            )
    finally:
        page.close()
        manager.close()


if __name__ == "__main__":
    main()
