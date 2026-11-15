# Shoe Store Stock Management System

A responsive Flask + SQLite inventory application for shoes and sandals.

## Features
- Dashboard summary, brand-wise totals, recent updates, low-stock alerts
- Brands: Sparx, Red Chief, Bata, Nike, Imported Brand
- Shoes and sandals managed separately
- Unique article number per brand
- Size-wise quantities and automatic totals
- Add, edit, delete, search, and filter inventory
- Configurable product and size-level stock thresholds
- Product image upload
- Excel, PDF, and CSV exports for current filters
- Persistent SQLite database

## Run locally
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

The database and uploads are created automatically. Sample products are inserted the first time the application starts.
