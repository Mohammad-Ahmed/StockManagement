SOLESTOCK BUILD 15 + 16 FIXED INSTALLER

This package replaces the broken PowerShell installer with Python scripts.
The Python installer avoids PowerShell quote, here-string, encoding, and terminator errors.

INSTALL FROM THE SOLESTOCK REPOSITORY ROOT

1. Extract this ZIP.
2. Copy the extracted solestock_build15_16_fixed folder into the repository root.
3. Run:
   python .\solestock_build15_16_fixed\install_build15_16.py
4. Verify:
   python .\solestock_build15_16_fixed\verify_build15_16.py
5. Deploy:
   uv run pywrangler deploy
6. Open:
   /?build=16
   /product/?id=<product-id>&build=16
7. Press Ctrl+F5.

CHANGES
- Home Stock Alerts: Brand + Category filters, Apply, Clear.
- Removes Product-name alert filter.
- Product form: replaces corrupted repeated remove symbol with &times;.
- Adds compact Render-compatible remove-button CSS.

SAFETY
- Creates .before-build16.bak backups beside both modified HTML files.
- Does not change Worker, D1, R2, products, sizes, quantities, or images.
