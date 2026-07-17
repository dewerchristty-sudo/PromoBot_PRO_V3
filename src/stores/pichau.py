import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from src.stores.base_store import BaseStore


class Pichau(BaseStore):

    @property
    def name(self):
        return "Pichau"

    @property
    def base_url(self):
        return "https://www.pichau.com.br/search?q={}"

    # ======================================================

    def search(self, product):

        resultados = []
        page = self.browser_manager.new_page()

        try:

            url = self.base_url.format(quote_plus(product))

            print(f"\n>>> {self.name}")
            print(f"Abrindo: {url}")

            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000)

            soup = BeautifulSoup(page.content(), "lxml")
            body_text = soup.get_text(" ", strip=True).lower()

            if "site em manutenção" in body_text or "site em manutencao" in body_text:
                print(f"{self.name}: site em manutencao no momento.")
                return []

            vistos = set()

            for anchor in soup.select("a[href]"):

                try:

                    href = anchor.get("href", "")

                    if not self.is_product_link(href):
                        continue

                    titulo = anchor.get_text(" ", strip=True)
                    bloco = self.product_block(anchor)

                    if not titulo or len(titulo) < 12:
                        titulo = self.extract_title(bloco)

                    if not titulo or len(titulo) < 12:
                        continue

                    link = self.link(href, "https://www.pichau.com.br")

                    if not link or link in vistos:
                        continue

                    vistos.add(link)

                    texto_bloco = bloco.get_text(" ", strip=True)
                    preco = self.extract_price(texto_bloco)
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

    def is_product_link(self, href):

        if not href:
            return False

        ignorar = (
            "/search",
            "/login",
            "/account",
            "/cart",
            "/checkout",
            "/categoria",
            "/departamento",
        )

        if any(parte in href for parte in ignorar):
            return False

        return (
            "/produto/" in href
            or "/product/" in href
            or "/p/" in href
        )

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

    def extract_title(self, bloco):

        for seletor in ("h2", "h3", "h4", "[class*='title']", "[class*='name']"):

            elemento = bloco.select_one(seletor) if bloco else None

            if elemento:
                texto = elemento.get_text(" ", strip=True)

                if len(texto) >= 12:
                    return texto

        return ""

    # ======================================================

    def extract_price(self, text):

        valores = re.findall(r"R\$\s*([\d\.]+,\d{2})", text or "")

        if not valores:
            return ""

        return self.price(valores[0])
