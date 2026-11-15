SOLESTOCK RENDER DELETE + CSV BUILD 11

Next migration step:
- Delete Product
- CSV stock export

UI continues to use the previous Render stocks.html/base.html/style.css structure.
No plus, minus, adjust, or stock-update buttons are included.

Delete behavior:
- authenticated DELETE /api/product/{id}
- removes stock_movement, size_stock and product rows
- browser confirmation before deletion
- existing Cloudinary asset cleanup is deferred until R2 migration

CSV behavior:
- authenticated GET /api/export/csv
- same Render report columns:
  Brand, Article Name, Product Name, Category, Available Sizes,
  Size-wise Quantities, Total Quantity, Stock Status, Updated At
- UTF-8 BOM for Excel compatibility

INSTALL
1. Use cloudflare-migration branch.
2. Extract ZIP.
3. Copy pyproject.toml, wrangler.jsonc, src and public into repository root.
4. Replace all files.
5. Run:
   uv sync
   uv run python -m py_compile .\src\worker.py
   uv run pywrangler deploy
6. Verify /health shows build 11.
7. Recheck Home, Stocks, Brands, Add and Edit.
8. Test deletion only with a temporary product.
9. Download CSV and compare totals with the Stocks page.
