from pathlib import Path
import shutil

ROOT = Path.cwd()
STOCKS = ROOT / "public" / "stocks" / "index.html"
PRODUCT = ROOT / "public" / "product" / "index.html"

for path in (STOCKS, PRODUCT):
    if not path.exists():
        raise SystemExit(f"ERROR: Missing {path}. Run this script from the SoleStock repository root.")
    backup = path.with_suffix(path.suffix + ".before-build17.bak")
    if not backup.exists():
        shutil.copy2(path, backup)

stocks = STOCKS.read_text(encoding="utf-8")

old_edit = "const edit=node('a','icon-button','Edit');edit.href=`/product/?id=${id}`;"
new_edit = "const edit=node('a','icon-button','Edit');edit.href=`/product/?id=${id}&return=${encodeURIComponent(buildStocksReturnUrl())}`;"
if old_edit in stocks:
    stocks = stocks.replace(old_edit, new_edit, 1)
elif new_edit not in stocks:
    raise SystemExit("ERROR: Could not find the Stocks Edit-link code.")

helper_anchor = "function createProductCard(product){"
helper = """function buildStocksReturnUrl(){
  const params=new URLSearchParams();
  const search=ui.search.value.trim();
  if(search)params.set('q',search);
  if(ui.brand.value)params.set('brand',ui.brand.value);
  if(ui.category.value)params.set('category',ui.category.value);
  if(ui.size.value)params.set('size',ui.size.value);
  if(ui.status.value)params.set('status',ui.status.value);
  const query=params.toString();
  return query?`/stocks/?${query}`:'/stocks/';
}
function restoreStocksFilters(){
  const params=new URLSearchParams(location.search);
  ui.search.value=params.get('q')||'';
  ui.brand.value=params.get('brand')||'';
  ui.category.value=params.get('category')||'';
  ui.size.value=params.get('size')||'';
  ui.status.value=params.get('status')||'';
  ui.tabs.querySelectorAll('[data-brand]').forEach(button=>button.classList.toggle('selected',button.dataset.brand===ui.brand.value));
}
"""
if "function buildStocksReturnUrl()" not in stocks:
    if helper_anchor not in stocks:
        raise SystemExit("ERROR: Could not find createProductCard() in Stocks page.")
    stocks = stocks.replace(helper_anchor, helper + "\n" + helper_anchor, 1)

old_load = "setupFilters();renderProducts();ui.loading.hidden=true;"
new_load = "setupFilters();restoreStocksFilters();renderProducts();ui.loading.hidden=true;"
if old_load in stocks:
    stocks = stocks.replace(old_load, new_load, 1)
elif new_load not in stocks:
    raise SystemExit("ERROR: Could not find the Stocks load/render sequence.")

STOCKS.write_text(stocks, encoding="utf-8", newline="\n")

product = PRODUCT.read_text(encoding="utf-8")

old_declaration = "const $=id=>document.getElementById(id),params=new URLSearchParams(location.search),productId=params.get('id');"
new_declaration = "const $=id=>document.getElementById(id),params=new URLSearchParams(location.search),productId=params.get('id'),requestedReturn=params.get('return')||'/stocks/',returnUrl=requestedReturn.startsWith('/stocks/')&&!requestedReturn.startsWith('//')?requestedReturn:'/stocks/';"
if old_declaration in product:
    product = product.replace(old_declaration, new_declaration, 1)
elif new_declaration not in product:
    raise SystemExit("ERROR: Could not find the Product-page URL declaration.")

old_cancel = '<a class="button ghost" href="/stocks/">Cancel</a>'
new_cancel = '<a id="cancelButton" class="button ghost" href="/stocks/">Cancel</a>'
if old_cancel in product:
    product = product.replace(old_cancel, new_cancel, 1)
elif new_cancel not in product:
    raise SystemExit("ERROR: Could not find the Product Cancel link.")

session_anchor = "async function session(){"
cancel_code = "$('cancelButton').href=returnUrl;\n"
if cancel_code not in product:
    if session_anchor not in product:
        raise SystemExit("ERROR: Could not find Product session function.")
    product = product.replace(session_anchor, cancel_code + session_anchor, 1)

old_redirect = "setTimeout(()=>location.replace(`/stocks/?brand=${encodeURIComponent(body.brand)}`),700)"
new_redirect = "setTimeout(()=>location.replace(returnUrl),700)"
if old_redirect in product:
    product = product.replace(old_redirect, new_redirect, 1)
elif new_redirect not in product:
    raise SystemExit("ERROR: Could not find the Product save redirect.")

PRODUCT.write_text(product, encoding="utf-8", newline="\n")

print("Build 17 installed successfully.")
print("Stocks Edit now carries the active search and filter state.")
print("Save Product and Cancel return to the same filtered Stocks view.")
