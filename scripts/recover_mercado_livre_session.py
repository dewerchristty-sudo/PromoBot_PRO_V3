import os
import time
import json
from pathlib import Path
from urllib.parse import quote

for variable in ("PWDEBUG", "PLAYWRIGHT_DEBUG", "PLAYWRIGHT_INSPECTOR"):
    os.environ.pop(variable, None)

from bs4 import BeautifulSoup

from scripts.setup_mercado_livre_profile import (
    close_auxiliary_blank_tabs, mercado_livre_tab, print_tabs,
)
from src.stores.mercado_livre import MercadoLivre
from src.stores.mercado_livre_browser import MercadoLivrePersistentContext


def classify_session(url, title="", html=""):
    text = f"{url}\n{title}\n{html[:200000]}".casefold()
    if "account-verification" in text or "captcha" in text:
        return "VERIFICATION_REQUIRED"
    if any(marker in text for marker in (
        "/login", "login_required", "iniciar sessao", "entrar na sua conta",
    )):
        return "LOGIN_REQUIRED"
    if any(marker in text for marker in (
        "access denied", "temporarily blocked", "bloqueado temporariamente",
    )):
        return "BLOCKED_TEMPORARILY"
    if "mercadolivre.com.br" in str(url).casefold():
        return "SESSION_READY"
    return "UNKNOWN_SESSION_STATE"


def main(
    input_fn=input, query="ssd 1tb",
    session_factory=MercadoLivrePersistentContext, store=None,
):
    session = session_factory(headless=False)
    context = session.start()
    page = context.pages[0] if context.pages else context.new_page()
    store = store or MercadoLivre.__new__(MercadoLivre)
    started = time.perf_counter()
    try:
        page.goto(
            "https://www.mercadolivre.com.br/",
            wait_until="domcontentloaded", timeout=60000,
        )
        page = mercado_livre_tab(context, page)
        close_auxiliary_blank_tabs(context, page)
        status = classify_session(page.url, page.title(), page.content())
        print("Perfil reutilizado:", session.profile_reused)
        print("Estado inicial:", status)
        print_tabs(context, page)
        if status != "SESSION_READY":
            print(
                "Conclua manualmente o login ou a verificacao no navegador. "
                "O PromoBot nao contorna CAPTCHA e nao armazena senha."
            )
            input_fn(
                "Pressione ENTER somente depois que a verificacao terminar..."
            )
            page = mercado_livre_tab(context, page)
            status = classify_session(
                page.url, page.title(), page.content()
            )
        requested = (
            "https://lista.mercadolivre.com.br/"
            + quote(query.strip().replace(" ", "-"), safe="-")
        )
        page.goto(requested, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4500)
        page = mercado_livre_tab(context, page)
        html = page.content()
        final_status = classify_session(page.url, page.title(), html)
        cards, counts = store.find_cards(BeautifulSoup(html, "lxml"))
        products = store.parse_cards(cards)
        if store.block_reason(page.url, page.title(), html):
            final_status = "VERIFICATION_REQUIRED"
        print("Estado final:", final_status)
        print("URL ativa:", page.url)
        print("Cards encontrados:", len(cards))
        print("Produtos validos:", len(products))
        print("Seletores:", counts)
        print("Perfil salvo:", session.profile_path.exists())
        result = {
            "status": final_status,
            "products_collected": len(products),
            "cards": len(cards),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "profile_reused": session.profile_reused,
        }
        output = Path(
            "reports/affiliate_onboarding/"
            "mercado_livre_session_recovery.json"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("Relatorio:", output)
        return result
    finally:
        session.close()


if __name__ == "__main__":
    main()
