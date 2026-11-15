import csv
import getpass
import http.cookiejar
import json
import mimetypes
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://solestock-cloudflare.mohammadahmedpanjwani.workers.dev"
BASE_URL = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL).rstrip("/")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
LOG_PATH = Path(__file__).resolve().parent / "r2_migration_log.csv"

cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 SoleStock-R2-Migration/2.0"),
    ("Accept", "application/json"),
]


def error_text(error):
    try:
        raw = error.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        return payload.get("error") or payload.get("message") or raw
    except Exception:
        return str(error)


def open_url(path_or_url, method="GET", data=None, headers=None, timeout=60):
    url = path_or_url if path_or_url.startswith(("http://", "https://")) else BASE_URL + path_or_url
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        return opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"{method} {url} failed with HTTP {error.code}: {error_text(error)}"
        ) from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach {url}: {error.reason}") from None


def json_request(path, method="GET", payload=None, timeout=60):
    body = None
    headers = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
    with open_url(path, method, body, headers, timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def preflight():
    health = json_request("/health")
    build = int(health.get("build", 0))
    if build < 12:
        raise RuntimeError(f"Worker build {build} is deployed. Build 12 or newer is required.")
    print(f"Connected to {BASE_URL} (Worker build {build}).")


def sign_in():
    user_id = input("SoleStock User ID: ").strip()
    password = getpass.getpass("SoleStock password: ")
    try:
        result = json_request(
            "/api/login",
            "POST",
            {"user_id": user_id, "password": password},
        )
    finally:
        password = None
    if not result.get("authenticated"):
        raise RuntimeError("Login response did not confirm authentication.")
    session = json_request("/api/session")
    if not session.get("authenticated"):
        raise RuntimeError("The login cookie was not retained by the migration script.")
    print(f"Authenticated as {session.get('user_id') or user_id}.")


def is_external_image(url):
    if not url.startswith(("http://", "https://")):
        return False
    return urllib.parse.urlparse(url).netloc.lower() != urllib.parse.urlparse(BASE_URL).netloc.lower()


def download_image(url):
    with open_url(
        url,
        headers={"Accept": "image/avif,image/webp,image/png,image/jpeg,*/*"},
        timeout=120,
    ) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_IMAGE_BYTES:
            raise RuntimeError(f"Image is larger than 5 MB ({declared} bytes).")
        data = response.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise RuntimeError("Image is larger than 5 MB.")
        content_type = response.headers.get_content_type().lower()
        if content_type not in {"image/png", "image/jpeg", "image/webp"}:
            guessed = mimetypes.guess_type(urllib.parse.urlparse(url).path)[0]
            if guessed not in {"image/png", "image/jpeg", "image/webp"}:
                raise RuntimeError(f"Unsupported image type: {content_type}")
            content_type = guessed
        return data, content_type


def upload_image(data, content_type, filename):
    path = "/api/images/upload?filename=" + urllib.parse.quote(filename)
    with open_url(
        path,
        "PUT",
        data,
        {"Content-Type": content_type, "Content-Length": str(len(data))},
        120,
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def delete_key(key):
    encoded = urllib.parse.quote(key, safe="")
    try:
        json_request(f"/api/images/{encoded}", "DELETE")
    except Exception as error:
        print(f"Warning: failed to roll back {key}: {error}")


def save_log(rows):
    with LOG_PATH.open("w", newline="", encoding="utf-8") as handle:
        columns = [
            "product_id", "article_name", "source_url", "r2_key",
            "r2_url", "status", "message",
        ]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def update_payload(product, uploaded):
    return {
        "brand": product.get("brand", ""),
        "article_name": product.get("article_name", ""),
        "product_name": product.get("product_name", ""),
        "note": product.get("note") or "",
        "category": product.get("category", ""),
        "minimum_threshold": int(product.get("minimum_threshold") or 0),
        "sizes": product.get("sizes") or [],
        "image_url": uploaded["url"],
        "image_public_id": uploaded["key"],
    }


def migrate():
    payload = json_request("/api/products", timeout=120)
    products = payload.get("products") or []
    candidates = [
        product for product in products
        if is_external_image(str(product.get("image_url") or ""))
    ]
    print(f"Found {len(candidates)} external image(s) among {len(products)} products.")
    if not candidates:
        print("Nothing to migrate. Products already using R2 are skipped.")
        return

    answer = input(f"Migrate {len(candidates)} image(s) to R2? [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Migration cancelled.")
        return

    logs = []
    succeeded = failed = 0
    for index, product in enumerate(candidates, 1):
        product_id = int(product["id"])
        article = str(product.get("article_name") or product_id)
        source_url = str(product.get("image_url") or "")
        r2_key = r2_url = ""
        try:
            filename = Path(urllib.parse.unquote(urllib.parse.urlparse(source_url).path)).name
            if not filename or "." not in filename:
                filename = f"product-{product_id}.jpg"
            image_data, content_type = download_image(source_url)
            uploaded = upload_image(image_data, content_type, filename)
            r2_key, r2_url = uploaded["key"], uploaded["url"]
            detail = json_request(f"/api/product/{product_id}")["product"]
            json_request(
                f"/api/product/{product_id}",
                "PUT",
                update_payload(detail, uploaded),
                120,
            )
            succeeded += 1
            status, message = "migrated", "OK"
            print(f"[{index}/{len(candidates)}] Migrated {article} -> {r2_key}")
        except Exception as error:
            failed += 1
            status, message = "failed", str(error)
            if r2_key:
                delete_key(r2_key)
            print(f"[{index}/{len(candidates)}] FAILED {article}: {error}")
        logs.append({
            "product_id": product_id,
            "article_name": article,
            "source_url": source_url,
            "r2_key": r2_key,
            "r2_url": r2_url,
            "status": status,
            "message": message,
        })
        save_log(logs)

    print(f"Migration finished: {succeeded} succeeded, {failed} failed.")
    print(f"Log: {LOG_PATH}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        preflight()
        sign_in()
        migrate()
    except KeyboardInterrupt:
        print("\nMigration cancelled.")
        raise SystemExit(130)
    except Exception as error:
        print(f"ERROR: {error}")
        print("Verify Build 12+, browser login, R2 binding, Worker URL, and credentials.")
        raise SystemExit(1)
