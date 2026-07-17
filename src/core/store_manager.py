from src.stores import Americanas
from src.stores import Amazon
from src.stores import CasasBahia
from src.stores import Kabum
from src.stores import Magalu
from src.stores import MercadoLivre
from src.stores import Pichau
from src.stores import Shopee
from src.stores import Terabyte
from src.scraper import Parser


class StoreManager:

    STABLE_STORES = [
        "Mercado Livre",
        "Amazon",
        "Kabum",
        "Shopee",
    ]

    EXPERIMENTAL_STORES = [
        "Terabyte",
        "Americanas",
        "Pichau",
        "Magalu",
        "Casas Bahia",
    ]

    def __init__(self, progress_callback=None, enabled_stores=None):

        self.progress_callback = progress_callback
        self.enabled_stores = enabled_stores

        self.stores = [

            MercadoLivre(),

            Amazon(),

            Kabum(),

            Terabyte(),

            Pichau(),

            Magalu(),

            CasasBahia(),

            Americanas(),

            Shopee(),

        ]

        if self.enabled_stores:
            self.stores = [
                store for store in self.stores
                if store.name in self.enabled_stores
            ]

    # ==========================================

    def log(self, message):

        print(message)

        if self.progress_callback:

            self.progress_callback(message)

    # ==========================================

    def search_all(self, product):

        resultados = []

        self.log("\n" + "=" * 60)
        self.log(f"Pesquisando: {product}")
        self.log("=" * 60)

        for store in self.stores:

            self.log(f"\n>>> {store.name}")

            try:

                encontrados = store.search(product)
                encontrados = self.sanitize_results(encontrados)

                self.log(
                    f"{store.name}: {len(encontrados)} produtos"
                )

                resultados.extend(
                    encontrados
                )

            except Exception as e:

                self.log(f"[ERRO] {store.name}: {e}")

        self.log("\n" + "=" * 60)
        self.log(
            f"TOTAL: {len(resultados)} produtos"
        )
        self.log("=" * 60 + "\n")

        return resultados

    # ==========================================

    def sanitize_results(self, produtos):

        limpos = []
        vistos = set()

        for produto in produtos or []:

            titulo = (produto.get("titulo") or "").strip()
            link = (produto.get("link") or "").strip()
            loja = (produto.get("loja") or "").strip()
            preco = (produto.get("preco") or "").strip()

            if not titulo or not link or not loja:
                continue

            if not link.startswith("http"):
                continue

            if link in vistos:
                continue

            vistos.add(link)

            limpos.append({
                "loja": loja,
                "titulo": Parser.clean_text(titulo),
                "preco": Parser.clean_price(preco),
                "link": Parser.remove_tracking(link),
                "imagem": (produto.get("imagem") or "").strip(),
            })

        return limpos

    # ==========================================

    @classmethod
    def stable_store_names(cls):

        return list(cls.STABLE_STORES)

    # ==========================================

    @classmethod
    def experimental_store_names(cls):

        return list(cls.EXPERIMENTAL_STORES)
