SOLESTOCK R2 MIGRATION FIX - BUILD 13

Replace only:
scripts/migrate_cloudinary_to_r2.py

The rest of Build 12 stays unchanged.

Fixes:
- retains the HttpOnly session cookie using CookieJar
- sends a normal User-Agent
- verifies /health before asking for credentials
- verifies /api/session immediately after login
- displays the actual server error body for HTTP errors
- asks for confirmation before writing
- skips images already on R2
- rolls back a new R2 object if the D1 update fails
- writes scripts/r2_migration_log.csv after every product

Run:
python .\scripts\migrate_cloudinary_to_r2.py
