import json
from workers import Response, WorkerEntrypoint


def json_response(payload, status=200):
    return Response(
        json.dumps(payload),
        status=status,
        headers={
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
        },
    )


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = request.url.split("?", 1)[0]

        if path.endswith("/health"):
            return json_response({"status": "ok", "service": "solestock"})

        if path.endswith("/api/summary"):
            products = await self.env.DB.prepare(
                "SELECT COUNT(*) AS count FROM product"
            ).first()
            pairs = await self.env.DB.prepare(
                "SELECT COALESCE(SUM(quantity), 0) AS total FROM size_stock"
            ).first()
            return json_response({
                "products": int(products.count or 0),
                "total_pairs": int(pairs.total or 0),
            })

        if path.endswith("/api/debug"):
            product_count = await self.env.DB.prepare("SELECT COUNT(*) AS count FROM product").first()
            size_count = await self.env.DB.prepare("SELECT COUNT(*) AS count FROM size_stock").first()
            brand_count = await self.env.DB.prepare("SELECT COUNT(*) AS count FROM brand").first()
            return json_response({
                "database": "solestock-db",
                "products": int(product_count.count or 0),
                "sizes": int(size_count.count or 0),
                "brands": int(brand_count.count or 0),
                "build": 2,
            })

        if path.endswith("/api/products"):
            product_result = await self.env.DB.prepare(
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
                    LOWER(COALESCE(NULLIF(product_name, ''), article_name)),
                    LOWER(article_name)
                """
            ).all()

            size_result = await self.env.DB.prepare(
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
                        WHEN size GLOB '[0-9]*' THEN CAST(size AS REAL)
                        ELSE 999999
                    END,
                    LOWER(size)
                """
            ).all()

            sizes_by_product = {}
            for row in size_result.results:
                product_id = int(row.product_id)
                quantity = int(row.quantity or 0)
                threshold = int(row.minimum_threshold or 0)
                sizes_by_product.setdefault(product_id, []).append({
                    "id": int(row.id),
                    "size": str(row.size or ""),
                    "quantity": quantity,
                    "minimum_threshold": threshold,
                    "status": (
                        "out" if quantity == 0
                        else "low" if quantity <= threshold
                        else "good"
                    ),
                })

            products = []
            for row in product_result.results:
                product_id = int(row.id)
                sizes = sizes_by_product.get(product_id, [])
                total_quantity = sum(item["quantity"] for item in sizes)
                product_threshold = int(row.minimum_threshold or 0)
                article_name = str(row.article_name or "").strip()
                product_name = str(row.product_name or "").strip() or article_name
                status = (
                    "out" if total_quantity == 0
                    else "low" if total_quantity <= product_threshold
                    else "good"
                )
                products.append({
                    "id": product_id,
                    "brand": str(row.brand or ""),
                    "article_name": article_name,
                    "product_name": product_name or "Unnamed product",
                    "note": row.note,
                    "category": str(row.category or ""),
                    "image_url": row.image_url,
                    "image_public_id": row.image_public_id,
                    "minimum_threshold": product_threshold,
                    "updated_at": row.updated_at,
                    "total_quantity": total_quantity,
                    "status": status,
                    "sizes": sizes,
                })

            brand_result = await self.env.DB.prepare(
                "SELECT name FROM brand ORDER BY LOWER(name)"
            ).all()
            brands = [str(item.name or "").strip() for item in brand_result.results if str(item.name or "").strip()]

            return json_response({
                "build": 2,
                "brands": brands,
                "product_count": len(products),
                "size_row_count": sum(len(item["sizes"]) for item in products),
                "products": products,
            })

        return json_response({"error": "Route not found"}, status=404)
