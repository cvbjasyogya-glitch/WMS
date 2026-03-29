import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app
from database import get_db
from werkzeug.security import generate_password_hash
from services.request_service import create_request
from services.notification_service import notify_roles, notify_user

app = create_app()
with app.app_context():
    db = get_db()
    # warehouses
    whs = db.execute('SELECT id, name FROM warehouses').fetchall()
    print('Warehouses:', [dict(w) for w in whs])
    mega = db.execute("SELECT id FROM warehouses WHERE name LIKE '%Mega%' LIMIT 1").fetchone()
    matar = db.execute("SELECT id FROM warehouses WHERE name LIKE '%Mataram%' LIMIT 1").fetchone()
    if not mega or not matar:
        raise SystemExit('Expected two warehouses')
    mega_id = int(mega['id'])
    matar_id = int(matar['id'])

    def ensure_user(username, role, warehouse_id=None, email=None, phone=None, notify_email=1, notify_whatsapp=0):
        u = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if u:
            return u['id']
        db.execute('INSERT INTO users(username,password,role,email,phone,notify_email,notify_whatsapp,warehouse_id) VALUES (?,?,?,?,?,?,?,?)',
                   (username, generate_password_hash('pass1234'), role, email, phone, notify_email, notify_whatsapp, warehouse_id))
        db.commit()
        return db.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()['id']

    leader_mega = ensure_user('leader_mega','leader', mega_id, 'lmega@example.test', '628111111', 1, 0)
    admin_mega = ensure_user('admin_mega','admin', mega_id, 'amega@example.test', '628222222', 1, 1)
    leader_matar = ensure_user('leader_matar','leader', matar_id, 'lmatar@example.test', '628333333', 1, 0)
    admin_matar = ensure_user('admin_matar','admin', matar_id, 'amatar@example.test', '628444444', 1, 1)

    # product
    p = db.execute("SELECT id FROM products WHERE sku=?", ('TESTSKU',)).fetchone()
    if not p:
        db.execute("INSERT INTO products(sku,name,category_id) VALUES (?,?,?)", ('TESTSKU','Product Test', None))
        db.commit()
        p = db.execute("SELECT id FROM products WHERE sku=?", ('TESTSKU',)).fetchone()
    pid = p['id']
    v = db.execute('SELECT id FROM product_variants WHERE product_id=?', (pid,)).fetchone()
    if not v:
        db.execute('INSERT INTO product_variants(product_id,variant) VALUES (?,?)', (pid, 'Default'))
        db.commit()
        v = db.execute('SELECT id FROM product_variants WHERE product_id=?', (pid,)).fetchone()
    vid = v['id']

    # create stock batch in mega
    db.execute('INSERT INTO stock_batches(product_id,variant_id,warehouse_id,qty,remaining_qty,cost,expiry_date,created_at) VALUES (?,?,?,?,?,?,?,datetime("now"))', (pid, vid, mega_id, 100, 100, 10000, None))
    db.commit()

    # create request from mega -> mataram by admin_mega
    req_id = create_request(pid, vid, mega_id, matar_id, 10)
    print('Created request id:', req_id)

    subj = 'Request Baru Test'
    msg = f'Request #{req_id} Produk:{pid} Qty:10 Dari:{mega_id} Ke:{matar_id}'
    res = notify_roles(['leader','owner','super_admin'], subj, msg, warehouse_id=mega_id)
    print('notify_roles result:', res)

    rows = db.execute('SELECT id, user_id, role, channel, recipient, subject, status, created_at FROM notifications ORDER BY id DESC LIMIT 10').fetchall()
    print('Recent notifications:')
    for r in rows:
        print(dict(r))

    # notify requester directly
    requester = db.execute('SELECT requested_by FROM requests WHERE id=?', (req_id,)).fetchone()['requested_by']
    print('Requester id:', requester)
    notify_user(requester, 'Test: your request is pending', 'This is a test message')
    rows2 = db.execute('SELECT id, user_id, channel, recipient, subject, status FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 5', (requester,)).fetchall()
    print('Notifications for requester:', [dict(r) for r in rows2])

print('SMOKE TEST DONE')
