import re
import unicodedata
from typing import Callable, Optional, Any

from src.stores import Amazon
from src.stores import MercadoLivre
from src.stores import Shopee
from src.stores.active import ACTIVE_STORE_NAMES
from src.scraper import Parser


class StoreManager:

    DEFAULT_STORES = list(ACTIVE_STORE_NAMES)
    STABLE_STORES = list(ACTIVE_STORE_NAMES)
    EXPERIMENTAL_STORES = []

    def __init__(
        self,
        progress_callback: Optional[Callable[[str], None]] = None,
        enabled_stores: Optional[list[str]] = None,
        offer_pipeline=None,
        offer_shadow_enabled: Optional[bool] = None,
    ) -> None:

        self.progress_callback = progress_callback
        self.enabled_stores = enabled_stores
        self.offer_pipeline = offer_pipeline
        self.offer_shadow_enabled = offer_shadow_enabled

        self.stores = [

            MercadoLivre(),

            Amazon(),

            Shopee(),

        ]

        if self.enabled_stores is not None:
            self.stores = [
                store for store in self.stores
                if store.name in self.enabled_stores
            ]

    # ==========================================

    def log(self, message: str) -> None:

        print(message)

        if self.progress_callback:

            self.progress_callback(message)

    # ==========================================

    def search_all(self, product: str) -> list[dict[str, Any]]:

        resultados = []

        self.log("\n" + "=" * 60)
        self.log(f"Pesquisando: {product}")
        self.log("=" * 60)

        for store in self.stores:

            self.log(f"\n>>> {store.name}")

            try:

                encontrados = store.search(product)
                encontrados = self.sanitize_results(encontrados)
                encontrados = self.filter_by_requested_capacity(
                    product,
                    encontrados
                )
                encontrados = self.filter_by_requested_product_type(
                    product,
                    encontrados
                )
                encontrados = self.filter_by_requested_model_codes(
                    product,
                    encontrados
                )
                encontrados = self.filter_by_query_relevance(
                    product,
                    encontrados
                )

                self.log(
                    f"{store.name}: {len(encontrados)} produtos"
                )

                resultados.extend(
                    encontrados
                )

            except Exception as e:

                self.log(f"[ERRO] {store.name}: {str(e)}")

        self.log("\n" + "=" * 60)
        self.log(
            f"TOTAL: {len(resultados)} produtos"
        )
        self.log("=" * 60 + "\n")

        self.observe_offer_shadow(resultados)

        return resultados

    # ==========================================

    def observe_offer_shadow(self, products):
        """Observa a coleta sem alterar retorno, banco ou notificações atuais."""

        pipeline = self.offer_pipeline
        owned_pipeline = False

        try:
            from src.offers.pipeline import OfferPipeline

            if self.offer_shadow_enabled is False:
                return None
            if not OfferPipeline.enabled():
                return None

            if pipeline is None:
                pipeline = OfferPipeline.from_environment()
                owned_pipeline = True

            result = pipeline.process_batch(list(products or []))
            self.log(
                "OfferPipeline sombra: "
                f"{result.metrics.received_count} recebido(s), "
                f"{result.metrics.queued_count} enfileirado(s), "
                f"{result.metrics.selected_shadow_count} selecionado(s)."
            )
            return result

        except Exception as error:
            self.log(
                "[AVISO] OfferPipeline sombra indisponivel; "
                f"coleta atual preservada: {error}"
            )
            return None

        finally:
            if owned_pipeline and pipeline is not None:
                try:
                    pipeline.close()
                except Exception:
                    pass

    # ==========================================

    def sanitize_results(self, produtos: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:

        limpos = []
        vistos: set[str] = set()

        for produto in produtos or []:

            titulo = (produto.get("titulo") or "").strip()
            link = (produto.get("link") or "").strip()
            loja = (produto.get("loja") or "").strip()
            preco = (produto.get("preco") or "").strip()

            if not titulo or not link or not loja:
                continue

            if not link.startswith("http"):
                continue

            link = Parser.remove_tracking(link)

            if link in vistos:
                continue

            vistos.add(link)

            limpos.append({
                "loja": loja,
                "titulo": Parser.clean_text(titulo),
                "preco": Parser.clean_price(preco),
                "link": link,
                "imagem": (produto.get("imagem") or "").strip(),
            })

        return limpos

    # ==========================================

    @classmethod
    def filter_by_requested_capacity(
        cls,
        query: str,
        produtos: Optional[list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:

        requested = cls.extract_capacities_gb(query)

        if not requested:
            return list(produtos or [])

        return [
            produto for produto in produtos or []
            if cls.capacity_matches(
                requested,
                cls.extract_capacities_gb(produto.get("titulo", ""))
            )
        ]

    @staticmethod
    def extract_capacities_gb(text: str) -> list[float]:

        capacities = []
        pattern = r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(tb|gb)\b"

        for raw_value, unit in re.findall(pattern, text or "", re.IGNORECASE):
            value = float(raw_value.replace(",", "."))
            capacities.append(value * 1000 if unit.lower() == "tb" else value)

        return capacities

    @staticmethod
    def capacity_matches(requested: list[float], found: list[float]) -> bool:

        if not found:
            return False

        for target in requested:
            for capacity in found:
                # Fabricantes anunciam 1 TB tanto como 1000 GB quanto 1024 GB.
                tolerance = max(1.0, target * 0.03)
                if abs(target - capacity) <= tolerance:
                    return True

        return False

    # ==========================================

    @classmethod
    def filter_by_requested_product_type(
        cls,
        query: str,
        produtos: Optional[list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:

        query_types = cls.requested_product_types(query)

        if not query_types:
            return list(produtos or [])

        return [
            produto for produto in produtos or []
            if all(
                any(
                    re.search(pattern, produto.get("titulo", ""), re.IGNORECASE)
                    for pattern in aliases
                )
                for aliases in query_types
            )
        ]

    @staticmethod
    def requested_product_types(query: str) -> list[tuple[str, ...]]:

        product_types = (
            (r"\bssd\b", (r"\bssd\b", r"\bsolid state drive\b")),
            (r"\bhdd\b", (r"\bhdd\b", r"\bdisco r[ií]gido\b")),
        )

        return [
            aliases for query_pattern, aliases in product_types
            if re.search(query_pattern, query or "", re.IGNORECASE)
        ]

    # ==========================================

    @classmethod
    def filter_by_requested_model_codes(
        cls,
        query: str,
        produtos: Optional[list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:

        model_codes = cls.extract_model_codes(query)

        if not model_codes:
            return list(produtos or [])

        return [
            produto for produto in produtos or []
            if all(
                code in cls.normalize_model_text(produto.get("titulo", ""))
                for code in model_codes
            )
        ]

    @classmethod
    def extract_model_codes(cls, text: str) -> list[str]:

        codes = []

        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9/_-]*", text or ""):
            normalized = cls.normalize_model_text(token)
            has_letter = any(character.isalpha() for character in normalized)
            has_digit = any(character.isdigit() for character in normalized)

            if len(normalized) >= 6 and has_letter and has_digit:
                codes.append(normalized)

        return codes

    @staticmethod
    def normalize_model_text(text: str) -> str:

        return re.sub(r"[^a-z0-9]", "", (text or "").lower())

    # ==========================================

    @classmethod
    def filter_by_query_relevance(
        cls,
        query: str,
        produtos: Optional[list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:

        products = list(produtos or [])
        tokens = cls.relevant_query_tokens(query)
        if not tokens:
            return products

        required = len(tokens) if len(tokens) <= 2 else max(
            2, int(len(tokens) * 0.6 + 0.999)
        )
        ranked = []
        normalized_query = " ".join(tokens)

        for product in products:
            title = cls.normalize_search_text(product.get("titulo", ""))
            matched = sum(
                1 for token in tokens
                if re.search(rf"\b{re.escape(token)}\b", title)
                or (len(token) >= 5 and token in title)
            )
            if matched < required:
                continue
            if cls.is_accessory_mismatch(tokens, title):
                continue
            exact_phrase = normalized_query in title
            price = Parser.price_to_float(product.get("preco", "")) or 999999999
            ranked.append((
                -int(exact_phrase),
                -(matched / len(tokens)),
                price,
                product,
            ))

        ranked.sort(key=lambda item: item[:3])
        # Alguns marketplaces traduzem ou abreviam completamente o termo.
        # Nesses casos, manter a resposta original e melhor que transformar
        # uma busca valida em zero resultados.
        return [item[3] for item in ranked] if ranked else products

    @classmethod
    def relevant_query_tokens(cls, text: str) -> list[str]:

        ignored = {
            "de", "da", "do", "das", "dos", "para", "com", "sem", "e",
            "em", "um", "uma", "novo", "nova", "barato", "barata",
            "oferta", "ofertas", "promocao", "promocoes", "liquidacao",
            "cupom", "achadinho", "achadinhos", "dia", "melhor", "preco",
        }
        normalized = cls.normalize_search_text(text)
        return list(dict.fromkeys(
            token
            for token in re.findall(r"[a-z0-9]+", normalized)
            if len(token) >= 2 and token not in ignored
        ))

    @staticmethod
    def normalize_search_text(text: str) -> str:

        normalized = unicodedata.normalize("NFKD", str(text or "").casefold())
        without_accents = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        return re.sub(r"[^a-z0-9]+", " ", without_accents).strip()

    @staticmethod
    def is_accessory_mismatch(tokens: list[str], title: str) -> bool:

        accessory_terms = {
            "notebook": {
                "capa", "case", "carregador", "fonte", "teclado", "bateria",
                "suporte", "mochila", "pelicula", "tela", "dobradica",
            },
            "celular": {
                "capa", "case", "pelicula", "carregador", "cabo", "suporte",
            },
            "smartphone": {
                "capa", "case", "pelicula", "carregador", "cabo", "suporte",
            },
            "impressora": {"tinta", "cartucho", "toner", "cabo", "refil"},
            "aspirador": {"filtro", "mangueira", "bico", "saco", "peca"},
        }
        query_set = set(tokens)
        for product_type, accessories in accessory_terms.items():
            if product_type not in query_set:
                continue
            if query_set & accessories:
                continue
            if set(title.split()) & accessories:
                return True
        return False

    # ==========================================

    @classmethod
    def stable_store_names(cls) -> list[str]:

        return list(cls.STABLE_STORES)

    @classmethod
    def default_store_names(cls) -> list[str]:

        return list(cls.DEFAULT_STORES)

    # ==========================================

    @classmethod
    def experimental_store_names(cls) -> list[str]:

        return list(cls.EXPERIMENTAL_STORES)
