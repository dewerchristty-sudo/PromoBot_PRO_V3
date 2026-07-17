import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup

from src.core.browser_manager import BrowserManager


def main():

    if len(sys.argv) < 2:
        print("Uso: python scripts\\inspect_store_structure.py <url>")
        return

    url = sys.argv[1]
    browser = BrowserManager(headless=False)
    page = browser.new_page()

    try:

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(12000)

        print("title:", page.title())
        print("url:", page.url)
        print("anchors:", page.locator("a").count())
        print("json scripts:", page.locator("script[type='application/json'], script#__NEXT_DATA__").count())
        print()
        print("body:")
        print(page.locator("body").inner_text(timeout=5000)[:3000])

        soup = BeautifulSoup(page.content(), "lxml")
        links = []

        for anchor in soup.select("a[href]"):
            href = anchor.get("href") or ""

            if "produto" in href or "/p/" in href or "product" in href:
                links.append((href, anchor.get_text(" ", strip=True)[:160]))

        print()
        print("product-like links:", len(links))

        for href, text in links[:20]:
            print("-", href, "|", text)

    finally:

        browser.close()


if __name__ == "__main__":
    main()
