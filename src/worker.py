import hashlib
import hmac
import json
import re
import time

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
        path = request.url.split("?", 1)[0]
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
                "build": 9,
            })

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
                        COUNT(p.id) AS product_count,
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
                    "build": 9,
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
                "build": 9,
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
                "build": 9,
            })

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
                "build": 9,
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
