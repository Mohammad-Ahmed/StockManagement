import os
import io
import csv
from datetime import datetime
from secrets import compare_digest
import time

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, or_, func, text
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from config import Config

load_dotenv(override=True)
app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600
app.config.from_object(Config)

database_url = os.environ.get("DATABASE_URL")
if database_url:
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_size": 5,
        "max_overflow": 5,
        "pool_timeout": 10,
    }
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(os.path.dirname(__file__), "inventory.db")

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)
CATEGORIES = ["Shoes", "Sandals"]
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


class Brand(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(60), nullable=False, index=True)
    article_name = db.Column(db.String(80), nullable=False, index=True)
    product_name = db.Column(db.String(160), nullable=False)
    category = db.Column(db.String(30), nullable=False, index=True)
    image_filename = db.Column(db.String(255))
    minimum_threshold = db.Column(db.Integer, default=5, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)
    sizes = db.relationship("SizeStock", backref="product", cascade="all, delete-orphan", lazy=True)
    __table_args__ = (UniqueConstraint("brand", "article_name", name="uq_brand_article"),)

    @property
    def total_quantity(self):
        return sum(stock.quantity for stock in self.sizes)

    @property
    def status(self):
        if self.total_quantity == 0:
            return "out"
        if self.total_quantity <= self.minimum_threshold:
            return "low"
        return "good"


class SizeStock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    size = db.Column(db.String(20), nullable=False, index=True)
    quantity = db.Column(db.Integer, default=0, nullable=False)
    minimum_threshold = db.Column(db.Integer, default=1, nullable=False)
    __table_args__ = (UniqueConstraint("product_id", "size", name="uq_product_size"),)


def get_brand_names():
    return [brand.name for brand in Brand.query.order_by(Brand.name.asc()).all()]


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def size_sort_key(size_value):
    value = str(size_value).strip()
    if value.replace(".", "", 1).isdigit():
        return 0, float(value)
    return 1, value.lower()


def apply_filters(query):
    search_text = request.args.get("q", "").strip()
    brand = request.args.get("brand", "").strip()
    category = request.args.get("category", "").strip()
    size = request.args.get("size", "").strip()
    stock_status = request.args.get("status", "").strip()

    if search_text:
        value = f"%{search_text}%"
        query = query.filter(or_(Product.article_name.ilike(value), Product.product_name.ilike(value), Product.brand.ilike(value), Product.category.ilike(value)))
    if brand:
        query = query.filter(Product.brand == brand)
    if category:
        query = query.filter(Product.category == category)
    if size:
        query = query.join(SizeStock).filter(SizeStock.size == size, SizeStock.quantity > 0)

    products = query.options(selectinload(Product.sizes)).order_by(Product.updated_at.desc()).all()
    if stock_status:
        products = [product for product in products if product.status == stock_status]
    return products


def product_to_dict(product):
    size_details = []
    for stock in sorted(product.sizes, key=lambda item: size_sort_key(item.size)):
        status = "out" if stock.quantity == 0 else "low" if stock.quantity <= stock.minimum_threshold else "good"
        size_details.append({"size": stock.size, "quantity": stock.quantity, "minimum_threshold": stock.minimum_threshold, "status": status})
    return {
        "id": product.id,
        "brand": product.brand,
        "article_name": product.article_name,
        "product_name": product.product_name,
        "category": product.category,
        "image_filename": product.image_filename,
        "sizes": size_details,
        "available_sizes": [item["size"] for item in size_details if item["quantity"] > 0],
        "minimum_threshold": product.minimum_threshold,
        "total_quantity": product.total_quantity,
        "stock_status": product.status,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
    }


@app.before_request
def require_login():
    if request.endpoint in {None, "login", "static"}:
        return None
    if not session.get("logged_in"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Authentication required"}), 401
        return redirect(url_for("login"))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("home"))
    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip()
        password = request.form.get("password", "")
        if compare_digest(user_id, app.config["LOGIN_USER_ID"]) and compare_digest(password, app.config["LOGIN_PASSWORD"]):
            session.clear()
            session["logged_in"] = True
            session["user_id"] = user_id
            session.permanent = False
            return redirect(url_for("home"))
        flash("Incorrect User ID or Password.", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/brands", methods=["GET", "POST"])
def manage_brands():
    if request.method == "POST":
        brand_name = request.form.get("brand_name", "").strip()
        if not brand_name:
            flash("Brand name is required.", "error")
            return redirect(url_for("manage_brands"))
        existing = Brand.query.filter(func.lower(Brand.name) == brand_name.lower()).first()
        if existing:
            flash("This brand already exists.", "error")
            return redirect(url_for("manage_brands"))
        db.session.add(Brand(name=brand_name))
        db.session.commit()
        flash(f'Brand "{brand_name}" added successfully.', "success")
        return redirect(url_for("manage_brands"))

    brands = Brand.query.order_by(Brand.name.asc()).all()
    product_counts = db.session.query(func.lower(Product.brand), func.count(Product.id)).group_by(func.lower(Product.brand)).all()
    counts_by_name = dict(product_counts)
    brand_product_counts = {brand.id: counts_by_name.get(brand.name.lower(), 0) for brand in brands}
    return render_template("brands.html", brands=brands, brand_product_counts=brand_product_counts)


@app.post("/brands/<int:brand_id>/rename")
def rename_brand(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    new_name = request.form.get("brand_name", "").strip()
    if not new_name:
        flash("Brand name is required.", "error")
        return redirect(url_for("manage_brands"))
    duplicate = Brand.query.filter(func.lower(Brand.name) == new_name.lower(), Brand.id != brand.id).first()
    if duplicate:
        flash("Another brand already uses this name.", "error")
        return redirect(url_for("manage_brands"))
    old_name = brand.name
    try:
        for product in Product.query.filter(func.lower(Product.brand) == old_name.lower()).all():
            product.brand = new_name
        brand.name = new_name
        db.session.commit()
        flash(f'Brand renamed from "{old_name}" to "{new_name}".', "success")
    except Exception:
        db.session.rollback()
        raise
    return redirect(url_for("manage_brands"))


@app.post("/brands/<int:brand_id>/delete")
def delete_brand(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    count = Product.query.filter(func.lower(Product.brand) == brand.name.lower()).count()
    if count:
        flash(f'Cannot delete "{brand.name}" because {count} product(s) use this brand.', "error")
        return redirect(url_for("manage_brands"))
    name = brand.name
    db.session.delete(brand)
    db.session.commit()
    flash(f'Brand "{name}" deleted successfully.', "success")
    return redirect(url_for("manage_brands"))


@app.route("/")
def home():
    products = Product.query.options(selectinload(Product.sizes)).all()
    totals = {
        "products": len(products),
        "pairs": sum(p.total_quantity for p in products),
        "shoes": sum(p.total_quantity for p in products if p.category == "Shoes"),
        "sandals": sum(p.total_quantity for p in products if p.category == "Sandals"),
        "low": sum(p.status == "low" for p in products),
        "out": sum(p.status == "out" for p in products),
    }
    brand_summary = [(brand, sum(p.total_quantity for p in products if p.brand == brand), sum(1 for p in products if p.brand == brand)) for brand in get_brand_names()]
    recent = sorted(products, key=lambda p: p.updated_at, reverse=True)[:5]

    stock_alerts = []
    for product in products:
        zero_sizes = sorted(
            [stock.size for stock in product.sizes if stock.quantity == 0],
            key=size_sort_key,
        )
        if zero_sizes:
            stock_alerts.append({
                "product": product,
                "zero_sizes": zero_sizes,
            })

    stock_alerts.sort(
        key=lambda alert: (
            alert["product"].brand.lower(),
            alert["product"].article_name.lower(),
        )
    )

    return render_template(
        "home.html",
        totals=totals,
        brand_summary=brand_summary,
        recent=recent,
        alerts=stock_alerts,
    )


@app.route("/stocks")
def stocks():
    products = apply_filters(Product.query)
   all_sizes = sorted(
    [
        row[0]
        for row in db.session.query(
            SizeStock.size
        )
        .distinct()
        .all()
    ],
    key=size_sort_key
)
    return render_template("stocks.html", products=products, brands=get_brand_names(), categories=CATEGORIES, all_sizes=all_sizes, filter_query=request.query_string.decode())


@app.route("/product/new", methods=["GET", "POST"])
@app.route("/product/<int:product_id>/edit", methods=["GET", "POST"])
def product_form(product_id=None):
    product = Product.query.options(selectinload(Product.sizes)).filter_by(id=product_id).first_or_404() if product_id else None
    brands = get_brand_names()
    if request.method == "POST":
        try:
            brand = request.form.get("brand", "").strip()
            article = request.form.get("article_name", "").strip()
            product_name = request.form.get("product_name", "").strip()
            category = request.form.get("category", "").strip()
            if brand not in brands or not article or not product_name or category not in CATEGORIES:
                flash("Please complete all product fields correctly.", "error")
                return render_template("product_form.html", product=product, brands=brands, categories=CATEGORIES)

            duplicate = Product.query.filter(func.lower(Product.brand) == brand.lower(), func.lower(Product.article_name) == article.lower()).first()
            if duplicate and (not product or duplicate.id != product.id):
                flash("Article number already exists for this brand.", "error")
                return render_template("product_form.html", product=product, brands=brands, categories=CATEGORIES)

            if not product:
                product = Product()
                db.session.add(product)
            product.brand = brand
            product.article_name = article
            product.product_name = product_name
            product.category = category
            product.minimum_threshold = max(0, int(request.form.get("minimum_threshold", 5) or 0))

            image = request.files.get("image")
            if image and image.filename:
                if not allowed_file(image.filename):
                    db.session.rollback()
                    flash("Use PNG, JPG, JPEG, or WEBP images only.", "error")
                    return render_template("product_form.html", product=product, brands=brands, categories=CATEGORIES)
                old_image = product.image_filename
                filename = f'{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}_{secure_filename(image.filename)}'
                image.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                product.image_filename = filename
                if old_image:
                    old_path = os.path.join(app.config["UPLOAD_FOLDER"], old_image)
                    if os.path.isfile(old_path):
                        try:
                            os.remove(old_path)
                        except OSError:
                            pass

            submitted = {}
            duplicates = set()
            for size, quantity, threshold in zip(request.form.getlist("size[]"), request.form.getlist("quantity[]"), request.form.getlist("size_threshold[]")):
                size = str(size).strip()
                if not size:
                    continue
                key = size.lower()
                if key in submitted:
                    duplicates.add(size)
                    continue
                submitted[key] = {"display": size, "quantity": max(0, int(quantity or 0)), "threshold": max(0, int(threshold or 0))}
            if duplicates or not submitted:
                db.session.rollback()
                flash("Duplicate sizes are not allowed." if duplicates else "Add at least one product size.", "error")
                return render_template("product_form.html", product=product, brands=brands, categories=CATEGORIES)

            existing = {stock.size.strip().lower(): stock for stock in product.sizes}
            for key, values in submitted.items():
                if key in existing:
                    stock = existing[key]
                    stock.size = values["display"]
                    stock.quantity = values["quantity"]
                    stock.minimum_threshold = values["threshold"]
                else:
                    product.sizes.append(SizeStock(size=values["display"], quantity=values["quantity"], minimum_threshold=values["threshold"]))
            for key, stock in existing.items():
                if key not in submitted:
                    db.session.delete(stock)
            db.session.commit()
            flash("Product saved successfully.", "success")
            return redirect(url_for("stocks", brand=brand))
        except (TypeError, ValueError):
            db.session.rollback()
            flash("Quantity and threshold values must be valid numbers.", "error")
        except Exception:
            db.session.rollback()
            raise
    return render_template("product_form.html", product=product, brands=brands, categories=CATEGORIES)


@app.post("/product/<int:product_id>/delete")
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    image_filename = product.image_filename
    db.session.delete(product)
    db.session.commit()
    if image_filename:
        path = os.path.join(app.config["UPLOAD_FOLDER"], image_filename)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
    flash("Product deleted successfully.", "success")
    return redirect(url_for("stocks"))


@app.route("/export/<fmt>")
def export(fmt):
    products = apply_filters(Product.query)
    headers = ["Brand", "Article Name", "Product Name", "Category", "Available Sizes", "Size-wise Quantities", "Total Quantity", "Stock Status", "Updated At"]
    rows = []
    for product in products:
        sizes = sorted(product.sizes, key=lambda stock: size_sort_key(stock.size))
        rows.append([product.brand, product.article_name, product.product_name, product.category, ", ".join(s.size for s in sizes if s.quantity > 0), ", ".join(f"{s.size}: {s.quantity}" for s in sizes), product.total_quantity, product.status.title(), product.updated_at.strftime("%Y-%m-%d %H:%M")])
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    if fmt == "csv":
        output = io.StringIO(); writer = csv.writer(output); writer.writerow(headers); writer.writerows(rows)
        data = io.BytesIO(output.getvalue().encode("utf-8-sig")); data.seek(0)
        return send_file(data, as_attachment=True, download_name=f"shoe_stock_{stamp}.csv", mimetype="text/csv")
    if fmt == "xlsx":
        workbook = Workbook(); sheet = workbook.active; sheet.title = "Stock"; sheet.append(headers)
        for row in rows: sheet.append(row)
        for cell in sheet[1]: cell.font = cell.font.copy(bold=True)
        sheet.freeze_panes = "A2"; sheet.auto_filter.ref = sheet.dimensions
        for index, width in enumerate([18, 18, 28, 14, 24, 42, 16, 15, 20], 1): sheet.column_dimensions[chr(64 + index)].width = width
        data = io.BytesIO(); workbook.save(data); data.seek(0)
        return send_file(data, as_attachment=True, download_name=f"shoe_stock_{stamp}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if fmt == "pdf":
        data = io.BytesIO(); document = SimpleDocTemplate(data, pagesize=landscape(A4), leftMargin=22, rightMargin=22, topMargin=24, bottomMargin=24)
        styles = getSampleStyleSheet(); story = [Paragraph("Shoe Store Stock Report", styles["Title"]), Spacer(1, 12)]
        pdf_rows = [[Paragraph(str(value), styles["BodyText"]) for value in [row[0], row[1], row[2], row[3], row[5], row[6], row[7]]] for row in rows]
        table = Table([["Brand", "Article", "Product", "Category", "Sizes / Quantities", "Total", "Status"]] + pdf_rows, colWidths=[72, 75, 130, 60, 220, 45, 55], repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#171717")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("GRID", (0,0), (-1,-1), .4, colors.HexColor("#cfcfcf")), ("VALIGN", (0,0), (-1,-1), "TOP"), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f5f2eb")]), ("FONTSIZE", (0,0), (-1,-1), 8), ("PADDING", (0,0), (-1,-1), 5)]))
        story.append(table); document.build(story); data.seek(0)
        return send_file(data, as_attachment=True, download_name=f"shoe_stock_{stamp}.pdf", mimetype="application/pdf")
    return "Unsupported export format", 400


@app.route("/api/products")
def api_products():
    brand = request.args.get("brand", "").strip(); category = request.args.get("category", "").strip(); article = request.args.get("article", "").strip()
    query = Product.query.options(selectinload(Product.sizes))
    if brand: query = query.filter(func.lower(Product.brand) == brand.lower())
    if category: query = query.filter(func.lower(Product.category) == category.lower())
    if article: query = query.filter(func.lower(Product.article_name) == article.lower())
    products = query.order_by(Product.brand, Product.article_name).all()
    return jsonify({"brand_filter": brand or None, "category_filter": category or None, "article_filter": article or None, "product_count": len(products), "products": [product_to_dict(p) for p in products]})


@app.post("/api/products")
def api_add_product():
    data = request.get_json(silent=True) or {}
    brand = str(data.get("brand", "")).strip(); article = str(data.get("article_name", "")).strip(); name = str(data.get("product_name", "")).strip(); category = str(data.get("category", "")).strip()
    if brand not in get_brand_names() or not article or not name or category not in CATEGORIES:
        return jsonify({"error": "Invalid or missing product fields"}), 400
    if Product.query.filter(func.lower(Product.brand) == brand.lower(), func.lower(Product.article_name) == article.lower()).first():
        return jsonify({"error": "Article already exists for this brand"}), 409
    try:
        product = Product(brand=brand, article_name=article, product_name=name, category=category, minimum_threshold=max(0, int(data.get("minimum_threshold", 5))))
        seen = set()
        for item in data.get("sizes", []):
            size = str(item.get("size", "")).strip(); key = size.lower()
            if not size or key in seen: continue
            seen.add(key)
            product.sizes.append(SizeStock(size=size, quantity=max(0, int(item.get("quantity", 0))), minimum_threshold=max(0, int(item.get("minimum_threshold", 1)))))
        if not product.sizes: return jsonify({"error": "At least one size is required"}), 400
        db.session.add(product); db.session.commit()
        return jsonify({"message": "Product added successfully", "product": product_to_dict(product)}), 201
    except (TypeError, ValueError):
        db.session.rollback(); return jsonify({"error": "Quantity and threshold values must be integers"}), 400


@app.delete("/api/products/<int:product_id>")
def api_delete_product(product_id):
    product = db.session.get(Product, product_id)
    if not product: return jsonify({"error": "Product not found"}), 404
    deleted = {"id": product.id, "brand": product.brand, "article_name": product.article_name, "product_name": product.product_name}
    db.session.delete(product); db.session.commit()
    return jsonify({"message": "Product deleted successfully", "deleted_product": deleted})


@app.route("/api/summary")
def api_summary():
    products = Product.query.options(selectinload(Product.sizes)).all()
    return jsonify({"total_products": len(products), "total_pairs": sum(p.total_quantity for p in products), "total_shoes": sum(p.total_quantity for p in products if p.category == "Shoes"), "total_sandals": sum(p.total_quantity for p in products if p.category == "Sandals"), "low_stock_products": sum(p.status == "low" for p in products), "out_of_stock_products": sum(p.status == "out" for p in products)})


def seed():
    for name in ["Sparx", "Red Chief", "Bata", "Nike", "Imported Brand"]:
        if not Brand.query.filter(func.lower(Brand.name) == name.lower()).first():
            db.session.add(Brand(name=name))
    db.session.commit()


def initialize_database():
    with app.app_context():
        db.create_all()
        seed()
        for statement in [
            "CREATE INDEX IF NOT EXISTS ix_product_brand ON product (brand)",
            "CREATE INDEX IF NOT EXISTS ix_product_article_name ON product (article_name)",
            "CREATE INDEX IF NOT EXISTS ix_product_category ON product (category)",
            "CREATE INDEX IF NOT EXISTS ix_product_updated_at ON product (updated_at)",
            "CREATE INDEX IF NOT EXISTS ix_size_stock_size ON size_stock (size)",
        ]:
            db.session.execute(text(statement))
        db.session.commit()


if __name__ == "__main__":
    initialize_database()
    app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False)
