import csv
import hashlib
import io
import hmac
import json
import re
import time
from urllib.parse import parse_qs, unquote, urlparse
from datetime import datetime

from workers import Response, WorkerEntrypoint


SESSION_COOKIE_NAME = "solestock_session"
SESSION_DURATION_SECONDS = 8 * 60 * 60


def json_response(payload, status=200, extra_headers=None):
    headers = {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
    }
    if extra_headers:
        headers.update(extra_headers)
    return Response(json.dumps(payload), status=status, headers=headers)


def get_cookie(request, cookie_name):
    cookie_header = request.headers.get("cookie") or ""
    for cookie_part in cookie_header.split(";"):
        name, separator, value = cookie_part.strip().partition("=")
        if separator and name == cookie_name:
            return value
    return None


def create_signature(user_id, expires_at, secret):
    message = f"{user_id}|{expires_at}".encode("utf-8")
    return hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def create_session_token(user_id, secret):
    expires_at = int(time.time()) + SESSION_DURATION_SECONDS
    signature = create_signature(user_id, expires_at, secret)
    return f"{user_id}|{expires_at}|{signature}"


def validate_session_token(token, secret):
    if not token:
        return None
    try:
        user_id, expires_text, signature = token.split("|", 2)
        expires_at = int(expires_text)
    except (TypeError, ValueError):
        return None

    if expires_at <= int(time.time()):
        return None

    expected = create_signature(user_id, expires_at, secret)
    if not hmac.compare_digest(signature, expected):
        return None
    return user_id


async def read_json(request):
    try:
        return await request.json()
    except Exception:
        return {}


def row_text(row, field_name, fallback=""):
    value = getattr(row, field_name, None)
    if value is None:
        return fallback
    return str(value).strip()


def row_int(row, field_name, fallback=0):
    value = getattr(row, field_name, None)
    if value is None:
        return fallback
    return int(value)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        parsed_url = urlparse(request.url)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)
        method = request.method.upper()

        session_secret = str(self.env.SESSION_SECRET)
        login_user_id = str(self.env.LOGIN_USER_ID)
        login_password = str(self.env.LOGIN_PASSWORD)

        session_token = get_cookie(request, SESSION_COOKIE_NAME)
        logged_in_user = validate_session_token(
            session_token,
            session_secret,
        )

        if path.endswith("/health"):
            return json_response({
                "status": "ok",
                "service": "solestock",
                "build": 12,
            })

        # GET /images/{key} - public image delivery through Worker
        if path.startswith("/images/") and method == "GET":
            key = unquote(path[len("/images/"):]).lstrip("/")
            if not key or ".." in key:
                return Response("Image not found", status=404)
            image_object = await self.env.IMAGES.get(key)
            if image_object is None:
                return Response("Image not found", status=404)
            extension = key.rsplit(".", 1)[-1].lower() if "." in key else ""
            content_types = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "webp": "image/webp",
            }
            return Response(
                image_object.body,
                headers={
                    "content-type": content_types.get(
                        extension,
                        "application/octet-stream",
                    ),
                    "cache-control": "public, max-age=31536000, immutable",
                    "etag": getattr(image_object, "etag", ""),
                },
            )

        # GET /api/session
        if path.endswith("/api/session") and method == "GET":
            return json_response({
                "authenticated": bool(logged_in_user),
                "user_id": logged_in_user,
            })

        # POST /api/login
        if path.endswith("/api/login") and method == "POST":
            body = await read_json(request)
            supplied_user = str(body.get("user_id", "")).strip()
            supplied_password = str(body.get("password", ""))

            valid_user = hmac.compare_digest(
                supplied_user,
                login_user_id,
            )
            valid_password = hmac.compare_digest(
                supplied_password,
                login_password,
            )

            if not (valid_user and valid_password):
                return json_response(
                    {"error": "Incorrect User ID or password."},
                    status=401,
                )

            token = create_session_token(supplied_user, session_secret)
            cookie = (
                f"{SESSION_COOKIE_NAME}={token}; "
                "Path=/; Max-Age=28800; HttpOnly; Secure; SameSite=Lax"
            )
            return json_response(
                {
                    "authenticated": True,
                    "user_id": supplied_user,
                },
                extra_headers={"set-cookie": cookie},
            )

        # POST /api/logout
        if path.endswith("/api/logout") and method == "POST":
            cookie = (
                f"{SESSION_COOKIE_NAME}=; "
                "Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax"
            )
            return json_response(
                {"authenticated": False},
                extra_headers={"set-cookie": cookie},
            )

        protected_paths = (
            "/api/home",
            "/api/brands",
            "/api/export/csv",
            "/api/images/upload",
            "/api/summary",
            "/api/products",
            "/api/debug",
        )
        if any(path.endswith(item) for item in protected_paths):
            if not logged_in_user:
                return json_response(
                    {"error": "Authentication required"},
                    status=401,
                )

        if (
            "/api/product/" in path
            or "/api/products/" in path
            or "/api/images/" in path
        ) and not logged_in_user:
            return json_response({"error": "Authentication required"}, status=401)

        if "/api/brands/" in path and not logged_in_user:
            return json_response(
                {"error": "Authentication required"},
                status=401,
            )

        # GET/POST/PATCH/DELETE /api/brands
        if path.endswith("/api/brands"):
            if method == "GET":
                result = await self.env.DB.prepare(
                    """
                    SELECT
                        b.id,
                        b.name,
                        COUNT(DISTINCT p.id) AS product_count,
                        COALESCE(SUM(s.quantity), 0) AS total_pairs
                    FROM brand AS b
                    LEFT JOIN product AS p
                        ON LOWER(p.brand) = LOWER(b.name)
                    LEFT JOIN size_stock AS s
                        ON s.product_id = p.id
                    GROUP BY b.id, b.name
                    ORDER BY LOWER(b.name)
                    """
                ).all()
                return json_response({
                    "build": 12,
                    "brands": [
                        {
                            "id": row_int(row, "id"),
                            "name": row_text(row, "name", "Unnamed brand"),
                            "product_count": row_int(row, "product_count"),
                            "total_pairs": row_int(row, "total_pairs"),
                        }
                        for row in result.results
                    ],
                })

            if method == "POST":
                body = await read_json(request)
                name = str(body.get("name", "")).strip()
                if not name:
                    return json_response({"error": "Brand name is required"}, 400)
                if len(name) > 60:
                    return json_response({"error": "Brand name must be 60 characters or fewer"}, 400)
                existing = await self.env.DB.prepare(
                    "SELECT id FROM brand WHERE LOWER(name) = LOWER(?1) LIMIT 1"
                ).bind(name).first()
                if existing:
                    return json_response({"error": "Brand already exists"}, 409)
                await self.env.DB.prepare(
                    "INSERT INTO brand (name) VALUES (?1)"
                ).bind(name).run()
                created = await self.env.DB.prepare(
                    "SELECT id, name FROM brand WHERE LOWER(name) = LOWER(?1) LIMIT 1"
                ).bind(name).first()
                return json_response({
                    "message": "Brand added successfully.",
                    "brand": {
                        "id": row_int(created, "id"),
                        "name": row_text(created, "name"),
                        "product_count": 0,
                        "total_pairs": 0,
                    },
                }, 201)

            return json_response({"error": "Method not allowed"}, 405)

        brand_match = re.search(r"/api/brands/(\d+)$", path)
        if brand_match:
            brand_id = int(brand_match.group(1))
            current = await self.env.DB.prepare(
                "SELECT id, name FROM brand WHERE id = ?1"
            ).bind(brand_id).first()
            if not current:
                return json_response({"error": "Brand not found"}, 404)

            current_name = row_text(current, "name")
            product_count_row = await self.env.DB.prepare(
                "SELECT COUNT(*) AS count FROM product WHERE LOWER(brand) = LOWER(?1)"
            ).bind(current_name).first()
            product_count = row_int(product_count_row, "count")

            if method == "PATCH":
                body = await read_json(request)
                new_name = str(body.get("name", "")).strip()
                if not new_name:
                    return json_response({"error": "Brand name is required"}, 400)
                if len(new_name) > 60:
                    return json_response({"error": "Brand name must be 60 characters or fewer"}, 400)
                duplicate = await self.env.DB.prepare(
                    "SELECT id FROM brand WHERE LOWER(name) = LOWER(?1) AND id != ?2 LIMIT 1"
                ).bind(new_name, brand_id).first()
                if duplicate:
                    return json_response({"error": "Brand already exists"}, 409)
                await self.env.DB.batch([
                    self.env.DB.prepare(
                        "UPDATE product SET brand = ?1 WHERE LOWER(brand) = LOWER(?2)"
                    ).bind(new_name, current_name),
                    self.env.DB.prepare(
                        "UPDATE brand SET name = ?1 WHERE id = ?2"
                    ).bind(new_name, brand_id),
                ])
                return json_response({
                    "message": "Brand renamed successfully.",
                    "brand": {
                        "id": brand_id,
                        "name": new_name,
                        "product_count": product_count,
                    },
                })

            if method == "DELETE":
                if product_count > 0:
                    return json_response({
                        "error": "This brand still has products"
                    }, 409)
                await self.env.DB.prepare(
                    "DELETE FROM brand WHERE id = ?1"
                ).bind(brand_id).run()
                return json_response({
                    "message": "Brand deleted successfully.",
                    "deleted_brand": {
                        "id": brand_id,
                        "name": current_name,
                    },
                })

            return json_response({"error": "Method not allowed"}, 405)

        # PUT /api/images/upload?filename=name.jpg
        if path.endswith("/api/images/upload") and method == "PUT":
            filename = str(query.get("filename", [""])[0]).strip()
            content_type = str(
                request.headers.get("content-type") or ""
            ).lower()
            allowed_types = {
                "image/png": "png",
                "image/jpeg": "jpg",
                "image/webp": "webp",
            }
            extension = allowed_types.get(content_type)
            if extension is None:
                return json_response({
                    "error": "Use a PNG, JPG, JPEG, or WEBP image."
                }, 400)
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > 5 * 1024 * 1024:
                        return json_response({
                            "error": "Image must be 5 MB or smaller."
                        }, 413)
                except ValueError:
                    pass
            safe_name = re.sub(
                r"[^A-Za-z0-9._-]+",
                "-",
                filename or f"product.{extension}",
            ).strip("-.")
            stem = safe_name.rsplit(".", 1)[0][:70] or "product"
            unique = hashlib.sha256(
                f"{logged_in_user}|{time.time_ns()}|{safe_name}".encode("utf-8")
            ).hexdigest()[:16]
            key = f"products/{int(time.time())}-{unique}-{stem}.{extension}"
            uploaded = await self.env.IMAGES.put(key, request.body)
            if uploaded is None:
                return json_response({"error": "Image upload failed."}, 500)
            return json_response({
                "message": "Image uploaded successfully.",
                "key": key,
                "url": f"/images/{key}",
                "content_type": content_type,
            }, 201)

        image_delete_match = re.search(r"/api/images/(.+)$", path)
        if image_delete_match and method == "DELETE":
            key = unquote(image_delete_match.group(1)).lstrip("/")
            if not key.startswith("products/") or ".." in key:
                return json_response({"error": "Invalid image key"}, 400)
            await self.env.IMAGES.delete(key)
            return json_response({"message": "Image deleted successfully."})

        # GET /api/debug
        if path.endswith("/api/debug") and method == "GET":
            products = await self.env.DB.prepare(
                "SELECT COUNT(*) AS count FROM product"
            ).first()
            sizes = await self.env.DB.prepare(
                "SELECT COUNT(*) AS count FROM size_stock"
            ).first()
            brands = await self.env.DB.prepare(
                "SELECT COUNT(*) AS count FROM brand"
            ).first()
            return json_response({
                "database": "solestock-db",
                "products": row_int(products, "count"),
                "sizes": row_int(sizes, "count"),
                "brands": row_int(brands, "count"),
                "build": 12,
            })

        # GET /api/summary
        if path.endswith("/api/summary") and method == "GET":
            products = await self.env.DB.prepare(
                "SELECT COUNT(*) AS count FROM product"
            ).first()
            pairs = await self.env.DB.prepare(
                "SELECT COALESCE(SUM(quantity), 0) AS total FROM size_stock"
            ).first()
            return json_response({
                "products": row_int(products, "count"),
                "total_pairs": row_int(pairs, "total"),
            })

        # GET /api/home
        if path.endswith("/api/home") and method == "GET":
            totals_row = await self.env.DB.prepare(
                """
                SELECT
                    COUNT(DISTINCT p.id) AS total_products,
                    COALESCE(SUM(s.quantity), 0) AS total_pairs,
                    COALESCE(SUM(CASE WHEN LOWER(p.category) = 'shoes'
                        THEN s.quantity ELSE 0 END), 0) AS total_shoes,
                    COALESCE(SUM(CASE WHEN LOWER(p.category) = 'sandals'
                        THEN s.quantity ELSE 0 END), 0) AS total_sandals
                FROM product AS p
                LEFT JOIN size_stock AS s ON s.product_id = p.id
                """
            ).first()

            product_totals = await self.env.DB.prepare(
                """
                SELECT
                    p.id,
                    p.minimum_threshold,
                    COALESCE(SUM(s.quantity), 0) AS total_quantity
                FROM product AS p
                LEFT JOIN size_stock AS s ON s.product_id = p.id
                GROUP BY p.id, p.minimum_threshold
                """
            ).all()

            low_count = 0
            out_count = 0
            for row in product_totals.results:
                quantity = row_int(row, "total_quantity")
                threshold = row_int(row, "minimum_threshold")
                if quantity == 0:
                    out_count += 1
                elif quantity <= threshold:
                    low_count += 1

            brand_rows = await self.env.DB.prepare(
                """
                SELECT
                    p.brand,
                    COUNT(DISTINCT p.id) AS product_count,
                    COALESCE(SUM(s.quantity), 0) AS total_pairs
                FROM product AS p
                LEFT JOIN size_stock AS s ON s.product_id = p.id
                GROUP BY p.brand
                ORDER BY LOWER(p.brand)
                """
            ).all()

            recent_rows = await self.env.DB.prepare(
                """
                SELECT
                    p.id,
                    p.brand,
                    p.article_name,
                    p.product_name,
                    p.category,
                    p.image_url,
                    p.updated_at,
                    p.minimum_threshold,
                    COALESCE(SUM(s.quantity), 0) AS total_quantity
                FROM product AS p
                LEFT JOIN size_stock AS s ON s.product_id = p.id
                GROUP BY
                    p.id, p.brand, p.article_name, p.product_name,
                    p.category, p.image_url, p.updated_at,
                    p.minimum_threshold
                ORDER BY p.updated_at DESC
                LIMIT 5
                """
            ).all()

            alert_rows = await self.env.DB.prepare(
                """
                SELECT
                    p.id, p.brand, p.article_name, p.product_name,
                    p.category, s.size
                FROM product AS p
                INNER JOIN size_stock AS s ON s.product_id = p.id
                WHERE s.quantity = 0
                ORDER BY
                    LOWER(p.brand), LOWER(p.article_name),
                    CASE WHEN s.size GLOB '[0-9]*'
                        THEN CAST(s.size AS REAL) ELSE 999999 END,
                    LOWER(s.size)
                """
            ).all()

            brands = [{
                "brand": row_text(row, "brand"),
                "product_count": row_int(row, "product_count"),
                "total_pairs": row_int(row, "total_pairs"),
            } for row in brand_rows.results]

            recent_products = []
            for row in recent_rows.results:
                article = row_text(row, "article_name")
                name = row_text(row, "product_name") or article or "Unnamed product"
                recent_products.append({
                    "id": row_int(row, "id"),
                    "brand": row_text(row, "brand"),
                    "article_name": article,
                    "product_name": name,
                    "category": row_text(row, "category"),
                    "image_url": getattr(row, "image_url", None),
                    "updated_at": getattr(row, "updated_at", None),
                    "total_quantity": row_int(row, "total_quantity"),
                    "status": (
                        "out"
                        if row_int(row, "total_quantity") == 0
                        else "low"
                        if row_int(row, "total_quantity")
                        <= row_int(row, "minimum_threshold")
                        else "good"
                    ),
                })

            alerts_by_product = {}
            for row in alert_rows.results:
                product_id = row_int(row, "id")
                if product_id not in alerts_by_product:
                    article = row_text(row, "article_name")
                    name = row_text(row, "product_name") or article or "Unnamed product"
                    alerts_by_product[product_id] = {
                        "id": product_id,
                        "brand": row_text(row, "brand"),
                        "article_name": article,
                        "product_name": name,
                        "category": row_text(row, "category"),
                        "zero_sizes": [],
                    }
                alerts_by_product[product_id]["zero_sizes"].append(
                    row_text(row, "size")
                )

            return json_response({
                "totals": {
                    "products": row_int(totals_row, "total_products"),
                    "pairs": row_int(totals_row, "total_pairs"),
                    "shoes": row_int(totals_row, "total_shoes"),
                    "sandals": row_int(totals_row, "total_sandals"),
                    "low": low_count,
                    "out": out_count,
                },
                "brands": brands,
                "recent_products": recent_products,
                "alerts": list(alerts_by_product.values()),
                "build": 12,
            })

        # GET/PUT /api/product/{id}
        product_match = re.search(r"/api/product/(\d+)$", path)
        if product_match:
            product_id = int(product_match.group(1))
            found = await self.env.DB.prepare(
                """
                SELECT id, brand, article_name, product_name, note, category,
                       image_url, image_public_id, minimum_threshold, updated_at
                FROM product WHERE id = ?1
                """
            ).bind(product_id).first()
            if not found:
                return json_response({"error": "Product not found"}, 404)

            if method == "GET":
                size_rows = await self.env.DB.prepare(
                    """
                    SELECT id, size, quantity, minimum_threshold
                    FROM size_stock WHERE product_id = ?1
                    ORDER BY CASE WHEN size GLOB '[0-9]*'
                        THEN CAST(size AS REAL) ELSE 999999 END, LOWER(size)
                    """
                ).bind(product_id).all()
                return json_response({
                    "build": 12,
                    "product": {
                        "id": product_id,
                        "brand": row_text(found, "brand"),
                        "article_name": row_text(found, "article_name"),
                        "product_name": row_text(found, "product_name"),
                        "note": getattr(found, "note", None),
                        "category": row_text(found, "category"),
                        "image_url": getattr(found, "image_url", None),
                        "image_public_id": getattr(found, "image_public_id", None),
                        "minimum_threshold": row_int(found, "minimum_threshold"),
                        "sizes": [
                            {
                                "id": row_int(row, "id"),
                                "size": row_text(row, "size"),
                                "quantity": row_int(row, "quantity"),
                                "minimum_threshold": row_int(row, "minimum_threshold"),
                            }
                            for row in size_rows.results
                        ],
                    },
                })

            if method == "PUT":
                body = await read_json(request)
                brand = str(body.get("brand", "")).strip()
                article = str(body.get("article_name", "")).strip()
                name = str(body.get("product_name", "")).strip()
                category = str(body.get("category", "")).strip()
                note = str(body.get("note", "")).strip() or None
                submitted_image_url = str(
                    body.get("image_url", "")
                ).strip() or getattr(found, "image_url", None)
                submitted_image_key = str(
                    body.get("image_public_id", "")
                ).strip() or getattr(found, "image_public_id", None)
                old_image_key = getattr(found, "image_public_id", None)
                try:
                    threshold = max(0, int(body.get("minimum_threshold", 5)))
                except (TypeError, ValueError):
                    return json_response({"error": "Threshold must be a valid number"}, 400)
                if not brand or not article or not name or category not in ("Shoes", "Sandals"):
                    return json_response({"error": "Please complete all product fields correctly."}, 400)
                valid_brand = await self.env.DB.prepare(
                    "SELECT id FROM brand WHERE LOWER(name) = LOWER(?1) LIMIT 1"
                ).bind(brand).first()
                if not valid_brand:
                    return json_response({"error": "Select a valid brand"}, 400)
                duplicate = await self.env.DB.prepare(
                    "SELECT id FROM product WHERE LOWER(brand)=LOWER(?1) AND LOWER(article_name)=LOWER(?2) AND id != ?3 LIMIT 1"
                ).bind(brand, article, product_id).first()
                if duplicate:
                    return json_response({"error": "Article number already exists for this brand."}, 409)
                sizes = body.get("sizes", []) if isinstance(body.get("sizes", []), list) else []
                normalized = []
                seen = set()
                try:
                    for item in sizes:
                        size = str(item.get("size", "")).strip()
                        key = size.lower()
                        if not size or key in seen:
                            continue
                        seen.add(key)
                        normalized.append((size, max(0, int(item.get("quantity", 0))), max(0, int(item.get("minimum_threshold", 0)))))
                except (TypeError, ValueError):
                    return json_response({"error": "Quantity and threshold values must be valid numbers."}, 400)
                if not normalized:
                    return json_response({"error": "Add at least one product size."}, 400)
                statements = [
                    self.env.DB.prepare(
                        """
                        UPDATE product SET brand=?1, article_name=?2, product_name=?3,
                            note=?4, category=?5, minimum_threshold=?6,
                            image_url=?7, image_public_id=?8,
                            updated_at=CURRENT_TIMESTAMP WHERE id=?9
                        """
                    ).bind(
                        brand, article, name, note, category, threshold,
                        submitted_image_url, submitted_image_key, product_id,
                    ),
                    self.env.DB.prepare("DELETE FROM size_stock WHERE product_id=?1").bind(product_id),
                ]
                for size, quantity, size_threshold in normalized:
                    statements.append(self.env.DB.prepare(
                        "INSERT INTO size_stock (product_id,size,quantity,minimum_threshold) VALUES (?1,?2,?3,?4)"
                    ).bind(product_id, size, quantity, size_threshold))
                await self.env.DB.batch(statements)
                if (
                    old_image_key
                    and old_image_key != submitted_image_key
                    and str(old_image_key).startswith("products/")
                ):
                    await self.env.IMAGES.delete(str(old_image_key))
                return json_response({
                    "message": "Product saved successfully.",
                    "product_id": product_id,
                    "image_url": submitted_image_url,
                    "image_public_id": submitted_image_key,
                })

            if method == "DELETE":
                image_public_id = getattr(found, "image_public_id", None)
                image_url = getattr(found, "image_url", None)
                await self.env.DB.batch([
                    self.env.DB.prepare(
                        "DELETE FROM stock_movement WHERE product_id = ?1"
                    ).bind(product_id),
                    self.env.DB.prepare(
                        "DELETE FROM size_stock WHERE product_id = ?1"
                    ).bind(product_id),
                    self.env.DB.prepare(
                        "DELETE FROM product WHERE id = ?1"
                    ).bind(product_id),
                ])
                if image_public_id and str(image_public_id).startswith("products/"):
                    await self.env.IMAGES.delete(str(image_public_id))
                return json_response({
                    "message": "Product deleted successfully.",
                    "deleted_product": {
                        "id": product_id,
                        "article_name": row_text(found, "article_name"),
                        "product_name": row_text(found, "product_name"),
                        "image_public_id": image_public_id,
                        "image_url": image_url,
                    },
                    "image_cleanup_deferred": bool(
                        (image_public_id or image_url)
                        and not str(image_public_id or "").startswith("products/")
                    ),
                })

            return json_response({"error": "Method not allowed"}, 405)

        # GET /api/export/csv
        if path.endswith("/api/export/csv") and method == "GET":
            rows = await self.env.DB.prepare(
                """
                SELECT
                    p.id,
                    p.brand,
                    p.article_name,
                    p.product_name,
                    p.category,
                    p.minimum_threshold,
                    p.updated_at,
                    s.size,
                    s.quantity
                FROM product AS p
                LEFT JOIN size_stock AS s ON s.product_id = p.id
                ORDER BY
                    LOWER(p.product_name),
                    LOWER(p.article_name),
                    CASE WHEN s.size GLOB '[0-9]*'
                        THEN CAST(s.size AS REAL) ELSE 999999 END,
                    LOWER(s.size)
                """
            ).all()

            products = {}
            for row in rows.results:
                product_id = row_int(row, "id")
                if product_id not in products:
                    products[product_id] = {
                        "brand": row_text(row, "brand"),
                        "article": row_text(row, "article_name"),
                        "name": row_text(row, "product_name"),
                        "category": row_text(row, "category"),
                        "threshold": row_int(row, "minimum_threshold"),
                        "updated_at": row_text(row, "updated_at"),
                        "sizes": [],
                    }
                if getattr(row, "size", None) is not None:
                    products[product_id]["sizes"].append({
                        "size": row_text(row, "size"),
                        "quantity": row_int(row, "quantity"),
                    })

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "Brand",
                "Article Name",
                "Product Name",
                "Category",
                "Available Sizes",
                "Size-wise Quantities",
                "Total Quantity",
                "Stock Status",
                "Updated At",
            ])
            for product in products.values():
                total = sum(item["quantity"] for item in product["sizes"])
                status = (
                    "Out"
                    if total == 0
                    else "Low"
                    if total <= product["threshold"]
                    else "Good"
                )
                writer.writerow([
                    product["brand"],
                    product["article"],
                    product["name"],
                    product["category"],
                    ", ".join(
                        item["size"]
                        for item in product["sizes"]
                        if item["quantity"] > 0
                    ),
                    ", ".join(
                        f'{item["size"]}: {item["quantity"]}'
                        for item in product["sizes"]
                    ),
                    total,
                    status,
                    product["updated_at"],
                ])

            stamp = datetime.now().strftime("%Y%m%d_%H%M")
            return Response(
                "\ufeff" + output.getvalue(),
                headers={
                    "content-type": "text/csv; charset=utf-8",
                    "content-disposition": (
                        f'attachment; filename="shoe_stock_{stamp}.csv"'
                    ),
                    "cache-control": "no-store",
                },
            )

        # POST /api/products
        if path.endswith("/api/products") and method == "POST":
            body = await read_json(request)
            brand = str(body.get("brand", "")).strip()
            article = str(body.get("article_name", "")).strip()
            name = str(body.get("product_name", "")).strip()
            category = str(body.get("category", "")).strip()
            note = str(body.get("note", "")).strip() or None
            image_url = str(body.get("image_url", "")).strip() or None
            image_public_id = str(
                body.get("image_public_id", "")
            ).strip() or None
            try:
                threshold = max(0, int(body.get("minimum_threshold", 5)))
            except (TypeError, ValueError):
                return json_response({"error": "Threshold must be a valid number"}, 400)
            if not brand or not article or not name or category not in ("Shoes", "Sandals"):
                return json_response({"error": "Please complete all product fields correctly."}, 400)
            valid_brand = await self.env.DB.prepare(
                "SELECT id FROM brand WHERE LOWER(name)=LOWER(?1) LIMIT 1"
            ).bind(brand).first()
            if not valid_brand:
                return json_response({"error": "Select a valid brand"}, 400)
            duplicate = await self.env.DB.prepare(
                "SELECT id FROM product WHERE LOWER(brand)=LOWER(?1) AND LOWER(article_name)=LOWER(?2) LIMIT 1"
            ).bind(brand, article).first()
            if duplicate:
                return json_response({"error": "Article number already exists for this brand."}, 409)
            sizes = body.get("sizes", []) if isinstance(body.get("sizes", []), list) else []
            normalized = []
            seen = set()
            try:
                for item in sizes:
                    size = str(item.get("size", "")).strip()
                    key = size.lower()
                    if not size or key in seen:
                        continue
                    seen.add(key)
                    normalized.append((size, max(0, int(item.get("quantity", 0))), max(0, int(item.get("minimum_threshold", 0)))))
            except (TypeError, ValueError):
                return json_response({"error": "Quantity and threshold values must be valid numbers."}, 400)
            if not normalized:
                return json_response({"error": "Add at least one product size."}, 400)
            await self.env.DB.prepare(
                """
                INSERT INTO product
                    (
                        brand, article_name, product_name, note, category,
                        minimum_threshold, image_url, image_public_id,
                        updated_at
                    )
                VALUES (?1,?2,?3,?4,?5,?6,?7,?8,CURRENT_TIMESTAMP)
                """
            ).bind(
                brand, article, name, note, category, threshold,
                image_url, image_public_id,
            ).run()
            created = await self.env.DB.prepare(
                "SELECT id FROM product WHERE LOWER(brand)=LOWER(?1) AND LOWER(article_name)=LOWER(?2) LIMIT 1"
            ).bind(brand, article).first()
            product_id = row_int(created, "id")
            await self.env.DB.batch([
                self.env.DB.prepare(
                    "INSERT INTO size_stock (product_id,size,quantity,minimum_threshold) VALUES (?1,?2,?3,?4)"
                ).bind(product_id, size, quantity, size_threshold)
                for size, quantity, size_threshold in normalized
            ])
            return json_response({"message": "Product saved successfully.", "product_id": product_id}, 201)

        # GET /api/products
        if path.endswith("/api/products") and method == "GET":
            rows = await self.env.DB.prepare(
                """
                SELECT
                    p.id AS product_id,
                    p.brand,
                    p.article_name,
                    p.product_name,
                    p.note,
                    p.category,
                    p.image_url,
                    p.image_public_id,
                    p.minimum_threshold AS product_threshold,
                    p.updated_at,
                    s.id AS size_id,
                    s.size,
                    s.quantity,
                    s.minimum_threshold AS size_threshold
                FROM product AS p
                LEFT JOIN size_stock AS s ON s.product_id = p.id
                ORDER BY
                    LOWER(COALESCE(NULLIF(p.product_name, ''), p.article_name)),
                    LOWER(p.article_name),
                    CASE WHEN s.size GLOB '[0-9]*'
                        THEN CAST(s.size AS REAL) ELSE 999999 END,
                    LOWER(s.size)
                """
            ).all()

            products_by_id = {}
            missing_names = 0
            missing_articles = 0
            missing_brands = 0
            products_without_sizes = 0

            for row in rows.results:
                product_id = row_int(row, "product_id")
                if product_id not in products_by_id:
                    article = row_text(row, "article_name")
                    raw_name = row_text(row, "product_name")
                    brand = row_text(row, "brand")
                    category = row_text(row, "category")

                    if not raw_name:
                        missing_names += 1
                    if not article:
                        missing_articles += 1
                    if not brand:
                        missing_brands += 1

                    products_by_id[product_id] = {
                        "id": product_id,
                        "brand": brand or "Unknown brand",
                        "article_name": article or f"Product {product_id}",
                        "product_name": raw_name or article or f"Product {product_id}",
                        "note": getattr(row, "note", None),
                        "category": category or "Uncategorized",
                        "image_url": getattr(row, "image_url", None),
                        "image_public_id": getattr(row, "image_public_id", None),
                        "minimum_threshold": row_int(row, "product_threshold"),
                        "updated_at": getattr(row, "updated_at", None),
                        "sizes": [],
                    }

                size_id = getattr(row, "size_id", None)
                if size_id is not None:
                    quantity = row_int(row, "quantity")
                    threshold = row_int(row, "size_threshold")
                    products_by_id[product_id]["sizes"].append({
                        "id": int(size_id),
                        "size": row_text(row, "size", "-") or "-",
                        "quantity": quantity,
                        "minimum_threshold": threshold,
                        "status": (
                            "out" if quantity == 0
                            else "low" if quantity <= threshold
                            else "good"
                        ),
                    })

            products = []
            for product in products_by_id.values():
                sizes = product["sizes"]
                if not sizes:
                    products_without_sizes += 1
                total = sum(item["quantity"] for item in sizes)
                threshold = product["minimum_threshold"]
                product["total_quantity"] = total
                product["status"] = (
                    "out" if total == 0
                    else "low" if total <= threshold
                    else "good"
                )
                products.append(product)

            brand_rows = await self.env.DB.prepare(
                "SELECT name FROM brand ORDER BY LOWER(name)"
            ).all()
            brands = [
                row_text(row, "name")
                for row in brand_rows.results
                if row_text(row, "name")
            ]

            return json_response({
                "build": 12,
                "brands": brands,
                "product_count": len(products),
                "size_row_count": sum(len(item["sizes"]) for item in products),
                "data_quality": {
                    "missing_product_names": missing_names,
                    "missing_article_names": missing_articles,
                    "missing_brands": missing_brands,
                    "products_without_sizes": products_without_sizes,
                },
                "products": products,
            })

        return json_response({"error": "Route not found"}, status=404)
