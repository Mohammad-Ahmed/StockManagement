import hashlib
import hmac
import json
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
                "build": 4,
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
                "build": 4,
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
                    id, brand, article_name, product_name,
                    category, image_url, updated_at
                FROM product
                ORDER BY updated_at DESC
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
                "build": 4,
            })

        # GET /api/products
        if path.endswith("/api/products") and method == "GET":
            product_rows = await self.env.DB.prepare(
                """
                SELECT
                    id, brand, article_name, product_name, note, category,
                    image_url, image_public_id, minimum_threshold, updated_at
                FROM product
                ORDER BY
                    LOWER(COALESCE(NULLIF(product_name, ''), article_name)),
                    LOWER(article_name)
                """
            ).all()

            size_rows = await self.env.DB.prepare(
                """
                SELECT id, product_id, size, quantity, minimum_threshold
                FROM size_stock
                ORDER BY
                    product_id,
                    CASE WHEN size GLOB '[0-9]*'
                        THEN CAST(size AS REAL) ELSE 999999 END,
                    LOWER(size)
                """
            ).all()

            sizes_by_product = {}
            for row in size_rows.results:
                product_id = row_int(row, "product_id")
                quantity = row_int(row, "quantity")
                threshold = row_int(row, "minimum_threshold")
                sizes_by_product.setdefault(product_id, []).append({
                    "id": row_int(row, "id"),
                    "size": row_text(row, "size"),
                    "quantity": quantity,
                    "minimum_threshold": threshold,
                    "status": (
                        "out" if quantity == 0
                        else "low" if quantity <= threshold
                        else "good"
                    ),
                })

            products = []
            for row in product_rows.results:
                product_id = row_int(row, "id")
                sizes = sizes_by_product.get(product_id, [])
                total_quantity = sum(item["quantity"] for item in sizes)
                threshold = row_int(row, "minimum_threshold")
                article = row_text(row, "article_name")
                name = row_text(row, "product_name") or article or "Unnamed product"
                status = (
                    "out" if total_quantity == 0
                    else "low" if total_quantity <= threshold
                    else "good"
                )
                products.append({
                    "id": product_id,
                    "brand": row_text(row, "brand"),
                    "article_name": article,
                    "product_name": name,
                    "note": getattr(row, "note", None),
                    "category": row_text(row, "category"),
                    "image_url": getattr(row, "image_url", None),
                    "image_public_id": getattr(row, "image_public_id", None),
                    "minimum_threshold": threshold,
                    "updated_at": getattr(row, "updated_at", None),
                    "total_quantity": total_quantity,
                    "status": status,
                    "sizes": sizes,
                })

            brand_rows = await self.env.DB.prepare(
                "SELECT name FROM brand ORDER BY LOWER(name)"
            ).all()
            brands = [
                row_text(row, "name")
                for row in brand_rows.results
                if row_text(row, "name")
            ]

            return json_response({
                "build": 4,
                "brands": brands,
                "product_count": len(products),
                "size_row_count": sum(len(item["sizes"]) for item in products),
                "products": products,
            })

        return json_response({"error": "Route not found"}, status=404)
