from src.stores.generic_marketplace import GenericMarketplace


class Americanas(GenericMarketplace):

    store_name = "Americanas"
    search_url = "https://www.americanas.com.br/s?q={}"
    base_domain = "https://www.americanas.com.br"
    product_markers = ("/produto/", "/p/", "/p")
    ignore_markers = ("/busca/", "/login", "/carrinho", "/categoria/")
