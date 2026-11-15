import os
import io
import csv

from datetime import datetime
from secrets import compare_digest

from dotenv import load_dotenv
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    send_file,
    session
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, or_
from werkzeug.utils import secure_filename
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer
)

from config import Config


# =========================================================
# Application configuration
# =========================================================

load_dotenv(override=True)

app = Flask(__name__)
app.config.from_object(Config)

database_url = os.environ.get("DATABASE_URL")

if database_url:
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///"
        + os.path.join(
            os.path.dirname(__file__),
            "inventory.db"
        )
    )

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["UPLOAD_FOLDER"] = os.path.join(
    os.path.dirname(__file__),
    "static",
    "uploads"
)

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

os.makedirs(
    app.config["UPLOAD_FOLDER"],
    exist_ok=True
)

db = SQLAlchemy(app)


# =========================================================
# Constants
# =========================================================

BRANDS = [
    "Sparx",
    "Red Chief",
    "Bata",
    "Nike",
    "Imported Brand"
]

CATEGORIES = [
    "Shoes",
    "Sandals"
]

ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "webp"
}


# =========================================================
# Database models
# =========================================================

class Product(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    brand = db.Column(
        db.String(60),
        nullable=False
    )

    article_name = db.Column(
        db.String(80),
        nullable=False
    )

    product_name = db.Column(
        db.String(160),
        nullable=False
    )

    category = db.Column(
        db.String(30),
        nullable=False
    )

    image_filename = db.Column(
        db.String(255)
    )

    minimum_threshold = db.Column(
        db.Integer,
        default=5,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    sizes = db.relationship(
        "SizeStock",
        backref="product",
        cascade="all, delete-orphan",
        lazy=True
    )

    __table_args__ = (
        UniqueConstraint(
            "brand",
            "article_name",
            name="uq_brand_article"
        ),
    )

    @property
    def total_quantity(self):
        return sum(
            stock.quantity
            for stock in self.sizes
        )

    @property
    def status(self):
        if self.total_quantity == 0:
            return "out"

        if self.total_quantity <= self.minimum_threshold:
            return "low"

        return "good"


class SizeStock(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id"),
        nullable=False
    )

    size = db.Column(
        db.String(20),
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    minimum_threshold = db.Column(
        db.Integer,
        default=1,
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "size",
            name="uq_product_size"
        ),
    )


# =========================================================
# Helper functions
# =========================================================

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def size_sort_key(size_value):
    value = str(size_value).strip()

    if value.replace(".", "", 1).isdigit():
        return 0, float(value)

    return 1, value.lower()


def apply_filters(query):
    search_text = request.args.get(
        "q",
        ""
    ).strip()

    brand = request.args.get(
        "brand",
        ""
    ).strip()

    category = request.args.get(
        "category",
        ""
    ).strip()

    size = request.args.get(
        "size",
        ""
    ).strip()

    stock_status = request.args.get(
        "status",
        ""
    ).strip()

    if search_text:
        like_value = f"%{search_text}%"

        query = query.filter(
            or_(
                Product.article_name.ilike(like_value),
                Product.product_name.ilike(like_value),
                Product.brand.ilike(like_value),
                Product.category.ilike(like_value)
            )
        )

    if brand:
        query = query.filter(
            Product.brand == brand
        )

    if category:
        query = query.filter(
            Product.category == category
        )

    if size:
        query = query.join(
            SizeStock
        ).filter(
            SizeStock.size == size,
            SizeStock.quantity > 0
        )

    products = query.order_by(
        Product.updated_at.desc()
    ).all()

    if stock_status:
        products = [
            product
            for product in products
            if product.status == stock_status
        ]

    return products


def product_to_api_dictionary(product):
    sorted_sizes = sorted(
        product.sizes,
        key=lambda item: size_sort_key(item.size)
    )

    size_details = []

    for stock in sorted_sizes:
        if stock.quantity == 0:
            size_status = "out"
        elif stock.quantity <= stock.minimum_threshold:
            size_status = "low"
        else:
            size_status = "good"

        size_details.append({
            "size": stock.size,
            "quantity": stock.quantity,
            "minimum_threshold": stock.minimum_threshold,
            "status": size_status
        })

    return {
        "id": product.id,
        "brand": product.brand,
        "article_name": product.article_name,
        "product_name": product.product_name,
        "category": product.category,
        "image_filename": product.image_filename,
        "sizes": size_details,
        "available_sizes": [
            stock["size"]
            for stock in size_details
            if stock["quantity"] > 0
        ],
        "minimum_threshold": product.minimum_threshold,
        "total_quantity": product.total_quantity,
        "stock_status": product.status,
        "updated_at": product.updated_at.isoformat()
        if product.updated_at
        else None
    }


# =========================================================
# Login protection
# =========================================================

@app.before_request
def require_login():
    allowed_endpoints = {
        "login",
        "static"
    }

    if request.endpoint is None:
        return None

    if request.endpoint in allowed_endpoints:
        return None

    if not session.get("logged_in"):
        if request.path.startswith("/api/"):
            return jsonify({
                "error": "Authentication required"
            }), 401

        return redirect(
            url_for("login")
        )

    return None


# =========================================================
# Login and logout routes
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():
    if session.get("logged_in"):
        return redirect(
            url_for("home")
        )

    if request.method == "POST":
        user_id = request.form.get(
            "user_id",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        user_matches = compare_digest(
            user_id,
            app.config["LOGIN_USER_ID"]
        )

        password_matches = compare_digest(
            password,
            app.config["LOGIN_PASSWORD"]
        )

        if user_matches and password_matches:
            session.clear()

            session["logged_in"] = True
            session["user_id"] = user_id
            session.permanent = False

            return redirect(
                url_for("home")
            )

        flash(
            "Incorrect User ID or Password.",
            "error"
        )

    return render_template(
        "login.html"
    )


@app.post("/logout")
def logout():
    session.clear()

    flash(
        "You have been logged out successfully.",
        "success"
    )

    return redirect(
        url_for("login")
    )


# =========================================================
# Home dashboard
# =========================================================

@app.route("/")
def home():
    products = Product.query.all()

    totals = {
        "products": len(products),
        "pairs": sum(
            product.total_quantity
            for product in products
        ),
        "shoes": sum(
            product.total_quantity
            for product in products
            if product.category == "Shoes"
        ),
        "sandals": sum(
            product.total_quantity
            for product in products
            if product.category == "Sandals"
        ),
        "low": sum(
            product.status == "low"
            for product in products
        ),
        "out": sum(
            product.status == "out"
            for product in products
        )
    }

    brand_summary = [
        (
            brand,
            sum(
                product.total_quantity
                for product in products
                if product.brand == brand
            ),
            sum(
                1
                for product in products
                if product.brand == brand
            )
        )
        for brand in BRANDS
    ]

    recent = sorted(
        products,
        key=lambda product: product.updated_at,
        reverse=True
    )[:5]

    alerts = [
        product
        for product in products
        if product.status in ("low", "out")
    ][:8]

    return render_template(
        "home.html",
        totals=totals,
        brand_summary=brand_summary,
        recent=recent,
        alerts=alerts
    )


# =========================================================
# Stocks page
# =========================================================

@app.route("/stocks")
def stocks():
    products = apply_filters(
        Product.query
    )

    all_sizes = sorted(
        {
            stock.size
            for stock in SizeStock.query.all()
        },
        key=size_sort_key
    )

    return render_template(
        "stocks.html",
        products=products,
        brands=BRANDS,
        categories=CATEGORIES,
        all_sizes=all_sizes,
        filter_query=request.query_string.decode()
    )


# =========================================================
# Add and edit products
# =========================================================

@app.route(
    "/product/new",
    methods=["GET", "POST"]
)
@app.route(
    "/product/<int:product_id>/edit",
    methods=["GET", "POST"]
)
def product_form(product_id=None):
    product = (
        Product.query.get_or_404(product_id)
        if product_id
        else None
    )

    if request.method == "POST":
        try:
            brand = request.form.get(
                "brand",
                ""
            ).strip()

            article = request.form.get(
                "article_name",
                ""
            ).strip()

            product_name = request.form.get(
                "product_name",
                ""
            ).strip()

            category = request.form.get(
                "category",
                ""
            ).strip()

            if not brand:
                flash(
                    "Brand is required.",
                    "error"
                )

                return render_template(
                    "product_form.html",
                    product=product,
                    brands=BRANDS,
                    categories=CATEGORIES
                )

            if brand not in BRANDS:
                flash(
                    "Please select a valid brand.",
                    "error"
                )

                return render_template(
                    "product_form.html",
                    product=product,
                    brands=BRANDS,
                    categories=CATEGORIES
                )

            if not article:
                flash(
                    "Article name or number is required.",
                    "error"
                )

                return render_template(
                    "product_form.html",
                    product=product,
                    brands=BRANDS,
                    categories=CATEGORIES
                )

            if not product_name:
                flash(
                    "Product name is required.",
                    "error"
                )

                return render_template(
                    "product_form.html",
                    product=product,
                    brands=BRANDS,
                    categories=CATEGORIES
                )

            if category not in CATEGORIES:
                flash(
                    "Please select a valid category.",
                    "error"
                )

                return render_template(
                    "product_form.html",
                    product=product,
                    brands=BRANDS,
                    categories=CATEGORIES
                )

            duplicate = Product.query.filter(
                db.func.lower(Product.brand)
                == brand.lower(),
                db.func.lower(Product.article_name)
                == article.lower()
            ).first()

            if (
                duplicate
                and (
                    not product
                    or duplicate.id != product.id
                )
            ):
                flash(
                    "Article number already exists for this brand.",
                    "error"
                )

                return render_template(
                    "product_form.html",
                    product=product,
                    brands=BRANDS,
                    categories=CATEGORIES
                )

            if not product:
                product = Product()
                db.session.add(product)

            product.brand = brand
            product.article_name = article
            product.product_name = product_name
            product.category = category

            product.minimum_threshold = max(
                0,
                int(
                    request.form.get(
                        "minimum_threshold",
                        5
                    ) or 0
                )
            )

            # ---------------------------------------------
            # Product image handling
            # ---------------------------------------------

            image = request.files.get(
                "image"
            )

            if image and image.filename:
                if not allowed_file(image.filename):
                    db.session.rollback()

                    flash(
                        "Use PNG, JPG, JPEG, or WEBP images only.",
                        "error"
                    )

                    return render_template(
                        "product_form.html",
                        product=product,
                        brands=BRANDS,
                        categories=CATEGORIES
                    )

                old_image_filename = product.image_filename

                safe_filename = secure_filename(
                    image.filename
                )

                timestamp = datetime.utcnow().strftime(
                    "%Y%m%d%H%M%S%f"
                )

                filename = (
                    f"{timestamp}_{safe_filename}"
                )

                image_path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    filename
                )

                image.save(
                    image_path
                )

                product.image_filename = filename

                if old_image_filename:
                    old_image_path = os.path.join(
                        app.config["UPLOAD_FOLDER"],
                        old_image_filename
                    )

                    if (
                        os.path.isfile(old_image_path)
                        and old_image_filename != filename
                    ):
                        try:
                            os.remove(old_image_path)
                        except OSError:
                            pass

            # ---------------------------------------------
            # Size-wise stock handling
            # ---------------------------------------------

            sizes = request.form.getlist(
                "size[]"
            )

            quantities = request.form.getlist(
                "quantity[]"
            )

            thresholds = request.form.getlist(
                "size_threshold[]"
            )

            submitted_sizes = {}
            duplicate_sizes = set()

            for size, quantity, threshold in zip(
                sizes,
                quantities,
                thresholds
            ):
                size = str(size).strip()

                if not size:
                    continue

                normalized_size = size.lower()

                if normalized_size in submitted_sizes:
                    duplicate_sizes.add(size)
                    continue

                submitted_sizes[normalized_size] = {
                    "display_size": size,
                    "quantity": max(
                        0,
                        int(quantity or 0)
                    ),
                    "minimum_threshold": max(
                        0,
                        int(threshold or 0)
                    )
                }

            if duplicate_sizes:
                db.session.rollback()

                flash(
                    "Duplicate sizes are not allowed: "
                    + ", ".join(
                        sorted(
                            duplicate_sizes,
                            key=size_sort_key
                        )
                    ),
                    "error"
                )

                return render_template(
                    "product_form.html",
                    product=product,
                    brands=BRANDS,
                    categories=CATEGORIES
                )

            if not submitted_sizes:
                db.session.rollback()

                flash(
                    "Add at least one product size.",
                    "error"
                )

                return render_template(
                    "product_form.html",
                    product=product,
                    brands=BRANDS,
                    categories=CATEGORIES
                )

            existing_sizes = {
                stock.size.strip().lower(): stock
                for stock in product.sizes
            }

            # Update existing sizes or add new sizes.
            for normalized_size, values in submitted_sizes.items():
                if normalized_size in existing_sizes:
                    stock = existing_sizes[
                        normalized_size
                    ]

                    stock.size = values[
                        "display_size"
                    ]

                    stock.quantity = values[
                        "quantity"
                    ]

                    stock.minimum_threshold = values[
                        "minimum_threshold"
                    ]
                else:
                    product.sizes.append(
                        SizeStock(
                            size=values[
                                "display_size"
                            ],
                            quantity=values[
                                "quantity"
                            ],
                            minimum_threshold=values[
                                "minimum_threshold"
                            ]
                        )
                    )

            # Delete sizes removed from the edit form.
            for normalized_size, stock in existing_sizes.items():
                if normalized_size not in submitted_sizes:
                    db.session.delete(stock)

            db.session.commit()

            flash(
                "Product saved successfully.",
                "success"
            )

            return redirect(
                url_for(
                    "stocks",
                    brand=brand
                )
            )

        except (TypeError, ValueError):
            db.session.rollback()

            flash(
                "Quantity, stock threshold, and minimum alert "
                "must contain valid numbers.",
                "error"
            )

            return render_template(
                "product_form.html",
                product=product,
                brands=BRANDS,
                categories=CATEGORIES
            )

        except Exception:
            db.session.rollback()
            raise

    return render_template(
        "product_form.html",
        product=product,
        brands=BRANDS,
        categories=CATEGORIES
    )


# =========================================================
# Delete product
# =========================================================

@app.post(
    "/product/<int:product_id>/delete"
)
def delete_product(product_id):
    product = Product.query.get_or_404(
        product_id
    )

    image_filename = product.image_filename

    try:
        db.session.delete(product)
        db.session.commit()

        if image_filename:
            image_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                image_filename
            )

            if os.path.isfile(image_path):
                try:
                    os.remove(image_path)
                except OSError:
                    pass

        flash(
            "Product deleted successfully.",
            "success"
        )

    except Exception:
        db.session.rollback()

        flash(
            "Unable to delete the product.",
            "error"
        )

    return redirect(
        url_for("stocks")
    )


# =========================================================
# Export inventory
# =========================================================

@app.route("/export/<fmt>")
def export(fmt):
    products = apply_filters(
        Product.query
    )

    headers = [
        "Brand",
        "Article Name",
        "Product Name",
        "Category",
        "Available Sizes",
        "Size-wise Quantities",
        "Total Quantity",
        "Stock Status",
        "Updated At"
    ]

    rows = []

    for product in products:
        sorted_sizes = sorted(
            product.sizes,
            key=lambda stock: size_sort_key(stock.size)
        )

        available = ", ".join(
            stock.size
            for stock in sorted_sizes
            if stock.quantity > 0
        )

        breakdown = ", ".join(
            f"{stock.size}: {stock.quantity}"
            for stock in sorted_sizes
        )

        rows.append([
            product.brand,
            product.article_name,
            product.product_name,
            product.category,
            available,
            breakdown,
            product.total_quantity,
            product.status.title(),
            product.updated_at.strftime(
                "%Y-%m-%d %H:%M"
            )
        ])

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M"
    )

    if fmt == "csv":
        output = io.StringIO()

        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)

        data = io.BytesIO(
            output.getvalue().encode(
                "utf-8-sig"
            )
        )

        data.seek(0)

        return send_file(
            data,
            as_attachment=True,
            download_name=f"shoe_stock_{stamp}.csv",
            mimetype="text/csv"
        )

    if fmt == "xlsx":
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Stock"

        worksheet.append(headers)

        for row in rows:
            worksheet.append(row)

        for cell in worksheet[1]:
            cell.font = cell.font.copy(
                bold=True
            )

        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

        widths = [
            18,
            18,
            28,
            14,
            24,
            42,
            16,
            15,
            20
        ]

        for index, width in enumerate(
            widths,
            start=1
        ):
            worksheet.column_dimensions[
                chr(64 + index)
            ].width = width

        data = io.BytesIO()
        workbook.save(data)
        data.seek(0)

        return send_file(
            data,
            as_attachment=True,
            download_name=f"shoe_stock_{stamp}.xlsx",
            mimetype=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )

    if fmt == "pdf":
        data = io.BytesIO()

        document = SimpleDocTemplate(
            data,
            pagesize=landscape(A4),
            leftMargin=22,
            rightMargin=22,
            topMargin=24,
            bottomMargin=24
        )

        styles = getSampleStyleSheet()

        story = [
            Paragraph(
                "Shoe Store Stock Report",
                styles["Title"]
            ),
            Spacer(1, 12)
        ]

        pdf_headers = [
            "Brand",
            "Article",
            "Product",
            "Category",
            "Sizes / Quantities",
            "Total",
            "Status"
        ]

        pdf_rows = []

        for row in rows:
            selected_values = [
                row[0],
                row[1],
                row[2],
                row[3],
                row[5],
                row[6],
                row[7]
            ]

            pdf_rows.append([
                Paragraph(
                    str(value),
                    styles["BodyText"]
                )
                for value in selected_values
            ])

        table = Table(
            [pdf_headers] + pdf_rows,
            colWidths=[
                72,
                75,
                130,
                60,
                220,
                45,
                55
            ],
            repeatRows=1
        )

        table.setStyle(
            TableStyle([
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#171717")
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#cfcfcf")
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP"
                ),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [
                        colors.white,
                        colors.HexColor("#f5f2eb")
                    ]
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    8
                ),
                (
                    "PADDING",
                    (0, 0),
                    (-1, -1),
                    5
                )
            ])
        )

        story.append(table)
        document.build(story)

        data.seek(0)

        return send_file(
            data,
            as_attachment=True,
            download_name=f"shoe_stock_{stamp}.pdf",
            mimetype="application/pdf"
        )

    return (
        "Unsupported export format",
        400
    )


# =========================================================
# Read inventory API
# =========================================================

@app.route("/api/products")
def api_products():
    brand = request.args.get(
        "brand",
        ""
    ).strip()

    category = request.args.get(
        "category",
        ""
    ).strip()

    article = request.args.get(
        "article",
        ""
    ).strip()

    query = Product.query

    if brand:
        query = query.filter(
            db.func.lower(Product.brand)
            == brand.lower()
        )

    if category:
        query = query.filter(
            db.func.lower(Product.category)
            == category.lower()
        )

    if article:
        query = query.filter(
            db.func.lower(Product.article_name)
            == article.lower()
        )

    products = query.order_by(
        Product.brand,
        Product.article_name
    ).all()

    results = [
        product_to_api_dictionary(product)
        for product in products
    ]

    return jsonify({
        "brand_filter": brand or None,
        "category_filter": category or None,
        "article_filter": article or None,
        "product_count": len(results),
        "products": results
    })


# =========================================================
# Add product API
# =========================================================

@app.post("/api/products")
def api_add_product():
    data = request.get_json(
        silent=True
    )

    if not data:
        return jsonify({
            "error": "JSON request body is required"
        }), 400

    required_fields = [
        "brand",
        "article_name",
        "product_name",
        "category"
    ]

    missing_fields = [
        field
        for field in required_fields
        if not str(
            data.get(field, "")
        ).strip()
    ]

    if missing_fields:
        return jsonify({
            "error": "Required fields are missing",
            "missing_fields": missing_fields
        }), 400

    brand = str(
        data["brand"]
    ).strip()

    article_name = str(
        data["article_name"]
    ).strip()

    product_name = str(
        data["product_name"]
    ).strip()

    category = str(
        data["category"]
    ).strip()

    if brand not in BRANDS:
        return jsonify({
            "error": "Invalid brand",
            "allowed_brands": BRANDS
        }), 400

    if category not in CATEGORIES:
        return jsonify({
            "error": "Invalid category",
            "allowed_categories": CATEGORIES
        }), 400

    duplicate = Product.query.filter(
        db.func.lower(Product.brand)
        == brand.lower(),
        db.func.lower(Product.article_name)
        == article_name.lower()
    ).first()

    if duplicate:
        return jsonify({
            "error": (
                "Article already exists for this brand"
            ),
            "product_id": duplicate.id
        }), 409

    try:
        product = Product(
            brand=brand,
            article_name=article_name,
            product_name=product_name,
            category=category,
            minimum_threshold=max(
                0,
                int(
                    data.get(
                        "minimum_threshold",
                        5
                    )
                )
            )
        )

        seen_sizes = set()

        for item in data.get(
            "sizes",
            []
        ):
            size = str(
                item.get(
                    "size",
                    ""
                )
            ).strip()

            normalized_size = size.lower()

            if not size:
                continue

            if normalized_size in seen_sizes:
                return jsonify({
                    "error": (
                        f"Duplicate size submitted: {size}"
                    )
                }), 400

            seen_sizes.add(
                normalized_size
            )

            product.sizes.append(
                SizeStock(
                    size=size,
                    quantity=max(
                        0,
                        int(
                            item.get(
                                "quantity",
                                0
                            )
                        )
                    ),
                    minimum_threshold=max(
                        0,
                        int(
                            item.get(
                                "minimum_threshold",
                                1
                            )
                        )
                    )
                )
            )

        if not product.sizes:
            return jsonify({
                "error": (
                    "At least one size is required"
                )
            }), 400

        db.session.add(product)
        db.session.commit()

        return jsonify({
            "message": (
                "Product added successfully"
            ),
            "product": product_to_api_dictionary(
                product
            )
        }), 201

    except (TypeError, ValueError):
        db.session.rollback()

        return jsonify({
            "error": (
                "Quantity and threshold values "
                "must be valid integers"
            )
        }), 400

    except Exception:
        db.session.rollback()
        raise


# =========================================================
# Delete product API
# =========================================================

@app.delete(
    "/api/products/<int:product_id>"
)
def api_delete_product(product_id):
    product = db.session.get(
        Product,
        product_id
    )

    if not product:
        return jsonify({
            "error": "Product not found"
        }), 404

    deleted_product = {
        "id": product.id,
        "brand": product.brand,
        "article_name": product.article_name,
        "product_name": product.product_name
    }

    image_filename = product.image_filename

    try:
        db.session.delete(product)
        db.session.commit()

        if image_filename:
            image_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                image_filename
            )

            if os.path.isfile(image_path):
                try:
                    os.remove(image_path)
                except OSError:
                    pass

        return jsonify({
            "message": (
                "Product deleted successfully"
            ),
            "deleted_product": deleted_product
        }), 200

    except Exception:
        db.session.rollback()
        raise


# =========================================================
# Summary API
# =========================================================

@app.route("/api/summary")
def api_summary():
    products = Product.query.all()

    return jsonify({
        "total_products": len(products),
        "total_pairs": sum(
            product.total_quantity
            for product in products
        ),
        "total_shoes": sum(
            product.total_quantity
            for product in products
            if product.category == "Shoes"
        ),
        "total_sandals": sum(
            product.total_quantity
            for product in products
            if product.category == "Sandals"
        ),
        "low_stock_products": sum(
            product.status == "low"
            for product in products
        ),
        "out_of_stock_products": sum(
            product.status == "out"
            for product in products
        )
    })


# =========================================================
# Initial sample data
# =========================================================

def seed():
    if Product.query.count():
        return

    samples = [
        (
            "Sparx",
            "SM-784",
            "Men's Casual Sandal",
            "Sandals",
            {
                "6": 4,
                "7": 5,
                "8": 8,
                "9": 3,
                "10": 2,
                "11": 0,
                "12": 0
            }
        ),
        (
            "Sparx",
            "SX-310",
            "Men's Running Shoe",
            "Shoes",
            {
                "6": 1,
                "7": 2,
                "8": 1,
                "9": 0,
                "10": 0,
                "11": 0,
                "12": 0
            }
        ),
        (
            "Bata",
            "BT-220",
            "Classic Formal Shoe",
            "Shoes",
            {
                "6": 0,
                "7": 3,
                "8": 4,
                "9": 2,
                "10": 2,
                "11": 0,
                "12": 0
            }
        ),
        (
            "Nike",
            "NK-AIR-01",
            "Air Cushion Sneaker",
            "Shoes",
            {
                "6": 0,
                "7": 0,
                "8": 0,
                "9": 0,
                "10": 0,
                "11": 0,
                "12": 0
            }
        ),
        (
            "Red Chief",
            "RC-115",
            "Leather Outdoor Sandal",
            "Sandals",
            {
                "6": 2,
                "7": 3,
                "8": 2,
                "9": 2,
                "10": 1,
                "11": 0,
                "12": 0
            }
        )
    ]

    for (
        brand,
        article,
        product_name,
        category,
        size_stock
    ) in samples:
        product = Product(
            brand=brand,
            article_name=article,
            product_name=product_name,
            category=category,
            minimum_threshold=5
        )

        product.sizes = [
            SizeStock(
                size=size,
                quantity=quantity,
                minimum_threshold=1
            )
            for size, quantity
            in size_stock.items()
        ]

        db.session.add(product)

    db.session.commit()


# =========================================================
# Database initialization
# =========================================================

with app.app_context():
    db.create_all()
    seed()


# =========================================================
# Run application
# =========================================================

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5050,
        debug=True,
        use_reloader=False
    )