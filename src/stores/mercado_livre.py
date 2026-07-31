from bs4 import BeautifulSoup
from dataclasses import dataclass
from enum import Enum
import json
from urllib.parse import parse_qs, quote, urljoin, urlparse
from pathlib import Path
import logging
import re
import time
import unicodedata
import requests

from src.stores.base_store import BaseStore
from src.stores.mercado_livre_browser import MercadoLivrePersistentContext
from src.scraper import Parser

logger = logging.getLogger(__name__)


class MercadoLivreBlockedError(RuntimeError):
    """Bloqueio externo controlado; o StoreManager preserva outras lojas."""


class MercadoLivreIdentityType(str, Enum):
    ITEM = "ITEM"
    CATALOGO = "CATALOGO"
    SOCIAL = "SOCIAL"
    DESCONHECIDO = "DESCONHECIDO"


@dataclass(frozen=True)
class MercadoLivreIdentity:
    tipo: MercadoLivreIdentityType
    id_item: str = ""
    id_catalogo: str = ""
    url_origem: str = ""
    url_final: str = ""
    fonte_da_identidade: str = ""

    def with_final_url(self, url):
        return MercadoLivreIdentity(
            tipo=self.tipo,
            id_item=self.id_item,
            id_catalogo=self.id_catalogo,
            url_origem=self.url_origem,
            url_final=str(url or ""),
            fonte_da_identidade=self.fonte_da_identidade,
        )


class MercadoLivreIdentityError(ValueError):
    classification = "FALHA_TECNICA"


class MercadoLivreAmbiguousIdentity(MercadoLivreIdentityError):
    classification = "IDENTIDADE_AMBIGUA"


class MercadoLivreUnavailableError(MercadoLivreIdentityError):
    classification = "ANUNCIO_INDISPONIVEL"


class MercadoLivre(BaseStore):

    api_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
        ),
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
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
        "a[href*='produto.mercadolivre.com.br/MLBU-']",
        "a[href*='mercadolivre.com.br/p/MLB']",
        "a[href*='mercadolivre.com.br/p/MLBU']",
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
            self.close(page)

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
            origin_identity = self.identity_from_url(url, url_origem=url)
            response = page.goto(
                url, wait_until="domcontentloaded", timeout=60000
            )
            page.wait_for_timeout(3000)
            final_url = str(page.url or url)
            html = page.content()
            status = response.status if response else None
            final_identity = self.identity_from_url(
                final_url,
                url_origem=url,
                url_final=final_url,
            )

            if final_identity.tipo == MercadoLivreIdentityType.SOCIAL:
                main_url = self.primary_social_product_url(html, final_url)
                response = page.goto(
                    main_url, wait_until="domcontentloaded", timeout=60000
                )
                page.wait_for_timeout(3000)
                final_url = str(page.url or main_url)
                html = page.content()
                status = response.status if response else None
                final_identity = self.identity_from_url(
                    final_url,
                    url_origem=url,
                    url_final=final_url,
                )

            block = self.block_reason(final_url, page.title(), html)
            if block:
                raise MercadoLivreBlockedError(
                    "BLOQUEIO_MERCADO_LIVRE: o Mercado Livre bloqueou "
                    "temporariamente a consulta."
                )
            if status == 404:
                raise MercadoLivreUnavailableError(
                    "ANUNCIO_INDISPONIVEL: a página informada não existe."
                )

            identity = self.reconcile_identity(
                origin_identity,
                final_identity,
                html,
                final_url,
            )
            try:
                product = self.product_data_from_html(html, final_url)
                product["ml_identity"] = self.identity_payload(identity)
                product["ml_classification"] = "PRODUTO_RECUPERADO"
                return product
            except ValueError as page_error:
                if identity.id_item:
                    return self.product_data_from_api(
                        final_url or url,
                        fallback_url=url,
                        page_error=page_error,
                        identity=identity,
                    )
                if identity.tipo == MercadoLivreIdentityType.CATALOGO:
                    raise MercadoLivreIdentityError(
                        "CATALOGO_VALIDO_SEM_ITEM: o catálogo foi identificado, "
                        "mas não apresentou dados completos e inequívocos."
                    ) from page_error
                return self.product_data_from_api(
                    final_url or url,
                    fallback_url=url,
                    page_error=page_error,
                    identity=identity,
                )

        finally:
            self.close(page)

    @staticmethod
    def identity_payload(identity):
        return {
            "tipo": identity.tipo.value,
            "id_item": identity.id_item,
            "id_catalogo": identity.id_catalogo,
            "url_origem": identity.url_origem,
            "url_final": identity.url_final,
            "fonte_da_identidade": identity.fonte_da_identidade,
        }

    @classmethod
    def identity_from_url(cls, url, url_origem="", url_final=""):
        value = str(url or "").strip()
        parsed = urlparse(value)
        host = (parsed.hostname or "").casefold()
        path = parsed.path
        query = parse_qs(parsed.query)
        fragment_query = parse_qs(parsed.fragment)
        for key, values in fragment_query.items():
            query.setdefault(key, []).extend(values)

        if host == "meli.la" or "/social/" in path.casefold():
            return MercadoLivreIdentity(
                MercadoLivreIdentityType.SOCIAL,
                url_origem=str(url_origem or value),
                url_final=str(url_final or value),
                fonte_da_identidade="LINK_AFILIADO_SOCIAL",
            )

        filters = " ".join(query.get("pdp_filters", ()))
        item_match = re.search(r"item_id[:%]3?A?(MLBU?\d+)", filters, re.I)
        if not item_match:
            item_match = re.search(r"item_id:?(MLBU?\d+)", filters, re.I)
        wid = next(
            (
                cls.normalize_product_id(candidate)
                for candidate in query.get("wid", ())
                if cls.normalize_product_id(str(candidate))
            ),
            "",
        )
        id_item = (
            cls.normalize_product_id(item_match.group(1))
            if item_match else wid
        )

        path_lower = path.casefold()
        if "/up/" not in path_lower and "/p/" not in path_lower:
            direct = re.search(
                r"/(MLBU?-?\d+)(?:[-/?#]|$)", path, re.I
            )
            if direct and not id_item:
                id_item = cls.normalize_product_id(direct.group(1))

        catalog = re.search(
            r"/p/(MLBU?\d+)(?:[/?#]|$)", path, re.I
        )
        catalog_up = re.search(r"/up/(MLBU\d+)(?:[/?#]|$)", path, re.I)
        id_catalogo = (
            catalog.group(1).upper() if catalog
            else catalog_up.group(1).upper() if catalog_up
            else ""
        )

        if id_item:
            source = (
                "PDP_FILTERS_ITEM_ID" if item_match
                else "WID" if wid
                else "URL_ITEM"
            )
            return MercadoLivreIdentity(
                MercadoLivreIdentityType.ITEM,
                id_item=id_item,
                id_catalogo=id_catalogo,
                url_origem=str(url_origem or value),
                url_final=str(url_final or value),
                fonte_da_identidade=source,
            )
        if id_catalogo:
            return MercadoLivreIdentity(
                MercadoLivreIdentityType.CATALOGO,
                id_catalogo=id_catalogo,
                url_origem=str(url_origem or value),
                url_final=str(url_final or value),
                fonte_da_identidade="URL_CATALOGO",
            )
        return MercadoLivreIdentity(
            MercadoLivreIdentityType.DESCONHECIDO,
            url_origem=str(url_origem or value),
            url_final=str(url_final or value),
            fonte_da_identidade="URL_SEM_IDENTIDADE_QUALIFICADA",
        )

    @classmethod
    def primary_social_product_url(cls, html, base_url):
        soup = BeautifulSoup(html or "", "lxml")
        candidates = []
        selectors = (
            "a.poly-component__title[href*='c_id=/home/card-featured/']",
            "a.poly-component__link--action-link[href*='c_id=/home/card-featured/']",
        )
        for selector in selectors:
            for anchor in soup.select(selector):
                href = urljoin(base_url, str(anchor.get("href") or "").strip())
                identity = cls.identity_from_url(href, url_origem=base_url)
                if identity.tipo in {
                    MercadoLivreIdentityType.ITEM,
                    MercadoLivreIdentityType.CATALOGO,
                }:
                    candidates.append(href)
        unique = list(dict.fromkeys(candidates))
        if not unique:
            raise MercadoLivreIdentityError(
                "ITEM_NAO_CONFIRMADO: a página social não informou o produto "
                "principal destacado."
            )
        qualified = [(value, cls.identity_from_url(value)) for value in unique]
        item_ids = {
            identity.id_item for _, identity in qualified if identity.id_item
        }
        catalog_ids = {
            identity.id_catalogo
            for _, identity in qualified if identity.id_catalogo
        }
        if len(item_ids) > 1 or len(catalog_ids) > 1:
            raise MercadoLivreAmbiguousIdentity(
                "IDENTIDADE_AMBIGUA: a página social apresentou mais de um "
                "produto principal."
            )
        return next(
            (
                value for value, identity in qualified
                if identity.id_item
            ),
            unique[0],
        )

    @classmethod
    def reconcile_identity(cls, origin, final, html, final_url):
        soup = BeautifulSoup(html or "", "lxml")
        identities = [identity for identity in (origin, final)]
        for selector, source in (
            ("link[rel='canonical']", "CANONICAL"),
            ("meta[property='og:url']", "OG_URL"),
        ):
            node = soup.select_one(selector)
            candidate = str(
                node.get("href") or node.get("content") or ""
            ).strip() if node else ""
            if candidate:
                found = cls.identity_from_url(
                    candidate,
                    url_origem=origin.url_origem,
                    url_final=final_url,
                )
                if found.tipo != MercadoLivreIdentityType.DESCONHECIDO:
                    identities.append(found)

        item_ids = {value.id_item for value in identities if value.id_item}
        catalog_ids = {
            value.id_catalogo for value in identities if value.id_catalogo
        }
        if len(item_ids) > 1 or len(catalog_ids) > 1:
            raise MercadoLivreAmbiguousIdentity(
                "IDENTIDADE_AMBIGUA: URL, redirecionamento e metadados "
                "identificam produtos divergentes."
            )
        id_item = next(iter(item_ids), "")
        id_catalogo = next(iter(catalog_ids), "")
        kind = (
            MercadoLivreIdentityType.ITEM
            if id_item else MercadoLivreIdentityType.CATALOGO
            if id_catalogo else MercadoLivreIdentityType.DESCONHECIDO
        )
        source = "+".join(
            dict.fromkeys(
                value.fonte_da_identidade for value in identities
                if value.id_item or value.id_catalogo
            )
        )
        return MercadoLivreIdentity(
            kind,
            id_item=id_item,
            id_catalogo=id_catalogo,
            url_origem=origin.url_origem,
            url_final=final_url,
            fonte_da_identidade=source or "SEM_IDENTIDADE_CONFIRMADA",
        )

    def product_data_from_html(self, html, url):
        """Combina HTML visível, metadados e JSON estruturado da página."""

        soup = BeautifulSoup(html or "", "lxml")
        title = soup.select_one("h1.ui-pdp-title")
        image = (
            soup.select_one("meta[property='og:image']")
            or soup.select_one(".ui-pdp-gallery__figure img")
        )
        current = (
            soup.select_one(
                ".ui-pdp-price__second-line "
                ".andes-money-amount:not(.andes-money-amount--previous)"
            )
            or soup.select_one(
                ".ui-pdp-price__main-container "
                ".andes-money-amount:not(.andes-money-amount--previous)"
            )
        )
        previous = (
            soup.select_one(
                ".ui-pdp-price__original-value .andes-money-amount"
            )
            or soup.select_one(".andes-money-amount--previous")
        )
        title_text = title.get_text(" ", strip=True) if title else ""
        price_text = self.money_amount_text(current)
        old_price_text = self.money_amount_text(previous)
        image_url = ""
        if image:
            image_url = str(
                image.get("content")
                or image.get("data-zoom")
                or image.get("src")
                or ""
            ).strip()

        for node in self.serialized_product_nodes(soup):
            title_text = title_text or str(node.get("name") or "").strip()
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = next(
                    (value for value in offers if isinstance(value, dict)),
                    {},
                )
            if isinstance(offers, dict):
                price_text = price_text or str(
                    offers.get("price") or offers.get("lowPrice") or ""
                )
                old_price_text = old_price_text or str(
                    offers.get("original_price")
                    or offers.get("originalPrice")
                    or offers.get("highPrice")
                    or ""
                )
            candidate_image = node.get("image") or ""
            if isinstance(candidate_image, list):
                candidate_image = candidate_image[0] if candidate_image else ""
            if isinstance(candidate_image, dict):
                candidate_image = (
                    candidate_image.get("url")
                    or candidate_image.get("contentUrl")
                    or ""
                )
            image_url = image_url or str(candidate_image).strip()

        if not title_text:
            meta = soup.select_one("meta[property='og:title']")
            title_text = str(meta.get("content") or "").strip() if meta else ""
        if not price_text:
            meta = (
                soup.select_one("meta[property='product:price:amount']")
                or soup.select_one("meta[property='og:price:amount']")
            )
            price_text = str(meta.get("content") or "").strip() if meta else ""

        normalized_price = self.normalize_price(price_text)
        if not title_text or not normalized_price:
            raise ValueError(
                "O Mercado Livre não retornou título e preço verificáveis."
            )
        product = {
            "loja": self.name,
            "titulo": title_text,
            "preco": normalized_price,
            "link": str(url or "").strip(),
            "imagem": image_url,
        }
        old_price = self.normalize_price(old_price_text)
        if (
            old_price
            and Parser.price_to_float(old_price)
            > Parser.price_to_float(normalized_price)
        ):
            product["preco_antigo"] = old_price
        breadcrumb = self.breadcrumb_from_soup(soup)
        product["breadcrumb"] = " > ".join(breadcrumb) if breadcrumb else ""
        product["categoria_original"] = breadcrumb[-1] if breadcrumb else ""
        return product

    @staticmethod
    def normalize_price(value):
        if isinstance(value, (int, float)):
            return f"{float(value):.2f}".replace(".", ",")
        text = str(value or "").strip()
        if re.fullmatch(r"\d+\.\d{1,2}", text):
            return f"{float(text):.2f}".replace(".", ",")
        return Parser.clean_price(text)

    @staticmethod
    def money_amount_text(element):
        if not element:
            return ""
        fraction = element.select_one(".andes-money-amount__fraction")
        cents = element.select_one(".andes-money-amount__cents")
        if not fraction:
            return ""
        value = fraction.get_text(strip=True)
        return value + (
            "," + cents.get_text(strip=True).zfill(2) if cents else ""
        )

    @staticmethod
    def serialized_product_nodes(soup):
        """Lê JSON-LD e estados JSON internos sem executar scripts."""

        nodes = []
        for script in soup.select("script"):
            raw = script.string or script.get_text() or ""
            raw = raw.strip()
            if not raw or raw[0:1] not in {"{", "["}:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            stack = payload if isinstance(payload, list) else [payload]
            while stack:
                node = stack.pop()
                if isinstance(node, list):
                    stack.extend(node)
                elif isinstance(node, dict):
                    node_type = str(node.get("@type") or "").casefold()
                    looks_like_product = bool(
                        node.get("name", node.get("title"))
                        and (
                            node.get("offers")
                            or node.get("price") not in (None, "")
                            or node.get("current_price") not in (None, "")
                        )
                    )
                    if node_type == "product" or looks_like_product:
                        if "name" not in node and node.get("title"):
                            node = {**node, "name": node["title"]}
                        if "offers" not in node:
                            node = {
                                **node,
                                "offers": {
                                    "price": node.get(
                                        "price", node.get("current_price")
                                    ),
                                    "original_price": node.get(
                                        "original_price",
                                        node.get("previous_price"),
                                    ),
                                },
                            }
                        nodes.append(node)
                    stack.extend(
                        value for value in node.values()
                        if isinstance(value, (dict, list))
                    )
        return nodes

    @staticmethod
    def normalize_product_id(raw_id):
        """Normaliza Product ID do Mercado Livre (MLB ou MLBU).

        Preserva a diferenca entre MLB e MLBU.
        Remove apenas o hifen.
        Retorna em maiusculas.
        Nunca converte MLBU em MLB.
        Nunca retorna ID vazio para um ID valido.
        """
        if not raw_id:
            return ""
        cleaned = str(raw_id).strip().upper().replace("-", "")
        if re.fullmatch(r"MLBU?\d+", cleaned):
            return cleaned
        return ""

    @staticmethod
    def product_id_from_url(url):
        identity = MercadoLivre.identity_from_url(url)
        return identity.id_item

    def product_data_from_api(
        self,
        url,
        fallback_url="",
        page_error=None,
        identity=None,
    ):
        identity = identity or self.identity_from_url(
            url, url_origem=fallback_url or url, url_final=url
        )
        product_id = identity.id_item
        if not product_id:
            raise ValueError(
                "ITEM_NAO_CONFIRMADO: o link não contém um ID de anúncio "
                "qualificado para consulta à API."
            ) from page_error
        try:
            response = requests.get(
                f"https://api.mercadolibre.com/items/{product_id}",
                headers=dict(self.api_headers),
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise ValueError(
                f"Não foi possível recuperar o produto {product_id}."
            ) from error
        product = {
            "loja": self.name,
            "titulo": str(payload.get("title") or "").strip(),
            "preco": self.normalize_price(payload.get("price")),
            "link": str(url or fallback_url).strip(),
            "imagem": str(
                payload.get("secure_thumbnail")
                or payload.get("thumbnail")
                or ""
            ).replace("http://", "https://", 1),
        }
        old_price = self.normalize_price(payload.get("original_price"))
        if (
            old_price
            and Parser.price_to_float(old_price)
            > Parser.price_to_float(product["preco"])
        ):
            product["preco_antigo"] = old_price
        if not product["titulo"] or not product["preco"]:
            raise ValueError(
                f"A fonte pública não retornou dados completos de {product_id}."
            ) from page_error
        product["ml_identity"] = self.identity_payload(identity)
        product["ml_classification"] = "PRODUTO_RECUPERADO"
        return product

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

            normalized_id = MercadoLivre.normalize_product_id(produto_id)
            if normalized_id:
                if normalized_id.startswith("MLBU"):
                    prefix = "MLBU"
                    suffix = normalized_id[4:]
                else:
                    prefix = "MLB"
                    suffix = normalized_id[3:]
                return f"https://produto.mercadolivre.com.br/{prefix}-{suffix}"

            direct_path = parsed.path.lower()
            is_direct_product = (
                "/p/mlb" in direct_path
                or "/p/mlbu" in direct_path
                or "/up/mlbu" in direct_path
                or (
                    "produto.mercadolivre.com.br" in parsed.netloc.lower()
                    and ("/mlb-" in direct_path or "/mlbu-" in direct_path)
                )
            )
            if (
                is_direct_product
                and "mercadolivre.com.br" in parsed.netloc.lower()
                and "clicks/external" not in href
            ):
                return self.link(href, "https://www.mercadolivre.com.br")

        return ""
