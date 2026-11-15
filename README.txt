SOLESTOCK CLOUDFLARE FIXED BUILD 2

WHY THIS FIXES THE LOADING SCREEN
- All Stocks-page JavaScript is embedded directly inside public/stocks/index.html.
- The browser no longer depends on /stocks.js, MIME types, or an old cached JavaScript file.
- /api/products now returns an explicit brands list from the D1 brand table.
- /api/debug shows the actual remote D1 counts and build number.

REPLACE THESE ITEMS IN THE ROOT OF cloudflare-migration:
- pyproject.toml
- wrangler.jsonc
- src folder
- public folder

RUN:
uv sync
uv run python -m py_compile .\src\worker.py
uv run pywrangler deploy

VERIFY:
https://solestock-cloudflare.mohammadahmedpanjwani.workers.dev/api/debug
Expected build: 2 and non-zero products/sizes/brands.

https://solestock-cloudflare.mohammadahmedpanjwani.workers.dev/api/products
Expected build: 2, a brands array, products array, and size_row_count > 0.

OPEN:
https://solestock-cloudflare.mohammadahmedpanjwani.workers.dev/stocks/?build=2
Then Ctrl+F5.

A small 'Cloudflare build 2' label confirms the new HTML is live.
