SOLESTOCK RENDER-MATCHED BUILD 7

This build deliberately uses the same class names and card structure as the original Render stocks.html:
product-grid, product-card, photo, status, product-body, article, sizes, product-foot, icon-button.

It also uses the Render sizing rules:
- 3-column grid
- 260px image section
- product-body as a visible flex column
- size badge is 43px wide
- product-foot is pinned to the bottom

INSTALL
1. Use cloudflare-migration branch.
2. Extract ZIP.
3. Copy pyproject.toml, wrangler.jsonc, src and public into the repository root.
4. Replace all files.
5. Run:
   uv sync
   uv run python -m py_compile .\src\worker.py
   uv run pywrangler deploy
6. Verify /health shows build 7.
7. After login, verify /api/products shows build 7.
8. Open /stocks/?build=7 and press Ctrl+F5.

Required secrets: SESSION_SECRET, LOGIN_USER_ID, LOGIN_PASSWORD
