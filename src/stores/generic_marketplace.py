import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from src.stores.base_store import BaseStore


class GenericMarketplace(BaseStore):

    store_name = ""
    search_url = ""
    base_domain = ""
    product_markers = ()
    ignore_markers = ()

    @property
    def name(self):
        return self.store_name

    @property
    def base_url(self):
        return self.search_url

    def search(self, product):

        resultados = []
        page = self.browser_manager.new_page()

        try:

            url = self.base_url.format(quote_plus(product))

            print(f"\n>>> {self.name}")
            print(f"Abrindo: {url}")

            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(7000)

            soup = BeautifulSoup(page.content(), "lxml")
            vistos = set()

            for anchor in soup.select("a[href]"):

                try:

                    href = anchor.get("href", "")

                    if not self.is_product_link(href):
                        continue

                    bloco = self.product_block(anchor)
                    titulo = self.extract_title(anchor, bloco)

                    if not titulo:
                        continue

                    link = self.link(href, self.base_domain)

                    if not link or link in vistos:
                        continue

                    vistos.add(link)

                    texto_bloco = bloco.get_text(" ", strip=True)
                    preco = self.extract_price(texto_bloco)

                    if not preco:
                        continue

                    imagem = ""
                    img = anchor.select_one("img")

                    if img is None and bloco:
                        img = bloco.select_one("img")

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

    def is_product_link(self, href):

        if not href:
            return False

        if any(marker in href for marker in self.ignore_markers):
            return False

        return any(marker in href for marker in self.product_markers)

    def product_block(self, anchor):

        bloco = anchor

        for _ in range(9):

            if not bloco.parent:
                break

            bloco = bloco.parent
            texto = bloco.get_text(" ", strip=True)

            if "R$" in texto and len(texto) > 80:
                return bloco

        return anchor.parent or anchor

    def extract_title(self, anchor, bloco):

        candidatos = [
            anchor.get("title", ""),
            anchor.get("aria-label", ""),
            anchor.get_text(" ", strip=True),
        ]

        for seletor in ("h2", "h3", "h4", "[class*='title']", "[class*='name']"):

            elemento = bloco.select_one(seletor) if bloco else None

            if elemento:
                candidatos.append(elemento.get_text(" ", strip=True))

        for texto in candidatos:

            texto = self.text_value(texto)

            if len(texto) >= 12 and "R$" not in texto:
                return texto[:240]

        return ""

    def extract_price(self, text):

        pix = re.search(
            r"R\$\s*([\d\.]+,\d{2})\s*(?:no\s*)?Pix",
            text or "",
            re.IGNORECASE
        )

        if pix:
            return self.price(pix.group(1))

        valores = re.findall(r"R\$\s*([\d\.]+,\d{2})", text or "")

        if not valores:
            return ""

        return self.price(valores[0])

    def text_value(self, text):

        return " ".join((text or "").split()).strip()
