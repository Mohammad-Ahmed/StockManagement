from pathlib import Path

root = Path.cwd()
stocks_path = root / "public" / "stocks" / "index.html"
product_path = root / "public" / "product" / "index.html"

stocks = stocks_path.read_text(encoding="utf-8")
product = product_path.read_text(encoding="utf-8")

checks = {
    "Stocks return URL builder exists": "function buildStocksReturnUrl()" in stocks,
    "Search term is preserved": "params.set('q',search)" in stocks,
    "Brand is preserved": "params.set('brand',ui.brand.value)" in stocks,
    "Category is preserved": "params.set('category',ui.category.value)" in stocks,
    "Size is preserved": "params.set('size',ui.size.value)" in stocks,
    "Status is preserved": "params.set('status',ui.status.value)" in stocks,
    "Edit carries return URL": "return=${encodeURIComponent(buildStocksReturnUrl())}" in stocks,
    "Stocks restores filters": "restoreStocksFilters();renderProducts()" in stocks,
    "Product reads safe return URL": "requestedReturn.startsWith('/stocks/')" in product,
    "Cancel returns to previous view": "$('cancelButton').href=returnUrl" in product,
    "Save returns to previous view": "setTimeout(()=>location.replace(returnUrl),700)" in product,
    "Old brand-only redirect removed": "location.replace(`/stocks/?brand=${encodeURIComponent(body.brand)}`)" not in product,
}

width = max(len(name) for name in checks)
for name, passed in checks.items():
    print(f"{name:<{width}} : {'PASS' if passed else 'FAIL'}")
if not all(checks.values()):
    raise SystemExit("Build 17 verification failed.")
print("All Build 17 checks passed.")
