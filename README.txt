SOLESTOCK BUILD 4 UPDATE

This update contains the corrected src/worker.py with:
- /health build 4
- /api/session
- /api/login
- /api/logout
- /api/debug
- /api/summary
- /api/home
- /api/products

INSTALL
1. Extract this ZIP.
2. Copy the src folder into the root of your SoleStock repository.
3. Select Replace when asked to replace src/worker.py.
4. Keep your currently working public folder, pyproject.toml, and wrangler.jsonc unchanged.
5. Run:
   uv run python -m py_compile .\src\worker.py
   uv run pywrangler deploy

VERIFY
- /health returns build 4
- Log in
- /api/home returns totals, brands, recent_products, alerts and build 4
