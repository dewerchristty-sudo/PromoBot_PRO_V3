import sys
from pathlib import Path
import json
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.browser_manager import BrowserManager


def main():
    b = BrowserManager(headless=True)
    p = b.new_page(stealth=True)
    verify_detected = False
    try:
        p.goto('https://shopee.com.br/search?keyword=ssd+1tb', wait_until='domcontentloaded', timeout=60000)
        p.wait_for_timeout(3000)
        url = p.url or ''
        if '/verify/traffic/error' in url.lower():
            verify_detected = True
        else:
            try:
                content = p.content().lower()
                if 'verify/traffic/error' in content or 'redirect_to_error_page' in content:
                    verify_detected = True
            except Exception:
                pass
    finally:
        b.close()

    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    disabled_file = logs / 'disabled_stores.json'

    data = {}
    if disabled_file.exists():
        try:
            data = json.loads(disabled_file.read_text(encoding='utf-8') or '{}')
        except Exception:
            data = {}

    if verify_detected:
        expiry = (datetime.now() + timedelta(minutes=60)).isoformat(timespec='seconds')
        data['Shopee'] = expiry
        print('Shopee verify detected — disabled until', expiry)
    else:
        # remove Shopee if present
        if 'Shopee' in data:
            del data['Shopee']
            print('Shopee appears ok — removed from disabled list')
        else:
            print('Shopee appears ok')

    disabled_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
