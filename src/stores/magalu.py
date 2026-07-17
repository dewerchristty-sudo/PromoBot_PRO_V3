from src.stores.generic_marketplace import GenericMarketplace


class Magalu(GenericMarketplace):

    store_name = "Magalu"
    search_url = "https://www.magazineluiza.com.br/busca/{}/"
    base_domain = "https://www.magazineluiza.com.br"
    product_markers = ("/p/", "/p", "/produto/")
    ignore_markers = ("/busca/", "/login", "/sacola", "/departamento/")
