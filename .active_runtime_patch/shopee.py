from urllib.parse import quote_plus
from html import unescape
import logging
import re

from bs4 import BeautifulSoup

from src.constants import TIMEOUT_WAIT_MEDIUM
from src.core.browser_manager import BrowserManager
from src.stores.base_store import BaseStore
from src.scraper import Parser
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

    @staticmethod
    def normalize_price(raw_value):
        """Converte os formatos de preco usados pela Shopee para 12,34."""

        text = str(raw_value or "").strip()
        if not text:
            return ""

        text = re.sub(r"[^\d,.-]", "", text)
        if not text:
            return ""

        # A API da Shopee normalmente representa R$ 31,97 como 3197000
        # (cinco casas decimais implícitas).
        if re.fullmatch(r"\d+", text):
            number = int(text)
            if number >= 100000:
                return Parser.format_brl(number / 100000)
        return Parser.clean_price(text)

    @classmethod
    def prices_from_page(cls, soup):
        """Extrai preco atual e anterior dos JSONs internos da pagina."""

        current = ""
        old = ""
        current_patterns = (
            r'"price"\s*:\s*"?(\d+(?:[.,]\d+)?)"?',
            r'"price_min"\s*:\s*"?(\d+(?:[.,]\d+)?)"?',
        )
        old_patterns = (
            r'"price_before_discount"\s*:\s*"?(\d+(?:[.,]\d+)?)"?',
            r'"price_min_before_discount"\s*:\s*"?(\d+(?:[.,]\d+)?)"?',
        )

        for script in soup.select("script"):
            text = unescape(script.string or script.get_text() or "")
            # Alguns estados serializados escapam as aspas do JSON.
            text = text.replace('\\"', '"')
            if not current:
                for pattern in current_patterns:
                    match = re.search(pattern, text)
                    if match:
                        current = cls.normalize_price(match.group(1))
                        if current:
                            break
            if not old:
                for pattern in old_patterns:
                    match = re.search(pattern, text)
                    if match:
                        old = cls.normalize_price(match.group(1))
                        if old:
                            break
            if current and old:
                break

        return current, old

    # ======================================================

    @classmethod
    def old_price_from_visible_page(cls, page, current_price):
        """Le o valor riscado que a Shopee renderiza na area da oferta."""

        try:
            candidates = page.evaluate(
                """() => {
                    const values = [];
                    const nodes = document.querySelectorAll('body *');
                    for (const node of nodes) {
                        if (node.children.length > 0) continue;
                        const text = (node.textContent || '').trim();
                        if (!/R\\$\\s*[\\d.]+,\\d{2}/.test(text)) continue;
                        const style = getComputedStyle(node);
                        const tag = node.tagName.toLowerCase();
                        const crossed = style.textDecorationLine.includes('line-through')
                            || tag === 'del' || tag === 's';
                        const priceClass = String(node.className || '').toLowerCase();
                        if (crossed || /before|original|old-price|price-old/.test(priceClass)) {
                            values.push(text);
                        }
                    }
                    return values;
                }"""
            ) or []
        except Exception:
            return ""

        current = cls.price_number(current_price)
        for candidate in candidates:
            for raw_price in re.findall(r"R\$\s*([\d.]+,\d{2})", candidate):
                normalized = cls.normalize_price(raw_price)
                if cls.price_number(normalized) > current:
                    return normalized
        return ""

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

                        result = {

                            "loja": self.name,
                            "titulo": titulo,
                            "preco": preco,
                            "link": link,
                            "imagem": item.get("image", "")

                        }
                        old_price = self.normalize_price(
                            item.get("oldPrice", "")
                        )
                        if (
                            old_price
                            and self.price_number(old_price)
                            > self.price_number(preco)
                        ):
                            result["preco_antigo"] = old_price
                        resultados.append(result)

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
                    const oldPriceNode = Array.from(
                        anchor.querySelectorAll('del, s, [class*="before"], '
                            + '[class*="original"], [class*="old-price"]')
                    ).find(node => /R\\$|[\\d.,]+/.test(node.textContent || ''));

                    return {
                        href: anchor.href || anchor.getAttribute("href") || "",
                        text: anchor.innerText || "",
                        image: image ? image.src : "",
                        imageAlt: image ? image.alt : "",
                        oldPrice: oldPriceNode ? oldPriceNode.textContent : ""
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

    def product_from_url(self, url, debug=False):
        """Coleta um unico produto a partir da pagina da Shopee.

        Tenta duas configuracoes de navegador para contornar
        a pagina de verificacao da Shopee.

        Parameters
        ----------
        url : str
            URL do produto na Shopee.
        debug : bool, optional
            Se True, tenta abrir navegador visivel como ultima
            tentativa (para depuracao). Padrao False.
        """

        attempts = [
            {"headless": True, "stealth": True},
            {"headless": True, "stealth": False},
        ]

        if debug:
            attempts.append({"headless": False, "stealth": True})

        last_error = ""

        for attempt in attempts:
            headless = attempt["headless"]
            stealth = attempt["stealth"]

            manager = BrowserManager(headless=headless)
            page = manager.new_page(stealth=stealth)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(8000)

                verify_page = self.is_verify_page(page)

                import json

                content = page.content()
                soup = BeautifulSoup(content, "lxml")
                json_price, old_price_text = self.prices_from_page(soup)

                # Tenta obter via Open Graph
                og_title = soup.find("meta", property="og:title")
                og_image = soup.find("meta", property="og:image")
                og_price = soup.find("meta", property="product:price:amount")

                title_text = og_title.get("content", "").strip() if og_title else ""
                image_url = og_image.get("content", "").strip() if og_image else ""
                price_text = og_price.get("content", "").strip() if og_price else ""

                # Fallback: extrai do JSON interno da pagina
                if not title_text or not price_text:
                    for script in soup.select("script"):
                        text = script.string or ""
                        if '"product_name"' in text or '"name"' in text:
                            match = re.search(r'"product_name"\s*:\s*"([^"]+)"', text)
                            if match and not title_text:
                                title_text = match.group(1)
                            if not price_text:
                                match_price = re.search(r'"price"\s*:\s*([\d.]+)', text)
                                if match_price:
                                    price_text = match_price.group(1)
                            if title_text and price_text:
                                break

                # Fallback 2: JSON-LD
                if not title_text or not price_text:
                    for script in soup.select("script[type='application/ld+json']"):
                        try:
                            payload = json.loads(script.string or script.get_text() or "null")
                            candidates = payload if isinstance(payload, list) else [payload]
                            for candidate in candidates:
                                if isinstance(candidate, dict) and candidate.get("@type") == "Product":
                                    title_text = title_text or str(candidate.get("name") or "")
                                    candidate_image = candidate.get("image") or ""
                                    if isinstance(candidate_image, list):
                                        candidate_image = candidate_image[0] if candidate_image else ""
                                    image_url = image_url or str(candidate_image).strip()
                                    offers = candidate.get("offers") or {}
                                    if isinstance(offers, list):
                                        offers = offers[0] if offers else {}
                                    if isinstance(offers, dict):
                                        price_text = price_text or str(offers.get("price") or "")
                                    break
                        except Exception:
                            continue

                # Fallback 3: busca imagem via Playwright evaluate
                if not image_url:
                    try:
                        image_url = page.evaluate(
                            """() => {
                                const selectors = [
                                    'img[src*="susercontent"]',
                                    'img[class*="product"]',
                                    'img[class*="image"]',
                                    'div[class*="image"] img',
                                    'div[class*="product"] img'
                                ];
                                for (const sel of selectors) {
                                    const img = document.querySelector(sel);
                                    if (img && img.src && img.src.startsWith('http')) {
                                        return img.src;
                                    }
                                }
                                return '';
                            }"""
                        ) or ""
                    except Exception:
                        pass

                # Fallback 4: twitter:image
                if not image_url:
                    tw_image = (
                        soup.find("meta", property="twitter:image")
                        or soup.find("meta", attrs={"name": "twitter:image"})
                    )
                    if tw_image:
                        image_url = tw_image.get("content", "").strip()

                # Fallback 5: busca imageUrl em qualquer JSON interno
                if not image_url:
                    for script in soup.select("script"):
                        text = script.string or ""
                        for pattern in [
                            r'"imageUrl"\s*:\s*"([^"]+)"',
                            r'"image"\s*:\s*"([^"]+)"',
                        ]:
                            match = re.search(pattern, text)
                            if match:
                                candidate = match.group(1)
                                if candidate.startswith("http"):
                                    image_url = candidate
                                    break
                        if image_url:
                            break

                parsed_price = self.normalize_price(price_text or json_price)
                parsed_old_price = self.normalize_price(old_price_text)
                if not parsed_old_price:
                    parsed_old_price = self.old_price_from_visible_page(
                        page,
                        parsed_price,
                    )
                valid_image = image_url.startswith(("http://", "https://"))

                if verify_page and (
                    not title_text or not parsed_price or not valid_image
                ):
                    last_error = (
                        "A Shopee bloqueou o acesso com pagina de "
                        "verificacao. Tente novamente mais tarde ou "
                        "cadastre o produto manualmente informando "
                        "titulo, preco e link da imagem."
                    )
                    continue

                if not title_text:
                    last_error = (
                        "A Shopee nao retornou os dados do produto. "
                        "Abra o link no navegador e confirme que ele "
                        "leva diretamente ao produto."
                    )
                    continue

                product_data = {
                    "loja": self.name,
                    "titulo": title_text,
                    "preco": parsed_price,
                    "link": url,
                    "imagem": image_url,
                }
                if (
                    parsed_old_price
                    and self.price_number(parsed_old_price)
                    > self.price_number(parsed_price)
                ):
                    product_data["preco_antigo"] = parsed_old_price

                return product_data

            finally:
                page.close()
                manager.close()

        # Todas as tentativas falharam
        raise ValueError(last_error)

    # ======================================================

    def extract_price(self, lines):

        for index, line in enumerate(lines):

            if line == "R$" and index + 1 < len(lines):
                return self.price(lines[index + 1])

            if "R$" in line:
                return self.price(line)

        return ""

    @staticmethod
    def price_number(value):
        return Parser.price_to_float(value)
