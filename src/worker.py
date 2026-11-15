import hashlib
import hmac
import json
import time

from workers import Response
from workers import WorkerEntrypoint


SESSION_COOKIE_NAME = "solestock_session"
SESSION_DURATION_SECONDS = 8 * 60 * 60


def json_response(
    payload,
    status=200,
    extra_headers=None,
):
    headers = {
        "content-type":
            "application/json; charset=utf-8",
        "cache-control":
            "no-store",
    }

    if extra_headers:
        headers.update(extra_headers)

    return Response(
        json.dumps(payload),
        status=status,
        headers=headers,
    )


def get_cookie(request, cookie_name):
    cookie_header = (
        request.headers.get("cookie") or ""
    )

    for cookie_part in cookie_header.split(";"):
        name, separator, value = (
            cookie_part.strip().partition("=")
        )

        if (
            separator
            and name == cookie_name
        ):
            return value

    return None


def create_signature(
    user_id,
    expires_at,
    secret,
):
    message = (
        f"{user_id}|{expires_at}"
        .encode("utf-8")
    )

    return hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def create_session_token(
    user_id,
    secret,
):
    expires_at = (
        int(time.time())
        + SESSION_DURATION_SECONDS
    )

    signature = create_signature(
        user_id,
        expires_at,
        secret,
    )

    return (
        f"{user_id}|{expires_at}|{signature}"
    )


def validate_session_token(
    token,
    secret,
):
    if not token:
        return None

    try:
        user_id, expires_text, signature = (
            token.split("|", 2)
        )

        expires_at = int(expires_text)

    except (TypeError, ValueError):
        return None

    if expires_at <= int(time.time()):
        return None

    expected_signature = create_signature(
        user_id,
        expires_at,
        secret,
    )

    if not hmac.compare_digest(
        signature,
        expected_signature,
    ):
        return None

    return user_id


async def read_json(request):
    try:
        return await request.json()

    except Exception:
        return {}


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = request.url.split(
            "?",
            1,
        )[0]

        method = request.method.upper()

        session_secret = str(
            self.env.SESSION_SECRET
        )

        login_user_id = str(
            self.env.LOGIN_USER_ID
        )

        login_password = str(
            self.env.LOGIN_PASSWORD
        )

        session_token = get_cookie(
            request,
            SESSION_COOKIE_NAME,
        )

        logged_in_user = (
            validate_session_token(
                session_token,
                session_secret,
            )
        )

        if path.endswith("/health"):
            return json_response({
                "status": "ok",
                "service": "solestock",
            })

        # GET /api/session
        if (
            path.endswith("/api/session")
            and method == "GET"
        ):
            return json_response({
                "authenticated":
                    bool(logged_in_user),
                "user_id":
                    logged_in_user,
            })

        # POST /api/login
        if (
            path.endswith("/api/login")
            and method == "POST"
        ):
            body = await read_json(request)

            supplied_user_id = str(
                body.get("user_id", "")
            ).strip()

            supplied_password = str(
                body.get("password", "")
            )

            valid_user = hmac.compare_digest(
                supplied_user_id,
                login_user_id,
            )

            valid_password = (
                hmac.compare_digest(
                    supplied_password,
                    login_password,
                )
            )

            if not (
                valid_user
                and valid_password
            ):
                return json_response(
                    {
                        "error":
                            "Incorrect User ID or password."
                    },
                    status=401,
                )

            token = create_session_token(
                supplied_user_id,
                session_secret,
            )

            cookie = (
                f"{SESSION_COOKIE_NAME}={token}; "
                "Path=/; "
                "Max-Age=28800; "
                "HttpOnly; "
                "Secure; "
                "SameSite=Lax"
            )

            return json_response(
                {
                    "authenticated": True,
                    "user_id":
                        supplied_user_id,
                },
                extra_headers={
                    "set-cookie": cookie,
                },
            )

        # POST /api/logout
        if (
            path.endswith("/api/logout")
            and method == "POST"
        ):
            cookie = (
                f"{SESSION_COOKIE_NAME}=; "
                "Path=/; "
                "Max-Age=0; "
                "HttpOnly; "
                "Secure; "
                "SameSite=Lax"
            )

            return json_response(
                {
                    "authenticated": False,
                },
                extra_headers={
                    "set-cookie": cookie,
                },
            )

        # Protect remaining API routes.
        if (
            path.endswith("/api/summary")
            or path.endswith("/api/products")
            or path.endswith("/api/debug")
        ):
            if not logged_in_user:
                return json_response(
                    {
                        "error":
                            "Authentication required"
                    },
                    status=401,
                )

        if path.endswith("/api/debug"):
            product_count = await (
                self.env.DB
                .prepare(
                    """
                    SELECT COUNT(*) AS count
                    FROM product
                    """
                )
                .first()
            )

            size_count = await (
                self.env.DB
                .prepare(
                    """
                    SELECT COUNT(*) AS count
                    FROM size_stock
                    """
                )
                .first()
            )

            brand_count = await (
                self.env.DB
                .prepare(
                    """
                    SELECT COUNT(*) AS count
                    FROM brand
                    """
                )
                .first()
            )

            return json_response({
                "database": "solestock-db",
                "products": int(
                    product_count.count or 0
                ),
                "sizes": int(
                    size_count.count or 0
                ),
                "brands": int(
                    brand_count.count or 0
                ),
                "build": 3,
            })

        if path.endswith("/api/summary"):
            products = await (
                self.env.DB
                .prepare(
                    """
                    SELECT COUNT(*) AS count
                    FROM product
                    """
                )
                .first()
            )

            pairs = await (
                self.env.DB
                .prepare(
                    """
                    SELECT COALESCE(
                        SUM(quantity),
                        0
                    ) AS total
                    FROM size_stock
                    """
                )
                .first()
            )

            return json_response({
                "products":
                    int(products.count or 0),
                "total_pairs":
                    int(pairs.total or 0),
            })

        if path.endswith("/api/products"):
            product_result = await (
                self.env.DB
                .prepare(
                    """
                    SELECT
                        id,
                        brand,
                        article_name,
                        product_name,
                        note,
                        category,
                        image_url,
                        image_public_id,
                        minimum_threshold,
                        updated_at
                    FROM product
                    ORDER BY
                        LOWER(
                            COALESCE(
                                NULLIF(
                                    product_name,
                                    ''
                                ),
                                article_name
                            )
                        ),
                        LOWER(article_name)
                    """
                )
                .all()
            )

            size_result = await (
                self.env.DB
                .prepare(
                    """
                    SELECT
                        id,
                        product_id,
                        size,
                        quantity,
                        minimum_threshold
                    FROM size_stock
                    ORDER BY
                        product_id,
                        CASE
                            WHEN size GLOB '[0-9]*'
                            THEN CAST(size AS REAL)
                            ELSE 999999
                        END,
                        LOWER(size)
                    """
                )
                .all()
            )

            sizes_by_product = {}

            for row in size_result.results:
                product_id = int(
                    row.product_id
                )

                quantity = int(
                    row.quantity or 0
                )

                threshold = int(
                    row.minimum_threshold or 0
                )

                sizes_by_product.setdefault(
                    product_id,
                    [],
                ).append({
                    "id": int(row.id),
                    "size": str(
                        row.size or ""
                    ),
                    "quantity": quantity,
                    "minimum_threshold":
                        threshold,
                    "status": (
                        "out"
                        if quantity == 0
                        else "low"
                        if quantity <= threshold
                        else "good"
                    ),
                })

            products = []

            for row in product_result.results:
                product_id = int(row.id)

                sizes = sizes_by_product.get(
                    product_id,
                    [],
                )

                total_quantity = sum(
                    item["quantity"]
                    for item in sizes
                )

                product_threshold = int(
                    row.minimum_threshold or 0
                )

                article_name = str(
                    row.article_name or ""
                ).strip()

                product_name = str(
                    row.product_name or ""
                ).strip()

                if not product_name:
                    product_name = (
                        article_name
                        or "Unnamed product"
                    )

                status = (
                    "out"
                    if total_quantity == 0
                    else "low"
                    if (
                        total_quantity
                        <= product_threshold
                    )
                    else "good"
                )

                products.append({
                    "id": product_id,
                    "brand": str(
                        row.brand or ""
                    ),
                    "article_name":
                        article_name,
                    "product_name":
                        product_name,
                    "note": row.note,
                    "category": str(
                        row.category or ""
                    ),
                    "image_url":
                        row.image_url,
                    "image_public_id":
                        row.image_public_id,
                    "minimum_threshold":
                        product_threshold,
                    "updated_at":
                        row.updated_at,
                    "total_quantity":
                        total_quantity,
                    "status": status,
                    "sizes": sizes,
                })

            brand_result = await (
                self.env.DB
                .prepare(
                    """
                    SELECT name
                    FROM brand
                    ORDER BY LOWER(name)
                    """
                )
                .all()
            )

            brands = [
                str(row.name or "").strip()
                for row in brand_result.results
                if str(row.name or "").strip()
            ]

            return json_response({
                "build": 3,
                "brands": brands,
                "product_count":
                    len(products),
                "size_row_count": sum(
                    len(product["sizes"])
                    for product in products
                ),
                "products": products,
            })

        return json_response(
            {
                "error": "Route not found"
            },
            status=404,
        )
