from bs4 import BeautifulSoup
from urllib.parse import parse_qs
from urllib.parse import unquote
from urllib.parse import urlparse

from src.stores.base_store import BaseStore


class Amazon(BaseStore):

    @property
    def name(self):
        return "Amazon"

    @property
    def base_url(self):
        return "https://www.amazon.com.br/s?k={}"

    # ======================================================

    def search(self, product):

        resultados = []

        page = self.browser_manager.new_page()

        try:

            url = self.base_url.format(
                product.replace(" ", "+")
            )

            print(f"\n>>> {self.name}")
            print(f"Abrindo: {url}")

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(5000)

            soup = BeautifulSoup(
                page.content(),
                "lxml"
            )

            produtos = soup.select(
                "div[data-component-type='s-search-result']"
            )

            print(f"Produtos encontrados: {len(produtos)}")

            for item in produtos[:20]:

                try:

                    titulo = item.select_one("h2 span")
                    preco = (
                        item.select_one(".a-price .a-offscreen")
                        or item.select_one(".a-price-whole")
                    )
                    link = self.product_link(item)
                    imagem = item.select_one("img")

                    titulo_texto = titulo.get_text(strip=True) if titulo else ""

                    if not titulo_texto or not link:
                        continue

                    resultados.append({

                        "loja": self.name,

                        "titulo": titulo_texto,

                        "preco": self.price(
                            preco.get_text(strip=True) if preco else ""
                        ),

                        "link": link,

                        "imagem": imagem.get("src", "") if imagem else ""

                    })

                except Exception:
                    continue

            print(f"{self.name}: {len(resultados)} produtos encontrados.")

            return resultados

        finally:

            page.close()

            self.browser_manager.close()

    # ======================================================

    def product_link(self, item):

        for anchor in item.select("a[href]"):

            href = anchor.get("href", "")

            if href in ("", "#") or href.startswith("javascript:"):
                continue

            if "/sspa/click" in href:

                query = parse_qs(urlparse(href).query)
                destino = query.get("url", [""])[0]

                if destino:
                    href = unquote(destino)

            if "/dp/" not in href and "/gp/product/" not in href:
                continue

            return self.link(
                href,
                "https://www.amazon.com.br"
            )

        return ""
