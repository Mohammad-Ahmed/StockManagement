SOLESTOCK RENDER BRANDS BUILD 9

Next migration: Brand management.
UI is adapted only from existing Render templates/base.html, templates/brands.html and static/style.css.
No stock increase/decrease/adjust buttons are included.

Features:
- GET /api/brands
- POST /api/brands
- PATCH /api/brands/{id}
- DELETE /api/brands/{id}
- Add brand
- Rename brand and update matching product.brand values
- Delete only unused brands
- Product counts and total pair counts
- Home, Stocks and Brands navigation
- Existing Build 8 Home dashboard and Render-matched Stocks page

INSTALL
1. Use cloudflare-migration branch.
2. Extract ZIP.
3. Copy pyproject.toml, wrangler.jsonc, src and public into repository root.
4. Replace all files.
5. Run:
   uv sync
   uv run python -m py_compile .\src\worker.py
   uv run pywrangler deploy
6. Verify /health shows build 9.
7. Log in and open /api/brands, confirm build 9.
8. Open /brands/?build=9 and test add, rename and delete-unused.
9. Recheck /?build=9 and /stocks/?build=9.
