SOLESTOCK UI FIX BUILD 14

Updated files:
- public/index.html
- public/build14.css

Fixes:
- Edit article opens /product/?id=<product_id>
- Product filter in Stock Alerts
- Shoes/Sandals category filter in Stock Alerts
- Apply and Clear filters
- Product edit image uses object-fit: contain
- "No image uploaded" placeholder is hidden when a current image exists

INSTALL
1. Extract ZIP.
2. Copy the public folder into the repository root.
3. Replace public/index.html and add public/build14.css.
4. No Worker, D1, R2, wrangler or database changes are required.
5. Deploy: uv run pywrangler deploy
6. Open /?build=14 and Ctrl+F5.
7. Open /product/?id=<id>; build14.css is loaded only by Home currently. Add the line below to public/product/index.html head if not already present:
   <link rel="stylesheet" href="/build14.css?v=14">

For convenience, apply_product_css.ps1 is included to add this link safely.
