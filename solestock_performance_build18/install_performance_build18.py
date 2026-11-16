from pathlib import Path
import re
import shutil

ROOT = Path.cwd()
FILES = {
    "home": ROOT / "public" / "index.html",
    "stocks": ROOT / "public" / "stocks" / "index.html",
    "brands": ROOT / "public" / "brands" / "index.html",
}

for path in FILES.values():
    if not path.exists():
        raise SystemExit(f"ERROR: Missing {path}. Run from the repository root.")
    backup = path.with_suffix(path.suffix + ".before-performance18.bak")
    if not backup.exists():
        shutil.copy2(path, backup)

# HOME: protected /api/home already handles 401, so remove serial /api/session request.
home = FILES["home"].read_text(encoding="utf-8")
old_home = "const session=await api('/api/session');$('currentUser').textContent=session.user_id||'admin';const d=await api('/api/home')"
new_home = "$('currentUser').textContent='admin';const d=await api('/api/home')"
if old_home in home:
    home = home.replace(old_home, new_home, 1)
elif new_home not in home:
    raise SystemExit("ERROR: Could not find Home load() session sequence.")
FILES["home"].write_text(home, encoding="utf-8", newline="\n")

# BRANDS: /api/brands is protected and api() already redirects on 401.
brands = FILES["brands"].read_text(encoding="utf-8")
old_start = "(async()=>{try{await requireSession();await loadBrands()}catch(error)"
new_start = "(async()=>{try{await loadBrands()}catch(error)"
if old_start in brands:
    brands = brands.replace(old_start, new_start, 1)
elif new_start not in brands:
    raise SystemExit("ERROR: Could not find Brands startup sequence.")
FILES["brands"].write_text(brands, encoding="utf-8", newline="\n")

# STOCKS: remove serial session check and render product cards in batches.
stocks = FILES["stocks"].read_text(encoding="utf-8")
old_stock_start = "(async()=>{try{await requireSession();await loadProducts()}catch(error)"
new_stock_start = "(async()=>{try{await loadProducts()}catch(error)"
if old_stock_start in stocks:
    stocks = stocks.replace(old_stock_start, new_stock_start, 1)
elif new_stock_start not in stocks:
    raise SystemExit("ERROR: Could not find Stocks startup sequence.")

# Replace the minified synchronous renderer used by the current Render-matched page.
old_render = "function renderProducts(){const products=getFilteredProducts();ui.count.textContent=`${products.length} ${products.length===1?'matching article':'matching articles'}`;ui.grid.replaceChildren();if(products.length){for(const product of products)ui.grid.appendChild(createProductCard(product))}else{const empty=node('div','empty-state');empty.appendChild(node('h2','','No products found'));empty.appendChild(node('p','','Change the filters or add a new product.'));ui.grid.appendChild(empty)}}"
new_render = """let renderGeneration=0;
function appendProductBatch(products,start,generation,batchSize=30){
  if(generation!==renderGeneration)return;
  const end=Math.min(start+batchSize,products.length);
  const fragment=document.createDocumentFragment();
  for(let index=start;index<end;index+=1)fragment.appendChild(createProductCard(products[index]));
  ui.grid.appendChild(fragment);
  if(end<products.length)requestAnimationFrame(()=>appendProductBatch(products,end,generation,batchSize));
}
function renderProducts(){const products=getFilteredProducts();ui.count.textContent=`${products.length} ${products.length===1?'matching article':'matching articles'}`;ui.grid.replaceChildren();renderGeneration+=1;const generation=renderGeneration;if(products.length){appendProductBatch(products,0,generation,30)}else{const empty=node('div','empty-state');empty.appendChild(node('h2','','No products found'));empty.appendChild(node('p','','Change the filters or add a new product.'));ui.grid.appendChild(empty)}}"""
if old_render in stocks:
    stocks = stocks.replace(old_render, new_render, 1)
elif "function appendProductBatch(" not in stocks:
    raise SystemExit("ERROR: Could not find the current Stocks renderProducts() implementation.")
FILES["stocks"].write_text(stocks, encoding="utf-8", newline="\n")

print("Performance Build 18 installed successfully.")
print("- Removed duplicate session request from Home, Stocks, and Brands.")
print("- Stocks now renders cards in batches of 30.")
print("- No API, D1, R2, product, image, or inventory data was changed.")
