import json

from workers import Response
from workers import WorkerEntrypoint


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = request.url.split(
            "?",
            1
        )[0]

        if path.endswith("/health"):
            return Response(
                json.dumps({
                    "status": "ok",
                    "service": "solestock"
                }),
                headers={
                    "content-type":
                        "application/json"
                }
            )

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

            return Response(
                json.dumps({
                    "products": products.count,
                    "total_pairs": pairs.total
                }),
                headers={
                    "content-type":
                        "application/json"
                }
            )



                    

        if path.endswith("/api/products"):
            result = await (
                self.env.DB
                .prepare(
                    """
                    SELECT
                        p.id,
                        p.brand,
                        p.article_name,
                        p.product_name,
                        p.note,
                        p.category,
                        p.image_url,
                        p.image_public_id,
                        p.minimum_threshold,
                        p.updated_at,
                        COALESCE(
                            SUM(s.quantity),
                            0
                        ) AS total_quantity
                    FROM product AS p
                    LEFT JOIN size_stock AS s
                        ON s.product_id = p.id
                    GROUP BY
                        p.id,
                        p.brand,
                        p.article_name,
                        p.product_name,
                        p.note,
                        p.category,
                        p.image_url,
                        p.image_public_id,
                        p.minimum_threshold,
                        p.updated_at
                    ORDER BY
                        LOWER(p.product_name),
                        LOWER(p.article_name)
                    """
                )
                .all()
            )

            products = []

            for row in result.results:
                products.append({
                    "id": row.id,
                    "brand": row.brand,
                    "article_name": row.article_name,
                    "product_name": row.product_name,
                    "note": row.note,
                    "category": row.category,
                    "image_url": row.image_url,
                    "image_public_id":
                        row.image_public_id,
                    "minimum_threshold":
                        row.minimum_threshold,
                    "updated_at": row.updated_at,
                    "total_quantity":
                        row.total_quantity
                })

            return Response(
                json.dumps({
                    "product_count": len(products),
                    "products": products
                }),
                headers={
                    "content-type":
                        "application/json"
                }
            )



            

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
                        LOWER(product_name),
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
                product_id = row.product_id

                if product_id not in sizes_by_product:
                    sizes_by_product[product_id] = []

                sizes_by_product[product_id].append({
                    "id": row.id,
                    "size": row.size,
                    "quantity": row.quantity,
                    "minimum_threshold":
                        row.minimum_threshold,
                })

            products = []

            for row in product_result.results:
                sizes = sizes_by_product.get(
                    row.id,
                    []
                )

                total_quantity = sum(
                    item["quantity"]
                    for item in sizes
                )

                if total_quantity == 0:
                    status = "out"

                elif (
                    total_quantity
                    <= row.minimum_threshold
                ):
                    status = "low"

                else:
                    status = "good"

                products.append({
                    "id": row.id,
                    "brand": row.brand,
                    "article_name":
                        row.article_name,
                    "product_name":
                        row.product_name,
                    "note": row.note,
                    "category": row.category,
                    "image_url": row.image_url,
                    "image_public_id":
                        row.image_public_id,
                    "minimum_threshold":
                        row.minimum_threshold,
                    "updated_at": row.updated_at,
                    "total_quantity":
                        total_quantity,
                    "status": status,
                    "sizes": sizes,
                })

            return Response(
                json.dumps({
                    "product_count": len(products),
                    "products": products,
                }),
                headers={
                    "content-type":
                        "application/json",
                    "access-control-allow-origin":
                        "*",
                }
            )



        return Response(
            "SoleStock Cloudflare Worker is running",
            headers={
                "content-type": "text/plain"
            }
        )



