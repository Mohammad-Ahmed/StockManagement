from pathlib import Path
import re
import shutil
import sys

ROOT = Path.cwd()
HOME = ROOT / "public" / "index.html"
PRODUCT = ROOT / "public" / "product" / "index.html"
CSS = ROOT / "public" / "build16.css"

for path in (HOME, PRODUCT):
    if not path.exists():
        raise SystemExit(f"ERROR: Missing {path}. Run this from the SoleStock repository root.")

# Backups are created once and never overwritten.
for path in (HOME, PRODUCT):
    backup = path.with_suffix(path.suffix + ".before-build16.bak")
    if not backup.exists():
        shutil.copy2(path, backup)

home = HOME.read_text(encoding="utf-8")

# Build 15: Product filter -> Brand filter.
home = home.replace(
    '<label>Product<select id="stockAlertProductFilter"><option value="">All products</option></select></label>',
    '<label>Brand<select id="stockAlertBrandFilter"><option value="">All brands</option></select></label>',
)

# Replace Build 14 minified filter functions using a bounded regex.
filter_re = re.compile(
    r"function setupAlertFilters\(items\)\{.*?\}"
    r"\s*function selectedAlerts\(\)\{.*?\}"
    r"(?=\s*function alerts)",
    re.DOTALL,
)
filter_code = (
    "function setupAlertFilters(items){"
    "const select=$('stockAlertBrandFilter');"
    "select.replaceChildren(new Option('All brands',''));"
    "const brands=[...new Set(items.map(item=>clean(item.brand)).filter(Boolean))]"
    ".sort((a,b)=>a.localeCompare(b,undefined,{sensitivity:'base'}));"
    "for(const brand of brands)select.add(new Option(brand,brand))}"
    "\nfunction selectedAlerts(){"
    "const brand=$('stockAlertBrandFilter').value.toLowerCase(),"
    "category=$('stockAlertCategoryFilter').value.toLowerCase();"
    "return state.alerts.filter(item=>"
    "(!brand||clean(item.brand).toLowerCase()===brand)&&"
    "(!category||clean(item.category).toLowerCase()===category))}"
)
if "stockAlertProductFilter" in home:
    home, count = filter_re.subn(filter_code, home, count=1)
    if count != 1:
        raise SystemExit("ERROR: Could not replace the old Stock Alert filter functions.")

home = home.replace(
    "$('stockAlertProductFilter').value='';$('stockAlertCategoryFilter').value='';",
    "$('stockAlertBrandFilter').value='';$('stockAlertCategoryFilter').value='';",
)
home = home.replace("/build14.css?v=14", "/build14.css?v=16")
home = home.replace("/style.css?v=14", "/style.css?v=16")

if 'id="stockAlertBrandFilter"' not in home:
    raise SystemExit("ERROR: Brand filter was not inserted.")
if "stockAlertProductFilter" in home:
    raise SystemExit("ERROR: Old product filter still exists.")
if "clean(item.brand).toLowerCase()===brand" not in home:
    raise SystemExit("ERROR: Brand filter logic is missing.")

HOME.write_text(home, encoding="utf-8", newline="\n")

# Build 16: fix corrupted remove-size button.
product = PRODUCT.read_text(encoding="utf-8")
button_patterns = [
    re.compile(r'(<button[^>]*class="remove"[^>]*>).*?(</button>)', re.I | re.S),
    re.compile(r'(<button[^>]*aria-label="Remove size"[^>]*>).*?(</button>)', re.I | re.S),
]
changed = 0
for pattern in button_patterns:
    product, amount = pattern.subn(r'\1&times;\2', product)
    changed += amount

# Handle common mojibake sequences anywhere in the file.
for broken in ("Ã—", "Â×", "Ä—", "Ãƒâ€”", "Ã‚×"):
    product = product.replace(broken, "&times;")

css_link = '<link rel="stylesheet" href="/build16.css?v=16">'
if "/build16.css?v=16" not in product:
    if "</head>" not in product:
        raise SystemExit("ERROR: Product page does not contain </head>.")
    product = product.replace("</head>", f"  {css_link}\n</head>", 1)

if 'class="remove"' not in product:
    raise SystemExit("ERROR: No remove-size button was found.")
if "&times;" not in product:
    raise SystemExit("ERROR: Safe remove symbol was not inserted.")
if any(value in product for value in ("Ã—", "Â×", "Ä—", "Ãƒâ€”", "Ã‚×")):
    raise SystemExit("ERROR: A corrupted remove symbol remains.")

PRODUCT.write_text(product, encoding="utf-8", newline="\n")

CSS.write_text(
    """/* Build 16: Render-compatible size-row remove control. */
.size-row .remove,
.size-row button.remove {
    width: 38px !important;
    min-width: 38px !important;
    max-width: 38px !important;
    height: 42px !important;
    min-height: 42px !important;
    padding: 0 !important;
    align-self: end !important;
    display: inline-grid !important;
    place-items: center !important;
    overflow: hidden !important;
    border: 1px solid #e2bebc !important;
    border-radius: 8px !important;
    color: var(--red) !important;
    background: #fff8f8 !important;
    font-family: Arial, sans-serif !important;
    font-size: 22px !important;
    font-weight: 400 !important;
    line-height: 1 !important;
    text-decoration: none !important;
    white-space: nowrap !important;
    cursor: pointer !important;
}
.size-row .remove:hover,
.size-row button.remove:hover {
    color: #fff !important;
    border-color: var(--red) !important;
    background: var(--red) !important;
}
.size-row .remove::before,
.size-row .remove::after {
    content: none !important;
    display: none !important;
}
@media (max-width: 680px) {
    .size-row .remove,
    .size-row button.remove {
        width: 36px !important;
        min-width: 36px !important;
        max-width: 36px !important;
    }
}
""",
    encoding="utf-8",
    newline="\n",
)

print("Build 15 + Build 16 installed successfully.")
print("Updated public/index.html")
print("Updated public/product/index.html")
print("Created public/build16.css")
