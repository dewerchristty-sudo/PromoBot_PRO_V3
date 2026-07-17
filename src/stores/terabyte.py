import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from src.stores.base_store import BaseStore


class Terabyte(BaseStore):

    @property
    def name(self):
        return "Terabyte"

    @property
    def base_url(self):
        return "https://www.terabyteshop.com.br/busca?str={}"

    # ======================================================

    def search(self, product):

        resultados = []
        page = self.browser_manager.new_page()

        try:

            url = self.base_url.format(quote_plus(product))

            print(f"\n>>> {self.name}")
            print(f"Abrindo: {url}")

            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            soup = BeautifulSoup(page.content(), "lxml")
            vistos = set()

            for anchor in soup.select("a[href*='/produto/']"):

                try:

                    href = anchor.get("href", "")
                    titulo = anchor.get_text(" ", strip=True)

                    if not titulo or len(titulo) < 12:
                        continue

                    link = self.link(href, "https://www.terabyteshop.com.br")

                    if not link or link in vistos:
                        continue

                    vistos.add(link)

                    bloco = self.product_block(anchor)
                    preco = self.extract_price(bloco.get_text(" ", strip=True))
                    imagem = ""
                    img = bloco.select_one("img") if bloco else None

                    if img:
                        imagem = img.get("src") or img.get("data-src") or ""

                    resultados.append({
                        "loja": self.name,
                        "titulo": titulo,
                        "preco": preco,
                        "link": link,
                        "imagem": imagem,
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

    # ======================================================

    def product_block(self, anchor):

        bloco = anchor

        for _ in range(8):

            if not bloco.parent:
                break

            bloco = bloco.parent
            texto = bloco.get_text(" ", strip=True)

            if "R$" in texto and len(texto) > 80:
                return bloco

        return anchor.parent or anchor

    # ======================================================

    def extract_price(self, text):

        if not text:
            return ""

        match = re.search(r"por:\s*R\$\s*([\d\.]+,\d{2})", text, re.IGNORECASE)

        if match:
            return self.price(match.group(1))

        valores = re.findall(r"R\$\s*([\d\.]+,\d{2})", text)

        if not valores:
            return ""

        return self.price(valores[0])
