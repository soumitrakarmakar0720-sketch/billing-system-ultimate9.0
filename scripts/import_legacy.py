"""One-time migration of old SQLite data into Ultimate DB.
Usage: LEGACY_SQLITE=/path/old.db DATABASE_URL=... SECRET_KEY=... python scripts/import_legacy.py --apply
Run only against an EMPTY Ultimate database, after backup and rehearsal.
"""
import os, sqlite3, sys, secrets
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app, db, User, Product, Order, OrderItem, Audit
from werkzeug.security import generate_password_hash
from datetime import datetime
from decimal import Decimal

source = os.environ.get('LEGACY_SQLITE', '')
if not source or not Path(source).is_file(): raise SystemExit('Set LEGACY_SQLITE to a readable copy of the old database')
old = sqlite3.connect(source); old.row_factory = sqlite3.Row
counts = {table: old.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('users', 'products', 'orders', 'order_items')}
print('Legacy source:', source, 'counts:', counts)
if '--apply' not in sys.argv:
    print('DRY RUN. To import, set --apply after verifying backups and destination.'); sys.exit(0)
with app.app_context():
    db.create_all()
    if any(db.session.query(model).first() for model in (User, Product, Order, OrderItem)):
        raise SystemExit('Destination not empty. Refusing import.')
    for u in old.execute('SELECT * FROM users'):
        db.session.add(User(id=u['id'], username=u['username'], password_hash=u['password_hash'], role='admin', active=True))
    for p in old.execute('SELECT * FROM products'):
        db.session.add(Product(id=p['id'], name=p['name'], sku=p['sku'] or '', price=Decimal(str(p['price'])), stock=p['stock'], active=bool(p['active'])))
    for o in old.execute('SELECT * FROM orders'):
        cols = set(o.keys())
        dt = datetime.fromisoformat(o['created_at']) if o['created_at'] else datetime.utcnow()
        db.session.add(Order(id=o['id'], order_no=o['order_no'], customer=o['customer'], phone=o['phone'] or '', subtotal=Decimal(str(o['subtotal'])), discount=Decimal(str(o['discount'])), tax_rate=Decimal(str(o['tax_rate'])), tax=Decimal(str(o['tax'])), total=Decimal(str(o['total'])), status=o['status'], payment_ref=o['payment_ref'] or '', payment_reported_at=datetime.fromisoformat(o['payment_reported_at']) if 'payment_reported_at' in cols and o['payment_reported_at'] else None, public_token=secrets.token_urlsafe(32), created_at=dt))
    for i in old.execute('SELECT * FROM order_items'):
        db.session.add(OrderItem(id=i['id'], order_id=i['order_id'], product_id=i['product_id'], name=i['name'], qty=i['qty'], price=Decimal(str(i['price'])), line_total=Decimal(str(i['line_total']))))
    db.session.add(Audit(actor='migration', action='LEGACY_IMPORT', details=str(counts)))
    db.session.commit()
    print('Import completed. Existing /checkout/ORDERNO links are replaced with /pay/TOKEN links; distribute new links.')
