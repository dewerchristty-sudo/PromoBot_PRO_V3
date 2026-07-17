import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.browser_manager import BrowserManager


def main():

    browser = BrowserManager(headless=False)
    page = browser.new_page()

    try:

        page.goto(
            "https://shopee.com.br/search?keyword=ssd+1tb",
            wait_until="domcontentloaded",
            timeout=60000
        )
        page.wait_for_timeout(10000)

        print("title", page.title())
        print("url", page.url)
        print(
            "links",
            page.locator(
                "a[href*='-i.'], a[href*='/product/']"
            ).count()
        )

    finally:

        browser.close()


if __name__ == "__main__":
    main()
