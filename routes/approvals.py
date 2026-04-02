from flask import Blueprint, render_template, request, redirect, flash, session
from database import get_db
from services.stock_service import add_stock, remove_stock, adjust_stock
from services.notification_service import notify_operational_event, notify_roles, notify_user
from services.rbac import has_permission

approvals_bp = Blueprint("approvals", __name__, url_prefix="/approvals")


def require_leader():
    if not has_permission(session.get("role"), "approve_stock_ops"):
        flash("Akses ditolak", "error")
        return False
    return True


def _approval_result_link(approval_row):
    approval_type = str((approval_row or {}).get("type") or "").strip().upper()
    if approval_type == "INBOUND":
        return "/inbound"
    if approval_type == "OUTBOUND":
        return "/outbound"
    if approval_type == "ADJUST":
        return "/stock/"
    return "/approvals"


def _approval_item_context(db, approval_row):
    if not approval_row:
        return None

    return db.execute(
        """
        SELECT
            p.sku,
            p.name AS product_name,
            COALESCE(v.variant, 'default') AS variant_name,
            w.name AS warehouse_name
        FROM products p
        JOIN product_variants v ON v.product_id = p.id
        JOIN warehouses w ON w.id = ?
        WHERE p.id=? AND v.id=?
        """,
        (
            approval_row.get("warehouse_id"),
            approval_row.get("product_id"),
            approval_row.get("variant_id"),
        ),
    ).fetchone()


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

            try:
                approval_item = _approval_item_context(db, a)
                if approval_item:
                    variant_label = (
                        "Default"
                        if str(approval_item["variant_name"]).lower() == "default"
                        else approval_item["variant_name"]
                    )
                    approval_type = str(a.get("type") or "APPROVAL").strip().upper()
                    notify_operational_event(
                        f"Approval {approval_type} diproses",
                        (
                            f"{approval_type} untuk {approval_item['sku']} - {approval_item['product_name']} / "
                            f"{variant_label} sebanyak {a.get('qty')} item di "
                            f"{(approval_item['warehouse_name'] or f'Gudang {a.get('warehouse_id')}').strip()} "
                            "sudah dijalankan."
                        ),
                        warehouse_id=a.get("warehouse_id"),
                        category="inventory",
                        link_url=_approval_result_link(a),
                        source_type="approval_execution",
                        source_id=str(a.get("id")),
                        push_title=f"Approval {approval_type}",
                        push_body=f"{approval_item['sku']} | Qty {a.get('qty')}",
                    )
            except Exception as exc:
                print("APPROVAL EXECUTION NOTIFICATION ERROR:", exc)

            flash('Approval disetujui dan aksi dijalankan', 'success')
            # notify requester
            try:
                if a.get('requested_by'):
                    subj = f"Permintaan {a.get('type')} #{a.get('id')} disetujui"
                    msg = f"Permintaan Anda (ID #{a.get('id')}) telah disetujui dan diproses oleh {session.get('user_id')}"
                    notify_user(
                        a.get('requested_by'),
                        subj,
                        msg,
                        category="approval",
                        link_url=_approval_result_link(a),
                        source_type="approval_result",
                        source_id=str(a.get("id")),
                    )
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
                    notify_user(
                        a.get('requested_by'),
                        subj,
                        msg,
                        category="approval",
                        link_url=_approval_result_link(a),
                        source_type="approval_result",
                        source_id=str(a.get("id")),
                    )
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
            notify_user(
                a.get('requested_by'),
                subj,
                msg,
                category="approval",
                link_url=_approval_result_link(a),
                source_type="approval_result",
                source_id=str(a.get("id")),
            )
    except Exception:
        pass

    flash('Approval ditolak', 'success')
    return redirect('/approvals')
