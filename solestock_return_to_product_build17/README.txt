SOLESTOCK BUILD 17 - RETURN TO EDITED PRODUCT

Behavior:
- Search for article 651 on Stocks.
- Click Edit on product 651.
- Change quantity/details and Save Product.
- Browser returns to /stocks/?q=651 and displays the same filtered product.

Also preserves:
- Brand filter
- Category filter
- Size filter
- Stock-status filter
- Combined filters

Cancel behaves the same way and returns to the previous filtered Stocks view.
The return path is restricted to /stocks/ to prevent unsafe external redirects.

INSTALL
1. Extract this ZIP and copy the folder into the SoleStock repository root.
2. From the repository root run:
   python .\solestock_return_to_product_build17\install_build17.py
3. Verify:
   python .\solestock_return_to_product_build17\verify_build17.py
4. Deploy:
   uv run pywrangler deploy
5. Open /stocks/?build=17 and press Ctrl+F5.

FILES MODIFIED
- public/stocks/index.html
- public/product/index.html

Backups are created once:
- public/stocks/index.html.before-build17.bak
- public/product/index.html.before-build17.bak
