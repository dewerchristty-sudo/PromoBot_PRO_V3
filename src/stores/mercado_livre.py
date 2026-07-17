from bs4 import BeautifulSoup
from urllib.parse import parse_qs
from urllib.parse import urlparse

from src.stores.base_store import BaseStore


class MercadoLivre(BaseStore):

    @property
    def name(self):
        return "Mercado Livre"

    @property
    def base_url(self):
        return "https://lista.mercadolivre.com.br/{}"

    # ======================================================

    def search(self, product):

        resultados = []

        page = self.browser_manager.new_page()

        try:

            url = self.base_url.format(
                product.replace(" ", "-")
            )

            print(f"\n>>> {self.name}")
            print(f"Abrindo: {url}")

            page.goto(
                url,
                wait_until="networkidle",
                timeout=60000
            )

            page.wait_for_timeout(5000)

            soup = BeautifulSoup(
                page.content(),
                "lxml"
            )

            produtos = soup.select(
                "li.ui-search-layout__item"
            )

            print(
                f"Produtos encontrados: {len(produtos)}"
            )

            for item in produtos[:20]:

                try:

                    titulo = item.select_one("h3")

                    preco = item.select_one(
                        ".andes-money-amount__fraction"
                    )

                    link = self.product_link(item)

                    imagem = item.select_one("img")

                    titulo_texto = (
                        titulo.get_text(strip=True)
                        if titulo else ""
                    )

                    if not titulo_texto or not link:
                        continue

                    resultados.append({

                        "loja": self.name,

                        "titulo": titulo_texto,

                        "preco": self.price(
                            preco.get_text(strip=True)
                            if preco else ""
                        ),

                        "link": link,

                        "imagem": (
                            imagem.get("src")
                            or imagem.get("data-src")
                            or ""
                        ) if imagem else ""

                    })

                except Exception:
                    continue

            print(
                f"{self.name}: {len(resultados)} produtos encontrados."
            )

            return resultados

        finally:

            page.close()

            self.browser_manager.close()

    # ======================================================

    def product_link(self, item):

        for anchor in item.select("a[href]"):

            href = anchor.get("href", "")

            if not href:
                continue

            if "mercadolivre.com.br" in href and "clicks/external" not in href:
                return self.link(href, "https://www.mercadolivre.com.br")

            parsed = urlparse(href)
            query = parse_qs(parsed.query)
            produto_id = ""

            filtros = query.get("pdp_filters", [""])[0]

            if "item_id:" in filtros:
                produto_id = filtros.split("item_id:", 1)[1].split("|", 1)[0]

            if not produto_id:
                produto_id = query.get("wid", [""])[0]

            if produto_id.startswith("MLB"):
                return f"https://produto.mercadolivre.com.br/{produto_id[:3]}-{produto_id[3:]}"

        return ""
