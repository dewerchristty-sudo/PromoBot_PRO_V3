from datetime import datetime
from pathlib import Path
import sys
import time
from urllib.parse import quote

from src.core.browser_manager import BrowserManager


SELECTORS = (
    "li.ui-search-layout__item",
    "div.ui-search-result__wrapper",
    "div.poly-card",
    "div.andes-card.poly-card",
    "ol.ui-search-layout a[href*='/p/']",
    "a[href*='produto.mercadolivre.com.br/MLB-']",
    "a[href*='mercadolivre.com.br/p/MLB']",
)

BLOCK_MARKERS = (
    "captcha", "não sou um robô", "nao sou um robo", "security",
    "segurança", "seguranca", "access denied", "verifique",
)


def main():
    term = " ".join(sys.argv[1:]).strip() or "ssd 1tb"
    file_slug = "_".join(term.casefold().split())
    slug = quote(term.replace(" ", "-"), safe="-")
    requested = f"https://lista.mercadolivre.com.br/{slug}"
    manager = BrowserManager(headless=True)
    page = manager.new_page()
    started = time.perf_counter()
    response = None
    try:
        response = page.goto(
            requested, wait_until="domcontentloaded", timeout=60000
        )
        page.wait_for_timeout(6000)
        for _ in range(4):
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(600)
        html = page.content()
        final_url = page.url
        title = page.title()
        lowered = f"{title}\n{html[:200000]}".casefold()
        counts = {
            selector: page.locator(selector).count()
            for selector in SELECTORS
        }
        blocked = [
            marker for marker in BLOCK_MARKERS if marker in lowered
        ]
        timestamp = datetime.now().isoformat(timespec="seconds")
        Path("logs").mkdir(exist_ok=True)
        Path("logs/mercado_livre_diagnostico.html").write_text(
            html, encoding="utf-8"
        )
        Path(f"logs/mercado_livre_diagnostico_{file_slug}.html").write_text(
            html, encoding="utf-8"
        )
        lines = [
            f"timestamp={timestamp}",
            f"term={term}",
            f"requested_url={requested}",
            f"final_url={final_url}",
            f"redirected={final_url.rstrip('/') != requested.rstrip('/')}",
            f"status={response.status if response else 'sem_resposta'}",
            f"title={title}",
            f"html_bytes={len(html.encode('utf-8'))}",
            f"blocked_markers={blocked}",
            f"elapsed_seconds={time.perf_counter() - started:.3f}",
            "selector_counts:",
            *[f"  {selector}={count}" for selector, count in counts.items()],
        ]
        Path("logs/mercado_livre_diagnostico.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        Path(f"logs/mercado_livre_diagnostico_{file_slug}.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        print("\n".join(lines))
    finally:
        page.close()
        manager.close()


if __name__ == "__main__":
    main()
