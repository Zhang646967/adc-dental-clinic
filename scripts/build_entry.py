"""Build the portable loopback entry from the same curated HTTP content."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adc_core.entry_catalog import ENTRY_ROUTES, render_entry
from adc_core.route_manifest import named_routes


def main():
    routes = named_routes(ROOT)
    html = render_entry({name: routes[name] for name in ENTRY_ROUTES}, standalone=True)
    (ROOT / 'START_HERE.html').write_text(html, encoding='utf-8')
    print('Built portable entry with six business routes; application/database not modified.')


if __name__ == '__main__':
    main()
