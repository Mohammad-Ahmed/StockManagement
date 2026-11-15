SOLESTOCK RENDER PRODUCT BUILD 10

Fix: Brand product counts now use COUNT(DISTINCT p.id), so size joins cannot multiply product counts.
Next feature: Add/Edit Product using the Render product_form.html layout and classes.
No stock adjustment buttons are included.
Image upload is intentionally deferred to R2; existing Cloudinary images are preserved on edits.

Install: copy pyproject.toml, wrangler.jsonc, src and public to repo root, replace all, then run:
uv sync
uv run python -m py_compile .\src\worker.py
uv run pywrangler deploy

Verify /health build 10, /api/brands counts, /product/ add, /product/?id=ID edit, /stocks/ display.
