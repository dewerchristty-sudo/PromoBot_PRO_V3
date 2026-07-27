from bs4 import BeautifulSoup
from urllib.parse import parse_qs, urlparse
import json
import logging
import re
import requests
import unicodedata

from src.stores.base_store import BaseStore
from src.stores.mercado_livre_browser import MercadoLivrePersistentContext
from src.scraper import Parser

logger = logging.getLogger(__name__)


class MercadoLivre(BaseStore):

    offers_url = "https://www.mercadolivre.com.br/ofertas"
    api_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }

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

        resultados = []

        page = self.browser_manager.new_page()

        try:

            url = self.base_url.format(
                product.replace(" ", "-")
            )

            print(f"\n>>> {self.name}")
            print(f"Abrindo: {url}")

            page.goto(
                url,
                wait_until="networkidle",
                timeout=60000
            )

            page.wait_for_timeout(5000)

            soup = BeautifulSoup(
                page.content(),
                "lxml"
            )

            produtos = soup.select("li.ui-search-layout__item")

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
                soup = BeautifulSoup(page.content(), "lxml")
                produtos = soup.select("div.andes-card.poly-card")
            elif not produtos:
                print(
                    "Busca do Mercado Livre bloqueada por verificacao externa; "
                    "nenhuma oferta generica sera usada para substituir o "
                    "termo pesquisado."
                )

            print(
                f"Produtos encontrados: {len(produtos)}"
            )

            for item in produtos[:20]:

                try:

                    titulo = (
                        item.select_one(".poly-component__title")
                        or item.select_one("h3")
                    )

                    preco = item.select_one(
                        ".andes-money-amount__fraction"
                    )
                    previous = item.select_one(
                        ".andes-money-amount--previous"
                    )

                    link = self.product_link(item)

                    imagem = item.select_one("img")

                    titulo_texto = (
                        titulo.get_text(strip=True)
                        if titulo else ""
                    )

                    if not titulo_texto or not link:
                        continue

                    result = {

                        "loja": self.name,

                        "titulo": titulo_texto,

                        "preco": self.price(
                            preco.get_text(strip=True)
                            if preco else ""
                        ),

                        "link": link,

                        "imagem": (
                            imagem.get("src")
                            or imagem.get("data-src")
                            or ""
                        ) if imagem else ""

                    }
                    old_price = self.normalized_old_price(
                        self.money_amount_text(previous),
                        result["preco"],
                    )
                    if old_price:
                        result["preco_antigo"] = old_price
                    resultados.append(result)

                except Exception as e:
                    logger.debug(f"Erro ao processar item do Mercado Livre: {str(e)}")
                    continue

            print(
                f"{self.name}: {len(resultados)} produtos encontrados."
            )

            return resultados

        finally:

            page.close()

            self.browser_manager.close()

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
        """Importa um produto usando fontes públicas em ordem segura."""

        page = self.browser_manager.new_page()
        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(4000)
            html = page.content()
            return self.product_data_from_sources(html, url)
        finally:
            page.close()
            self.browser_manager.close()

    def product_data_from_sources(self, html, url):
        """Tenta HTML, JSON-LD, OG, estado embutido e por último a API."""

        sources = (
            ("HTML", self.product_data_from_html),
            ("JSON_LD", self.product_data_from_json_ld),
            ("OPEN_GRAPH", self.product_data_from_open_graph),
            ("EMBEDDED_STATE", self.product_data_from_embedded_state),
        )
        failures = []
        for source, extractor in sources:
            try:
                product = extractor(html, url)
                self.validate_recovered_product(product, source)
                logger.info(
                    "mercado livre product recovery: source=%s "
                    "product_id=%s result=complete",
                    source,
                    self.product_id_from_url(url) or "NOT_AVAILABLE",
                )
                return product
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                failures.append(f"{source}={self.safe_log_text(error)}")
                logger.info(
                    "mercado livre product recovery: source=%s "
                    "product_id=%s result=incomplete reason=%s",
                    source,
                    self.product_id_from_url(url) or "NOT_AVAILABLE",
                    self.safe_log_text(error),
                )
        try:
            product = self.product_data_from_api(url)
            self.validate_recovered_product(product, "PUBLIC_ITEM_API")
            return product
        except ValueError as error:
            failures.append(
                f"PUBLIC_ITEM_API={self.safe_log_text(error)}"
            )
            raise ValueError(
                "Não foi possível recuperar dados completos e verificáveis do "
                "produto Mercado Livre. Fontes tentadas: "
                + "; ".join(failures)
            ) from error

    def product_data_from_api(self, url, page_error=None):
        """Fallback público, com diagnóstico seguro da resposta HTTP."""

        product_id = self.product_id_from_url(url)
        if not product_id:
            raise ValueError(
                "O identificador MLB não foi encontrado na URL do produto."
            ) from page_error
        endpoint = f"https://api.mercadolibre.com/items/{product_id}"
        try:
            response = requests.get(
                endpoint,
                headers=dict(self.api_headers),
                timeout=20,
            )
            logger.info(
                "mercado livre api: url=%s status=%s "
                "request_headers=%s response_body=%s",
                endpoint,
                response.status_code,
                self.safe_request_headers(self.api_headers),
                self.response_summary(response),
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise ValueError(
                "O Mercado Livre bloqueou a página e a API pública não "
                f"retornou o produto {product_id}: {error}"
            ) from page_error
        title = str(payload.get("title") or "").strip()
        price = payload.get("price")
        image = str(
            payload.get("secure_thumbnail")
            or payload.get("thumbnail")
            or ""
        ).strip()
        if image.startswith("http://"):
            image = "https://" + image.removeprefix("http://")
        if not title or price in (None, ""):
            raise ValueError(
                f"A API pública não retornou título e preço de {product_id}."
            ) from page_error
        breadcrumb = ()
        category_id = str(payload.get("category_id") or "").strip()
        if category_id:
            try:
                category_response = requests.get(
                    "https://api.mercadolibre.com/categories/"
                    + category_id,
                    headers=dict(self.api_headers),
                    timeout=20,
                )
                category_response.raise_for_status()
                category_payload = category_response.json()
                breadcrumb = tuple(
                    str(item.get("name") or "").strip()
                    for item in category_payload.get("path_from_root") or ()
                    if str(item.get("name") or "").strip()
                )
                category_name = str(
                    category_payload.get("name") or ""
                ).strip()
                if category_name and category_name not in breadcrumb:
                    breadcrumb += (category_name,)
            except (requests.RequestException, ValueError, TypeError):
                logger.warning(
                    "mercado livre product_from_url: category_api_failed "
                    "product_id=%s category_id=%s",
                    product_id,
                    category_id,
                )
        product = {
            "loja": self.name,
            "titulo": title,
            "preco": Parser.format_brl(price),
            "link": str(url or "").strip(),
            "imagem": image,
        }
        original_price = payload.get("original_price")
        if (
            original_price not in (None, "")
            and float(original_price) > float(price)
        ):
            product["preco_antigo"] = (
                Parser.format_brl(original_price)
            )
        if breadcrumb:
            product["breadcrumb"] = " > ".join(breadcrumb)
            product["categoria_original"] = breadcrumb[-1]
        logger.info(
            "mercado livre product_from_url: source=PUBLIC_ITEM_API "
            "product_id=%s title_found=True price_found=True "
            "image_found=%s breadcrumb=%s",
            product_id,
            bool(image),
            product.get("breadcrumb", "NOT_AVAILABLE"),
        )
        return product

    def product_data_from_json_ld(self, html, url):
        """Extrai Product/Offer de JSON-LD verificável da página."""

        soup = BeautifulSoup(html or "", "lxml")
        for script in soup.select("script[type='application/ld+json']"):
            raw = script.string or script.get_text() or ""
            if not raw.strip():
                continue
            payload = json.loads(raw)
            for node in self.iter_json_nodes(payload):
                if str(node.get("@type") or "").casefold() != "product":
                    continue
                offers = node.get("offers") or {}
                if isinstance(offers, list):
                    offers = next(
                        (item for item in offers if isinstance(item, dict)),
                        {},
                    )
                image = node.get("image") or ""
                if isinstance(image, list):
                    image = image[0] if image else ""
                if isinstance(image, dict):
                    image = image.get("url") or image.get("contentUrl") or ""
                return self.build_product(
                    url=url,
                    title=node.get("name") or "",
                    price=(
                        offers.get("price")
                        if isinstance(offers, dict) else ""
                    ),
                    image=image,
                    breadcrumb=self.breadcrumb_from_soup(soup),
                    old_price=self.original_price_from_json_node(offers),
                )
        raise ValueError("nenhum Product JSON-LD válido")

    def product_data_from_open_graph(self, html, url):
        """Extrai metadados Open Graph sem inventar campos ausentes."""

        soup = BeautifulSoup(html or "", "lxml")

        def value(property_name):
            element = (
                soup.select_one(f"meta[property='{property_name}']")
                or soup.select_one(f"meta[name='{property_name}']")
            )
            return str(element.get("content", "") if element else "").strip()

        price = (
            value("product:price:amount")
            or value("og:price:amount")
            or value("price")
        )
        return self.build_product(
            url=url,
            title=value("og:title"),
            price=price,
            image=value("og:image"),
            breadcrumb=self.breadcrumb_from_soup(soup),
            old_price=(
                value("product:original_price:amount")
                or value("product:price:original_amount")
                or value("og:original_price:amount")
            ),
        )

    def product_data_from_embedded_state(self, html, url):
        """Procura o produto no estado JSON serializado pelo próprio site."""

        soup = BeautifulSoup(html or "", "lxml")
        expected_id = self.product_id_from_url(url)
        for script in soup.find_all("script"):
            raw = script.string or script.get_text() or ""
            stripped = raw.strip()
            if not stripped or stripped[0:1] not in ("{", "["):
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            for node in self.iter_json_nodes(payload):
                node_id = str(
                    node.get("id")
                    or node.get("item_id")
                    or node.get("itemId")
                    or ""
                ).replace("-", "").upper()
                if expected_id and node_id and node_id != expected_id:
                    continue
                title = node.get("title") or node.get("name") or ""
                price = self.price_from_json_node(node)
                old_price = self.original_price_from_json_node(node)
                image = self.image_from_json_node(node)
                if title and price not in (None, "") and image:
                    return self.build_product(
                        url=url,
                        title=title,
                        price=price,
                        image=image,
                        breadcrumb=self.breadcrumb_from_soup(soup),
                        old_price=old_price,
                    )
        raise ValueError("estado JSON não contém produto completo")

    @staticmethod
    def iter_json_nodes(payload):

        if isinstance(payload, dict):
            yield payload
            for value in payload.values():
                yield from MercadoLivre.iter_json_nodes(value)
        elif isinstance(payload, list):
            for value in payload:
                yield from MercadoLivre.iter_json_nodes(value)

    @staticmethod
    def price_from_json_node(node):

        for key in ("price", "current_price", "currentPrice", "amount"):
            value = node.get(key)
            if isinstance(value, dict):
                value = value.get("amount") or value.get("value")
            if value not in (None, ""):
                return value
        return ""

    @staticmethod
    def original_price_from_json_node(node):

        if not isinstance(node, dict):
            return ""
        for key in (
            "original_price",
            "originalPrice",
            "previous_price",
            "previousPrice",
            "list_price",
            "listPrice",
        ):
            value = node.get(key)
            if isinstance(value, dict):
                value = value.get("amount") or value.get("value")
            if value not in (None, ""):
                return value
        specification = node.get("priceSpecification")
        if isinstance(specification, list):
            for item in specification:
                value = MercadoLivre.original_price_from_json_node(item)
                if value not in (None, ""):
                    return value
        return ""

    @staticmethod
    def image_from_json_node(node):

        for key in ("secure_thumbnail", "thumbnail", "image", "pictures"):
            value = node.get(key)
            if isinstance(value, list):
                value = value[0] if value else ""
            if isinstance(value, dict):
                value = (
                    value.get("secure_url")
                    or value.get("url")
                    or value.get("src")
                    or value.get("contentUrl")
                    or ""
                )
            if isinstance(value, str) and value.startswith(
                ("http://", "https://")
            ):
                return value
        return ""

    def build_product(
        self,
        url,
        title,
        price,
        image,
        breadcrumb=(),
        old_price="",
    ):

        title = str(title or "").strip()
        image = str(image or "").strip()
        if image.startswith("http://"):
            image = "https://" + image.removeprefix("http://")
        if isinstance(price, (int, float)):
            price = Parser.format_brl(price)
        else:
            price = self.price(str(price or "").strip())
        product = {
            "loja": self.name,
            "titulo": title,
            "preco": price,
            "link": str(url or "").strip(),
            "imagem": image,
        }
        normalized_old_price = self.normalized_old_price(old_price, price)
        if normalized_old_price:
            product["preco_antigo"] = normalized_old_price
        breadcrumb = tuple(
            str(value).strip()
            for value in breadcrumb
            if str(value).strip()
        )
        if breadcrumb:
            product["breadcrumb"] = " > ".join(breadcrumb)
            product["categoria_original"] = breadcrumb[-1]
        return product

    def normalized_old_price(self, old_price, current_price):

        if old_price in (None, ""):
            return ""
        if isinstance(old_price, (int, float)):
            old_text = Parser.format_brl(old_price)
        else:
            old_text = self.price(str(old_price).strip())
        old_value = Parser.price_to_float(old_text)
        current_value = Parser.price_to_float(str(current_price or ""))
        return old_text if old_value > current_value > 0 else ""

    @staticmethod
    def validate_recovered_product(product, source):

        missing = []
        if not str(product.get("titulo") or "").strip():
            missing.append("título")
        if not str(product.get("preco") or "").strip():
            missing.append("preço")
        if not str(product.get("imagem") or "").startswith(
            ("http://", "https://")
        ):
            missing.append("imagem")
        if missing:
            raise ValueError(f"{source} não retornou " + ", ".join(missing))

    @staticmethod
    def safe_request_headers(headers):

        allowed = {"User-Agent", "Accept", "Accept-Language"}
        return {
            key: value
            for key, value in dict(headers or {}).items()
            if key in allowed
        }

    @staticmethod
    def response_summary(response, limit=300):

        content_type = str(response.headers.get("Content-Type") or "")
        body = re.sub(r"\s+", " ", str(response.text or "")).strip()
        body = re.sub(
            r'(?i)(access[_-]?token|authorization|cookie)"?\s*[:=]\s*"[^"]+"',
            r"\1=[REDACTED]",
            body,
        )
        return {
            "content_type": content_type[:100],
            "body": body[:limit],
            "truncated": len(body) > limit,
        }

    @staticmethod
    def safe_log_text(value, limit=300):

        return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]

    @staticmethod
    def product_id_from_url(url):

        match = re.search(r"\b(MLB-?\d+)\b", str(url or ""), re.IGNORECASE)
        return match.group(1).replace("-", "").upper() if match else ""

    def product_data_from_html(self, html, url):
        """Extrai o formato comum consumido pelo pipeline de afiliados."""

        soup = BeautifulSoup(html, "lxml")
        title = (
            soup.select_one("h1.ui-pdp-title")
            or soup.select_one("meta[property='og:title']")
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
            or soup.select_one(
                ".andes-money-amount:not(.andes-money-amount--previous)"
            )
        )
        previous = (
            soup.select_one(
                ".ui-pdp-price__original-value "
                ".andes-money-amount--previous"
            )
            or soup.select_one(
                ".ui-pdp-price__original-value .andes-money-amount"
            )
            or soup.select_one(".andes-money-amount--previous")
        )
        image = (
            soup.select_one("meta[property='og:image']")
            or soup.select_one(".ui-pdp-gallery__figure img")
        )
        title_text = ""
        if title:
            title_text = (
                title.get("content", "")
                if title.name == "meta"
                else title.get_text(" ", strip=True)
            )
        price_text = self.money_amount_text(current)
        image_url = ""
        if image:
            image_url = (
                image.get("content", "")
                or image.get("data-zoom", "")
                or image.get("src", "")
            ).strip()
        if not title_text or not price_text:
            missing = []
            if not title_text:
                missing.append("título")
            if not price_text:
                missing.append("preço")
            raise ValueError(
                "O Mercado Livre não retornou " + " e ".join(missing)
                + " do produto. Confirme que a URL abre diretamente o anúncio."
            )
        breadcrumb = self.breadcrumb_from_soup(soup)
        product = {
            "loja": self.name,
            "titulo": title_text.strip(),
            "preco": self.price(price_text),
            "link": str(url or "").strip(),
            "imagem": image_url,
        }
        old_price = self.normalized_old_price(
            self.money_amount_text(previous),
            product["preco"],
        )
        if old_price:
            product["preco_antigo"] = old_price
        if breadcrumb:
            product["breadcrumb"] = " > ".join(breadcrumb)
            product["categoria_original"] = breadcrumb[-1]
        logger.info(
            "mercado livre product_from_url: url=%s title_found=%s "
            "price_found=%s old_price_found=%s image_found=%s breadcrumb=%s",
            url,
            bool(product["titulo"]),
            bool(product["preco"]),
            bool(product.get("preco_antigo")),
            bool(product["imagem"]),
            product.get("breadcrumb", "NOT_PRESENT"),
        )
        return product

    @staticmethod
    def money_amount_text(element):

        if not element:
            return ""
        fraction = element.select_one(".andes-money-amount__fraction")
        cents = element.select_one(".andes-money-amount__cents")
        if not fraction:
            return ""
        value = fraction.get_text(strip=True)
        if cents:
            value += "," + cents.get_text(strip=True).zfill(2)
        return value

    @staticmethod
    def breadcrumb_from_soup(soup):

        selectors = (
            ".andes-breadcrumb__link",
            ".andes-breadcrumb__item",
            "nav[aria-label*='breadcrumb' i] a",
            "nav[aria-label*='migalha' i] a",
        )
        for selector in selectors:
            values = []
            for element in soup.select(selector):
                value = element.get_text(" ", strip=True)
                if value and value not in values:
                    values.append(value)
            if values:
                return tuple(values)
        return ()

    # ======================================================

    def product_link(self, item):

        for anchor in item.select("a[href]"):

            href = anchor.get("href", "")

            if not href:
                continue

            if "mercadolivre.com.br" in href and "clicks/external" not in href:
                return self.link(href, "https://www.mercadolivre.com.br")

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

        return ""
