SOLESTOCK PERFORMANCE BUILD 18

Validated low-risk changes based on the supplied Network timings:
- Removes the duplicate /api/session request from Home, Stocks and Brands.
- Protected APIs continue to redirect on HTTP 401.
- Stocks renders the first 30 cards immediately, then remaining cards in animation-frame batches.
- A render generation guard prevents stale cards when filters change during batching.

EXPECTED RESULT
- Approximately 98-101 ms removed from each Home, Stocks and Brands load.
- Stocks becomes interactive sooner after /api/products completes.
- The 829 ms /api/products and 676 ms /api/home server times are not cached or hidden.
  Server-side D1 batching and R2 custom-domain delivery should be handled separately after measurement.

INSTALL
1. Extract the ZIP and copy the solestock_performance_build18 folder into the repository root.
2. Run:
   python .\solestock_performance_build18\install_performance_build18.py
3. Verify:
   python .\solestock_performance_build18\verify_performance_build18.py
4. Deploy:
   uv run pywrangler deploy
5. Open Home, Stocks and Brands with ?performance=18 and press Ctrl+F5.
6. Compare Network timings. The separate session fetch should be absent.

FILES MODIFIED
- public/index.html
- public/stocks/index.html
- public/brands/index.html

BACKUPS CREATED
- *.before-performance18.bak

NOT CHANGED
- worker.py
- D1 queries or data
- R2 objects or images
- authentication rules
- product/brand functionality
- Render-based UI
