MAHARASHTRA BOOT HOUSE - PRE-OPTIMIZATION ROLLBACK PACKAGE

This package restores the previous code version from before the D1 read-cache optimization.
It does NOT include cache_seconds, private API caching, the D1 optimization migration, or the frontend cache patcher.

RECOMMENDED USE WITH YOUR NEW CLONE
1. Extract this ZIP outside the cloned repository.
2. Open PowerShell in the cloned repository root.
3. Run the installer from the extracted location, for example:
   & "C:\Users\YOUR_NAME\Downloads\mbh_previous_version_rollback\install_rollback.ps1"
4. Run:
   uv sync
5. Check:
   uv run pywrangler --version
6. Deploy:
   uv run pywrangler deploy
7. Open the website in InPrivate mode or press Ctrl+F5.

FILES RESTORED
- src/worker.py
- public/index.html

The rest of the website should remain from the clean Git clone. That is safer than replacing the complete repository with reconstructed files.
The installer also removes optimization-only files if they exist and restores any *.before-d1-cache.bak frontend backups.

D1 DATA AND R2 IMAGES
This rollback changes Worker code and the dashboard file only. It does not delete D1 data or R2 images.
Previously created D1 indexes can safely remain; they do not change the stored data.
