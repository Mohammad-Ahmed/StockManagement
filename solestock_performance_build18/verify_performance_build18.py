from pathlib import Path

root = Path.cwd()
home = (root / "public" / "index.html").read_text(encoding="utf-8")
stocks = (root / "public" / "stocks" / "index.html").read_text(encoding="utf-8")
brands = (root / "public" / "brands" / "index.html").read_text(encoding="utf-8")

checks = {
    "Home no longer waits for /api/session": "const session=await api('/api/session')" not in home,
    "Home still loads protected API": "const d=await api('/api/home')" in home,
    "Stocks startup skips requireSession": "await requireSession();await loadProducts()" not in stocks,
    "Stocks still loads products": "await loadProducts()" in stocks,
    "Stocks batch renderer exists": "function appendProductBatch(" in stocks,
    "Stocks batch size is 30": "batchSize=30" in stocks,
    "Stocks uses requestAnimationFrame": "requestAnimationFrame(" in stocks,
    "Stocks cancels stale renders": "renderGeneration" in stocks,
    "Brands startup skips requireSession": "await requireSession();await loadBrands()" not in brands,
    "Brands still loads protected API": "await loadBrands()" in brands,
    "401 handling remains on Home": "r.status===401" in home,
    "401 handling remains on Stocks": "response.status===401" in stocks,
    "401 handling remains on Brands": "response.status===401" in brands,
}
width = max(len(name) for name in checks)
for name, passed in checks.items():
    print(f"{name:<{width}} : {'PASS' if passed else 'FAIL'}")
if not all(checks.values()):
    raise SystemExit("Performance Build 18 verification failed.")
print("All Performance Build 18 checks passed.")
