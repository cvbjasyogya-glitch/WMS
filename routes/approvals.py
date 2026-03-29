from flask import Blueprint, render_template, request, redirect, flash, session
from database import get_db
from services.stock_service import add_stock, remove_stock, adjust_stock
from services.notification_service import notify_roles, notify_user

approvals_bp = Blueprint("approvals", __name__, url_prefix="/approvals")


def require_leader():
    role = session.get("role")
    # leaders and owners and super_admin can access approval pages
    if role not in ["leader", "owner", "super_admin"]:
        flash("Akses ditolak", "error")
        return False
    return True


@approvals_bp.route("/")
def approvals_page():
    if not require_leader():
        return redirect("/")

    db = get_db()

    # leaders see only approvals for their warehouse; owners/super_admin see all
    role = session.get('role')
    warehouse_scope = session.get('warehouse_id') if role == 'leader' else None

    if warehouse_scope:
        rows = db.execute("""
        SELECT a.*,
               p.name as product_name,
               v.variant as variant_name,
               w.name as warehouse_name,
               u.username as requester
        FROM approvals a
        LEFT JOIN products p ON a.product_id = p.id
        LEFT JOIN product_variants v ON a.variant_id = v.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        LEFT JOIN users u ON a.requested_by = u.id
        WHERE a.status = 'pending' AND a.warehouse_id = ?
        ORDER BY a.created_at ASC
        """, (warehouse_scope,)).fetchall()
    else:
        rows = db.execute("""
        SELECT a.*,
               p.name as product_name,
               v.variant as variant_name,
               w.name as warehouse_name,
               u.username as requester
        FROM approvals a
        LEFT JOIN products p ON a.product_id = p.id
        LEFT JOIN product_variants v ON a.variant_id = v.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        LEFT JOIN users u ON a.requested_by = u.id
        WHERE a.status = 'pending'
        ORDER BY a.created_at ASC
        """).fetchall()

    approvals = [dict(r) for r in rows]

    return render_template("approvals.html", approvals=approvals)


@approvals_bp.route('/approve/<int:id>', methods=["POST"])
def approve(id):
    if not require_leader():
        return redirect('/approvals')

    db = get_db()
    a = db.execute("SELECT * FROM approvals WHERE id=?", (id,)).fetchone()

    if not a:
        flash("Approval tidak ditemukan", "error")
        return redirect('/approvals')

    a = dict(a)

    try:
        ok = False
        # enforce warehouse scope for leaders
        role = session.get('role')
        if role == 'leader' and session.get('warehouse_id') and a['warehouse_id'] != session.get('warehouse_id'):
            flash('Tidak punya akses untuk approval ini', 'error')
            return redirect('/approvals')

        if a['type'] == 'INBOUND':
            ok = add_stock(a['product_id'], a['variant_id'], a['warehouse_id'], a['qty'], note=a['note'] or 'Inbound approval')
        elif a['type'] == 'OUTBOUND':
            ok = remove_stock(a['product_id'], a['variant_id'], a['warehouse_id'], a['qty'], note=a['note'] or 'Outbound approval')
        elif a['type'] == 'ADJUST':
            ok = adjust_stock(a['product_id'], a['variant_id'], a['warehouse_id'], a['qty'], note=a['note'] or 'Adjust approval')

        if ok:
            db.execute("UPDATE approvals SET status='approved', approved_by=?, approved_at=datetime('now') WHERE id=?", (session.get('user_id'), id))
            db.commit()
            flash('Approval disetujui dan aksi dijalankan', 'success')
            # notify requester
            try:
                if a.get('requested_by'):
                    subj = f"Permintaan {a.get('type')} #{a.get('id')} disetujui"
                    msg = f"Permintaan Anda (ID #{a.get('id')}) telah disetujui dan diproses oleh {session.get('user_id')}"
                    notify_user(a.get('requested_by'), subj, msg)
            except Exception:
                pass
        else:
            db.execute("UPDATE approvals SET status='rejected', approved_by=?, approved_at=datetime('now') WHERE id=?", (session.get('user_id'), id))
            db.commit()
            flash('Gagal memproses aksi', 'error')
            # notify requester about rejection
            try:
                if a.get('requested_by'):
                    subj = f"Permintaan {a.get('type')} #{a.get('id')} gagal diproses"
                    msg = f"Permintaan Anda (ID #{a.get('id')}) ditolak atau gagal diproses oleh {session.get('user_id')}"
                    notify_user(a.get('requested_by'), subj, msg)
            except Exception:
                pass

    except Exception as e:
        db.rollback()
        try:
            db.execute("UPDATE approvals SET status='rejected', approved_by=?, approved_at=datetime('now') WHERE id=?", (session.get('user_id'), id))
            db.commit()
        except:
            pass
        print('APPROVAL ERROR:', e)
        flash('Error saat proses approval', 'error')

    return redirect('/approvals')


@approvals_bp.route('/reject/<int:id>', methods=['POST'])
def reject(id):
    if not require_leader():
        return redirect('/approvals')

    reason = (request.form.get('reason') or '').strip()
    db = get_db()
    # enforce warehouse scope for leaders
    role = session.get('role')
    a = db.execute("SELECT * FROM approvals WHERE id=?", (id,)).fetchone()
    if a:
        a = dict(a)
    if role == 'leader' and session.get('warehouse_id') and a and a['warehouse_id'] != session.get('warehouse_id'):
        flash('Tidak punya akses untuk approval ini', 'error')
        return redirect('/approvals')

    db.execute("UPDATE approvals SET status='rejected', approved_by=?, approved_at=datetime('now'), note=COALESCE(note, '') || ' | REJECT: ' || ? WHERE id=?", (session.get('user_id'), reason, id))
    db.commit()
    # notify requester about rejection
    try:
        if a and a.get('requested_by'):
            subj = f"Permintaan {a.get('type')} #{a.get('id')} ditolak"
            msg = f"Permintaan Anda (ID #{a.get('id')}) telah ditolak oleh {session.get('user_id')}. Alasan: {reason}"
            notify_user(a.get('requested_by'), subj, msg)
    except Exception:
        pass

    flash('Approval ditolak', 'success')
    return redirect('/approvals')
