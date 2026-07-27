from bs4 import BeautifulSoup
import json
from urllib.parse import parse_qs, quote, urljoin, urlparse
from pathlib import Path
import logging
import time
import unicodedata

from src.stores.base_store import BaseStore
from src.stores.mercado_livre_browser import MercadoLivrePersistentContext

logger = logging.getLogger(__name__)


class MercadoLivreBlockedError(RuntimeError):
    """Bloqueio externo controlado; o StoreManager preserva outras lojas."""


class MercadoLivre(BaseStore):

    offers_url = "https://www.mercadolivre.com.br/ofertas"
    card_selectors = (
        "li.ui-search-layout__item",
        "div.ui-search-result__wrapper",
        "div.poly-card",
        "div.andes-card.poly-card",
    )
    link_fallback_selectors = (
        "a.poly-component__title[href]",
        "a.ui-search-link[href]",
        "a[href*='produto.mercadolivre.com.br/MLB-']",
        "a[href*='mercadolivre.com.br/p/MLB']",
        "a[href*='/up/MLBU']",
    )
    block_markers = (
        "account-verification", "captcha", "não sou um robô",
        "nao sou um robo", "access denied", "página de segurança",
        "pagina de seguranca",
    )

    def __init__(self, browser_manager=None):
        if (
            browser_manager is None
            and MercadoLivrePersistentContext.enabled()
        ):
            browser_manager = MercadoLivrePersistentContext()
        super().__init__(browser_manager)

    @property
    def name(self):
        return "Mercado Livre"

    @property
    def base_url(self):
        return "https://lista.mercadolivre.com.br/{}"

    # ======================================================

    def search(self, product):
        page = self.browser_manager.new_page()
        try:
            started = time.perf_counter()
            url = self.base_url.format(quote(
                str(product or "").strip().replace(" ", "-"), safe="-"
            ))

            print(f"\n>>> {self.name}")
            print(f"Abrindo: {url}")

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )
            page.wait_for_timeout(4500)
            for _ in range(3):
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(500)
            html = page.content()
            self.save_diagnostic(
                html, url, page.url, page.title(),
                response.status if response else None,
            )
            if self.block_reason(page.url, page.title(), html):
                raise MercadoLivreBlockedError(
                    "Mercado Livre bloqueou a coleta com página de "
                    f"verificação: {page.url}"
                )
            soup = BeautifulSoup(html, "lxml")
            produtos, selector_counts = self.find_cards(soup)

            if not produtos and self.is_generic_offers_query(product):
                print(
                    "Busca comum indisponivel; consultando a pagina publica "
                    "de ofertas do Mercado Livre."
                )
                page.goto(
                    self.offers_url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )
                page.wait_for_timeout(3000)
                html = page.content()
                if self.block_reason(page.url, page.title(), html):
                    raise MercadoLivreBlockedError(
                        "Mercado Livre bloqueou também a página pública "
                        "de ofertas."
                    )
                soup = BeautifulSoup(html, "lxml")
                produtos, selector_counts = self.find_cards(soup)
            elif not produtos:
                raise RuntimeError(
                    "Mercado Livre retornou página sem cards e sem marcador "
                    "de bloqueio. Consulte logs/mercado_livre_diagnostico.*"
                )

            resultados = self.parse_cards(produtos)

            print(
                f"Cards brutos: {len(produtos)} | validos e unicos: "
                f"{len(resultados)} | seletores: {selector_counts} | "
                f"tempo: {time.perf_counter() - started:.2f}s"
            )
            return resultados

        finally:

            page.close()

            self.browser_manager.close()

    def find_cards(self, soup):
        counts = {
            selector: len(soup.select(selector))
            for selector in self.card_selectors
        }
        for selector in self.card_selectors:
            cards = soup.select(selector)
            if cards:
                return cards, counts
        cards = []
        seen = set()
        for selector in self.link_fallback_selectors:
            links = soup.select(selector)
            counts[selector] = len(links)
            for anchor in links:
                card = (
                    anchor.find_parent("li")
                    or anchor.find_parent("div", class_=lambda value: value and (
                        "card" in " ".join(value).casefold()
                        if isinstance(value, list) else "card" in value.casefold()
                    ))
                    or anchor.parent
                )
                marker = id(card)
                if card and marker not in seen:
                    seen.add(marker)
                    cards.append(card)
        return cards, counts

    def parse_cards(self, cards, limit=20):
        results = []
        seen_links = set()
        for item in cards:
            try:
                title = (
                    item.select_one(".poly-component__title")
                    or item.select_one(".ui-search-item__title")
                    or item.select_one("h2")
                    or item.select_one("h3")
                )
                title_text = title.get_text(" ", strip=True) if title else ""
                price_text = self.current_price_text(item)
                link = self.product_link(item)
                if not title_text or not price_text or not link:
                    continue
                if link in seen_links:
                    continue
                seen_links.add(link)
                image = item.select_one("img")
                results.append({
                    "loja": self.name,
                    "titulo": title_text,
                    "preco": self.price(price_text),
                    "link": link,
                    "imagem": self.image_url(image),
                })
                if len(results) >= limit:
                    break
            except Exception as error:
                logger.debug("Card Mercado Livre inválido: %s", error)
        return results

    @staticmethod
    def current_price_text(item):
        amount = (
            item.select_one(
                ".poly-price__current .andes-money-amount:not("
                ".andes-money-amount--previous)"
            )
            or item.select_one(
                ".ui-search-price__second-line .andes-money-amount"
            )
            or item.select_one(
                ".andes-money-amount:not(.andes-money-amount--previous)"
            )
        )
        if not amount:
            return ""
        fraction = amount.select_one(".andes-money-amount__fraction")
        cents = amount.select_one(".andes-money-amount__cents")
        if not fraction:
            return ""
        value = fraction.get_text(strip=True)
        if cents:
            value += "," + cents.get_text(strip=True).zfill(2)
        return value

    @staticmethod
    def image_url(image):
        if not image:
            return ""
        for attribute in ("data-src", "data-lazy-src", "src"):
            value = str(image.get(attribute, "") or "").strip()
            if value.startswith("http"):
                return value
        srcset = str(image.get("srcset", "") or "")
        return srcset.split()[0] if srcset.startswith("http") else ""

    @classmethod
    def block_reason(cls, final_url, title, html):
        text = f"{final_url}\n{title}\n{html[:200000]}".casefold()
        return next((marker for marker in cls.block_markers if marker in text), "")

    @classmethod
    def save_diagnostic(cls, html, requested, final, title, status):
        Path("logs").mkdir(exist_ok=True)
        Path("logs/mercado_livre_diagnostico.html").write_text(
            html, encoding="utf-8"
        )
        Path("logs/mercado_livre_diagnostico.txt").write_text(
            "\n".join((
                f"requested_url={requested}",
                f"final_url={final}",
                f"redirected={requested.rstrip('/') != final.rstrip('/')}",
                f"status={status}",
                f"title={title}",
                f"block_reason={cls.block_reason(final, title, html)}",
                *(
                    f"{selector}={html.count(selector.split('.')[-1])}"
                    for selector in cls.card_selectors
                ),
            )) + "\n",
            encoding="utf-8",
        )

    # ======================================================

    @staticmethod
    def is_generic_offers_query(product):

        normalized = unicodedata.normalize(
            "NFKD",
            str(product or "").casefold()
        )
        normalized = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        words = set(normalized.replace("-", " ").split())

        return bool(words) and words <= {
            "oferta",
            "ofertas",
            "promocao",
            "promocoes",
            "do",
            "da",
            "de",
            "dia",
        }

    # ======================================================

    def product_from_url(self, url):
        """Coleta um unico produto a partir da pagina do Mercado Livre."""

        page = self.browser_manager.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            soup = BeautifulSoup(page.content(), "lxml")

            title = soup.select_one("h1.ui-pdp-title")
            price = soup.select_one(".andes-money-amount__fraction")
            image = soup.select_one("meta[property='og:image']")
            breadcrumb = self.breadcrumb_from_soup(soup)

            title_text = title.get_text(strip=True) if title else ""
            price_text = price.get_text(strip=True) if price else ""
            image_url = image.get("content", "").strip() if image else ""

            if not title_text:
                raise ValueError(
                    "O Mercado Livre nao retornou os dados do produto. "
                    "Abra o link no navegador e confirme que ele leva "
                    "diretamente ao produto."
                )

            product = {
                "loja": self.name,
                "titulo": title_text,
                "preco": self.price(price_text),
                "link": url,
                "imagem": image_url,
            }
            if breadcrumb:
                product["breadcrumb"] = " > ".join(breadcrumb)
                product["categoria_original"] = breadcrumb[-1]
                logger.info(
                    "mercado livre category extraction: url=%s "
                    "breadcrumb=%s original_category=%s source=PRODUCT_PAGE",
                    url,
                    product["breadcrumb"],
                    product["categoria_original"],
                )
            else:
                product["breadcrumb"] = ""
                product["categoria_original"] = ""
                logger.info(
                    "mercado livre category extraction: url=%s "
                    "breadcrumb=NOT_PRESENT original_category=NOT_PRESENT "
                    "source=PRODUCT_PAGE",
                    url,
                )
            return product

        finally:
            page.close()
            self.browser_manager.close()

    @staticmethod
    def breadcrumb_from_soup(soup):
        """Lê apenas a taxonomia exibida na página do Mercado Livre."""

        selectors = (
            ".andes-breadcrumb__link",
            ".andes-breadcrumb__item",
            "nav[aria-label*='breadcrumb' i] a",
            "nav[aria-label*='migalha' i] a",
            "[data-testid='breadcrumb'] a",
        )
        for selector in selectors:
            values = []
            for element in soup.select(selector):
                value = element.get_text(" ", strip=True)
                if value and value not in values:
                    values.append(value)
            if values:
                return tuple(values)
        for script in soup.select("script[type='application/ld+json']"):
            try:
                payload = json.loads(
                    script.string or script.get_text() or "null"
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            nodes = payload if isinstance(payload, list) else [payload]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                if isinstance(node.get("@graph"), list):
                    nodes.extend(node["@graph"])
                if node.get("@type") != "BreadcrumbList":
                    continue
                values = []
                for entry in node.get("itemListElement") or ():
                    if not isinstance(entry, dict):
                        continue
                    item = entry.get("item") or {}
                    value = (
                        entry.get("name")
                        or (item.get("name") if isinstance(item, dict) else "")
                    )
                    if value and str(value) not in values:
                        values.append(str(value))
                if values:
                    return tuple(values)
        return ()

    # ======================================================

    def product_link(self, item):

        for anchor in item.select("a[href]"):

            href = anchor.get("href", "")

            if not href:
                continue

            href = urljoin("https://www.mercadolivre.com.br", href)
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

            direct_path = parsed.path.lower()
            is_direct_product = (
                "/p/mlb" in direct_path
                or "/up/mlbu" in direct_path
                or (
                    "produto.mercadolivre.com.br" in parsed.netloc.lower()
                    and "/mlb-" in direct_path
                )
            )
            if (
                is_direct_product
                and "mercadolivre.com.br" in parsed.netloc.lower()
                and "clicks/external" not in href
            ):
                return self.link(href, "https://www.mercadolivre.com.br")

        return ""
