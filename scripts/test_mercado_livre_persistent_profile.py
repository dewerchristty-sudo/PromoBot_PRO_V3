import sys
import time

from src.stores.mercado_livre import (
    MercadoLivre,
    MercadoLivreBlockedError,
)
from src.stores.mercado_livre_browser import MercadoLivrePersistentContext


def main():
    term = " ".join(sys.argv[1:]).strip() or "ssd 1tb"
    session = MercadoLivrePersistentContext()
    store = MercadoLivre(session)
    started = time.perf_counter()
    try:
        products = store.search(term)
        print("Perfil criado:", session.profile_created)
        print("Perfil reutilizado:", session.profile_reused)
        print("Status da sessão: liberada")
        print("Produtos válidos e únicos:", len(products))
        for product in products[:10]:
            print(
                product["titulo"], "|", product["preco"], "|",
                product["link"], "| imagem:", bool(product["imagem"])
            )
    except MercadoLivreBlockedError as error:
        print("Perfil criado:", session.profile_created)
        print("Perfil reutilizado:", session.profile_reused)
        print("Status da sessão: expirada ou bloqueada")
        print("Motivo:", error)
        print(
            "Execute novamente scripts.setup_mercado_livre_profile "
            "para validação manual."
        )
    finally:
        print(f"Tempo: {time.perf_counter() - started:.3f}s")


if __name__ == "__main__":
    main()
