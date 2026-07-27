import os
import time
from urllib.parse import quote

# Impede que configurações herdadas abram o Inspector ou suspendam a página.
for debug_variable in (
    "PWDEBUG",
    "PLAYWRIGHT_DEBUG",
    "PLAYWRIGHT_INSPECTOR",
):
    os.environ.pop(debug_variable, None)

from bs4 import BeautifulSoup

from src.stores.mercado_livre import MercadoLivre
from src.stores.mercado_livre_browser import MercadoLivrePersistentContext


def print_tabs(context, active=None):
    print("\nAbas abertas:")
    for index, tab in enumerate(context.pages, 1):
        marker = " [ATIVA]" if tab is active else ""
        print(f"  {index}. {tab.url}{marker}")


def close_auxiliary_blank_tabs(context, active):
    for tab in tuple(context.pages):
        if tab is active or tab.is_closed():
            continue
        if tab.url in ("", "about:blank"):
            tab.close()


def mercado_livre_tab(context, current=None):
    pages = [tab for tab in context.pages if not tab.is_closed()]
    mercado_pages = [
        tab for tab in pages if "mercadolivre.com.br" in tab.url.casefold()
    ]
    selected = (
        mercado_pages[-1]
        if mercado_pages
        else current if current in pages
        else pages[-1] if pages
        else context.new_page()
    )
    selected.bring_to_front()
    close_auxiliary_blank_tabs(context, selected)
    return selected


def main():
    session = MercadoLivrePersistentContext(headless=False)
    context = session.start()
    # Um contexto persistente normalmente nasce com about:blank. Reutilizar
    # essa aba evita uma segunda janela auxiliar "Chrome for Testing".
    page = context.pages[0] if context.pages else context.new_page()
    context.add_init_script("""
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
""")
    store = MercadoLivre.__new__(MercadoLivre)
    started = time.perf_counter()
    try:
        page.goto(
            "https://www.mercadolivre.com.br/",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.bring_to_front()
        close_auxiliary_blank_tabs(context, page)
        print("Perfil:", session.profile_path)
        print("Perfil criado:", session.profile_created)
        print("Perfil reutilizado:", session.profile_reused)
        print("Modo de depuração: desativado")
        print_tabs(context, page)
        print(
            "Mercado Livre exige validação da sessão.\n"
            "Conclua o acesso no navegador aberto.\n"
            "A página continuará funcionando enquanto o terminal aguarda.\n"
            "Pressione ENTER somente quando o login estiver concluído."
        )
        input("Pressione ENTER após concluir o acesso/verificação...")
        page = mercado_livre_tab(context, page)
        print_tabs(context, page)
        requested = (
            "https://lista.mercadolivre.com.br/"
            + quote("ssd-1tb", safe="-")
        )
        page.goto(
            requested, wait_until="domcontentloaded", timeout=60000
        )
        page.wait_for_timeout(4000)
        page = mercado_livre_tab(context, page)
        html = page.content()
        blocked = store.block_reason(page.url, page.title(), html)
        cards, counts = store.find_cards(BeautifulSoup(html, "lxml"))
        products = store.parse_cards(cards)
        print("URL solicitada:", requested)
        print("URL final:", page.url)
        print_tabs(context, page)
        print("Status da sessão:", "bloqueada" if blocked else "liberada")
        print("Motivo:", blocked or "nenhum")
        print("Seletores:", counts)
        print("Cards brutos:", len(cards))
        print("Produtos válidos e únicos:", len(products))
        for product in products[:10]:
            print(
                product["titulo"], "|", product["preco"], "|",
                product["link"], "| imagem:", bool(product["imagem"])
            )
        print("Perfil salvo:", session.profile_path.exists())
        print(f"Tempo: {time.perf_counter() - started:.3f}s")
        input("Pressione ENTER para fechar o navegador...")
    finally:
        session.close()


if __name__ == "__main__":
    main()
