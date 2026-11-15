import os
import io
import csv

from dotenv import load_dotenv
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, or_
from werkzeug.utils import secure_filename
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

load_dotenv(override=True)
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY',
    'change-this-in-production'
)

database_url = os.environ.get('DATABASE_URL')

if database_url:
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        'sqlite:///'
        + os.path.join(
            os.path.dirname(__file__),
            'inventory.db'
        )
    )
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db = SQLAlchemy(app)
BRANDS = ['Sparx', 'Red Chief', 'Bata', 'Nike', 'Imported Brand']
CATEGORIES = ['Shoes', 'Sandals']
ALLOWED_EXTENSIONS = {'png','jpg','jpeg','webp'}

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(60), nullable=False)
    article_name = db.Column(db.String(80), nullable=False)
    product_name = db.Column(db.String(160), nullable=False)
    category = db.Column(db.String(30), nullable=False)
    image_filename = db.Column(db.String(255))
    minimum_threshold = db.Column(db.Integer, default=5, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    sizes = db.relationship('SizeStock', backref='product', cascade='all, delete-orphan', lazy=True)
    __table_args__ = (UniqueConstraint('brand', 'article_name', name='uq_brand_article'),)
    @property
    def total_quantity(self): return sum(x.quantity for x in self.sizes)
    @property
    def status(self):
        if self.total_quantity == 0: return 'out'
        if self.total_quantity <= self.minimum_threshold: return 'low'
        return 'good'

class SizeStock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    size = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Integer, default=0, nullable=False)
    minimum_threshold = db.Column(db.Integer, default=1, nullable=False)
    __table_args__ = (UniqueConstraint('product_id', 'size', name='uq_product_size'),)


def allowed_file(name): return '.' in name and name.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def apply_filters(query):
    q=request.args.get('q','').strip()
    brand=request.args.get('brand','').strip()
    category=request.args.get('category','').strip()
    size=request.args.get('size','').strip()
    status=request.args.get('status','').strip()
    if q:
        like=f'%{q}%'
        query=query.filter(or_(Product.article_name.ilike(like),Product.product_name.ilike(like),Product.brand.ilike(like),Product.category.ilike(like)))
    if brand: query=query.filter(Product.brand==brand)
    if category: query=query.filter(Product.category==category)
    if size: query=query.join(SizeStock).filter(SizeStock.size==size,SizeStock.quantity>0)
    products=query.order_by(Product.updated_at.desc()).all()
    if status: products=[p for p in products if p.status==status]
    return products

@app.route('/')
def home():
    products=Product.query.all()
    totals={'products':len(products),'pairs':sum(p.total_quantity for p in products),'shoes':sum(p.total_quantity for p in products if p.category=='Shoes'),'sandals':sum(p.total_quantity for p in products if p.category=='Sandals'),'low':sum(p.status=='low' for p in products),'out':sum(p.status=='out' for p in products)}
    brand_summary=[(b,sum(p.total_quantity for p in products if p.brand==b),sum(1 for p in products if p.brand==b)) for b in BRANDS]
    recent=sorted(products,key=lambda p:p.updated_at,reverse=True)[:5]
    alerts=[p for p in products if p.status in ('low','out')][:8]
    return render_template('home.html',totals=totals,brand_summary=brand_summary,recent=recent,alerts=alerts)

@app.route('/stocks')
def stocks():
    products=apply_filters(Product.query)
    all_sizes=sorted({s.size for s in SizeStock.query.all()}, key=lambda x:(not x.replace('.','',1).isdigit(), float(x) if x.replace('.','',1).isdigit() else x))
    return render_template('stocks.html',products=products,brands=BRANDS,categories=CATEGORIES,all_sizes=all_sizes,filter_query=request.query_string.decode())

@app.route('/product/new',methods=['GET','POST'])
@app.route('/product/<int:product_id>/edit',methods=['GET','POST'])
def product_form(product_id=None):
    product=Product.query.get_or_404(product_id) if product_id else None
    if request.method=='POST':
        brand=request.form['brand'].strip(); article=request.form['article_name'].strip(); name=request.form['product_name'].strip(); category=request.form['category']
        duplicate=Product.query.filter_by(brand=brand,article_name=article).first()
        if duplicate and (not product or duplicate.id!=product.id):
            flash('Article number already exists for this brand.','error')
            return render_template('product_form.html',product=product,brands=BRANDS,categories=CATEGORIES)
        if not product: product=Product(); db.session.add(product)
        product.brand=brand; product.article_name=article; product.product_name=name; product.category=category
        product.minimum_threshold=max(0,int(request.form.get('minimum_threshold',5) or 0))
        image=request.files.get('image')
        if image and image.filename:
            if not allowed_file(image.filename):
                flash('Use PNG, JPG, JPEG, or WEBP images only.','error'); return redirect(request.url)
            filename=f'{int(datetime.utcnow().timestamp())}_{secure_filename(image.filename)}'; image.save(os.path.join(app.config['UPLOAD_FOLDER'],filename)); product.image_filename=filename

        sizes = request.form.getlist('size[]')
        quantities = request.form.getlist('quantity[]')
        thresholds = request.form.getlist('size_threshold[]')

        submitted_sizes = {}
        duplicate_sizes = set()

        try:
            for size, quantity, threshold in zip(
                sizes,
                quantities,
                thresholds
            ):
                size = size.strip()

                if not size:
                    continue

                if size in submitted_sizes:
                    duplicate_sizes.add(size)
                    continue

                submitted_sizes[size] = {
                    'quantity': max(0, int(quantity or 0)),
                    'minimum_threshold': max(
                        0,
                        int(threshold or 0)
                    )
                }

            if duplicate_sizes:
                db.session.rollback()

                flash(
                    'Duplicate sizes are not allowed: '
                    + ', '.join(sorted(duplicate_sizes)),
                    'error'
                )

                return render_template(
                    'product_form.html',
                    product=product,
                    brands=BRANDS,
                    categories=CATEGORIES
                )

            existing_sizes = {
                stock.size: stock
                for stock in product.sizes
            }

            # Update existing sizes or add new sizes.
            for size, values in submitted_sizes.items():
                if size in existing_sizes:
                    stock = existing_sizes[size]
                    stock.quantity = values['quantity']
                    stock.minimum_threshold = values[
                        'minimum_threshold'
                    ]
                else:
                    product.sizes.append(
                        SizeStock(
                            size=size,
                            quantity=values['quantity'],
                            minimum_threshold=values[
                                'minimum_threshold'
                            ]
                        )
                    )

            # Delete sizes removed from the edit form.
            for size, stock in existing_sizes.items():
                if size not in submitted_sizes:
                    db.session.delete(stock)

            db.session.commit()

            flash(
                'Product saved successfully.',
                'success'
            )

            return redirect(
                url_for('stocks', brand=brand)
            )

        except (TypeError, ValueError):
            db.session.rollback()

            flash(
                'Quantity and minimum alert must contain valid numbers.',
                'error'
            )

            return render_template(
                'product_form.html',
                product=product,
                brands=BRANDS,
                categories=CATEGORIES
            )

        except Exception:
            db.session.rollback()
            raise
    return render_template('product_form.html',product=product,brands=BRANDS,categories=CATEGORIES)

@app.post('/product/<int:product_id>/delete')
def delete_product(product_id):
    product=Product.query.get_or_404(product_id); db.session.delete(product); db.session.commit(); flash('Product deleted.','success'); return redirect(url_for('stocks'))

@app.route('/export/<fmt>')
def export(fmt):
    products=apply_filters(Product.query)
    headers=['Brand','Article Name','Product Name','Category','Available Sizes','Size-wise Quantities','Total Quantity','Stock Status','Updated At']
    rows=[]
    for p in products:
        available=', '.join(s.size for s in p.sizes if s.quantity>0)
        breakdown=', '.join(f'{s.size}: {s.quantity}' for s in p.sizes)
        rows.append([p.brand,p.article_name,p.product_name,p.category,available,breakdown,p.total_quantity,p.status.title(),p.updated_at.strftime('%Y-%m-%d %H:%M')])
    stamp=datetime.now().strftime('%Y%m%d_%H%M')
    if fmt=='csv':
        out=io.StringIO(); w=csv.writer(out); w.writerow(headers); w.writerows(rows); data=io.BytesIO(out.getvalue().encode('utf-8-sig')); return send_file(data,as_attachment=True,download_name=f'shoe_stock_{stamp}.csv',mimetype='text/csv')
    if fmt=='xlsx':
        wb=Workbook(); ws=wb.active; ws.title='Stock'; ws.append(headers)
        for r in rows: ws.append(r)
        for cell in ws[1]: cell.font=cell.font.copy(bold=True)
        ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
        widths=[18,18,28,14,24,42,16,15,20]
        for i,w in enumerate(widths,1): ws.column_dimensions[chr(64+i)].width=w
        data=io.BytesIO(); wb.save(data); data.seek(0); return send_file(data,as_attachment=True,download_name=f'shoe_stock_{stamp}.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if fmt=='pdf':
        data=io.BytesIO(); doc=SimpleDocTemplate(data,pagesize=landscape(A4),leftMargin=22,rightMargin=22,topMargin=24,bottomMargin=24)
        styles=getSampleStyleSheet(); story=[Paragraph('Shoe Store Stock Report',styles['Title']),Spacer(1,12)]
        pdf_headers=['Brand','Article','Product','Category','Sizes / Quantities','Total','Status']
        pdf_rows=[[Paragraph(str(x),styles['BodyText']) for x in [r[0],r[1],r[2],r[3],r[5],r[6],r[7]]] for r in rows]
        table=Table([pdf_headers]+pdf_rows,colWidths=[72,75,130,60,220,45,55],repeatRows=1)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#171717')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#cfcfcf')),('VALIGN',(0,0),(-1,-1),'TOP'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f5f2eb')]),('FONTSIZE',(0,0),(-1,-1),8),('PADDING',(0,0),(-1,-1),5)])); story.append(table); doc.build(story); data.seek(0); return send_file(data,as_attachment=True,download_name=f'shoe_stock_{stamp}.pdf',mimetype='application/pdf')
    return ('Unsupported format',400)

@app.route('/api/products')
def api_products():
    brand = request.args.get('brand', '').strip()
    category = request.args.get('category', '').strip()
    article = request.args.get('article', '').strip()

    query = Product.query

    if brand:
        query = query.filter(
            db.func.lower(Product.brand) == brand.lower()
        )

    if category:
        query = query.filter(
            db.func.lower(Product.category) == category.lower()
        )

    if article:
        query = query.filter(
            db.func.lower(Product.article_name) == article.lower()
        )

    products = query.order_by(
        Product.brand,
        Product.article_name
    ).all()

    results = []

    for product in products:
        sorted_sizes = sorted(
            product.sizes,
            key=lambda item: (
                not item.size.replace('.', '', 1).isdigit(),
                float(item.size)
                if item.size.replace('.', '', 1).isdigit()
                else item.size
            )
        )

        size_details = []

        for stock in sorted_sizes:
            if stock.quantity == 0:
                size_status = 'out'
            elif stock.quantity <= stock.minimum_threshold:
                size_status = 'low'
            else:
                size_status = 'good'

            size_details.append({
                'size': stock.size,
                'quantity': stock.quantity,
                'minimum_threshold': stock.minimum_threshold,
                'status': size_status
            })

        results.append({
            'id': product.id,
            'brand': product.brand,
            'article_name': product.article_name,
            'product_name': product.product_name,
            'category': product.category,
            'sizes': size_details,
            'available_sizes': [
                stock['size']
                for stock in size_details
                if stock['quantity'] > 0
            ],
            'total_quantity': product.total_quantity,
            'stock_status': product.status
        })

    return jsonify({
        'brand_filter': brand or None,
        'category_filter': category or None,
        'article_filter': article or None,
        'product_count': len(results),
        'products': results
    })

@app.route('/api/summary')
def api_summary():
    products=Product.query.all(); return jsonify(total_products=len(products),total_pairs=sum(p.total_quantity for p in products))

def seed():
    if Product.query.count(): return
    samples=[('Sparx','SM-784',"Men's Casual Sandal",'Sandals',{'6':4,'7':5,'8':8,'9':3,'10':2}),('Sparx','SX-310',"Men's Running Shoe",'Shoes',{'6':1,'7':2,'8':1,'9':0,'10':0}),('Bata','BT-220','Classic Formal Shoe','Shoes',{'7':3,'8':4,'9':2,'10':2}),('Nike','NK-AIR-01','Air Cushion Sneaker','Shoes',{'7':0,'8':0,'9':0,'10':0}),('Red Chief','RC-115','Leather Outdoor Sandal','Sandals',{'6':2,'7':3,'8':2,'9':2,'10':1})]
    for b,a,n,c,ss in samples:
        p=Product(brand=b,article_name=a,product_name=n,category=c,minimum_threshold=5)
        p.sizes=[SizeStock(size=k,quantity=v,minimum_threshold=1) for k,v in ss.items()]; db.session.add(p)
    db.session.commit()

with app.app_context(): db.create_all(); seed()
if __name__=='__main__': app.run(host='127.0.0.1',port=5050,debug=True,use_reloader=False)
