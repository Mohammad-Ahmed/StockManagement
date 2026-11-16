from pathlib import Path
import sys

root = Path.cwd()
home_path = root / "public" / "index.html"
product_path = root / "public" / "product" / "index.html"
css_path = root / "public" / "build16.css"

for path in (home_path, product_path, css_path):
    if not path.exists():
        raise SystemExit(f"FAILED: Missing {path}")

home = home_path.read_text(encoding="utf-8")
product = product_path.read_text(encoding="utf-8")
css = css_path.read_text(encoding="utf-8")

checks = {
    "Brand alert filter exists": 'id="stockAlertBrandFilter"' in home,
    "All brands option exists": "All brands" in home,
    "Product alert filter removed": "stockAlertProductFilter" not in home,
    "Category filter retained": 'id="stockAlertCategoryFilter"' in home,
    "Apply retained": 'id="stockAlertFilters"' in home,
    "Clear retained": 'id="clearStockAlertFilters"' in home,
    "Brand filter logic exists": "clean(item.brand).toLowerCase()===brand" in home,
    "Edit article retained": "/product/?id=${num(x.id)}" in home,
    "Remove button exists": 'class="remove"' in product,
    "Safe remove entity exists": "&times;" in product,
    "Mojibake absent": not any(x in product for x in ("Ã—", "Â×", "Ä—", "Ãƒâ€”", "Ã‚×")),
    "Build 16 CSS linked": "/build16.css?v=16" in product,
    "Remove CSS exists": ".size-row .remove" in css,
    "Pseudo-elements disabled": "content: none !important" in css,
}

width = max(len(key) for key in checks)
for key, value in checks.items():
    print(f"{key:<{width}} : {'PASS' if value else 'FAIL'}")

if not all(checks.values()):
    raise SystemExit("Verification failed.")
print("All Build 15 + Build 16 checks passed.")
