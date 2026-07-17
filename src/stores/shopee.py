from urllib.parse import quote_plus

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

        page = self.browser_manager.new_page(stealth=False)

        try:

            url = self.base_url.format(quote_plus(product))

            print(f"\n>>> {self.name}")
            print(f"Abrindo: {url}")

            page.goto(
                url,
                wait_until="load",
                timeout=90000
            )

            page.wait_for_timeout(15000)

            cards = page.locator("a[href*='-i.']").evaluate_all(
                """
                elements => elements.slice(0, 40).map(anchor => {
                    const image = Array.from(anchor.querySelectorAll("img"))
                        .find(img => img.src && img.src.includes("susercontent"));

                    return {
                        href: anchor.href || anchor.getAttribute("href") || "",
                        text: anchor.innerText || "",
                        image: image ? image.src : "",
                        imageAlt: image ? image.alt : ""
                    };
                })
                """
            )

            print(f"Produtos encontrados: {len(cards)}")

            vistos = set()

            for item in cards:

                try:

                    href = item.get("href", "")
                    link = self.link(href, "https://shopee.com.br")

                    if not link or link in vistos:
                        continue

                    vistos.add(link)

                    linhas = self.text_lines(item.get("text", ""))
                    titulo = self.extract_title(linhas, item.get("imageAlt", ""))
                    preco = self.extract_price(linhas)

                    if titulo and preco:

                        resultados.append({

                            "loja": self.name,
                            "titulo": titulo,
                            "preco": preco,
                            "link": link,
                            "imagem": item.get("image", "")

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

    def text_lines(self, text):

        return [
            line.strip()
            for line in (text or "").splitlines()
            if line.strip()
        ]

    # ======================================================

    def extract_title(self, lines, image_alt=""):

        for value in [image_alt, *lines]:

            value = " ".join((value or "").split()).strip()

            if len(value) < 12:
                continue

            if value == "flag-label" or "R$" in value:
                continue

            return value[:240]

        return ""

    # ======================================================

    def extract_price(self, lines):

        for index, line in enumerate(lines):

            if line == "R$" and index + 1 < len(lines):
                return self.price(lines[index + 1])

            if "R$" in line:
                return self.price(line)

        return ""
