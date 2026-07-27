import sys
import time

from src.stores.mercado_livre import (
    MercadoLivre,
    MercadoLivreBlockedError,
)


def main():
    terms = sys.argv[1:] or ["ssd 1tb", "memória ram notebook 16gb"]
    for term in terms:
        started = time.perf_counter()
        try:
            products = MercadoLivre().search(term)
            print(f"term={term}")
            print(f"valid_products={len(products)}")
            for index, product in enumerate(products[:10], 1):
                print(
                    f"{index}. {product['titulo']} | {product['preco']} | "
                    f"{product['link']} | image={bool(product['imagem'])}"
                )
        except MercadoLivreBlockedError as error:
            print(f"term={term}")
            print("controlled_status=blocked")
            print(f"reason={error}")
            print("valid_products=0 (não interpretado como sucesso)")
        finally:
            print(f"elapsed_seconds={time.perf_counter() - started:.3f}")


if __name__ == "__main__":
    main()
