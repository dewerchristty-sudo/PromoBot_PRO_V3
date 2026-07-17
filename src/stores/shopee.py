from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from src.stores.base_store import BaseStore


class Shopee(BaseStore):

    @property
    def name(self):
        return "Shopee"

    @property
    def base_url(self):
        return "https://shopee.com.br/search?keyword={}"

    # ======================================================

    def search(self, product):

        resultados = []

        page = self.browser_manager.new_page()

        try:

            url = self.base_url.format(quote_plus(product))

            print(f"\n>>> {self.name}")
            print(f"Abrindo: {url}")

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(7000)

            soup = BeautifulSoup(
                page.content(),
                "lxml"
            )

            links = soup.select("a[href*='-i.'], a[href*='/product/']")

            print(f"Produtos encontrados: {len(links)}")

            vistos = set()

            for item in links[:40]:

                try:

                    href = item.get("href", "")
                    link = self.link(href, "https://shopee.com.br")

                    if not link or link in vistos:
                        continue

                    vistos.add(link)

                    titulo = item.get("title", "")

                    if not titulo:
                        candidatos = [
                            texto.strip()
                            for texto in item.stripped_strings
                            if len(texto.strip()) > 12
                        ]

                        titulo = candidatos[0] if candidatos else ""

                    preco = ""

                    for texto in item.stripped_strings:

                        texto_limpo = texto.strip()

                        if "R$" in texto_limpo:
                            preco = self.price(texto_limpo)
                            break

                    imagem = ""
                    img = item.select_one("img")

                    if img:
                        imagem = (
                            img.get("src")
                            or img.get("data-src")
                            or ""
                        )

                    if titulo:

                        resultados.append({

                            "loja": self.name,
                            "titulo": titulo,
                            "preco": preco,
                            "link": link,
                            "imagem": imagem

                        })

                    if len(resultados) >= 20:
                        break

                except Exception:
                    continue

            print(f"{self.name}: {len(resultados)} produtos encontrados.")

            return resultados

        finally:

            page.close()

            self.browser_manager.close()
