from urllib.parse import quote_plus
import logging

from src.constants import TIMEOUT_WAIT_MEDIUM
from src.core.browser_manager import BrowserManager
from src.stores.base_store import BaseStore
import time

logger = logging.getLogger(__name__)


class Shopee(BaseStore):

    @property
    def name(self):
        return "Shopee"

    @property
    def base_url(self):
        return "https://shopee.com.br/search?keyword={}"

    # ======================================================

    def search(self, product):

        url = self.base_url.format(quote_plus(product))

        print(f"\n>>> {self.name}")
        print(f"Abrindo: {url}")
        # Tentar múltiplas vezes alternando entre stealth False/True para
        # reduzir falsos-positivos de bloqueio intermitente.
        attempts = [False, True, False]
        last_result = []
        for idx, stealth in enumerate(attempts, start=1):
            if idx > 1:
                # pequeno intervalo antes de tentar novamente
                time.sleep(1)
            resultados = self._search_url(url, stealth=stealth)

            if resultados is None:
                logger.warning(
                    f"Shopee: tentativa {idx} com stealth={stealth} retornou página de verificação."
                )
                print(f"{self.name}: tentativa {idx} com stealth={stealth} -> verify page")
                continue

            # Se encontrou resultados, retorna imediatamente
            if resultados:
                return resultados

            # guarda último resultado (mesmo vazio) para retorno ao final
            last_result = resultados

        return last_result or []

    # ======================================================

    def _search_url(self, url, stealth):

        resultados = []
        manager = BrowserManager(headless=True)
        page = manager.new_page(stealth=stealth)

        try:

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=90000
            )

            page.wait_for_timeout(TIMEOUT_WAIT_MEDIUM)

            if self.is_verify_page(page):
                return None

            cards = self._extract_cards(page, "a[href*='-i.']")

            if not cards:
                cards = self._extract_cards(page, "a[href*='/product/']")

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

                except Exception as e:
                    logger.debug(f"Erro ao processar item do Shopee: {str(e)}")
                    continue

            print(f"{self.name}: {len(resultados)} produtos encontrados.")

            return resultados

        finally:
            page.close()
            manager.close()

    # ======================================================

    def is_verify_page(self, page):

        current_url = (page.url or "").lower()

        if "/verify/traffic/error" in current_url:
            return True

        try:
            content = page.content().lower()
        except Exception:
            return False

        return (
            "verify/traffic/error" in content
            or "redirect_to_error_page" in content
        )

    # ======================================================

    def _extract_cards(self, page, selector):

        try:
            return page.locator(selector).evaluate_all(
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
        except Exception as e:
            logger.debug(f"Erro ao extrair cards do Shopee: {str(e)}")
            return []

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
