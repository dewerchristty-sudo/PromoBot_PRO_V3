from src.stores.generic_marketplace import GenericMarketplace


class CasasBahia(GenericMarketplace):

    store_name = "Casas Bahia"
    search_url = "https://www.casasbahia.com.br/busca/{}"
    base_domain = "https://www.casasbahia.com.br"
    product_markers = ("/p/", "/p", "/produto/")
    ignore_markers = ("/busca/", "/login", "/carrinho", "/categoria/")
