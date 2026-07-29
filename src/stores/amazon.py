from bs4 import BeautifulSoup
from dataclasses import dataclass
import json
import logging
import re
from urllib.parse import parse_qs
from urllib.parse import unquote
from urllib.parse import urlparse

from src.stores.base_store import BaseStore


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AmazonPreviousPrice:
    value: str | None
    source: str
    reason: str


class Amazon(BaseStore):

    CURRENT_PRICE_SELECTORS = (
        "#corePrice_feature_div .priceToPay .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
        "#corePrice_feature_div .a-price:not(.a-text-price) .a-offscreen",
        "#corePriceDisplay_desktop_feature_div "
        ".a-price:not(.a-text-price) .a-offscreen",
        "#price_inside_buybox",
        "#newBuyBoxPrice",
        ".a-price:not(.a-text-price) .a-offscreen",
    )
    NON_FINAL_PRICE_MARKERS = (
        "parcela",
        "x de r$",
        "por mês",
        "/mês",
        "frete",
        "assinatura",
        "assine e economize",
        "subscribe",
        "preço prime",
    )

    @staticmethod
    def normalize_price(raw_value):
        """Normaliza valores Amazon para o formato brasileiro 12,34."""

        text = re.sub(r"[^\d,.-]", "", str(raw_value or "").strip())
        if not text:
            return ""

        if "," in text:
            normalized = text.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d+\.\d{1,2}", text):
            normalized = text
        else:
            normalized = text.replace(".", "")

        try:
            return f"{float(normalized):.2f}".replace(".", ",")
        except ValueError:
            return ""

    @staticmethod
    def price_number(value):
        text = str(value or "").replace(".", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return 0.0

    @classmethod
    def current_price_from_soup(cls, soup):
        """Seleciona o valor final à vista e rejeita preços auxiliares."""

        for selector in cls.CURRENT_PRICE_SELECTORS:
            for element in soup.select(selector):
                contexts = [element]
                parent = element.parent
                for _ in range(3):
                    if not parent or parent.name in {"body", "html"}:
                        break
                    contexts.append(parent)
                    parent = parent.parent
                context = " ".join(
                    node.get_text(" ", strip=True)
                    for node in contexts
                ).casefold()
                if any(marker in context for marker in cls.NON_FINAL_PRICE_MARKERS):
                    continue
                raw = (
                    element.get("aria-label")
                    or element.get("content")
                    or element.get_text(" ", strip=True)
                )
                normalized = cls.normalize_price(raw)
                if cls.price_number(normalized) > 0:
                    return normalized
        return ""

    @classmethod
    def explicit_previous_price_candidates(cls, soup):
        selectors = (
            "#basisPrice .a-offscreen",
            ".basisPrice .a-offscreen",
            "#corePriceDisplay_desktop_feature_div "
            ".a-price.a-text-price .a-offscreen",
            "#corePrice_feature_div .a-price.a-text-price .a-offscreen",
            ".a-price.a-text-price .a-offscreen",
            ".a-text-price .a-offscreen",
            "del .a-offscreen",
            "s .a-offscreen",
            "[data-a-strike='true'] .a-offscreen",
        )
        for selector in selectors:
            for element in soup.select(selector):
                context = element.parent.get_text(" ", strip=True).casefold()
                if any(word in context for word in (
                    "parcela", "frete", "cupom", "economize", "economia",
                    "mensal", "pix",
                )):
                    continue
                raw = (
                    element.get("aria-label")
                    or element.get("content")
                    or element.get_text(" ", strip=True)
                )
                yield raw

    @classmethod
    def structured_previous_price_candidates(cls, soup):
        keys = (
            "listPrice", "list_price", "wasPrice", "was_price",
            "priceBeforeDiscount", "price_before_discount", "highPrice",
        )
        for script in soup.select("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.string or script.get_text() or "null")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            stack = payload if isinstance(payload, list) else [payload]
            while stack:
                node = stack.pop()
                if isinstance(node, list):
                    stack.extend(node)
                elif isinstance(node, dict):
                    node_type = str(node.get("@type") or "")
                    if node_type in {"Product", "Offer", "AggregateOffer", ""}:
                        for key in keys:
                            if node.get(key) not in (None, ""):
                                yield node[key]
                    stack.extend(
                        value for value in node.values()
                        if isinstance(value, (dict, list))
                    )

    @classmethod
    def embedded_previous_price_candidates(cls, soup):
        keys = (
            "basisPrice", "listPrice", "wasPrice", "priceBeforeDiscount",
        )
        pattern = re.compile(
            rf'"(?:{"|".join(keys)})"\s*:\s*'
            r'(?:\{[^{}]{0,300}?"(?:amount|value)"\s*:\s*)?'
            r'(?:"(?:R\$\s*)?([\d.,]+)"|([\d.]+))',
            re.IGNORECASE,
        )
        for script in soup.select("script:not([type='application/ld+json'])"):
            text = script.string or script.get_text() or ""
            for match in pattern.finditer(text):
                yield next(value for value in match.groups() if value)

    @classmethod
    def validate_previous_price(cls, raw_value, current_price):
        candidate = cls.normalize_price(raw_value)
        if not candidate:
            return None, "previous_price_invalid"
        if cls.price_number(candidate) <= cls.price_number(current_price):
            return None, "previous_price_not_greater_than_current"
        return candidate, "accepted"

    @classmethod
    def previous_price_from_soup(
        cls, soup, current_price, explicit_source="PRODUCT_PAGE"
    ):
        """Extrai somente um preço anterior comprovadamente maior que o atual."""

        if cls.price_number(current_price) <= 0:
            return AmazonPreviousPrice(
                None, "NOT_AVAILABLE", "current_price_invalid"
            )
        strategies = (
            (
                explicit_source,
                cls.explicit_previous_price_candidates(soup),
            ),
            (
                "STRUCTURED_DATA",
                cls.structured_previous_price_candidates(soup),
            ),
            (
                "EMBEDDED_JSON",
                cls.embedded_previous_price_candidates(soup),
            ),
        )
        last_reason = "previous_price_not_present"
        for source, candidates in strategies:
            for raw_value in candidates:
                candidate, reason = cls.validate_previous_price(
                    raw_value, current_price
                )
                if candidate:
                    return AmazonPreviousPrice(candidate, source, reason)
                last_reason = reason
        return AmazonPreviousPrice(None, "NOT_AVAILABLE", last_reason)

    @classmethod
    def old_price_from_soup(cls, soup, current_price):
        """Interface legada preservada."""

        return cls.previous_price_from_soup(
            soup, current_price
        ).value or ""

    @staticmethod
    def log_price_extraction(current_price, extraction):
        logger.info(
            "amazon price extraction: current_price=%s previous_price=%s "
            "previous_price_source=%s reason=%s",
            current_price,
            extraction.value,
            extraction.source,
            extraction.reason,
        )

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
                        item.select_one(
                            ".a-price:not(.a-text-price) .a-offscreen"
                        )
                        or item.select_one(".a-price-whole")
                    )
                    link = self.product_link(item)
                    imagem = item.select_one("img")

                    titulo_texto = titulo.get_text(strip=True) if titulo else ""

                    if not titulo_texto or not link:
                        continue

                    preco_texto = self.normalize_price(
                        preco.get_text(strip=True) if preco else ""
                    )
                    extraction = self.previous_price_from_soup(
                        item, preco_texto, explicit_source="SEARCH_CARD"
                    )
                    self.log_price_extraction(preco_texto, extraction)

                    resultado = {

                        "loja": self.name,

                        "titulo": titulo_texto,

                        "preco": preco_texto,

                        "link": link,

                        "imagem": imagem.get("src", "") if imagem else ""

                    }
                    resultado["previous_price"] = extraction.value
                    resultado["previous_price_source"] = extraction.source
                    if extraction.value:
                        resultado["preco_antigo"] = extraction.value

                    resultados.append(resultado)

                except Exception:
                    continue

            print(f"{self.name}: {len(resultados)} produtos encontrados.")

            return resultados

        finally:

            page.close()

            self.browser_manager.close()

    # ======================================================

    def product_from_url(self, url):
        """Coleta um unico produto a partir da pagina /dp/ da Amazon."""

        page = self.browser_manager.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            return self.product_data_from_html(page.content(), url)

        finally:
            page.close()
            self.browser_manager.close()

    def product_data_from_html(self, html, url):
        """Extrai produto do HTML visivel, Open Graph ou JSON-LD."""

        soup = BeautifulSoup(html, "lxml")

        title = soup.select_one("#productTitle")
        image = soup.select_one("#landingImage") or soup.select_one("#imgBlkFront")

        title_text = title.get_text(" ", strip=True) if title else ""
        price_text = self.current_price_from_soup(soup)
        image_url = ""
        if image:
            image_url = image.get("data-old-hires") or image.get("src") or ""

        og_title = soup.select_one("meta[property='og:title']")
        og_image = soup.select_one("meta[property='og:image']")
        og_price = soup.select_one("meta[property='product:price:amount']")
        title_text = title_text or (og_title.get("content", "").strip() if og_title else "")
        image_url = image_url or (og_image.get("content", "").strip() if og_image else "")
        price_text = price_text or (og_price.get("content", "").strip() if og_price else "")

        for script in soup.select("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.string or script.get_text() or "null")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            candidates = payload if isinstance(payload, list) else [payload]
            expanded = []
            for candidate in candidates:
                if isinstance(candidate, dict) and isinstance(candidate.get("@graph"), list):
                    expanded.extend(candidate["@graph"])
                else:
                    expanded.append(candidate)
            for candidate in expanded:
                if not isinstance(candidate, dict) or candidate.get("@type") != "Product":
                    continue
                title_text = title_text or str(candidate.get("name") or "").strip()
                candidate_image = candidate.get("image") or ""
                if isinstance(candidate_image, list):
                    candidate_image = candidate_image[0] if candidate_image else ""
                image_url = image_url or str(candidate_image).strip()
                offers = candidate.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if isinstance(offers, dict):
                    price_text = price_text or str(offers.get("price") or "").strip()
                break

        if not title_text:
            raise ValueError(
                "A Amazon nao retornou os dados do produto. Abra o link no "
                "navegador e confirme que ele leva diretamente ao produto."
            )

        normalized_price = self.normalize_price(price_text)
        extraction = self.previous_price_from_soup(
            soup, normalized_price, explicit_source="PRODUCT_PAGE"
        )
        self.log_price_extraction(normalized_price, extraction)

        product_data = {
            "loja": self.name,
            "titulo": title_text,
            "preco": normalized_price,
            "link": url,
            "imagem": image_url,
            "previous_price": extraction.value,
            "previous_price_source": extraction.source,
            "previous_price_reason": extraction.reason,
        }
        if extraction.value:
            product_data["preco_antigo"] = extraction.value

        return product_data

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
