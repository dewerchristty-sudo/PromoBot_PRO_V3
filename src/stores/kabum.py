import re

from src.stores.base_store import BaseStore
from src.scraper import Locator


class Kabum(BaseStore):

    @property
    def name(self):
        return "Kabum"

    @property
    def base_url(self):
        return "https://www.kabum.com.br/busca/{}"

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

            page.wait_for_timeout(4000)

            produtos = Locator.all(
                page,
                "a[href*='/produto/']"
            )

            total = produtos.count()

            print(f"Produtos encontrados: {total}")

            for i in range(min(total, 20)):

                try:

                    item = produtos.nth(i)

                    titulo = ""
                    preco = ""
                    imagem = ""

                    spans = item.locator("span")

                    for j in range(spans.count()):

                        texto = self.text(
                            spans.nth(j)
                        )

                        if not texto:
                            continue

                        if len(texto) > 30 and titulo == "":
                            titulo = texto

                        if re.fullmatch(
                            r"\d{1,3}(\.\d{3})*,\d{2}",
                            texto
                        ):
                            preco = texto

                    imgs = item.locator("img")

                    if imgs.count():

                        imagem = Locator.attribute(
                            imgs.first,
                            "src"
                        )

                    href = Locator.attribute(
                        item,
                        "href"
                    )

                    href = self.link(
                        href,
                        "https://www.kabum.com.br"
                    )

                    if titulo:

                        resultados.append({

                            "loja": self.name,
                            "titulo": titulo,
                            "preco": preco,
                            "link": href,
                            "imagem": imagem

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