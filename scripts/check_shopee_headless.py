import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.browser_manager import BrowserManager


def main():
    for stealth in (True, False):
        print('\n--- stealth=', stealth)
        b = BrowserManager(headless=True)
        p = b.new_page(stealth=stealth)
        try:
            p.goto('https://shopee.com.br/search?keyword=ssd+1tb', wait_until='domcontentloaded', timeout=60000)
            p.wait_for_timeout(5000)
            print('url=', p.url)
            try:
                title = p.title()
            except Exception:
                title = '<no title>'
            print('title=', title)
            content = ''
            try:
                content = p.content()
            except Exception:
                pass
            print('content_len=', len(content))
            try:
                links_count = p.locator("a[href*='-i.'], a[href*='/product/']").count()
            except Exception as e:
                links_count = f'ERROR: {e}'
            print('links_count=', links_count)
        finally:
            b.close()


if __name__ == '__main__':
    main()
