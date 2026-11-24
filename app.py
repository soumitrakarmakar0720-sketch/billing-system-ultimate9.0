"""OWL STORE Ultimate: deployable Flask billing, staff, customer portal, gateway checkout."""
import base64
import csv
import hashlib
import hmac
import io
import os
import re
import secrets
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from types import SimpleNamespace
from urllib.parse import quote, urlparse

import qrcode
import requests
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

D = Decimal
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', ''),
    SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///owlstore-ultimate.db').replace('postgres://', 'postgresql+psycopg://', 1).replace('postgresql://', 'postgresql+psycopg://', 1),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', '1') == '1',
    MAX_CONTENT_LENGTH=1024 * 1024,
)
if not app.config['SECRET_KEY'] or app.config['SECRET_KEY'] == 'change-me':
    raise RuntimeError('Set a strong SECRET_KEY environment variable')
db = SQLAlchemy(app)
UPI_ID = os.environ.get('UPI_ID', 'owlstore@ybl')
UPI_NAME = os.environ.get('UPI_NAME', 'OWL STORE')
CF_ID = os.environ.get('CASHFREE_CLIENT_ID', '')
CF_SECRET = os.environ.get('CASHFREE_CLIENT_SECRET', '')
CF_ENV = os.environ.get('CASHFREE_ENV', 'sandbox')
CF_BASE = 'https://api.cashfree.com/pg' if CF_ENV == 'production' else 'https://sandbox.cashfree.com/pg'


def now(): return datetime.now(timezone.utc)
def money(v): return D(str(v)).quantize(D('.01'), rounding=ROUND_HALF_UP)
def rupees(v): return f'{money(v):,.2f}'
app.jinja_env.filters['rupees'] = rupees


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='staff')
    active = db.Column(db.Boolean, default=True, nullable=False)


class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

class StaffBranch(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'), nullable=False)

class TerminalPresence(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    seen_at = db.Column(db.DateTime(timezone=True), nullable=False)

class BillBranch(db.Model):
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'), nullable=False)

class TerminalAccess(db.Model):
    __tablename__ = 'terminal_access'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)


class TerminalTransaction(db.Model):
    __tablename__ = 'terminal_transaction'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)


class TerminalDispatch(db.Model):
    """One-time payment instruction for a particular terminal and existing invoice."""
    __tablename__ = 'terminal_dispatch'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    acknowledged_at = db.Column(db.DateTime(timezone=True))


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    sku = db.Column(db.String(100), default='')
    price = db.Column(db.Numeric(12, 2), nullable=False)
    stock = db.Column(db.Integer, default=0, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(45), unique=True, nullable=False)
    customer = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20), default='')
    email = db.Column(db.String(200), default='')
    subtotal = db.Column(db.Numeric(12, 2), nullable=False)
    discount = db.Column(db.Numeric(12, 2), default=0)
    tax_rate = db.Column(db.Numeric(6, 2), default=0)
    tax = db.Column(db.Numeric(12, 2), default=0)
    total = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(30), default='PENDING', nullable=False)
    payment_ref = db.Column(db.String(120), default='')
    payment_reported_at = db.Column(db.DateTime(timezone=True))
    rejection_reason = db.Column(db.String(300), default='')
    public_token = db.Column(db.String(90), unique=True, nullable=False)
    gateway_order_id = db.Column(db.String(90), unique=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)
    items = db.relationship('OrderItem', backref='order', cascade='all, delete-orphan', lazy='select')
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    deleted_by = db.Column(db.String(100), nullable=True)
    parent_order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True, index=True)
    installment_number = db.Column(db.Integer, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    emi_months = db.Column(db.Integer, nullable=True)
    installments = db.relationship('Order', backref=db.backref('parent_order', remote_side='Order.id'), lazy='select')


class EMIForeclosure(db.Model):
    __tablename__ = 'emi_foreclosure'
    id = db.Column(db.Integer, primary_key=True)
    parent_order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False, index=True)
    gateway_order_id = db.Column(db.String(90), unique=True, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='PENDING')
    payment_ref = db.Column(db.String(120))
    created_at = db.Column(db.DateTime(timezone=True), default=now, nullable=False)


def emi_children(parent_id):
    return Order.query.filter_by(parent_order_id=parent_id, deleted_at=None).order_by(Order.installment_number).all()


def current_emi(parent_id):
    return next((x for x in emi_children(parent_id) if x.status != 'PAID'), None)


def enforce_emi_payment(order):
    if order.parent_order_id is None: return
    parent = db.session.get(Order, order.parent_order_id)
    if not parent or parent.deleted_at or parent.status != 'EMI_PLAN':
        abort(409, 'This EMI plan is not accepting installment payments')
    if EMIForeclosure.query.filter_by(parent_order_id=parent.id, status='PENDING').first():
        abort(409, 'Foreclosure payment is in progress; contact the store')
    if current_emi(parent.id) != order:
        abort(409, 'Pay the earliest outstanding installment first')


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, nullable=True)
    name = db.Column(db.String(200), nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(12, 2), nullable=False)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)


class Audit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    order_id = db.Column(db.Integer)
    details = db.Column(db.String(500), default='')
    created_at = db.Column(db.DateTime(timezone=True), default=now)


class WebhookEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_key = db.Column(db.String(128), unique=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now)


def log(action, order=None, details='', actor=None):
    db.session.add(Audit(actor=actor or session.get('username', 'system'), action=action, order_id=order.id if order else None, details=str(details)[:500]))


def csrf_token():
    if '_csrf' not in session: session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']


@app.before_request
def protect_forms():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.endpoint != 'cashfree_webhook':
        if not hmac.compare_digest(request.form.get('_csrf', ''), session.get('_csrf', '')) or not session.get('_csrf'):
            abort(400, 'Invalid form token; reload the page and retry')


@app.context_processor
def globals_for_templates():
    return dict(store_name='OWL STORE', upi_id=UPI_ID, csrf_token=csrf_token, is_admin=session.get('role') == 'admin')


def auth(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('user_id'): return redirect(url_for('login'))
            user = db.session.get(User, session['user_id'])
            if not user or not user.active:
                session.clear()
                return redirect(url_for('login'))
            if role and user.role != role: abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def order_for_token(token):
    return Order.query.filter_by(public_token=token, deleted_at=None).filter(Order.status != 'EMI_PLAN').first_or_404()


def upi_uri(order):
    return f"upi://pay?pa={quote(UPI_ID)}&pn={quote(UPI_NAME)}&am={order.total:.2f}&cu=INR&tn={quote('OWL STORE '+order.order_no)}&tr={quote(order.order_no)}"


@app.get('/')
def home():
    return render_template('customer_bills.html', matches=None)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username', '').strip()).first()
        if user and user.active and check_password_hash(user.password_hash, request.form.get('password', '')):
            session.clear()
            session.update(user_id=user.id, username=user.username, role=user.role)
            return redirect(url_for('dashboard'))
        flash('Incorrect login details', 'error')
    return render_template('login.html')


@app.post('/logout')
def logout(): session.clear(); return redirect(url_for('login'))


@app.get('/dashboard')
@auth()
def dashboard():
    stats = dict(sales=Order.query.filter(Order.deleted_at.is_(None), Order.status != 'EMI_PLAN').count(), revenue=db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(Order.status == 'PAID', Order.deleted_at.is_(None)).scalar(), pending=Order.query.filter(Order.status.in_(['PENDING', 'PAYMENT_REPORTED']), Order.deleted_at.is_(None)).count(), products=Product.query.filter_by(active=True).count())
    return render_template('dashboard.html', stats=stats, orders=Order.query.filter(Order.deleted_at.is_(None), Order.parent_order_id.is_(None)).order_by(Order.id.desc()).limit(8).all())


@app.route('/products', methods=['GET', 'POST'])
@auth()
def products():
    if request.method == 'POST':
        try:
            name = request.form['name'].strip(); price = money(request.form['price']); stock = int(request.form['stock'])
            if not name or price < 0 or stock < 0: raise ValueError()
            db.session.add(Product(name=name, sku=request.form.get('sku', '').strip(), price=price, stock=stock))
            log('PRODUCT_CREATED', details=name); db.session.commit()
            flash('Product created', 'success')
        except (ValueError, InvalidOperation, KeyError):
            db.session.rollback(); flash('Invalid product', 'error')
        return redirect(url_for('products'))
    return render_template('products.html', products=Product.query.filter_by(active=True).order_by(Product.id.desc()).all())


@app.post('/products/<int:product_id>/delete')
@auth('admin')
def delete_product(product_id):
    product = db.get_or_404(Product, product_id); product.active = False
    log('PRODUCT_ARCHIVED', details=product.name); db.session.commit()
    return redirect(url_for('products'))


@app.get('/new-bill')
@auth()
def new_bill(): return render_template('new_bill.html', products=Product.query.filter_by(active=True).order_by(Product.name).all())


@app.post('/create-order')
@auth()
def create_order():
    try:
        customer = request.form.get('customer', '').strip(); phone = request.form.get('phone', '').strip()
        discount = money(request.form.get('discount', '0')); tax_rate = money(request.form.get('tax_rate', '0'))
        ids = request.form.getlist('product_id[]'); qtys = request.form.getlist('qty[]')
        if not customer or len(customer) > 150 or len(ids) != len(qtys) or not ids or len(ids) > 100 or not (0 <= tax_rate <= 100) or discount < 0: raise ValueError()
        items = []; subtotal = D('0')
        for pid, qty_text in zip(ids, qtys):
            qty = int(qty_text)
            if not 1 <= qty <= 10000: raise ValueError()
            product = db.session.get(Product, int(pid))
            if not product or not product.active: raise ValueError()
            line = money(product.price * qty); subtotal += line
            items.append(OrderItem(product_id=product.id, name=product.name, qty=qty, price=product.price, line_total=line))
        if discount > subtotal: raise ValueError()
        tax = money((subtotal - discount) * tax_rate / 100)
        order = Order(order_no='OWL-'+now().strftime('%y%m%d')+'-'+secrets.token_hex(4).upper(), customer=customer, phone=phone[:20], subtotal=subtotal, discount=discount, tax_rate=tax_rate, tax=tax, total=subtotal-discount+tax, status='PENDING', public_token=secrets.token_urlsafe(32), items=items)
        emi_months = int(request.form.get('emi_months', '1'))
        if emi_months not in (1, 3, 6, 9, 12, 18, 24, 36): raise ValueError()
        if emi_months > 1 and (order.total <= 0 or order.total < D('0.01') * emi_months): raise ValueError()
        db.session.add(order); db.session.flush()
        record_bill_branch(order, session['user_id'])
        if emi_months > 1:
            order.status = 'EMI_PLAN'  # Parent is a summary, never payable or counted as revenue.
            order.emi_months = emi_months
            start_text = request.form.get('first_due_date', '').strip()
            first_due = date.fromisoformat(start_text) if start_text else now().date()
            if first_due < now().date(): raise ValueError()
            cents = int((money(order.total) * 100).to_integral_value())
            share, remainder = divmod(cents, emi_months)
            for i in range(emi_months):
                year = first_due.year + (first_due.month - 1 + i) // 12
                month = (first_due.month - 1 + i) % 12 + 1
                from calendar import monthrange
                due = date(year, month, min(first_due.day, monthrange(year, month)[1]))
                part = D(share + (remainder if i == emi_months - 1 else 0)) / 100
                child = Order(order_no=f'{order.order_no}-EMI{i+1:02d}', customer=order.customer, phone=order.phone, email=order.email, subtotal=part, discount=0, tax_rate=0, tax=0, total=part, status='PENDING', public_token=secrets.token_urlsafe(32), parent_order_id=order.id, installment_number=i+1, due_date=due)
                db.session.add(child)
            log('EMI_PLAN_CREATED', order, f'{emi_months} installments')
        else:
            log('ORDER_CREATED', order)
        # Reuse the original bill: assign normal dashboard bills to their creator's terminal.
        # EMI parent orders are summaries; each installment remains governed by EMI rules.
        if emi_months == 1 and session.get('user_id'):
            db.session.add(TerminalTransaction(order_id=order.id, user_id=session['user_id']))
        db.session.commit()
        return redirect(url_for('emi_detail', order_id=order.id) if emi_months > 1 else url_for('checkout', token=order.public_token))
    except (ValueError, InvalidOperation, KeyError, TypeError, OverflowError):
        db.session.rollback(); flash('Check customer, quantities, discount, tax and EMI schedule', 'error')
        return redirect(url_for('new_bill'))


@app.get('/pay/<token>')
def checkout(token):
    order = order_for_token(token)
    if order.deleted_at or order.status == 'EMI_PLAN': abort(404)
    locked = bool(order.parent_order_id and (not db.session.get(Order, order.parent_order_id) or db.session.get(Order, order.parent_order_id).status != 'EMI_PLAN' or current_emi(order.parent_order_id) != order or EMIForeclosure.query.filter_by(parent_order_id=order.parent_order_id, status='PENDING').first()))
    return render_template('checkout.html', order=order, gateway_enabled=bool(CF_ID and CF_SECRET), locked=locked)


@app.route('/customer/bills', methods=['GET', 'POST'])
def customer_bills():
    matches = None
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        if not re.fullmatch(r'[0-9]{10}', phone):
            flash('Enter a valid 10-digit mobile number', 'error')
        else:
            matches = Order.query.filter_by(phone=phone, deleted_at=None, parent_order_id=None).order_by(Order.created_at.desc()).limit(50).all()
    return render_template('customer_bills.html', matches=matches)


@app.get('/qr/<token>.png')
def qr_image(token):
    order = order_for_token(token)
    enforce_emi_payment(order)
    img = qrcode.make(upi_uri(order)); out = io.BytesIO(); img.save(out, format='PNG'); out.seek(0)
    return send_file(out, mimetype='image/png')


@app.post('/pay/<token>/report')
def report_payment(token):
    order = order_for_token(token)
    enforce_emi_payment(order)
    ref = request.form.get('payment_ref', '').strip()
    if order.status == 'PAID' or len(ref) < 6 or len(ref) > 100 or not re.fullmatch(r'[A-Za-z0-9_\-/ ]+', ref):
        flash('Enter a valid UPI reference (6–100 characters) for an unpaid order', 'error')
        return redirect(url_for('checkout', token=token))
    order.status = 'PAYMENT_REPORTED'; order.payment_ref = ref; order.payment_reported_at = now(); order.rejection_reason = ''
    log('PAYMENT_REPORTED', order, ref, actor='customer'); db.session.commit()
    flash('Payment reported; awaiting verification', 'success')
    return redirect(url_for('checkout', token=token))


@app.get('/orders')
@auth()
def orders(): return render_template('orders.html', orders=Order.query.filter(Order.deleted_at.is_(None), Order.parent_order_id.is_(None)).order_by(Order.id.desc()).limit(300).all())


IST = timezone(timedelta(hours=5, minutes=30))

@app.template_filter('bill_date')
def bill_date(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(IST).date().isoformat()


def report_dates():
    today = now().astimezone(IST).date()
    period = request.args.get('period', 'all')
    ranges = {'today': (today, today), 'yesterday': (today-timedelta(days=1), today-timedelta(days=1)), 'week': (today-timedelta(days=today.weekday()), today), 'month': (today.replace(day=1), today)}
    if period in ranges:
        start, end = ranges[period]
    elif period == 'custom':
        try:
            start = date.fromisoformat(request.args['start'])
            end = date.fromisoformat(request.args['end'])
            if start > end or end == date.max: raise ValueError()
        except (ValueError, KeyError):
            abort(400, 'Choose a valid start and end date')
    else:
        period, start, end = 'all', None, None
    return period, start, end


@app.get('/admin/sales')
@app.get('/admin/bills')
@auth('admin')
def view_bills():
    q = request.args.get('q', '').strip()[:100]
    status = request.args.get('status', '').strip()[:40]
    period, start, end = report_dates()
    query = Order.query.filter(Order.deleted_at.is_(None))
    if start:
        query = query.filter(Order.created_at >= datetime.combine(start, datetime.min.time(), IST).astimezone(timezone.utc), Order.created_at < datetime.combine(end+timedelta(days=1), datetime.min.time(), IST).astimezone(timezone.utc))
    if q:
        query = query.filter(db.or_(Order.order_no.ilike('%'+q+'%'), Order.customer.ilike('%'+q+'%'), Order.phone.ilike('%'+q+'%')))
    if status:
        query = query.filter(Order.status == status)
    sales = query.filter(Order.parent_order_id.is_(None))
    count, total = sales.with_entities(func.count(Order.id), func.coalesce(func.sum(Order.total), 0)).one()
    paid = sales.filter(Order.status == 'PAID').with_entities(func.coalesce(func.sum(Order.total), 0)).scalar()
    unpaid = sales.filter(Order.status.notin_(['PAID','EMI_PLAN','FORECLOSED'])).with_entities(func.coalesce(func.sum(Order.total), 0)).scalar()
    daily = {}
    for created, amount in sales.with_entities(Order.created_at, Order.total).yield_per(500):
        key = bill_date(created)
        n, value = daily.get(key, (0, D('0')))
        daily[key] = (n+1, value+amount)
    page = query.order_by(Order.created_at.desc(), Order.id.desc()).paginate(page=max(1, request.args.get('page', 1, type=int)), per_page=50, error_out=False)
    return render_template('view_bills.html', page=page, q=q, status=status, period=period, start=start.isoformat() if start else '', end=end.isoformat() if end else '', sales_count=count, sales_total=total, paid=paid, unpaid=unpaid, daily=sorted(daily.items(), reverse=True))


@app.post('/orders/<int:order_id>/status')
@auth('admin')
def update_status(order_id):
    order = db.get_or_404(Order, order_id); action = request.form.get('action')
    if order.deleted_at or order.status == 'EMI_PLAN': abort(409)
    if action == 'confirm': enforce_emi_payment(order)
    if action not in ('confirm', 'reject'): abort(400)
    if order.status == 'PAID': abort(409, 'Paid orders cannot be changed using manual approval')
    if order.status not in ('PAYMENT_REPORTED', 'PAYMENT_REJECTED'):
        abort(409, 'Wait for a customer payment report before manual review')
    if action == 'confirm':
        if not request.form.get('verified', '') == 'yes': abort(400, 'Bank verification acknowledgment required')
        order.status = 'PAID'; order.rejection_reason = ''; log('MANUAL_PAYMENT_CONFIRMED', order, order.payment_ref)
    else:
        reason = request.form.get('reason', '').strip()
        if len(reason) < 3 or len(reason) > 300: abort(400, 'Provide a rejection reason')
        order.status = 'PAYMENT_REJECTED'; order.rejection_reason = reason; log('PAYMENT_REJECTED', order, reason)
    db.session.commit(); flash('Payment status updated', 'success')
    return redirect(url_for('orders'))


@app.get('/invoice/<token>')
def invoice(token): return render_template('invoice.html', order=order_for_token(token))


@app.get('/invoice/<token>.pdf')
def invoice_pdf(token):
    order = order_for_token(token)
    output = io.BytesIO(); c = canvas.Canvas(output, pagesize=A4); w, h = A4
    c.setFont('Helvetica-Bold', 19); c.drawString(44, h-54, 'OWL STORE - INVOICE')
    c.setFont('Helvetica', 10)
    for i, line in enumerate([f'Invoice: {order.order_no}', f'Customer: {order.customer[:65]}', f'Status: {order.status}', f'Date: {order.created_at.date().isoformat()}']): c.drawString(44, h-85-i*19, line)
    y = h-180
    for item in order.items:
        if y < 90: c.showPage(); y = h-70; c.setFont('Helvetica', 10)
        c.drawString(44, y, f'{item.name[:55]}  x{item.qty}  INR {item.line_total:.2f}'); y -= 19
    c.setFont('Helvetica-Bold', 12); c.drawString(44, y-25, f'TOTAL: INR {order.total:.2f}')
    c.setFont('Helvetica', 9); c.drawString(44, y-45, 'Payment receipt only when status is PAID. Tax details depend on your legal configuration.')
    c.save(); output.seek(0)
    return send_file(output, mimetype='application/pdf', as_attachment=True, download_name=f'{order.order_no}.pdf')


@app.get('/staff')
@auth('admin')
def staff(): return render_template('staff.html', users=User.query.order_by(User.id).all(), branches=Branch.query.order_by(Branch.name).all(), assignments={a.user_id:a.branch_id for a in StaffBranch.query.all()})


@app.post('/staff')
@auth('admin')
def add_staff():
    username = request.form.get('username', '').strip(); password = request.form.get('password', '')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{3,50}', username) or len(password) < 12: abort(400, 'Username invalid or password shorter than 12 characters')
    if User.query.filter_by(username=username).first(): abort(409, 'Username exists')
    branch = db.get_or_404(Branch, request.form.get('branch_id', type=int) or 0)
    user = User(username=username, password_hash=generate_password_hash(password), role='staff')
    db.session.add(user); db.session.flush()
    db.session.add(StaffBranch(user_id=user.id, branch_id=branch.id))
    log('STAFF_CREATED', details=username); db.session.commit(); return redirect(url_for('staff'))


@app.post('/staff/<int:user_id>/toggle')
@auth('admin')
def toggle_staff(user_id):
    user = db.get_or_404(User, user_id)
    if user.role == 'admin': abort(403)
    user.active = not user.active; log('STAFF_STATUS_CHANGED', details=f'{user.username}: {user.active}'); db.session.commit()
    return redirect(url_for('staff'))


@app.get('/audit')
@auth('admin')
def audit(): return render_template('audit.html', events=Audit.query.order_by(Audit.id.desc()).limit(300).all())


@app.get('/export/orders.csv')
@auth('admin')
def export_orders():
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(['Order', 'Customer', 'Phone', 'Total INR', 'Status', 'Reference', 'Created UTC'])
    for o in Order.query.order_by(Order.id.desc()).all(): writer.writerow([o.order_no, o.customer, o.phone, o.total, o.status, o.payment_ref, o.created_at.isoformat()])
    data = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(data, mimetype='text/csv', as_attachment=True, download_name='owl-orders.csv')


def cf_headers():
    return {'x-client-id': CF_ID, 'x-client-secret': CF_SECRET, 'x-api-version': '2023-08-01', 'Content-Type': 'application/json'}


@app.post('/pay/<token>/cashfree')
def cashfree_start(token):
    if not (CF_ID and CF_SECRET): abort(503, 'Cashfree not configured')
    order = order_for_token(token)
    if order.deleted_at or order.status == 'EMI_PLAN': abort(409)
    enforce_emi_payment(order)
    if order.status == 'PAID': abort(409)
    if order.total <= 0: abort(400)
    if not re.fullmatch(r'\d{10}', order.phone or ''):
        flash('A valid 10-digit customer phone is required for online gateway checkout', 'error')
        return redirect(url_for('checkout', token=token))
    if not order.gateway_order_id:
        order.gateway_order_id = 'owlu_' + str(order.id) + '_' + secrets.token_hex(5)
        db.session.commit()
    # Gateway order ID is stable; repeated calls use Cashfree's existing order where possible.
    payload = {'order_id': order.gateway_order_id, 'order_amount': float(order.total), 'order_currency': 'INR', 'customer_details': {'customer_id': f'owl_{order.id}', 'customer_name': order.customer[:100], 'customer_phone': order.phone}, 'order_meta': {'return_url': url_for('checkout', token=token, _external=True), 'notify_url': url_for('cashfree_webhook', _external=True)}}
    try:
        response = requests.post(CF_BASE+'/orders', headers=cf_headers(), json=payload, timeout=12)
        if response.status_code == 409:
            response = requests.get(CF_BASE+'/orders/'+order.gateway_order_id, headers=cf_headers(), timeout=12)
        response.raise_for_status(); data = response.json()
    except (requests.RequestException, ValueError) as exc:
        # Do not log credentials, request headers, or full API responses.
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            app.logger.error('Cashfree create order rejected: HTTP %s', exc.response.status_code)
        else:
            app.logger.exception('Cashfree create order failed')
        flash('Payment gateway unavailable; try again later', 'error')
        return redirect(url_for('checkout', token=token))
    payment_session_id = data.get('payment_session_id')
    if not payment_session_id:
        flash('Gateway did not return a payment session', 'error'); return redirect(url_for('checkout', token=token))
    # Normal-dashboard staff initiate checkout on their assigned terminal, not on this device.
    # Public customer checkouts and EMI installments retain their existing Cashfree behavior.
    uid = session.get('user_id')
    tx = TerminalTransaction.query.filter_by(order_id=order.id, user_id=uid).first() if uid else None
    if tx and order.parent_order_id is None:
        # Dispatch only AFTER Cashfree confirms the session exists; never emit phantom jobs.
        # Replace old unacknowledged dispatches for this bill to prevent stale launches.
        TerminalDispatch.query.filter_by(order_id=order.id, acknowledged_at=None).delete()
        db.session.add(TerminalDispatch(order_id=order.id, user_id=uid,
                                        expires_at=now() + timedelta(minutes=10)))
        log('TERMINAL_CASHFREE_DISPATCHED', order)
        db.session.commit()
        return redirect(url_for('dashboard_payment_wait', order_id=order.id))
    return render_template('gateway.html', order=order, payment_session_id=payment_session_id, cf_env=CF_ENV)


def verify_cf_webhook(raw, timestamp, signature):
    expected = base64.b64encode(hmac.new(CF_SECRET.encode(), (timestamp.encode()+raw), hashlib.sha256).digest()).decode()
    return bool(CF_SECRET and timestamp and signature and hmac.compare_digest(expected, signature))


@app.post('/webhooks/cashfree')
@app.post('/cashfree/webhook')
def cashfree_webhook():
    raw = request.get_data()
    if not verify_cf_webhook(raw, request.headers.get('x-webhook-timestamp', ''), request.headers.get('x-webhook-signature', '')): abort(401)
    try: data = request.get_json(force=True)
    except Exception: abort(400)
    info = data.get('data') or {}; order_info = info.get('order') or {}; payment = info.get('payment') or {}
    gateway_id = order_info.get('order_id'); payment_status = payment.get('payment_status')
    if not gateway_id: return jsonify(ok=True)
    order = Order.query.filter_by(gateway_order_id=gateway_id).first()
    if not order:
        foreclosure = EMIForeclosure.query.filter_by(gateway_order_id=gateway_id).first()
        if foreclosure: return handle_foreclosure_webhook(data, foreclosure, order_info, payment)
        return jsonify(ok=True)
    # Cashfree amount must be compared to the original order; never trust a browser redirect.
    try: received = money(payment.get('payment_amount', '-1'))
    except (InvalidOperation, ValueError): received = D('-1')
    if data.get('type') != 'PAYMENT_SUCCESS_WEBHOOK' or payment_status != 'SUCCESS' or received != money(order.total): return jsonify(ok=True)
    if order_info.get('order_currency', 'INR') != 'INR': return jsonify(ok=True)
    event_id = str(payment.get('cf_payment_id') or '')
    if not event_id: return jsonify(ok=True)
    event_key = hashlib.sha256(f'{gateway_id}:{event_id}:SUCCESS'.encode()).hexdigest()
    if WebhookEvent.query.filter_by(event_key=event_key).first(): return jsonify(ok=True)
    db.session.add(WebhookEvent(event_key=event_key))
    if order.status != 'PAID':
        order.status = 'PAID'; order.payment_ref = event_id
        log('GATEWAY_PAYMENT_CONFIRMED', order, event_id, actor='cashfree')
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception('Cashfree webhook database update failed')
        return jsonify(ok=False), 500
    return jsonify(ok=True)




def handle_foreclosure_webhook(data, foreclosure, order_info, payment):
    if data.get('type') != 'PAYMENT_SUCCESS_WEBHOOK' or payment.get('payment_status') != 'SUCCESS':
        return jsonify(ok=True)
    try: received = money(payment.get('payment_amount', '-1'))
    except (InvalidOperation, ValueError): return jsonify(ok=True)
    if received != money(foreclosure.amount) or order_info.get('order_currency', 'INR') != 'INR':
        return jsonify(ok=True)
    payment_id = str(payment.get('cf_payment_id') or '')
    if not payment_id: return jsonify(ok=True)
    try:
        # Lock parent to serialize against concurrent payment confirmations.
        parent = db.session.query(Order).filter_by(id=foreclosure.parent_order_id).with_for_update().one()
        db.session.refresh(foreclosure)
        if foreclosure.status == 'PAID': return jsonify(ok=True)
        if parent.status != 'EMI_PLAN': return jsonify(ok=True)
        remaining = emi_children(parent.id)
        outstanding = sum((money(x.total) for x in remaining if x.status != 'PAID'), D('0'))
        if outstanding != money(foreclosure.amount):
            app.logger.error('Foreclosure balance mismatch for parent %s', parent.id)
            db.session.rollback(); return jsonify(ok=False), 409
        foreclosure.status = 'PAID'; foreclosure.payment_ref = payment_id
        for installment in remaining:
            if installment.status != 'PAID': installment.status = 'SETTLED_FORECLOSURE'
        parent.status = 'FORECLOSED'
        log('EMI_FORECLOSED', parent, 'Verified Cashfree foreclosure payment', actor='cashfree')
        db.session.commit()
    except Exception:
        db.session.rollback(); app.logger.exception('Foreclosure webhook failed')
        return jsonify(ok=False), 500
    return jsonify(ok=True)


@app.post('/emi/<int:order_id>/foreclose')
@auth('admin')
def start_foreclosure(order_id):
    if not (CF_ID and CF_SECRET): abort(503, 'Cashfree not configured')
    parent = db.get_or_404(Order, order_id)
    if parent.status != 'EMI_PLAN' or parent.deleted_at: abort(409)
    existing = EMIForeclosure.query.filter_by(parent_order_id=parent.id, status='PENDING').first()
    if existing:
        flash('A foreclosure payment is already pending. Resolve it before starting another.', 'error')
        return redirect(url_for('emi_detail', order_id=parent.id))
    parts = emi_children(parent.id)
    if any(x.status == 'PAYMENT_REPORTED' for x in parts):
        abort(409, 'Verify or reject manually reported payments before foreclosure')
    amount = sum((money(x.total) for x in parts if x.status != 'PAID'), D('0'))
    if amount <= 0: abort(409)
    gateway_id = 'owlfc_' + str(parent.id) + '_' + secrets.token_hex(5)
    record = EMIForeclosure(parent_order_id=parent.id, gateway_order_id=gateway_id, amount=amount)
    db.session.add(record); db.session.commit()
    payload = {'order_id': gateway_id, 'order_amount': float(amount), 'order_currency': 'INR',
        'customer_details': {'customer_id': f'owl_{parent.id}', 'customer_name': parent.customer[:100], 'customer_phone': parent.phone},
        'order_meta': {'return_url': url_for('emi_detail', order_id=parent.id, _external=True), 'notify_url': url_for('cashfree_webhook', _external=True)}}
    try:
        response = requests.post(CF_BASE+'/orders', headers=cf_headers(), json=payload, timeout=12)
        response.raise_for_status(); data = response.json()
    except (requests.RequestException, ValueError):
        app.logger.exception('Cashfree foreclosure order creation failed')
        flash('Could not create foreclosure payment; contact admin to reconcile before retrying.', 'error')
        return redirect(url_for('emi_detail', order_id=parent.id))
    if not data.get('payment_session_id'):
        flash('Cashfree session missing; reconcile before retrying', 'error')
        return redirect(url_for('emi_detail', order_id=parent.id))
    return render_template('gateway.html', order=parent, payment_session_id=data['payment_session_id'], cf_env=CF_ENV)


def foreclosure_checkout_session(foreclosure, parent):
    """Retrieve an existing Cashfree session, or create it for this recorded request.

    Never create a second gateway order when the status of the first is unknown.
    """
    if not (CF_ID and CF_SECRET): abort(503, 'Cashfree is not configured')
    payload = {
        'order_id': foreclosure.gateway_order_id,
        'order_amount': float(money(foreclosure.amount)),
        'order_currency': 'INR',
        'customer_details': {
            'customer_id': f'owl_{parent.id}',
            'customer_name': parent.customer[:100],
            'customer_phone': parent.phone,
        },
        'order_meta': {
            'return_url': url_for('customer_emi', token=parent.public_token, _external=True),
            'notify_url': url_for('cashfree_webhook', _external=True),
        },
    }
    response = requests.get(CF_BASE + '/orders/' + foreclosure.gateway_order_id,
                            headers=cf_headers(), timeout=12)
    if response.status_code == 404:
        response = requests.post(CF_BASE + '/orders', headers=cf_headers(),
                                 json=payload, timeout=12)
        if response.status_code == 409:
            response = requests.get(CF_BASE + '/orders/' + foreclosure.gateway_order_id,
                                    headers=cf_headers(), timeout=12)
    response.raise_for_status()
    data = response.json()
    # If Cashfree already considers the order paid, wait for reconciliation/webhook.
    if data.get('order_status') == 'PAID':
        abort(409, 'Payment is being verified. Please refresh the EMI plan shortly.')
    payment_session_id = data.get('payment_session_id')
    if not payment_session_id: abort(503, 'Gateway session unavailable; contact the store')
    return payment_session_id


@app.post('/customer/emi/<token>/foreclose')
def customer_start_foreclosure(token):
    """Token-authorized customer action; CSRF applies through protect_forms."""
    parent = Order.query.filter_by(public_token=token, parent_order_id=None,
                                   deleted_at=None).first_or_404()
    if parent.status != 'EMI_PLAN': abort(409, 'This plan is not active')
    if not re.fullmatch(r'\d{10}', parent.phone or ''):
        abort(409, 'A valid customer phone is required for Cashfree checkout')
    # Serialize initiation for this parent across concurrent workers.
    try:
        parent = db.session.query(Order).filter_by(id=parent.id).with_for_update().one()
        if parent.status != 'EMI_PLAN' or parent.deleted_at: abort(409)
        parts = emi_children(parent.id)
        if not parts or any(x.status == 'PAYMENT_REPORTED' for x in parts):
            abort(409, 'A reported payment needs verification before foreclosure')
        # An existing installment checkout may already be paid but awaiting webhook.
        # Require reconciliation of its gateway status before starting foreclosure.
        outstanding = [x for x in parts if x.status != 'PAID']
        if any(x.gateway_order_id for x in outstanding):
            abort(409, 'An installment gateway payment must be reconciled before foreclosure')
        amount = sum((money(x.total) for x in outstanding), D('0'))
        if amount <= 0: abort(409, 'No outstanding installments')
        record = EMIForeclosure.query.filter_by(parent_order_id=parent.id, status='PENDING').first()
        if record is None:
            record = EMIForeclosure(parent_order_id=parent.id,
                gateway_order_id='owlfc_' + str(parent.id) + '_' + secrets.token_hex(5),
                amount=amount)
            db.session.add(record)
            db.session.commit()
        else:
            if money(record.amount) != amount:
                abort(409, 'Pending foreclosure amount differs; contact OWL STORE')
            db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    try:
        payment_session_id = foreclosure_checkout_session(record, parent)
    except (requests.RequestException, ValueError):
        app.logger.exception('Customer foreclosure Cashfree session failed')
        flash('Unable to start foreclosure checkout. Try again later or contact OWL STORE.', 'error')
        return redirect(url_for('customer_emi', token=token))
    display_order = SimpleNamespace(order_no=parent.order_no + ' · Full EMI settlement', total=record.amount)
    return render_template('gateway.html', order=display_order,
                           payment_session_id=payment_session_id, cf_env=CF_ENV)


@app.get('/customer/emi/<token>')
def customer_emi(token):
    parent = Order.query.filter_by(public_token=token, deleted_at=None, parent_order_id=None).first_or_404()
    if parent.status not in ('EMI_PLAN', 'FORECLOSED'): abort(404)
    parts = emi_children(parent.id)
    paid = sum((money(x.total) for x in parts if x.status == 'PAID'), D('0'))
    pending = EMIForeclosure.query.filter_by(parent_order_id=parent.id, status='PENDING').first()
    return render_template('customer_emi.html', parent=parent, parts=parts, paid=paid,
                           remaining=sum((money(x.total) for x in parts if x.status != 'PAID'), D('0')),
                           foreclosure=pending,
                           current=current_emi(parent.id) if parent.status == 'EMI_PLAN' and not pending else None)


@app.get('/emi/<int:order_id>')
@auth()
def emi_detail(order_id):
    parent = db.get_or_404(Order, order_id)
    if parent.status not in ('EMI_PLAN', 'FORECLOSED') or parent.deleted_at: abort(404)
    parts = Order.query.filter_by(parent_order_id=parent.id).order_by(Order.installment_number).all()
    paid = sum((money(x.total) for x in parts if x.status == 'PAID'), D('0'))
    return render_template('emi_detail.html', parent=parent, parts=parts, paid=paid, current=current_emi(parent.id) if parent.status == 'EMI_PLAN' else None, foreclosure=EMIForeclosure.query.filter_by(parent_order_id=parent.id, status='PENDING').first())


@app.get('/emi')
@auth()
def emi_list():
    plans = Order.query.filter(Order.status.in_(['EMI_PLAN', 'FORECLOSED']), Order.deleted_at.is_(None)).order_by(Order.id.desc()).all()
    return render_template('emi_list.html', plans=plans)



@app.post('/orders/<int:order_id>/delete')
@auth('admin')
def delete_bill(order_id):
    order = db.get_or_404(Order, order_id)

    if order.deleted_at is not None:
        abort(409, 'Bill is already in Trash')

    if order.parent_order_id is not None:
        abort(409, 'Delete EMI bills through their parent order')

    if request.form.get('confirm') != order.order_no:
        abort(400, 'Enter the exact bill number')

    # Protect active EMI plans and ongoing payments.
    if order.status == 'EMI_PLAN':
        abort(409, 'Close or settle the EMI plan before archiving')

    if order.status == 'PAYMENT_REPORTED':
        abort(409, 'Verify the reported payment first')

    # Do not archive while a foreclosure is pending.
    if EMIForeclosure.query.filter_by(
        parent_order_id=order.id,
        status='PENDING'
    ).first():
        abort(409, 'Foreclosure payment is pending')

    # Keep installment history attached to the parent.
    for child in order.installments:
        child.deleted_at = now()
        child.deleted_by = str(session.get('user_id'))

    # Archive the bill without changing payment status,
    # gateway references or transaction history.
    order.deleted_at = now()
    order.deleted_by = str(session.get('user_id'))

    log(
        'BILL_SOFT_DELETED',
        order,
        details='Archived by admin; payment records retained'
    )

    db.session.commit()

    flash('Bill moved to Trash. Payment history preserved.', 'success')
    return redirect(url_for('orders'))



@app.get('/trash')
@auth('admin')
def trash():
    deleted = Order.query.filter(Order.deleted_at.isnot(None), Order.parent_order_id.is_(None)).order_by(Order.deleted_at.desc()).all()
    return render_template('trash.html', orders=deleted)


@app.post('/orders/<int:order_id>/restore')
@auth('admin')
def restore_bill(order_id):
    order = db.get_or_404(Order, order_id)
    if not order.deleted_at or order.parent_order_id: abort(409)
    order.deleted_at = None; order.deleted_by = None
    if order.status == 'EMI_PLAN':
        for child in order.installments:
            child.deleted_at = None; child.deleted_by = None
    log('BILL_RESTORED', order)
    db.session.commit()
    flash('Bill restored', 'success')
    return redirect(url_for('trash'))

# Terminal Phase 1: separate code-based authentication, no payment initiation yet.
def terminal_auth(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        uid = session.get('terminal_user_id')
        access = TerminalAccess.query.filter_by(user_id=uid, active=True).first() if uid else None
        user = db.session.get(User, uid) if access else None
        if not user or not user.active or user.role not in ('staff', 'admin') or session.get('terminal_code_version') != hashlib.sha256(access.code_hash.encode()).hexdigest():
            session.pop('terminal_user_id', None)
            return redirect(url_for('terminal_login'))
        return fn(*args, **kwargs)
    return wrapped


@app.route('/terminal', methods=['GET', 'POST'])
def terminal_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        code = request.form.get('access_code', '')
        user = User.query.filter_by(username=username, active=True).first()
        access = TerminalAccess.query.filter_by(user_id=user.id, active=True).first() if user else None
        locked = False
        if access and access.locked_until:
            until = access.locked_until
            if until.tzinfo is None: until = until.replace(tzinfo=timezone.utc)
            locked = until > now()
        if access and not locked and check_password_hash(access.code_hash, code):
            access.failed_attempts = 0; access.locked_until = None
            session.clear(); session['terminal_user_id'] = user.id; session['terminal_code_version'] = hashlib.sha256(access.code_hash.encode()).hexdigest()
            log('TERMINAL_LOGIN', actor=user.username)
            db.session.commit()
            return redirect(url_for('terminal_dashboard'))
        if access and not locked:
            from datetime import timedelta
            access.failed_attempts += 1
            if access.failed_attempts >= 5:
                access.locked_until = now() + timedelta(minutes=15)
                access.failed_attempts = 0
            db.session.commit()
        flash('Invalid credentials or temporarily locked access', 'error')
    return render_template('terminal_login.html')


@app.get('/terminal/dashboard')
@terminal_auth
def terminal_dashboard():
    return render_template('terminal_dashboard.html', terminal_user=db.session.get(User, session['terminal_user_id']))


@app.get('/dashboard/payment/<int:order_id>/waiting')
@auth()
def dashboard_payment_wait(order_id):
    tx = TerminalTransaction.query.filter_by(order_id=order_id, user_id=session['user_id']).first_or_404()
    order = db.get_or_404(Order, tx.order_id)
    if order.deleted_at: abort(404)
    return render_template('dashboard_payment_wait.html', order=order)


@app.get('/dashboard/payment/<int:order_id>/status')
@auth()
def dashboard_payment_status(order_id):
    tx = TerminalTransaction.query.filter_by(order_id=order_id, user_id=session['user_id']).first_or_404()
    order = db.get_or_404(Order, tx.order_id)
    if order.deleted_at: abort(404)
    resp = jsonify(status=order.status, paid=order.status == 'PAID',
                   invoice_url=url_for('invoice_pdf', token=order.public_token) if order.status == 'PAID' else None)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.get('/terminal/next-payment')
@terminal_auth
def terminal_next_payment():
    """Deliver only newly initiated Cashfree checkout to the correct staff terminal."""
    uid = session['terminal_user_id']
    dispatch = (db.session.query(TerminalDispatch)
                .join(Order, Order.id == TerminalDispatch.order_id)
                .join(TerminalTransaction, TerminalTransaction.order_id == Order.id)
                .filter(TerminalDispatch.user_id == uid,
                        TerminalTransaction.user_id == uid,
                        TerminalDispatch.acknowledged_at.is_(None),
                        TerminalDispatch.expires_at > now(),
                        Order.deleted_at.is_(None), Order.parent_order_id.is_(None),
                        Order.status == 'PENDING', Order.gateway_order_id.isnot(None))
                .order_by(TerminalDispatch.id.asc()).first())
    response = jsonify(dispatch_id=dispatch.id if dispatch else None,
                       url=url_for('terminal_gateway', order_id=dispatch.order_id, dispatch_id=dispatch.id) if dispatch else None)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/terminal/gateway/<int:order_id>')
@terminal_auth
def terminal_gateway(order_id):
    """Reuse Cashfree's existing gateway order; never create a second invoice."""
    order = terminal_order_or_404(order_id)
    if order.parent_order_id is not None or order.status == 'EMI_PLAN': abort(409)
    if order.status == 'PAID': return redirect(url_for('terminal_payment', order_id=order.id))
    if not order.gateway_order_id: return redirect(url_for('terminal_dashboard'))
    dispatch_id = request.args.get('dispatch_id', type=int)
    dispatch = db.session.get(TerminalDispatch, dispatch_id) if dispatch_id else None
    if (not dispatch or dispatch.order_id != order.id or
            dispatch.user_id != session['terminal_user_id'] or
            dispatch.expires_at.replace(tzinfo=timezone.utc) <= now()):
        abort(403, 'Payment request expired or already used')
    if not (CF_ID and CF_SECRET): abort(503, 'Cashfree not configured')
    try:
        response = requests.get(CF_BASE+'/orders/'+quote(order.gateway_order_id, safe=''),
                                headers=cf_headers(), timeout=12)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        app.logger.exception('Terminal could not retrieve Cashfree session')
        abort(503, 'Cashfree session unavailable; retry shortly')
    payment_session_id = data.get('payment_session_id')
    if not payment_session_id: abort(409, 'Cashfree session not ready')
    if dispatch.acknowledged_at is None:
        dispatch.acknowledged_at = now()
        db.session.commit()
    if request.args.get('format') == 'json':
        response = jsonify(payment_session_id=payment_session_id,
                           mode='production' if CF_ENV == 'production' else 'sandbox',
                           order_id=order.id, order_no=order.order_no,
                           amount=str(order.total),
                           status_url=url_for('terminal_payment_status', order_id=order.id))
        response.headers['Cache-Control'] = 'no-store'
        return response
    return render_template('terminal_gateway.html', order=order,
                           payment_session_id=payment_session_id, cf_env=CF_ENV)


@app.post('/terminal/orders/<int:order_id>/claim')
@terminal_auth
def terminal_claim_order(order_id):
    order = db.get_or_404(Order, order_id)
    if order.deleted_at or order.parent_order_id or order.status not in ('PENDING', 'REJECTED', 'PAYMENT_REPORTED'):
        abort(409, 'Bill is not eligible for terminal collection')
    tx = TerminalTransaction.query.filter_by(order_id=order.id).first()
    if tx and tx.user_id != session['terminal_user_id']:
        abort(409, 'Bill is assigned to another staff member')
    if not tx:
        db.session.add(TerminalTransaction(order_id=order.id, user_id=session['terminal_user_id']))
        log('TERMINAL_EXISTING_BILL_CLAIMED', order, actor=db.session.get(User, session['terminal_user_id']).username)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            abort(409, 'Bill was claimed by another terminal')
    return redirect(url_for('terminal_payment', order_id=order.id))


@app.post('/terminal/logout')
def terminal_logout():
    session.clear()
    return redirect(url_for('terminal_login'))


@app.get('/admin/terminal')
@auth('admin')
def terminal_admin():
    staff_users = User.query.filter(User.role.in_(['staff', 'admin'])).order_by(User.username).all()
    access_by_user = {a.user_id: a for a in TerminalAccess.query.all()}
    return render_template('terminal_admin.html', staff_users=staff_users, access_by_user=access_by_user)


@app.post('/admin/terminal/<int:user_id>/rotate')
@auth('admin')
def terminal_rotate(user_id):
    user = db.get_or_404(User, user_id)
    if user.role not in ('staff', 'admin') or not user.active: abort(400)
    code = secrets.token_urlsafe(24)
    access = TerminalAccess.query.filter_by(user_id=user.id).first()
    if not access:
        access = TerminalAccess(user_id=user.id, code_hash=generate_password_hash(code))
        db.session.add(access)
    else:
        access.code_hash = generate_password_hash(code)
        access.active = True
        access.failed_attempts = 0
        access.locked_until = None
    log('TERMINAL_CODE_ROTATED', details=f'user_id={user.id}')
    db.session.commit()
    # Show once; never persist or log the plaintext code.
    return render_template('terminal_code_once.html', staff_user=user, access_code=code)


@app.post('/admin/terminal/<int:user_id>/revoke')
@auth('admin')
def terminal_revoke(user_id):
    access = TerminalAccess.query.filter_by(user_id=user_id).first_or_404()
    access.active = False
    log('TERMINAL_CODE_REVOKED', details=f'user_id={user_id}')
    db.session.commit()
    flash('Terminal code revoked', 'success')
    return redirect(url_for('terminal_admin'))


# Phase 2: terminal orders reuse the existing Cashfree payment and webhook pipeline.
def terminal_order_or_404(order_id):
    tx = TerminalTransaction.query.filter_by(order_id=order_id, user_id=session['terminal_user_id']).first()
    if not tx: abort(404)
    order = db.get_or_404(Order, order_id)
    if order.deleted_at: abort(404)
    return order


@app.get('/terminal/new-bill')
@terminal_auth
def terminal_new_bill():
    products = Product.query.filter_by(active=True).order_by(Product.name).all()
    return render_template('terminal_new_bill.html', products=products)


@app.post('/terminal/create-bill')
@terminal_auth
def terminal_create_bill():
    try:
        customer = request.form.get('customer', '').strip()
        phone = request.form.get('phone', '').strip()
        discount = money(request.form.get('discount', '0'))
        ids = request.form.getlist('product_id[]')
        qtys = request.form.getlist('qty[]')
        if not customer or len(customer) > 150 or not re.fullmatch(r'\d{10}', phone): raise ValueError()
        if not ids or len(ids) != len(qtys) or len(ids) > 50 or discount < 0: raise ValueError()
        items, subtotal = [], D('0')
        for pid, qty_text in zip(ids, qtys):
            qty = int(qty_text)
            if qty < 1 or qty > 10000: raise ValueError()
            product = db.session.get(Product, int(pid))
            if not product or not product.active: raise ValueError()
            line = money(product.price * qty)
            subtotal += line
            items.append(OrderItem(product_id=product.id, name=product.name, qty=qty, price=product.price, line_total=line))
        if discount >= subtotal: raise ValueError()
        order = Order(order_no='OWL-'+now().strftime('%y%m%d')+'-'+secrets.token_hex(4).upper(),
                      customer=customer, phone=phone, subtotal=subtotal, discount=discount,
                      tax_rate=0, tax=0, total=money(subtotal-discount), status='PENDING',
                      public_token=secrets.token_urlsafe(32), items=items)
        db.session.add(order)
        db.session.flush()
        record_bill_branch(order, session['terminal_user_id'])
        db.session.add(TerminalTransaction(order_id=order.id, user_id=session['terminal_user_id']))
        log('TERMINAL_BILL_CREATED', order, actor=db.session.get(User, session['terminal_user_id']).username)
        db.session.commit()
        return redirect(url_for('terminal_payment', order_id=order.id))
    except (ValueError, InvalidOperation, TypeError, OverflowError):
        db.session.rollback()
        flash('Enter valid customer details, a 10-digit phone number, items and discount.', 'error')
        return redirect(url_for('terminal_new_bill'))


@app.get('/terminal/payment/<int:order_id>')
@terminal_auth
def terminal_payment(order_id):
    order = terminal_order_or_404(order_id)
    # Legacy payment URL must never show the old customer-phone/same-device selector.
    # A live dispatch resumes the same Cashfree session instead of creating a bill.
    if order.status != 'PAID':
        dispatch = (TerminalDispatch.query.filter_by(
            order_id=order.id, user_id=session['terminal_user_id'])
            .filter(TerminalDispatch.expires_at > now())
            .order_by(TerminalDispatch.id.desc()).first())
        if dispatch and order.gateway_order_id:
            return redirect(url_for('terminal_gateway', order_id=order.id,
                                    dispatch_id=dispatch.id))
    return render_template('terminal_payment.html', order=order)


@app.get('/terminal/payment/<int:order_id>/status')
@terminal_auth
def terminal_payment_status(order_id):
    order = terminal_order_or_404(order_id)
    # Prevent browsers and intermediaries caching a payment status response.
    response = jsonify(status=order.status if order.status in ('PAID','PENDING','PAYMENT_REPORTED','REJECTED') else 'PENDING',
                       paid=order.status == 'PAID', order_no=order.order_no,
                       receipt_url=url_for('terminal_receipt', order_id=order.id) if order.status == 'PAID' else None)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/terminal/receipt/<int:order_id>')
@terminal_auth
def terminal_receipt(order_id):
    order = terminal_order_or_404(order_id)
    if order.status != 'PAID': abort(409, 'Payment has not been verified')
    return redirect(url_for('invoice_pdf', token=order.public_token))


@app.get('/health')
def health():
    try: db.session.execute(db.text('SELECT 1'))
    except Exception: return jsonify(status='error'), 503
    return jsonify(status='ok')


@app.after_request
def security_headers(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['Cache-Control'] = 'no-store' if request.endpoint in ('login', 'checkout', 'orders', 'dashboard') else 'private'
    return resp


@app.cli.command('init-db')
def init_db_command():
    db.create_all()
    print('Database tables created. Next run flask create-admin.')


@app.cli.command('create-admin')
def create_admin_command():
    username = os.environ.get('ADMIN_USERNAME', '').strip(); password = os.environ.get('ADMIN_PASSWORD', '')
    if not username or len(password) < 12: raise RuntimeError('Set ADMIN_USERNAME and ADMIN_PASSWORD (12+ characters)')
    user = User.query.filter_by(username=username).first()
    if user: raise RuntimeError('User exists; not overwriting password')
    db.session.add(User(username=username, password_hash=generate_password_hash(password), role='admin'))
    db.session.commit(); print('Admin created')


# Enterprise stage 9.1: read-only management views, no schema changes.
@app.get('/admin/enterprise')
@auth('admin')
def enterprise():
    live = Order.query.filter(Order.deleted_at.is_(None), Order.status != 'EMI_PLAN')
    totals = db.session.query(Order.status, func.count(Order.id), func.sum(Order.total)).filter(Order.deleted_at.is_(None), Order.status != 'EMI_PLAN').group_by(Order.status).all()
    terminals = db.session.query(User, TerminalAccess).join(TerminalAccess, User.id == TerminalAccess.user_id).order_by(User.username).all()
    return render_template('enterprise.html', totals=totals, terminals=terminals, recent=live.order_by(Order.id.desc()).limit(12).all(), low_stock=Product.query.filter(Product.active.is_(True), Product.stock <= 5).order_by(Product.stock).limit(20).all())

@app.get('/admin/customers')
@auth('admin')
def enterprise_customers():
    q = request.args.get('q', '').strip()[:100]
    rows = Order.query.filter(Order.deleted_at.is_(None), Order.parent_order_id.is_(None))
    if q:
        rows = rows.filter(db.or_(Order.customer.ilike('%'+q+'%'), Order.phone.ilike('%'+q+'%'), Order.email.ilike('%'+q+'%')))
    return render_template('enterprise_customers.html', rows=rows.order_by(Order.id.desc()).limit(100).all(), q=q)

def record_bill_branch(order, uid):
    assignment = db.session.get(StaffBranch, uid)
    if assignment:
        db.session.add(BillBranch(order_id=order.id, branch_id=assignment.branch_id))

@app.route('/admin/branches', methods=['GET','POST'])
@auth('admin')
def branches():
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        if not name or len(name)>120: abort(400)
        if Branch.query.filter_by(name=name).first():
            flash('Branch already exists', 'error'); return redirect(url_for('branches'))
        db.session.add(Branch(name=name)); log('BRANCH_CREATED', details=name); db.session.commit()
        return redirect(url_for('branches'))
    rows = []
    for b in Branch.query.order_by(Branch.name):
        count = StaffBranch.query.filter_by(branch_id=b.id).count()
        bills = Order.query.join(BillBranch, BillBranch.order_id==Order.id).filter(BillBranch.branch_id==b.id, Order.deleted_at.is_(None)).count()
        rows.append((b,count,bills))
    return render_template('branches.html', rows=rows)

@app.post('/admin/staff/<int:uid>/branch')
@auth('admin')
def assign_branch(uid):
    user = db.get_or_404(User,uid)
    branch = db.get_or_404(Branch,request.form.get('branch_id',type=int) or 0)
    db.session.merge(StaffBranch(user_id=user.id,branch_id=branch.id))
    log('BRANCH_ASSIGNED',details=f'{uid}: {branch.id}'); db.session.commit()
    return redirect(url_for('staff'))

@app.post('/terminal/heartbeat')
@terminal_auth
def terminal_heartbeat():
    db.session.merge(TerminalPresence(user_id=session['terminal_user_id'],seen_at=now()))
    db.session.commit(); return jsonify(ok=True)

@app.get('/admin/terminal/control')
@auth('admin')
def terminal_control():
    rows=[]
    for u,a in db.session.query(User,TerminalAccess).join(TerminalAccess,User.id==TerminalAccess.user_id):
        presence=db.session.get(TerminalPresence,u.id)
        seen=presence.seen_at if presence else None
        if seen and seen.tzinfo is None: seen=seen.replace(tzinfo=timezone.utc)
        state='Disabled' if not u.active or not a.active else ('Online' if seen and now()-seen<timedelta(seconds=45) else 'Offline')
        rows.append((u,a,state,seen))
    return render_template('terminal_control.html',rows=rows)

@app.get('/admin/customers/<int:oid>')
@auth('admin')
def customer_profile(oid):
    anchor=Order.query.filter_by(id=oid,deleted_at=None,parent_order_id=None).first_or_404()
    # Exact phone AND name only; missing phone never merges records.
    query=Order.query.filter_by(deleted_at=None,parent_order_id=None)
    rows=query.filter_by(phone=anchor.phone,customer=anchor.customer).all() if anchor.phone else [anchor]
    payments=[]; foreclosures=[]
    for o in rows:
        payments.extend(emi_children(o.id) if o.status=='EMI_PLAN' else [o])
        foreclosures.extend(EMIForeclosure.query.filter_by(parent_order_id=o.id).all())
    return render_template('customer_profile.html',anchor=anchor,rows=rows,payments=payments,foreclosures=foreclosures)

@app.cli.command('upgrade-enterprise')
def upgrade_enterprise():
    for model in (Branch,StaffBranch,TerminalPresence,BillBranch):
        model.__table__.create(db.engine,checkfirst=True)
    print('Enterprise tables ready')

if __name__ == '__main__':
    app.run(port=int(os.environ.get('PORT', 5000)))
