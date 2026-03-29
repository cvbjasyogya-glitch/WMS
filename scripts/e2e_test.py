import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app
from database import get_db
from werkzeug.security import generate_password_hash

app = create_app()
with app.app_context():
    db = get_db()
    # ensure users
    def ensure_user(username, role, warehouse_id=None, email=None, phone=None):
        u = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if u:
            return u['id']
        db.execute('INSERT INTO users(username,password,role,email,phone,notify_email,notify_whatsapp,warehouse_id) VALUES (?,?,?,?,?,?,?,?)',
                   (username, generate_password_hash('pass1234'), role, email, phone, 1, 0, warehouse_id))
        db.commit()
        return db.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()['id']

    # ensure product
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

    whs = db.execute('SELECT id,name FROM warehouses ORDER BY id').fetchall()
    if len(whs) < 2:
        raise SystemExit('Need 2 warehouses')
    wh1 = whs[0]['id']
    wh2 = whs[1]['id']

    leader_1 = ensure_user('leader_e2e','leader', wh1, 'leader_e2e@example.test', '62810101')
    admin_1 = ensure_user('admin_e2e','admin', wh1, 'admin_e2e@example.test', '62820202')
    leader_2 = ensure_user('leader_e2e2','leader', wh2, 'leader_e2e2@example.test', '62830303')

    # ensure stock in wh1
    db.execute('INSERT INTO stock_batches(product_id,variant_id,warehouse_id,qty,remaining_qty,cost,expiry_date,created_at) VALUES (?,?,?,?,?,?,?,datetime("now"))', (pid, vid, wh1, 50, 50, 1000, None))
    db.commit()

print('Setup complete; performing web flow')

with app.test_client() as c:
    # login admin_1
    res = c.post('/login', data={'username':'admin_e2e','password':'pass1234'}, follow_redirects=True)
    print('Login admin status:', res.status_code)

    # create request from wh1 -> wh2
    res = c.post('/request/', data={'product_id': pid, 'variant_id': vid, 'from_warehouse': wh1, 'to_warehouse': wh2, 'qty': 5}, follow_redirects=True)
    print('Create request status:', res.status_code)

    # find newest request
    with app.app_context():
        db = get_db()
        req = db.execute('SELECT id, status, requested_by FROM requests ORDER BY id DESC LIMIT 1').fetchone()
        print('Newest request:', dict(req))
        req_id = req['id']

    # logout admin
    c.get('/logout')

    # login as leader_1 and approve
    res = c.post('/login', data={'username':'leader_e2e','password':'pass1234'}, follow_redirects=True)
    print('Login leader status:', res.status_code)

    res = c.post(f'/request/approve/{req_id}', follow_redirects=True)
    print('Approve status:', res.status_code)

    # check request status
    with app.app_context():
        db = get_db()
        req2 = db.execute('SELECT id, status, approved_by FROM requests WHERE id=?', (req_id,)).fetchone()
        print('After approve:', dict(req2))

    # check notifications for requester (if any)
    if req2:
        requester_id = req2['approved_by']
        print('Approved_by:', requester_id)

print('E2E finished')
