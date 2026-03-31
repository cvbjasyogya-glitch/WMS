import os
import shutil
import unittest
import json
from datetime import date as date_cls
from io import BytesIO
from uuid import uuid4
import zipfile

import init_db as init_db_module
from app import create_app, repair_restored_data
from config import Config
from database import get_db
from werkzeug.security import generate_password_hash


class WmsRoutesTestCase(unittest.TestCase):
    def setUp(self):
        temp_root = os.path.join(os.path.dirname(__file__), ".tmp")
        os.makedirs(temp_root, exist_ok=True)
        self.db_path = os.path.join(temp_root, f"test_database_{uuid4().hex}.db")
        self.photo_upload_root = os.path.join(temp_root, f"uploads_{uuid4().hex}")

        init_db_module.DB_PATH = self.db_path
        Config.DATABASE = self.db_path
        Config.SESSION_COOKIE_SECURE = False

        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            SESSION_COOKIE_SECURE=False,
            BIOMETRIC_PHOTO_UPLOAD_FOLDER=self.photo_upload_root,
            BIOMETRIC_PHOTO_URL_PREFIX="/static/test-geotag",
        )
        self.client = self.app.test_client()

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            db_file = self.db_path + suffix
            if os.path.exists(db_file):
                os.remove(db_file)
        if os.path.isdir(self.photo_upload_root):
            shutil.rmtree(self.photo_upload_root)

    def login(self, username="admin", password="admin123"):
        return self.client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def logout(self):
        return self.client.get("/logout", follow_redirects=False)

    def login_hr_user(self, username="hr_test_user", password="pass1234"):
        self.create_user(username, password, "hr")
        return self.login(username, password)

    def create_user(
        self,
        username,
        password,
        role,
        warehouse_id=None,
        employee_id=None,
        email=None,
        phone=None,
        notify_email=1,
        notify_whatsapp=0,
    ):
        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO users(
                    username,
                    password,
                    role,
                    warehouse_id,
                    employee_id,
                    email,
                    phone,
                    notify_email,
                    notify_whatsapp
                )
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    username,
                    generate_password_hash(password),
                    role,
                    warehouse_id,
                    employee_id,
                    email,
                    phone,
                    notify_email,
                    notify_whatsapp,
                ),
            )
            db.commit()

    def get_user_id(self, username):
        with self.app.app_context():
            db = get_db()
            user = db.execute(
                "SELECT id FROM users WHERE username=?",
                (username,),
            ).fetchone()
        return user["id"] if user else None

    def create_employee_record(
        self,
        employee_code=None,
        full_name="Karyawan Uji",
        warehouse_id=1,
        department="Warehouse",
        position="Staff",
        employment_status="active",
        work_location=None,
    ):
        employee_code = employee_code or ("EMP-" + uuid4().hex[:6].upper())
        work_location = work_location or ("Gudang Mataram" if warehouse_id == 1 else "Gudang Mega")

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO employees(
                    employee_code,
                    full_name,
                    warehouse_id,
                    department,
                    position,
                    employment_status,
                    work_location
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    employee_code,
                    full_name,
                    warehouse_id,
                    department,
                    position,
                    employment_status,
                    work_location,
                ),
            )
            db.commit()
            employee = db.execute(
                "SELECT id FROM employees WHERE employee_code=?",
                (employee_code,),
            ).fetchone()
        return employee["id"]

    def create_product(self, sku=None, qty=5, variants="M,L", warehouse_id="1"):
        sku = sku or ("AUTO-" + uuid4().hex[:8].upper())

        response = self.client.post(
            "/products/add",
            data={
                "sku": sku,
                "name": "Produk Uji",
                "category_name": "Testing",
                "variants": variants,
                "qty": str(qty),
                "warehouse_id": str(warehouse_id),
                "price_retail": "150000",
                "price_discount": "135000",
                "price_nett": "120000",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()
            variants_rows = db.execute(
                "SELECT id, variant FROM product_variants WHERE product_id=? ORDER BY id",
                (product["id"],),
            ).fetchall()

        return response, product["id"], variants_rows

    def build_camera_photo_data_url(self):
        return (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
            "/w8AAgMBgN6lNn0AAAAASUVORK5CYII="
        )

    def build_xlsx_bytes(self, rows):
        def column_label(index):
            label = ""
            while index:
                index, remainder = divmod(index - 1, 26)
                label = chr(65 + remainder) + label
            return label

        shared_strings = []
        shared_index = {}

        def shared_id(value):
            text = "" if value is None else str(value)
            if text not in shared_index:
                shared_index[text] = len(shared_strings)
                shared_strings.append(text)
            return shared_index[text]

        sheet_rows = []
        for row_idx, row in enumerate(rows, start=1):
            cells = []
            for col_idx, value in enumerate(row, start=1):
                if value in (None, ""):
                    continue
                ref = f"{column_label(col_idx)}{row_idx}"
                cells.append(f'<c r="{ref}" t="s"><v>{shared_id(value)}</v></c>')
            sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

        shared_xml = "".join(
            f"<si><t>{text}</t></si>" for text in shared_strings
        )

        workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

        workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>"""

        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>"""

        root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

        sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {''.join(sheet_rows)}
  </sheetData>
</worksheet>"""

        shared_strings_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">
  {shared_xml}
</sst>"""

        output = BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", root_rels)
            archive.writestr("xl/workbook.xml", workbook_xml)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
            archive.writestr("xl/sharedStrings.xml", shared_strings_xml)

        output.seek(0)
        return output.getvalue()

    def test_login_and_protected_pages_render(self):
        login_response = self.login()
        self.assertEqual(login_response.status_code, 302)

        for path in [
            "/",
            "/absen/",
            "/schedule/",
            "/crm/",
            "/chat/",
            "/products/",
            "/stock/",
            "/inbound/",
            "/outbound/",
            "/transfers/",
            "/request/",
            "/hris/",
            "/audit/",
            "/so/",
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn('name="viewport"', html)
                self.assertIn('mobile-nav', html)
                self.assertIn('@admin', html)
                self.assertIn('data-theme-toggle', html)
                self.assertIn('>WMS<', html)
                self.assertIn('>HRIS<', html)
                self.assertIn('>Chat<', html)
                self.assertIn('>Absen<', html)

        admin_page = self.client.get("/admin/", follow_redirects=False)
        self.assertEqual(admin_page.status_code, 302)

    def test_schedule_route_renders_for_admin_view_only(self):
        self.login()
        employee_id = self.create_employee_record(
            employee_code="EMP-SCD-ADM",
            full_name="Ayu Mataram",
            warehouse_id=1,
            position="Leader",
        )

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO schedule_entries(employee_id, schedule_date, shift_code, note, updated_by)
                VALUES (?,?,?,?,?)
                """,
                (employee_id, "2026-03-30", "P", "Shift pagi reguler", 1),
            )
            db.commit()

        response = self.client.get("/schedule/?start=2026-03-30&days=7")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Penjadwalan Tim", html)
        self.assertIn("View Only", html)
        self.assertIn('name="warehouse" disabled', html)
        self.assertIn("Ayu", html)
        self.assertNotIn("Atur Jadwal Manual", html)
        self.assertNotIn("Master Shift", html)

    def test_hr_role_can_manage_schedule_and_hris(self):
        self.create_user("hr_ops", "pass1234", "hr")
        self.login("hr_ops", "pass1234")

        schedule_response = self.client.get("/schedule/")
        self.assertEqual(schedule_response.status_code, 200)
        schedule_html = schedule_response.get_data(as_text=True)
        self.assertIn("Atur Jadwal Manual", schedule_html)
        self.assertIn("Master Shift", schedule_html)
        self.assertIn("Display Staf di Board", schedule_html)
        self.assertIn('>HRIS<', schedule_html)
        self.assertIn('href="/hris/leave"', schedule_html)

        hris_response = self.client.get("/hris/employee")
        self.assertEqual(hris_response.status_code, 200)
        self.assertIn("Tambah Karyawan", hris_response.get_data(as_text=True))

    def test_hris_dashboard_root_shows_active_announcements_and_schedule_preview(self):
        self.create_user("hr_dashboard", "pass1234", "hr")
        employee_id = self.create_employee_record(
            employee_code="EMP-HRIS-DB",
            full_name="Ajeng Schedule",
            warehouse_id=1,
            position="HR Staff",
        )
        today = date_cls.today().isoformat()

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO announcement_posts(
                    warehouse_id,
                    title,
                    audience,
                    publish_date,
                    status,
                    channel,
                    message,
                    handled_by
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    1,
                    "Briefing Gudang Pagi",
                    "warehouse_team",
                    today,
                    "published",
                    "Dashboard Banner",
                    "Semua tim hadir briefing jam 08:00.",
                    1,
                ),
            )
            db.execute(
                """
                INSERT INTO schedule_entries(employee_id, schedule_date, shift_code, note, updated_by)
                VALUES (?,?,?,?,?)
                """,
                (employee_id, today, "P", "Opening shift", 1),
            )
            db.commit()

        self.login("hr_dashboard", "pass1234")
        response = self.client.get(f"/hris/?schedule_start={today}&days=7")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Dashboard HRIS", html)
        self.assertIn("Announcement Aktif", html)
        self.assertIn("Briefing Gudang Pagi", html)
        self.assertIn("Jadwal Tim", html)
        self.assertIn("Ajeng", html)
        self.assertIn("Opening shift", html)
        self.assertIn(f'href="/schedule/?start={today}&days=7"', html)

    def test_hr_can_save_schedule_profile_and_entry(self):
        self.create_user("hr_scheduler", "pass1234", "hr")
        employee_id = self.create_employee_record(
            employee_code="EMP-SCD-HR",
            full_name="Ajeng Planner",
            warehouse_id=2,
            position="HR Coordinator",
        )

        self.login("hr_scheduler", "pass1234")

        profile_response = self.client.post(
            f"/schedule/profile/save/{employee_id}",
            data={
                "custom_name": "Ajeng",
                "display_group": "HR",
                "location_label": "Mega",
                "display_order": "5",
                "include_in_schedule": "on",
                "profile_note": "PIC schedule mingguan",
                "start": "2026-03-30",
                "days": "7",
            },
            follow_redirects=False,
        )
        self.assertEqual(profile_response.status_code, 302)

        entry_response = self.client.post(
            "/schedule/entry/save",
            data={
                "employee_id": str(employee_id),
                "shift_code": "P",
                "entry_start_date": "2026-03-30",
                "entry_end_date": "2026-04-01",
                "note": "Kickoff minggu baru",
                "start": "2026-03-30",
                "days": "7",
            },
            follow_redirects=False,
        )
        self.assertEqual(entry_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            profile = db.execute(
                """
                SELECT custom_name, display_group, location_label, display_order, include_in_schedule, note
                FROM schedule_employee_profiles
                WHERE employee_id=?
                """,
                (employee_id,),
            ).fetchone()
            entry_count = db.execute(
                """
                SELECT COUNT(*)
                FROM schedule_entries
                WHERE employee_id=?
                  AND schedule_date BETWEEN '2026-03-30' AND '2026-04-01'
                """,
                (employee_id,),
            ).fetchone()[0]

        self.assertIsNotNone(profile)
        self.assertEqual(profile["custom_name"], "Ajeng")
        self.assertEqual(profile["display_group"], "HR")
        self.assertEqual(profile["location_label"], "Mega")
        self.assertEqual(profile["display_order"], 5)
        self.assertEqual(profile["include_in_schedule"], 1)
        self.assertEqual(entry_count, 3)

        board_response = self.client.get("/schedule/?start=2026-03-30&days=7")
        self.assertEqual(board_response.status_code, 200)
        board_html = board_response.get_data(as_text=True)
        self.assertIn("Ajeng", board_html)
        self.assertIn("Kickoff minggu baru", board_html)

    def test_admin_can_manage_crm_contacts_purchases_and_members(self):
        self.login()
        response, product_id, variants_rows = self.create_product(
            sku="CRM-PRD-001",
            qty=12,
            variants="40,41",
            warehouse_id="1",
        )
        self.assertEqual(response.status_code, 302)

        add_customer = self.client.post(
            "/crm/customers/add",
            data={
                "warehouse_id": "1",
                "customer_name": "Toko CRM",
                "contact_person": "Rian",
                "phone": "628111111111",
                "email": "rian@crm.test",
                "city": "Mataram",
                "instagram_handle": "@tokocrm",
                "customer_type": "member",
                "marketing_channel": "Repeat Order",
                "note": "Pelanggan setia raket premium",
            },
            follow_redirects=False,
        )
        self.assertEqual(add_customer.status_code, 302)

        with self.app.app_context():
            db = get_db()
            customer = db.execute(
                "SELECT id FROM crm_customers WHERE customer_name='Toko CRM'"
            ).fetchone()
        self.assertIsNotNone(customer)

        add_member = self.client.post(
            "/crm/members/add",
            data={
                "customer_id": str(customer["id"]),
                "member_code": "MBR-CRM-001",
                "tier": "gold",
                "status": "active",
                "join_date": "2026-03-30",
                "expiry_date": "2027-03-30",
                "points": "12",
                "benefit_note": "Diskon komunitas",
                "note": "Masuk loyalty badminton",
            },
            follow_redirects=False,
        )
        self.assertEqual(add_member.status_code, 302)

        with self.app.app_context():
            db = get_db()
            member = db.execute(
                "SELECT id FROM crm_memberships WHERE member_code='MBR-CRM-001'"
            ).fetchone()
        self.assertIsNotNone(member)

        add_purchase = self.client.post(
            "/crm/purchases/add",
            data={
                "warehouse_id": "1",
                "customer_id": str(customer["id"]),
                "member_id": str(member["id"]),
                "purchase_date": "2026-03-30",
                "invoice_no": "INV-CRM-001",
                "channel": "store",
                "note": "Order pembuka untuk stok toko",
                "items_json": json.dumps(
                    [
                        {
                            "product_id": product_id,
                            "variant_id": variants_rows[0]["id"],
                            "qty": 2,
                            "unit_price": 150000,
                            "display_name": "CRM-PRD-001 - Produk Uji",
                        },
                        {
                            "product_id": product_id,
                            "variant_id": variants_rows[1]["id"],
                            "qty": 1,
                            "unit_price": 175000,
                            "display_name": "CRM-PRD-001 - Produk Uji",
                        },
                    ]
                ),
            },
            follow_redirects=False,
        )
        self.assertEqual(add_purchase.status_code, 302)

        add_member_record = self.client.post(
            "/crm/member-records/add",
            data={
                "member_id": str(member["id"]),
                "record_date": "2026-03-31",
                "record_type": "point_adjustment",
                "reference_no": "PROMO-APRIL",
                "amount": "0",
                "points_delta": "25",
                "note": "Bonus poin pembukaan akun",
            },
            follow_redirects=False,
        )
        self.assertEqual(add_member_record.status_code, 302)

        with self.app.app_context():
            db = get_db()
            purchase = db.execute(
                """
                SELECT total_amount, items_count, channel
                FROM crm_purchase_records
                WHERE invoice_no='INV-CRM-001'
                """
            ).fetchone()
            purchase_items_count = db.execute(
                "SELECT COUNT(*) FROM crm_purchase_items"
            ).fetchone()[0]
            member_records = db.execute(
                """
                SELECT record_type, points_delta, amount
                FROM crm_member_records
                WHERE member_id=?
                ORDER BY id
                """,
                (member["id"],),
            ).fetchall()

        self.assertIsNotNone(purchase)
        self.assertEqual(purchase["total_amount"], 475000)
        self.assertEqual(purchase["items_count"], 3)
        self.assertEqual(purchase["channel"], "store")
        self.assertEqual(purchase_items_count, 2)
        self.assertEqual(len(member_records), 2)
        self.assertEqual(member_records[0]["record_type"], "purchase")
        self.assertEqual(member_records[0]["amount"], 475000)
        self.assertEqual(member_records[1]["record_type"], "point_adjustment")
        self.assertEqual(member_records[1]["points_delta"], 25)

        crm_response = self.client.get("/crm/?tab=contacts")
        self.assertEqual(crm_response.status_code, 200)
        crm_html = crm_response.get_data(as_text=True)
        self.assertIn("Toko CRM", crm_html)
        self.assertIn("MBR-CRM-001", crm_html)
        self.assertIn("Produk Uji / 40", crm_html)

    def test_chat_module_supports_direct_messages_and_realtime_unread(self):
        self.create_user("leader_chat", "pass1234", "leader", warehouse_id=1)
        self.create_user("staff_chat", "pass1234", "staff", warehouse_id=1)

        leader_user_id = self.get_user_id("leader_chat")
        self.assertIsNotNone(leader_user_id)

        self.login("staff_chat", "pass1234")

        chat_page = self.client.get("/chat/")
        self.assertEqual(chat_page.status_code, 200)
        self.assertIn("Chat Operasional Live", chat_page.get_data(as_text=True))

        start_thread = self.client.post(
            "/chat/thread/start",
            json={"target_user_id": leader_user_id},
            follow_redirects=False,
        )
        self.assertEqual(start_thread.status_code, 200)
        start_payload = start_thread.get_json()
        self.assertEqual(start_payload["status"], "ok")
        thread_id = start_payload["thread_id"]

        send_message = self.client.post(
            f"/chat/thread/{thread_id}/send",
            json={"message": "Leader tolong cek request masuk hari ini."},
            follow_redirects=False,
        )
        self.assertEqual(send_message.status_code, 200)
        send_payload = send_message.get_json()
        self.assertEqual(send_payload["status"], "ok")
        self.assertEqual(send_payload["message"]["body"], "Leader tolong cek request masuk hari ini.")

        with self.app.app_context():
            db = get_db()
            stored_message = db.execute(
                """
                SELECT body
                FROM chat_messages
                WHERE thread_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (thread_id,),
            ).fetchone()
            notification_row = db.execute(
                """
                SELECT channel, recipient
                FROM notifications
                WHERE channel='chat'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        self.assertIsNotNone(stored_message)
        self.assertEqual(stored_message["body"], "Leader tolong cek request masuk hari ini.")
        self.assertIsNotNone(notification_row)
        self.assertEqual(notification_row["channel"], "chat")
        self.assertEqual(notification_row["recipient"], "leader_chat")

        self.logout()
        self.login("leader_chat", "pass1234")

        realtime_before_open = self.client.get(
            "/chat/realtime?since_message_id=0&include_threads=1",
            follow_redirects=False,
        )
        self.assertEqual(realtime_before_open.status_code, 200)
        realtime_before_payload = realtime_before_open.get_json()
        self.assertEqual(realtime_before_payload["status"], "ok")
        self.assertEqual(realtime_before_payload["unread_total"], 1)
        self.assertEqual(len(realtime_before_payload["incoming"]), 1)
        self.assertEqual(realtime_before_payload["threads"][0]["partner_name"], "staff_chat")

        open_thread = self.client.get(f"/chat/?thread={thread_id}")
        self.assertEqual(open_thread.status_code, 200)
        self.assertIn("staff_chat", open_thread.get_data(as_text=True))

        realtime_after_open = self.client.get(
            "/chat/realtime?since_message_id=0&include_threads=1",
            follow_redirects=False,
        )
        self.assertEqual(realtime_after_open.status_code, 200)
        realtime_after_payload = realtime_after_open.get_json()
        self.assertEqual(realtime_after_payload["status"], "ok")
        self.assertEqual(realtime_after_payload["unread_total"], 0)

    def test_staff_cannot_access_crm_page(self):
        self.create_user("staff_crm", "pass1234", "staff", warehouse_id=1)
        self.login("staff_crm", "pass1234")

        response = self.client.get("/crm/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/schedule/", response.headers["Location"])

        dashboard_response = self.client.get("/")
        dashboard_html = dashboard_response.get_data(as_text=True)
        self.assertNotIn('>CRM<', dashboard_html)

    def test_staff_can_open_chat_but_still_cannot_open_crm(self):
        self.create_user("staff_chat_only", "pass1234", "staff", warehouse_id=1)
        self.login("staff_chat_only", "pass1234")

        chat_response = self.client.get("/chat/")
        self.assertEqual(chat_response.status_code, 200)
        self.assertIn("Chat Operasional Live", chat_response.get_data(as_text=True))

        crm_response = self.client.get("/crm/", follow_redirects=False)
        self.assertEqual(crm_response.status_code, 302)
        self.assertIn("/schedule/", crm_response.headers["Location"])

    def test_hr_can_rename_shift_code_without_breaking_existing_entries(self):
        self.create_user("hr_shift", "pass1234", "hr")
        employee_id = self.create_employee_record(
            employee_code="EMP-SCD-RNM",
            full_name="Rina Shift",
            warehouse_id=1,
            position="Scheduler",
        )

        self.login("hr_shift", "pass1234")

        entry_response = self.client.post(
            "/schedule/entry/save",
            data={
                "employee_id": str(employee_id),
                "shift_code": "P",
                "entry_start_date": "2026-03-30",
                "entry_end_date": "2026-03-30",
                "note": "Shift awal",
                "start": "2026-03-30",
                "days": "7",
            },
            follow_redirects=False,
        )
        self.assertEqual(entry_response.status_code, 302)

        rename_response = self.client.post(
            "/schedule/shift-code/save",
            data={
                "original_code": "P",
                "code": "P1",
                "label": "Pagi 1",
                "bg_color": "#c6e5ab",
                "text_color": "#17351a",
                "sort_order": "10",
                "is_active": "on",
                "start": "2026-03-30",
                "days": "7",
            },
            follow_redirects=False,
        )
        self.assertEqual(rename_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            renamed_shift = db.execute(
                "SELECT code, label FROM schedule_shift_codes WHERE code='P1'"
            ).fetchone()
            removed_shift = db.execute(
                "SELECT code FROM schedule_shift_codes WHERE code='P'"
            ).fetchone()
            schedule_entry = db.execute(
                """
                SELECT shift_code
                FROM schedule_entries
                WHERE employee_id=? AND schedule_date='2026-03-30'
                """,
                (employee_id,),
            ).fetchone()

        self.assertIsNotNone(renamed_shift)
        self.assertEqual(renamed_shift["label"], "Pagi 1")
        self.assertIsNone(removed_shift)
        self.assertEqual(schedule_entry["shift_code"], "P1")

    def test_schedule_board_applies_leave_and_offboarding_overrides(self):
        self.login()
        leave_employee_id = self.create_employee_record(
            employee_code="EMP-SCD-LV",
            full_name="Nina Leave",
            warehouse_id=1,
            position="Marketing",
        )
        offboarding_employee_id = self.create_employee_record(
            employee_code="EMP-SCD-OF",
            full_name="Dio Offboarding",
            warehouse_id=1,
            position="Host Live",
        )

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO schedule_entries(employee_id, schedule_date, shift_code, note, updated_by)
                VALUES (?,?,?,?,?)
                """,
                (leave_employee_id, "2026-03-30", "P", "Harus tertimpa cuti", 1),
            )
            db.execute(
                """
                INSERT INTO leave_requests(
                    employee_id,
                    warehouse_id,
                    leave_type,
                    start_date,
                    end_date,
                    total_days,
                    status,
                    reason,
                    handled_by
                )
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    leave_employee_id,
                    1,
                    "annual",
                    "2026-03-30",
                    "2026-03-30",
                    1,
                    "approved",
                    "Cuti keluarga",
                    1,
                ),
            )
            db.execute(
                """
                INSERT INTO offboarding_records(
                    employee_id,
                    warehouse_id,
                    notice_date,
                    last_working_date,
                    stage,
                    status,
                    handled_by
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    offboarding_employee_id,
                    1,
                    "2026-03-28",
                    "2026-03-30",
                    "handover",
                    "in_progress",
                    1,
                ),
            )
            db.commit()

        response = self.client.get("/schedule/?start=2026-03-30&days=7")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("CUTI", html)
        self.assertIn("OFFBD", html)

    def test_hris_attendance_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/attendance")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Attendance", html)
        self.assertIn("Log Kehadiran", html)
        self.assertIn("Tambah Attendance", html)

    def test_hris_leave_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/leave")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Leave", html)
        self.assertIn("Leave Tracker", html)
        self.assertIn("Tambah Leave", html)

    def test_hris_payroll_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/payroll")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Payroll", html)
        self.assertIn("Payroll Register", html)
        self.assertIn("Tambah Payroll", html)

    def test_hris_recruitment_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/recruitment")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Recruitment", html)
        self.assertIn("Hiring Pipeline", html)
        self.assertIn("Tambah Kandidat", html)

    def test_hris_onboarding_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/onboarding")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Onboarding", html)
        self.assertIn("Onboarding Tracker", html)
        self.assertIn("Tambah Onboarding", html)

    def test_hris_offboarding_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/offboarding")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Offboarding", html)
        self.assertIn("Offboarding Tracker", html)
        self.assertIn("Tambah Offboarding", html)

    def test_hris_performance_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/pms")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Performance", html)
        self.assertIn("Performance Review", html)
        self.assertIn("Tambah Review", html)

    def test_hris_helpdesk_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/helpdesk")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Helpdesk", html)
        self.assertIn("Ticket Helpdesk", html)
        self.assertIn("Tambah Ticket", html)

    def test_hris_asset_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/asset")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Asset", html)
        self.assertIn("Asset Register", html)
        self.assertIn("Tambah Asset", html)

    def test_hris_project_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/project")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Project", html)
        self.assertIn("Project Register", html)
        self.assertIn("Tambah Project", html)

    def test_hris_report_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/report")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Report", html)
        self.assertIn("HR Analytics Report", html)
        self.assertIn("Workforce Snapshot", html)

    def test_hris_biometric_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/biometric")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Geotag", html)
        self.assertIn("Log Geotag Absensi", html)
        self.assertIn("Tambah Absen Geotag", html)
        self.assertIn("Rekap Absensi Geotag", html)

    def test_attendance_portal_renders_for_logged_in_user(self):
        self.login()
        response = self.client.get("/absen/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Absen Foto & Geotag", html)
        self.assertIn("Riwayat Absen Terakhir", html)
        self.assertIn("belum ditautkan ke data karyawan", html.lower())

    def test_hris_announcement_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/announcement")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Announcement", html)
        self.assertIn("Announcement Board", html)
        self.assertIn("Tambah Announcement", html)

    def test_hris_documents_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/documents")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Documents", html)
        self.assertIn("Document Register", html)
        self.assertIn("Tambah Document", html)

    def test_admin_can_manage_employee_records_in_hris(self):
        self.login_hr_user()

        create_response = self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-001",
                "full_name": "Budi Santoso",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Stock Controller",
                "employment_status": "active",
                "phone": "628123456789",
                "email": "budi@example.com",
                "join_date": "2026-03-01",
                "work_location": "Gudang Mega",
                "notes": "Lead picker zone A",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, employee_code, full_name, warehouse_id, department, position, employment_status
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["full_name"], "Budi Santoso")
        self.assertEqual(employee["warehouse_id"], 2)
        self.assertEqual(employee["employment_status"], "active")

        update_response = self.client.post(
            f"/hris/employee/update/{employee['id']}",
            data={
                "employee_code": "EMP-001",
                "full_name": "Budi Santoso Update",
                "warehouse_id": "2",
                "department": "Warehouse Support",
                "position": "Inventory Analyst",
                "employment_status": "probation",
                "phone": "628123456789",
                "email": "budi@example.com",
                "join_date": "2026-03-01",
                "work_location": "Gudang Mataram",
                "notes": "Updated note",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            employee_after = db.execute(
                """
                SELECT full_name, warehouse_id, department, position, employment_status, work_location
                FROM employees
                WHERE id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertEqual(employee_after["full_name"], "Budi Santoso Update")
        self.assertEqual(employee_after["warehouse_id"], 2)
        self.assertEqual(employee_after["department"], "Warehouse Support")
        self.assertEqual(employee_after["position"], "Inventory Analyst")
        self.assertEqual(employee_after["employment_status"], "probation")
        self.assertEqual(employee_after["work_location"], "Gudang Mataram")

        delete_response = self.client.post(
            f"/hris/employee/delete/{employee['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            employee_count = db.execute(
                "SELECT COUNT(*) FROM employees"
            ).fetchone()[0]

        self.assertEqual(employee_count, 0)

    def test_admin_can_manage_attendance_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-ATT-001",
                "full_name": "Sinta Presensi",
                "warehouse_id": "2",
                "department": "People Operation",
                "position": "Admin HR",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-ATT-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/attendance/add",
            data={
                "employee_id": str(employee["id"]),
                "attendance_date": "2026-03-30",
                "check_in": "08:15",
                "check_out": "17:05",
                "status": "present",
                "note": "Shift pagi normal",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance = db.execute(
                """
                SELECT id, employee_id, warehouse_id, attendance_date, check_in, check_out, status, note
                FROM attendance_records
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(attendance)
        self.assertEqual(attendance["warehouse_id"], 2)
        self.assertEqual(attendance["attendance_date"], "2026-03-30")
        self.assertEqual(attendance["check_in"], "08:15")
        self.assertEqual(attendance["check_out"], "17:05")
        self.assertEqual(attendance["status"], "present")

        update_response = self.client.post(
            f"/hris/attendance/update/{attendance['id']}",
            data={
                "employee_id": str(employee["id"]),
                "attendance_date": "2026-03-30",
                "check_in": "08:35",
                "check_out": "17:30",
                "status": "late",
                "note": "Terlambat karena meeting vendor",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance_after = db.execute(
                """
                SELECT check_in, check_out, status, note
                FROM attendance_records
                WHERE id=?
                """,
                (attendance["id"],),
            ).fetchone()

        self.assertEqual(attendance_after["check_in"], "08:35")
        self.assertEqual(attendance_after["check_out"], "17:30")
        self.assertEqual(attendance_after["status"], "late")
        self.assertEqual(attendance_after["note"], "Terlambat karena meeting vendor")

        delete_response = self.client.post(
            f"/hris/attendance/delete/{attendance['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance_count = db.execute(
                "SELECT COUNT(*) FROM attendance_records"
            ).fetchone()[0]

        self.assertEqual(attendance_count, 0)

    def test_admin_can_manage_leave_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-LV-001",
                "full_name": "Rina Cuti",
                "warehouse_id": "2",
                "department": "HR Support",
                "position": "People Admin",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-LV-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/leave/add",
            data={
                "employee_id": str(employee["id"]),
                "leave_type": "annual",
                "start_date": "2026-04-10",
                "end_date": "2026-04-12",
                "status": "pending",
                "reason": "Cuti keluarga",
                "note": "Handover ke tim inventory",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            leave_request = db.execute(
                """
                SELECT id, employee_id, warehouse_id, leave_type, start_date, end_date, total_days, status, reason, note
                FROM leave_requests
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(leave_request)
        self.assertEqual(leave_request["warehouse_id"], 2)
        self.assertEqual(leave_request["leave_type"], "annual")
        self.assertEqual(leave_request["total_days"], 3)
        self.assertEqual(leave_request["status"], "pending")
        self.assertEqual(leave_request["reason"], "Cuti keluarga")

        update_response = self.client.post(
            f"/hris/leave/update/{leave_request['id']}",
            data={
                "employee_id": str(employee["id"]),
                "leave_type": "sick",
                "start_date": "2026-04-10",
                "end_date": "2026-04-11",
                "status": "approved",
                "reason": "Istirahat dokter",
                "note": "Disetujui supervisor",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            leave_after = db.execute(
                """
                SELECT leave_type, start_date, end_date, total_days, status, reason, note, handled_by
                FROM leave_requests
                WHERE id=?
                """,
                (leave_request["id"],),
            ).fetchone()

        self.assertEqual(leave_after["leave_type"], "sick")
        self.assertEqual(leave_after["end_date"], "2026-04-11")
        self.assertEqual(leave_after["total_days"], 2)
        self.assertEqual(leave_after["status"], "approved")
        self.assertEqual(leave_after["reason"], "Istirahat dokter")
        self.assertIsNotNone(leave_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/leave/delete/{leave_request['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            leave_count = db.execute(
                "SELECT COUNT(*) FROM leave_requests"
            ).fetchone()[0]

        self.assertEqual(leave_count, 0)

    def test_admin_can_manage_payroll_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-PY-001",
                "full_name": "Dani Payroll",
                "warehouse_id": "2",
                "department": "Finance",
                "position": "Payroll Admin",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-PY-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/payroll/add",
            data={
                "employee_id": str(employee["id"]),
                "period_month": "4",
                "period_year": "2026",
                "base_salary": "5500000",
                "allowance": "350000",
                "overtime_pay": "150000",
                "deduction": "100000",
                "leave_deduction": "50000",
                "status": "draft",
                "note": "Payroll April draft",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            payroll = db.execute(
                """
                SELECT id, employee_id, warehouse_id, period_month, period_year, base_salary, allowance,
                       overtime_pay, deduction, leave_deduction, net_pay, status, note
                FROM payroll_runs
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(payroll)
        self.assertEqual(payroll["warehouse_id"], 2)
        self.assertEqual(payroll["period_month"], 4)
        self.assertEqual(payroll["period_year"], 2026)
        self.assertEqual(payroll["net_pay"], 5850000)
        self.assertEqual(payroll["status"], "draft")

        update_response = self.client.post(
            f"/hris/payroll/update/{payroll['id']}",
            data={
                "employee_id": str(employee["id"]),
                "period_month": "4",
                "period_year": "2026",
                "base_salary": "5600000",
                "allowance": "400000",
                "overtime_pay": "200000",
                "deduction": "120000",
                "leave_deduction": "30000",
                "status": "paid",
                "note": "Payroll April final",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            payroll_after = db.execute(
                """
                SELECT base_salary, allowance, overtime_pay, deduction, leave_deduction, net_pay, status, note, handled_by
                FROM payroll_runs
                WHERE id=?
                """,
                (payroll["id"],),
            ).fetchone()

        self.assertEqual(payroll_after["base_salary"], 5600000)
        self.assertEqual(payroll_after["allowance"], 400000)
        self.assertEqual(payroll_after["overtime_pay"], 200000)
        self.assertEqual(payroll_after["deduction"], 120000)
        self.assertEqual(payroll_after["leave_deduction"], 30000)
        self.assertEqual(payroll_after["net_pay"], 6050000)
        self.assertEqual(payroll_after["status"], "paid")
        self.assertEqual(payroll_after["note"], "Payroll April final")
        self.assertIsNotNone(payroll_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/payroll/delete/{payroll['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            payroll_count = db.execute(
                "SELECT COUNT(*) FROM payroll_runs"
            ).fetchone()[0]

        self.assertEqual(payroll_count, 0)

    def test_admin_can_manage_recruitment_records_in_hris(self):
        self.login_hr_user()

        create_response = self.client.post(
            "/hris/recruitment/add",
            data={
                "candidate_name": "Farhan Nugraha",
                "position_title": "Warehouse Supervisor",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "stage": "interview",
                "status": "active",
                "source": "Referral",
                "phone": "628111111111",
                "email": "farhan@example.com",
                "expected_join_date": "2026-05-01",
                "note": "Kandidat kuat untuk shift utama",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            candidate = db.execute(
                """
                SELECT id, candidate_name, warehouse_id, position_title, stage, status, source
                FROM recruitment_candidates
                WHERE candidate_name=?
                """,
                ("Farhan Nugraha",),
            ).fetchone()

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["warehouse_id"], 2)
        self.assertEqual(candidate["stage"], "interview")
        self.assertEqual(candidate["status"], "active")

        update_response = self.client.post(
            f"/hris/recruitment/update/{candidate['id']}",
            data={
                "candidate_name": "Farhan Nugraha Update",
                "position_title": "Warehouse Lead",
                "warehouse_id": "2",
                "department": "Warehouse Support",
                "stage": "offer",
                "status": "closed",
                "source": "Job Portal",
                "phone": "628122222222",
                "email": "farhan.update@example.com",
                "expected_join_date": "2026-05-10",
                "note": "Offer final approved",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            candidate_after = db.execute(
                """
                SELECT candidate_name, warehouse_id, position_title, stage, status, source, handled_by
                FROM recruitment_candidates
                WHERE id=?
                """,
                (candidate["id"],),
            ).fetchone()

        self.assertEqual(candidate_after["candidate_name"], "Farhan Nugraha Update")
        self.assertEqual(candidate_after["warehouse_id"], 2)
        self.assertEqual(candidate_after["position_title"], "Warehouse Lead")
        self.assertEqual(candidate_after["stage"], "offer")
        self.assertEqual(candidate_after["status"], "closed")
        self.assertEqual(candidate_after["source"], "Job Portal")
        self.assertIsNotNone(candidate_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/recruitment/delete/{candidate['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            candidate_count = db.execute(
                "SELECT COUNT(*) FROM recruitment_candidates"
            ).fetchone()[0]

        self.assertEqual(candidate_count, 0)

    def test_admin_can_manage_onboarding_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-ONB-001",
                "full_name": "Ayu Onboarding",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Picker",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-ONB-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/onboarding/add",
            data={
                "employee_id": str(employee["id"]),
                "start_date": "2026-05-01",
                "target_date": "2026-05-07",
                "stage": "orientation",
                "status": "in_progress",
                "buddy_name": "Leader Andi",
                "note": "Sudah briefing awal",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            onboarding = db.execute(
                """
                SELECT id, employee_id, warehouse_id, start_date, target_date, stage, status, buddy_name, note
                FROM onboarding_records
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(onboarding)
        self.assertEqual(onboarding["warehouse_id"], 2)
        self.assertEqual(onboarding["stage"], "orientation")
        self.assertEqual(onboarding["status"], "in_progress")
        self.assertEqual(onboarding["buddy_name"], "Leader Andi")

        update_response = self.client.post(
            f"/hris/onboarding/update/{onboarding['id']}",
            data={
                "employee_id": str(employee["id"]),
                "start_date": "2026-05-01",
                "target_date": "2026-05-05",
                "stage": "go_live",
                "status": "completed",
                "buddy_name": "Leader Budi",
                "note": "Sudah siap operasional penuh",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            onboarding_after = db.execute(
                """
                SELECT target_date, stage, status, buddy_name, note, handled_by
                FROM onboarding_records
                WHERE id=?
                """,
                (onboarding["id"],),
            ).fetchone()

        self.assertEqual(onboarding_after["target_date"], "2026-05-05")
        self.assertEqual(onboarding_after["stage"], "go_live")
        self.assertEqual(onboarding_after["status"], "completed")
        self.assertEqual(onboarding_after["buddy_name"], "Leader Budi")
        self.assertEqual(onboarding_after["note"], "Sudah siap operasional penuh")
        self.assertIsNotNone(onboarding_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/onboarding/delete/{onboarding['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            onboarding_count = db.execute(
                "SELECT COUNT(*) FROM onboarding_records"
            ).fetchone()[0]

        self.assertEqual(onboarding_count, 0)

    def test_admin_can_manage_offboarding_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-OFF-001",
                "full_name": "Bayu Exit",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Inbound Staff",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-OFF-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/offboarding/add",
            data={
                "employee_id": str(employee["id"]),
                "notice_date": "2026-06-01",
                "last_working_date": "2026-06-15",
                "stage": "handover",
                "status": "in_progress",
                "exit_reason": "Relokasi keluarga",
                "handover_pic": "Leader Sinta",
                "note": "Perlu handover area inbound",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            offboarding = db.execute(
                """
                SELECT id, employee_id, warehouse_id, notice_date, last_working_date, stage,
                       status, exit_reason, handover_pic, note, handled_by
                FROM offboarding_records
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(offboarding)
        self.assertEqual(offboarding["warehouse_id"], 2)
        self.assertEqual(offboarding["notice_date"], "2026-06-01")
        self.assertEqual(offboarding["last_working_date"], "2026-06-15")
        self.assertEqual(offboarding["stage"], "handover")
        self.assertEqual(offboarding["status"], "in_progress")
        self.assertEqual(offboarding["exit_reason"], "Relokasi keluarga")
        self.assertEqual(offboarding["handover_pic"], "Leader Sinta")
        self.assertEqual(offboarding["note"], "Perlu handover area inbound")
        self.assertIsNotNone(offboarding["handled_by"])

        update_response = self.client.post(
            f"/hris/offboarding/update/{offboarding['id']}",
            data={
                "employee_id": str(employee["id"]),
                "notice_date": "2026-06-01",
                "last_working_date": "2026-06-18",
                "stage": "exit_complete",
                "status": "completed",
                "exit_reason": "Relokasi keluarga selesai",
                "handover_pic": "Leader Wati",
                "note": "Semua akses dan asset sudah ditutup",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            offboarding_after = db.execute(
                """
                SELECT last_working_date, stage, status, exit_reason, handover_pic, note, handled_by
                FROM offboarding_records
                WHERE id=?
                """,
                (offboarding["id"],),
            ).fetchone()

        self.assertEqual(offboarding_after["last_working_date"], "2026-06-18")
        self.assertEqual(offboarding_after["stage"], "exit_complete")
        self.assertEqual(offboarding_after["status"], "completed")
        self.assertEqual(offboarding_after["exit_reason"], "Relokasi keluarga selesai")
        self.assertEqual(offboarding_after["handover_pic"], "Leader Wati")
        self.assertEqual(offboarding_after["note"], "Semua akses dan asset sudah ditutup")
        self.assertIsNotNone(offboarding_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/offboarding/delete/{offboarding['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            offboarding_count = db.execute(
                "SELECT COUNT(*) FROM offboarding_records"
            ).fetchone()[0]

        self.assertEqual(offboarding_count, 0)

    def test_admin_can_manage_performance_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-PMS-001",
                "full_name": "Lina Review",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Stock Controller",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-PMS-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/performance/add",
            data={
                "employee_id": str(employee["id"]),
                "review_period": "2026-Q2",
                "goal_score": "88",
                "discipline_score": "90",
                "teamwork_score": "84",
                "status": "reviewed",
                "reviewer_name": "Manager Operasional",
                "note": "Konsisten dan siap naik tanggung jawab",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            review = db.execute(
                """
                SELECT id, employee_id, warehouse_id, review_period, goal_score, discipline_score,
                       teamwork_score, final_score, rating, status, reviewer_name, note, handled_by
                FROM performance_reviews
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(review)
        self.assertEqual(review["warehouse_id"], 2)
        self.assertEqual(review["review_period"], "2026-Q2")
        self.assertEqual(review["status"], "reviewed")
        self.assertEqual(review["reviewer_name"], "Manager Operasional")
        self.assertEqual(review["note"], "Konsisten dan siap naik tanggung jawab")
        self.assertAlmostEqual(review["final_score"], 87.33, places=2)
        self.assertEqual(review["rating"], "good")
        self.assertIsNotNone(review["handled_by"])

        update_response = self.client.post(
            f"/hris/performance/update/{review['id']}",
            data={
                "employee_id": str(employee["id"]),
                "review_period": "2026-Q2",
                "goal_score": "92",
                "discipline_score": "91",
                "teamwork_score": "90",
                "status": "acknowledged",
                "reviewer_name": "Head Operasional",
                "note": "Naik level dan siap pegang area lebih besar",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            review_after = db.execute(
                """
                SELECT goal_score, discipline_score, teamwork_score, final_score, rating, status,
                       reviewer_name, note, handled_by
                FROM performance_reviews
                WHERE id=?
                """,
                (review["id"],),
            ).fetchone()

        self.assertEqual(review_after["goal_score"], 92)
        self.assertEqual(review_after["discipline_score"], 91)
        self.assertEqual(review_after["teamwork_score"], 90)
        self.assertAlmostEqual(review_after["final_score"], 91.0, places=2)
        self.assertEqual(review_after["rating"], "excellent")
        self.assertEqual(review_after["status"], "acknowledged")
        self.assertEqual(review_after["reviewer_name"], "Head Operasional")
        self.assertEqual(review_after["note"], "Naik level dan siap pegang area lebih besar")
        self.assertIsNotNone(review_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/performance/delete/{review['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            performance_count = db.execute(
                "SELECT COUNT(*) FROM performance_reviews"
            ).fetchone()[0]

        self.assertEqual(performance_count, 0)

    def test_admin_can_manage_helpdesk_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-HLP-001",
                "full_name": "Novi Support",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Checker",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-HLP-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/helpdesk/add",
            data={
                "employee_id": str(employee["id"]),
                "ticket_title": "Scanner picking bermasalah",
                "category": "asset",
                "priority": "urgent",
                "status": "in_progress",
                "channel": "WhatsApp",
                "assigned_to": "IT Support",
                "note": "Perlu reset device area picking",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            ticket = db.execute(
                """
                SELECT id, employee_id, warehouse_id, ticket_title, category, priority,
                       status, channel, assigned_to, note, handled_by
                FROM helpdesk_tickets
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(ticket)
        self.assertEqual(ticket["warehouse_id"], 2)
        self.assertEqual(ticket["ticket_title"], "Scanner picking bermasalah")
        self.assertEqual(ticket["category"], "asset")
        self.assertEqual(ticket["priority"], "urgent")
        self.assertEqual(ticket["status"], "in_progress")
        self.assertEqual(ticket["channel"], "WhatsApp")
        self.assertEqual(ticket["assigned_to"], "IT Support")
        self.assertEqual(ticket["note"], "Perlu reset device area picking")
        self.assertIsNotNone(ticket["handled_by"])

        update_response = self.client.post(
            f"/hris/helpdesk/update/{ticket['id']}",
            data={
                "employee_id": str(employee["id"]),
                "ticket_title": "Scanner picking selesai ditangani",
                "category": "asset",
                "priority": "high",
                "status": "resolved",
                "channel": "Onsite",
                "assigned_to": "IT Lead",
                "note": "Firmware berhasil diperbarui",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            ticket_after = db.execute(
                """
                SELECT ticket_title, priority, status, channel, assigned_to, note, handled_by
                FROM helpdesk_tickets
                WHERE id=?
                """,
                (ticket["id"],),
            ).fetchone()

        self.assertEqual(ticket_after["ticket_title"], "Scanner picking selesai ditangani")
        self.assertEqual(ticket_after["priority"], "high")
        self.assertEqual(ticket_after["status"], "resolved")
        self.assertEqual(ticket_after["channel"], "Onsite")
        self.assertEqual(ticket_after["assigned_to"], "IT Lead")
        self.assertEqual(ticket_after["note"], "Firmware berhasil diperbarui")
        self.assertIsNotNone(ticket_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/helpdesk/delete/{ticket['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            ticket_count = db.execute(
                "SELECT COUNT(*) FROM helpdesk_tickets"
            ).fetchone()[0]

        self.assertEqual(ticket_count, 0)

    def test_admin_can_manage_asset_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-AST-001",
                "full_name": "Rafi Asset",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Picker",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-AST-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/asset/add",
            data={
                "employee_id": str(employee["id"]),
                "asset_name": "Handheld Scanner",
                "asset_code": "AST-001",
                "serial_number": "SN-7788",
                "category": "Device",
                "asset_status": "allocated",
                "condition_status": "good",
                "assigned_date": "2026-07-01",
                "return_date": "",
                "note": "Dipakai area picking",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            asset = db.execute(
                """
                SELECT id, employee_id, warehouse_id, asset_name, asset_code, serial_number,
                       category, asset_status, condition_status, assigned_date, return_date,
                       note, handled_by
                FROM asset_records
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(asset)
        self.assertEqual(asset["warehouse_id"], 2)
        self.assertEqual(asset["asset_name"], "Handheld Scanner")
        self.assertEqual(asset["asset_code"], "AST-001")
        self.assertEqual(asset["serial_number"], "SN-7788")
        self.assertEqual(asset["category"], "Device")
        self.assertEqual(asset["asset_status"], "allocated")
        self.assertEqual(asset["condition_status"], "good")
        self.assertEqual(asset["assigned_date"], "2026-07-01")
        self.assertEqual(asset["note"], "Dipakai area picking")
        self.assertIsNotNone(asset["handled_by"])

        update_response = self.client.post(
            f"/hris/asset/update/{asset['id']}",
            data={
                "employee_id": str(employee["id"]),
                "asset_name": "Handheld Scanner",
                "asset_code": "AST-001",
                "serial_number": "SN-7788-REV",
                "category": "Device",
                "asset_status": "returned",
                "condition_status": "fair",
                "assigned_date": "2026-07-01",
                "return_date": "2026-07-20",
                "note": "Dikembalikan setelah shift event",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            asset_after = db.execute(
                """
                SELECT serial_number, asset_status, condition_status, return_date, note, handled_by
                FROM asset_records
                WHERE id=?
                """,
                (asset["id"],),
            ).fetchone()

        self.assertEqual(asset_after["serial_number"], "SN-7788-REV")
        self.assertEqual(asset_after["asset_status"], "returned")
        self.assertEqual(asset_after["condition_status"], "fair")
        self.assertEqual(asset_after["return_date"], "2026-07-20")
        self.assertEqual(asset_after["note"], "Dikembalikan setelah shift event")
        self.assertIsNotNone(asset_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/asset/delete/{asset['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            asset_count = db.execute(
                "SELECT COUNT(*) FROM asset_records"
            ).fetchone()[0]

        self.assertEqual(asset_count, 0)

    def test_admin_can_manage_project_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-PRJ-001",
                "full_name": "Tio Project",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Leader",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-PRJ-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/project/add",
            data={
                "employee_id": str(employee["id"]),
                "project_name": "Rollout SOP Stock Audit",
                "project_code": "PRJ-001",
                "priority": "critical",
                "status": "active",
                "start_date": "2026-08-01",
                "due_date": "2026-08-20",
                "progress_percent": "35",
                "owner_name": "Leader Project",
                "note": "Butuh koordinasi lintas shift",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            project = db.execute(
                """
                SELECT id, employee_id, warehouse_id, project_name, project_code, priority,
                       status, start_date, due_date, progress_percent, owner_name, note, handled_by
                FROM project_records
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(project)
        self.assertEqual(project["warehouse_id"], 2)
        self.assertEqual(project["project_name"], "Rollout SOP Stock Audit")
        self.assertEqual(project["project_code"], "PRJ-001")
        self.assertEqual(project["priority"], "critical")
        self.assertEqual(project["status"], "active")
        self.assertEqual(project["start_date"], "2026-08-01")
        self.assertEqual(project["due_date"], "2026-08-20")
        self.assertEqual(project["progress_percent"], 35)
        self.assertEqual(project["owner_name"], "Leader Project")
        self.assertEqual(project["note"], "Butuh koordinasi lintas shift")
        self.assertIsNotNone(project["handled_by"])

        update_response = self.client.post(
            f"/hris/project/update/{project['id']}",
            data={
                "employee_id": str(employee["id"]),
                "project_name": "Rollout SOP Stock Audit Final",
                "project_code": "PRJ-001",
                "priority": "high",
                "status": "completed",
                "start_date": "2026-08-01",
                "due_date": "2026-08-18",
                "progress_percent": "100",
                "owner_name": "Manager Warehouse",
                "note": "Implementasi selesai penuh",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            project_after = db.execute(
                """
                SELECT project_name, priority, status, due_date, progress_percent, owner_name, note, handled_by
                FROM project_records
                WHERE id=?
                """,
                (project["id"],),
            ).fetchone()

        self.assertEqual(project_after["project_name"], "Rollout SOP Stock Audit Final")
        self.assertEqual(project_after["priority"], "high")
        self.assertEqual(project_after["status"], "completed")
        self.assertEqual(project_after["due_date"], "2026-08-18")
        self.assertEqual(project_after["progress_percent"], 100)
        self.assertEqual(project_after["owner_name"], "Manager Warehouse")
        self.assertEqual(project_after["note"], "Implementasi selesai penuh")
        self.assertIsNotNone(project_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/project/delete/{project['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            project_count = db.execute(
                "SELECT COUNT(*) FROM project_records"
            ).fetchone()[0]

        self.assertEqual(project_count, 0)

    def test_admin_can_manage_biometric_records_in_hris_and_sync_attendance(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-BIO-001",
                "full_name": "Dina Biometric",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Checker",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-BIO-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/biometric/add",
            data={
                "employee_id": str(employee["id"]),
                "location_label": "Gudang Mataram - Depan Kantor",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "12.5",
                "punch_time": "2026-09-01T08:05",
                "punch_type": "check_in",
                "sync_status": "synced",
                "note": "Check in geotag pagi",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric = db.execute(
                """
                SELECT id, employee_id, warehouse_id, device_name, location_label, latitude, longitude, accuracy_m,
                       punch_time, punch_type, sync_status, note, handled_by
                FROM biometric_logs
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()
            attendance = db.execute(
                """
                SELECT attendance_date, check_in, check_out, status, note
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee["id"], "2026-09-01"),
            ).fetchone()

        self.assertIsNotNone(biometric)
        self.assertEqual(biometric["warehouse_id"], 2)
        self.assertEqual(biometric["device_name"], "Mobile Geotag")
        self.assertEqual(biometric["location_label"], "Gudang Mataram - Depan Kantor")
        self.assertEqual(biometric["latitude"], -8.58314)
        self.assertEqual(biometric["longitude"], 116.116798)
        self.assertEqual(biometric["accuracy_m"], 12.5)
        self.assertEqual(biometric["punch_type"], "check_in")
        self.assertEqual(biometric["sync_status"], "synced")
        self.assertEqual(biometric["note"], "Check in geotag pagi")
        self.assertIsNotNone(biometric["handled_by"])
        self.assertIsNotNone(attendance)
        self.assertEqual(attendance["attendance_date"], "2026-09-01")
        self.assertEqual(attendance["check_in"], "08:05")
        self.assertIsNone(attendance["check_out"])
        self.assertEqual(attendance["status"], "present")
        self.assertEqual(attendance["note"], "Synced from geotag")

        update_response = self.client.post(
            f"/hris/biometric/update/{biometric['id']}",
            data={
                "employee_id": str(employee["id"]),
                "location_label": "Gudang Mataram - Area Kasir",
                "latitude": "-8.583500",
                "longitude": "116.117222",
                "accuracy_m": "8.0",
                "punch_time": "2026-09-01T08:40",
                "punch_type": "check_in",
                "sync_status": "manual",
                "note": "Disesuaikan setelah audit lokasi",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric_after = db.execute(
                """
                SELECT device_name, location_label, latitude, longitude, accuracy_m, punch_time, sync_status, note, handled_by
                FROM biometric_logs
                WHERE id=?
                """,
                (biometric["id"],),
            ).fetchone()
            attendance_after = db.execute(
                """
                SELECT check_in, status, note
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee["id"], "2026-09-01"),
            ).fetchone()

        self.assertEqual(biometric_after["device_name"], "Mobile Geotag")
        self.assertEqual(biometric_after["location_label"], "Gudang Mataram - Area Kasir")
        self.assertEqual(biometric_after["latitude"], -8.5835)
        self.assertEqual(biometric_after["longitude"], 116.117222)
        self.assertEqual(biometric_after["accuracy_m"], 8.0)
        self.assertEqual(biometric_after["sync_status"], "manual")
        self.assertEqual(biometric_after["note"], "Disesuaikan setelah audit lokasi")
        self.assertIsNotNone(biometric_after["handled_by"])
        self.assertEqual(attendance_after["check_in"], "08:40")
        self.assertEqual(attendance_after["status"], "late")
        self.assertEqual(attendance_after["note"], "Synced from geotag")

        recap_response = self.client.get("/hris/biometric?date_from=2026-09-01&date_to=2026-09-01")
        self.assertEqual(recap_response.status_code, 200)
        recap_html = recap_response.get_data(as_text=True)
        self.assertIn("Rekap Absensi Geotag", recap_html)
        self.assertIn("Gudang Mataram - Area Kasir", recap_html)
        self.assertIn("08:40", recap_html)

        delete_response = self.client.post(
            f"/hris/biometric/delete/{biometric['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric_count = db.execute(
                "SELECT COUNT(*) FROM biometric_logs"
            ).fetchone()[0]
            attendance_count = db.execute(
                """
                SELECT COUNT(*)
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                """,
                (employee["id"], "2026-09-01"),
            ).fetchone()[0]

        self.assertEqual(biometric_count, 0)
        self.assertEqual(attendance_count, 0)

    def test_attendance_portal_submits_photo_geotag_and_syncs_hris_log(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-001",
            full_name="Portal Attendance",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_staff", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_staff", "pass1234")

        submit_response = self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Pintu Utama",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": "2026-09-02T07:58",
                "punch_type": "check_in",
                "note": "Masuk shift pagi",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)
        self.assertIn("/absen/", submit_response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            biometric = db.execute(
                """
                SELECT employee_id, warehouse_id, device_name, device_user_id, location_label, punch_type,
                       sync_status, note, photo_path
                FROM biometric_logs
                WHERE employee_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id,),
            ).fetchone()
            attendance = db.execute(
                """
                SELECT attendance_date, check_in, status, note
                FROM attendance_records
                WHERE employee_id=? AND attendance_date='2026-09-02'
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id,),
            ).fetchone()

        self.assertIsNotNone(biometric)
        self.assertEqual(biometric["warehouse_id"], 1)
        self.assertEqual(biometric["device_name"], "Attendance Photo Portal")
        self.assertEqual(biometric["device_user_id"], "portal_staff")
        self.assertEqual(biometric["location_label"], "Gudang Mataram - Pintu Utama")
        self.assertEqual(biometric["punch_type"], "check_in")
        self.assertEqual(biometric["sync_status"], "synced")
        self.assertIn("Captured from attendance portal", biometric["note"])
        self.assertTrue(biometric["photo_path"])
        self.assertTrue(os.path.exists(os.path.join(self.photo_upload_root, biometric["photo_path"])))
        self.assertIsNotNone(attendance)
        self.assertEqual(attendance["attendance_date"], "2026-09-02")
        self.assertEqual(attendance["check_in"], "07:58")
        self.assertEqual(attendance["status"], "present")
        self.assertEqual(attendance["note"], "Synced from geotag")

        portal_page = self.client.get("/absen/")
        self.assertEqual(portal_page.status_code, 200)
        portal_html = portal_page.get_data(as_text=True)
        self.assertIn("Portal Attendance", portal_html)
        self.assertIn("/static/test-geotag/", portal_html)

        hris_page = self.client.get("/hris/biometric")
        self.assertEqual(hris_page.status_code, 200)
        hris_html = hris_page.get_data(as_text=True)
        self.assertIn("Lihat Foto", hris_html)
        self.assertIn("/static/test-geotag/", hris_html)

    def test_admin_can_manage_announcement_records_in_hris(self):
        self.login_hr_user()

        create_response = self.client.post(
            "/hris/announcement/add",
            data={
                "warehouse_id": "2",
                "title": "Briefing Audit Mingguan",
                "audience": "warehouse_team",
                "publish_date": "2026-10-01",
                "expires_at": "2026-10-07",
                "status": "published",
                "channel": "Dashboard Banner",
                "message": "Semua tim wajib ikut briefing audit jam 08:00.",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            announcement = db.execute(
                """
                SELECT id, warehouse_id, title, audience, publish_date, expires_at,
                       status, channel, message, handled_by
                FROM announcement_posts
                WHERE title=?
                """,
                ("Briefing Audit Mingguan",),
            ).fetchone()

        self.assertIsNotNone(announcement)
        self.assertEqual(announcement["warehouse_id"], 2)
        self.assertEqual(announcement["audience"], "warehouse_team")
        self.assertEqual(announcement["status"], "published")
        self.assertEqual(announcement["channel"], "Dashboard Banner")
        self.assertEqual(announcement["message"], "Semua tim wajib ikut briefing audit jam 08:00.")
        self.assertIsNotNone(announcement["handled_by"])

        update_response = self.client.post(
            f"/hris/announcement/update/{announcement['id']}",
            data={
                "warehouse_id": "2",
                "title": "Briefing Audit Final",
                "audience": "leaders",
                "publish_date": "2026-10-02",
                "expires_at": "2026-10-09",
                "status": "archived",
                "channel": "Morning Briefing",
                "message": "Briefing final dipindah ke jam 09:00.",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            announcement_after = db.execute(
                """
                SELECT warehouse_id, title, audience, publish_date, expires_at,
                       status, channel, message, handled_by
                FROM announcement_posts
                WHERE id=?
                """,
                (announcement["id"],),
            ).fetchone()

        self.assertEqual(announcement_after["warehouse_id"], 2)
        self.assertEqual(announcement_after["title"], "Briefing Audit Final")
        self.assertEqual(announcement_after["audience"], "leaders")
        self.assertEqual(announcement_after["publish_date"], "2026-10-02")
        self.assertEqual(announcement_after["expires_at"], "2026-10-09")
        self.assertEqual(announcement_after["status"], "archived")
        self.assertEqual(announcement_after["channel"], "Morning Briefing")
        self.assertEqual(announcement_after["message"], "Briefing final dipindah ke jam 09:00.")
        self.assertIsNotNone(announcement_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/announcement/delete/{announcement['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            announcement_count = db.execute(
                "SELECT COUNT(*) FROM announcement_posts"
            ).fetchone()[0]

        self.assertEqual(announcement_count, 0)

    def test_admin_can_manage_document_records_in_hris(self):
        self.login_hr_user()

        create_response = self.client.post(
            "/hris/documents/add",
            data={
                "warehouse_id": "2",
                "document_title": "SOP Cycle Count",
                "document_code": "DOC-001",
                "document_type": "sop",
                "status": "active",
                "effective_date": "2026-10-05",
                "review_date": "2026-12-01",
                "owner_name": "Ops Manager",
                "note": "Versi revisi untuk audit Q4",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            document = db.execute(
                """
                SELECT id, warehouse_id, document_title, document_code, document_type,
                       status, effective_date, review_date, owner_name, note, handled_by
                FROM document_records
                WHERE document_code=?
                """,
                ("DOC-001",),
            ).fetchone()

        self.assertIsNotNone(document)
        self.assertEqual(document["warehouse_id"], 2)
        self.assertEqual(document["document_title"], "SOP Cycle Count")
        self.assertEqual(document["document_type"], "sop")
        self.assertEqual(document["status"], "active")
        self.assertEqual(document["review_date"], "2026-12-01")
        self.assertEqual(document["owner_name"], "Ops Manager")
        self.assertEqual(document["note"], "Versi revisi untuk audit Q4")
        self.assertIsNotNone(document["handled_by"])

        update_response = self.client.post(
            f"/hris/documents/update/{document['id']}",
            data={
                "warehouse_id": "2",
                "document_title": "SOP Cycle Count Revisi",
                "document_code": "DOC-001",
                "document_type": "policy",
                "status": "archived",
                "effective_date": "2026-10-06",
                "review_date": "2027-01-15",
                "owner_name": "Senior Ops Manager",
                "note": "Dokumen diarsipkan setelah revisi final.",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            document_after = db.execute(
                """
                SELECT warehouse_id, document_title, document_code, document_type, status,
                       effective_date, review_date, owner_name, note, handled_by
                FROM document_records
                WHERE id=?
                """,
                (document["id"],),
            ).fetchone()

        self.assertEqual(document_after["warehouse_id"], 2)
        self.assertEqual(document_after["document_title"], "SOP Cycle Count Revisi")
        self.assertEqual(document_after["document_code"], "DOC-001")
        self.assertEqual(document_after["document_type"], "policy")
        self.assertEqual(document_after["status"], "archived")
        self.assertEqual(document_after["effective_date"], "2026-10-06")
        self.assertEqual(document_after["review_date"], "2027-01-15")
        self.assertEqual(document_after["owner_name"], "Senior Ops Manager")
        self.assertEqual(document_after["note"], "Dokumen diarsipkan setelah revisi final.")
        self.assertIsNotNone(document_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/documents/delete/{document['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            document_count = db.execute(
                "SELECT COUNT(*) FROM document_records"
            ).fetchone()[0]

        self.assertEqual(document_count, 0)

    def test_add_product_and_get_variants(self):
        self.login()
        response, product_id, variants_rows = self.create_product()

        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(product_id)
        self.assertEqual(len(variants_rows), 2)

        variants_response = self.client.get(f"/products/get_variants/{product_id}")
        self.assertEqual(variants_response.status_code, 200)
        self.assertEqual(len(variants_response.get_json()), 2)

    def test_add_product_supports_manual_variant_matrix(self):
        self.login()
        sku = "MANUAL-" + uuid4().hex[:6].upper()
        response = self.client.post(
            "/products/add",
            data={
                "sku": sku,
                "name": "Produk Matrix",
                "category_name": "Testing",
                "warehouse_id": "1",
                "variant_rows_json": json.dumps([
                    {
                        "variant": "39",
                        "price_retail": "649900",
                        "price_discount": "552415",
                        "price_nett": "500000",
                        "qty": "1",
                        "variant_code": "BED-39",
                        "gtin": "899990000039",
                        "no_gtin": False,
                    },
                    {
                        "variant": "40",
                        "price_retail": "649900",
                        "price_discount": "552415",
                        "price_nett": "500000",
                        "qty": "0",
                        "variant_code": "BED-40",
                        "gtin": "",
                        "no_gtin": True,
                    },
                ]),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()
            variants_rows = db.execute(
                """
                SELECT variant, qty.qty, variant_code, gtin, no_gtin
                FROM product_variants pv
                LEFT JOIN (
                    SELECT variant_id, SUM(qty) AS qty
                    FROM stock
                    GROUP BY variant_id
                ) qty ON qty.variant_id = pv.id
                WHERE product_id=?
                ORDER BY variant
                """,
                (product["id"],),
            ).fetchall()

        self.assertEqual(len(variants_rows), 2)
        self.assertEqual(variants_rows[0]["variant"], "39")
        self.assertEqual(variants_rows[0]["qty"], 1)
        self.assertEqual(variants_rows[0]["variant_code"], "BED-39")
        self.assertEqual(variants_rows[0]["gtin"], "899990000039")
        self.assertEqual(variants_rows[0]["no_gtin"], 0)
        self.assertEqual(variants_rows[1]["variant"], "40")
        self.assertIsNone(variants_rows[1]["qty"])
        self.assertEqual(variants_rows[1]["variant_code"], "BED-40")
        self.assertEqual(variants_rows[1]["gtin"], "")
        self.assertEqual(variants_rows[1]["no_gtin"], 1)

    def test_products_page_uses_10_item_pagination(self):
        self.login()
        for index in range(12):
            response, _, _ = self.create_product(
                sku=f"PAG-{index:02d}-{uuid4().hex[:4].upper()}",
                variants=f"V{index}",
            )
            self.assertEqual(response.status_code, 302)

        page_one = self.client.get("/products/")
        page_one_html = page_one.get_data(as_text=True)
        self.assertEqual(page_one.status_code, 200)
        self.assertEqual(page_one_html.count('class="row-check"'), 10)
        self.assertIn("Page 1 / 2", page_one_html)

        page_two = self.client.get("/products/?page=2")
        page_two_html = page_two.get_data(as_text=True)
        self.assertEqual(page_two.status_code, 200)
        self.assertEqual(page_two_html.count('class="row-check"'), 2)
        self.assertIn("Page 2 / 2", page_two_html)

    def test_product_picker_uses_20_item_pagination(self):
        self.login()
        for index in range(21):
            response, _, _ = self.create_product(
                sku=f"PICK-{index:02d}-{uuid4().hex[:4].upper()}",
                variants=f"V{index}",
            )
            self.assertEqual(response.status_code, 302)

        page_one = self.client.get("/products/picker?warehouse_id=1&page=1")
        self.assertEqual(page_one.status_code, 200)
        payload_one = page_one.get_json()

        self.assertEqual(payload_one["page_size"], 20)
        self.assertEqual(payload_one["page"], 1)
        self.assertEqual(len(payload_one["items"]), 20)
        self.assertGreaterEqual(payload_one["total_items"], 21)
        self.assertGreaterEqual(payload_one["total_pages"], 2)

        page_two = self.client.get("/products/picker?warehouse_id=1&page=2")
        self.assertEqual(page_two.status_code, 200)
        payload_two = page_two.get_json()

        self.assertEqual(payload_two["page"], 2)
        self.assertGreaterEqual(len(payload_two["items"]), 1)

    def test_leader_can_process_bulk_inbound_directly(self):
        self.create_user("leader_inbound", "pass1234", "leader", warehouse_id=1)
        self.login()
        response, product_id, variants_rows = self.create_product(qty=0, variants="41,42")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login("leader_inbound", "pass1234")
        inbound_response = self.client.post(
            "/inbound/",
            data={
                "warehouse_id": "1",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 3,
                        "note": "Restock size 41",
                        "cost": 245000,
                        "custom_date": "2026-03-30",
                    },
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[1]["id"],
                        "qty": 4,
                        "note": "Restock size 42",
                        "cost": 255000,
                        "custom_date": "2026-03-30",
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(inbound_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            stock_rows = db.execute(
                """
                SELECT variant_id, qty
                FROM stock
                WHERE product_id=? AND warehouse_id=1
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()

        self.assertEqual(len(stock_rows), 2)
        self.assertEqual(stock_rows[0]["qty"], 3)
        self.assertEqual(stock_rows[1]["qty"], 4)

    def test_leader_can_process_bulk_outbound_directly(self):
        self.create_user("leader_outbound", "pass1234", "leader", warehouse_id=1)
        self.login()
        response, product_id, variants_rows = self.create_product(qty=10, variants="41,42")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login("leader_outbound", "pass1234")
        outbound_response = self.client.post(
            "/outbound/",
            data={
                "warehouse_id": "1",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 2,
                        "note": "Order size 41",
                    },
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[1]["id"],
                        "qty": 3,
                        "note": "Order size 42",
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(outbound_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            stock_rows = db.execute(
                """
                SELECT variant_id, qty
                FROM stock
                WHERE product_id=? AND warehouse_id=1
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()

        self.assertEqual(len(stock_rows), 2)
        self.assertEqual(stock_rows[0]["qty"], 8)
        self.assertEqual(stock_rows[1]["qty"], 7)

    def test_admin_can_create_bulk_request_batch(self):
        self.create_user("super_req_batch", "pass1234", "super_admin")
        self.login("super_req_batch", "pass1234")
        response, product_id, variants_rows = self.create_product(qty=10, variants="41,42", warehouse_id="2")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login()

        request_response = self.client.post(
            "/request/",
            data={
                "from_warehouse": "1",
                "to_warehouse": "2",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 2,
                    },
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[1]["id"],
                        "qty": 3,
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_rows = db.execute(
                """
                SELECT variant_id, from_warehouse, to_warehouse, qty, status
                FROM requests
                WHERE product_id=?
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()

        self.assertEqual(len(request_rows), 2)
        self.assertEqual(request_rows[0]["from_warehouse"], 2)
        self.assertEqual(request_rows[0]["to_warehouse"], 1)
        self.assertEqual(request_rows[0]["qty"], 2)
        self.assertEqual(request_rows[0]["status"], "pending")
        self.assertEqual(request_rows[1]["from_warehouse"], 2)
        self.assertEqual(request_rows[1]["to_warehouse"], 1)
        self.assertEqual(request_rows[1]["qty"], 3)
        self.assertEqual(request_rows[1]["status"], "pending")

    def test_request_notifications_only_target_source_leader_owner_and_super_admin(self):
        self.create_user(
            "leader_mataram_notify",
            "pass1234",
            "leader",
            warehouse_id=1,
            email="leader_mataram@example.com",
            notify_email=1,
        )
        self.create_user(
            "leader_mega_notify",
            "pass1234",
            "leader",
            warehouse_id=2,
            email="leader_mega@example.com",
            notify_email=1,
        )
        self.create_user(
            "owner_request_notify",
            "pass1234",
            "owner",
            email="owner_request@example.com",
            notify_email=1,
        )
        self.create_user(
            "super_request_notify",
            "pass1234",
            "super_admin",
            email="super_request@example.com",
            notify_email=1,
        )
        self.create_user(
            "admin_mega_notify",
            "pass1234",
            "admin",
            warehouse_id=2,
            email="admin_mega@example.com",
            notify_email=1,
        )

        self.create_user("super_req_notify", "pass1234", "super_admin")
        self.login("super_req_notify", "pass1234")
        response, product_id, variants_rows = self.create_product(qty=10, variants="43", warehouse_id="2")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login()

        request_response = self.client.post(
            "/request/",
            data={
                "product_id": str(product_id),
                "variant_id": str(variants_rows[0]["id"]),
                "from_warehouse": "1",
                "to_warehouse": "2",
                "qty": "2",
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            notifications = db.execute(
                """
                SELECT role, recipient
                FROM notifications
                WHERE subject LIKE 'Request Baru:%'
                ORDER BY recipient
                """
            ).fetchall()

        recipients = {(row["role"], row["recipient"]) for row in notifications}
        self.assertEqual(
            recipients,
            {
                ("leader", "leader_mega@example.com"),
                ("owner", "owner_request@example.com"),
                ("super_admin", "super_request@example.com"),
            },
        )

    def test_admin_can_create_owner_request_batch_and_notify_owner(self):
        self.create_user(
            "owner_notify",
            "pass1234",
            "owner",
            email="owner_notify@example.com",
            notify_email=1,
        )
        self.login()
        response, product_id, variants_rows = self.create_product(qty=10, variants="41,42")
        self.assertEqual(response.status_code, 302)

        owner_page = self.client.get("/request/owner")
        self.assertEqual(owner_page.status_code, 200)
        owner_html = owner_page.get_data(as_text=True)
        self.assertIn('href="/request/"', owner_html)
        self.assertIn('href="/request/owner"', owner_html)
        self.assertIn("Kirim ke Owner", owner_html)

        request_response = self.client.post(
            "/request/owner",
            data={
                "warehouse_id": "1",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 2,
                        "note": "Restock cepat",
                    },
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[1]["id"],
                        "qty": 3,
                        "note": "Display menipis",
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_rows = db.execute(
                """
                SELECT variant_id, warehouse_id, qty, note, status
                FROM owner_requests
                WHERE product_id=?
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()
            notifications = db.execute(
                """
                SELECT role, recipient, subject, status
                FROM notifications
                WHERE subject LIKE 'Request Khusus ke Owner:%'
                ORDER BY id
                """,
            ).fetchall()

        self.assertEqual(len(request_rows), 2)
        self.assertEqual(request_rows[0]["warehouse_id"], 1)
        self.assertEqual(request_rows[0]["qty"], 2)
        self.assertEqual(request_rows[0]["note"], "Restock cepat")
        self.assertEqual(request_rows[0]["status"], "pending")
        self.assertEqual(request_rows[1]["qty"], 3)
        self.assertEqual(request_rows[1]["note"], "Display menipis")
        self.assertEqual(request_rows[1]["status"], "pending")
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["role"], "owner")
        self.assertEqual(notifications[0]["recipient"], "owner_notify@example.com")

    def test_owner_can_update_owner_request_status_and_notify_requester(self):
        self.create_user("owner_manager", "pass1234", "owner")
        self.login()
        response, product_id, variants_rows = self.create_product(qty=10, variants="41")
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                UPDATE users
                SET email=?, notify_email=1
                WHERE username=?
                """,
                ("admin_notify@example.com", "admin"),
            )
            db.commit()

        request_response = self.client.post(
            "/request/owner",
            data={
                "warehouse_id": "1",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 2,
                        "note": "Owner approval needed",
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            owner_request = db.execute(
                """
                SELECT id, requested_by, status
                FROM owner_requests
                WHERE product_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (product_id,),
            ).fetchone()

        self.assertEqual(owner_request["status"], "pending")

        self.logout()
        self.login("owner_manager", "pass1234")

        owner_queue = self.client.get("/request/owner")
        self.assertEqual(owner_queue.status_code, 200)
        self.assertIn("Proses", owner_queue.get_data(as_text=True))

        update_response = self.client.post(
            f"/request/owner/update/{owner_request['id']}",
            data={"status": "in_progress"},
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            owner_request_after = db.execute(
                "SELECT status, handled_by FROM owner_requests WHERE id=?",
                (owner_request["id"],),
            ).fetchone()
            requester_notification = db.execute(
                """
                SELECT recipient, subject, status
                FROM notifications
                WHERE recipient=?
                  AND subject LIKE ?
                ORDER BY id DESC
                LIMIT 1
                """,
                ("admin_notify@example.com", f"Request ke owner #{owner_request['id']}%"),
            ).fetchone()

        self.assertEqual(owner_request_after["status"], "in_progress")
        self.assertIsNotNone(owner_request_after["handled_by"])
        self.assertIsNotNone(requester_notification)
        self.assertIn("Diproses", requester_notification["subject"])

    def test_leader_can_process_bulk_transfer_directly(self):
        self.create_user("leader_transfer", "pass1234", "leader", warehouse_id=1)
        self.login()
        response, product_id, variants_rows = self.create_product(qty=10, variants="41,42")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login("leader_transfer", "pass1234")
        transfer_response = self.client.post(
            "/transfers/",
            data={
                "from_warehouse": "1",
                "to_warehouse": "2",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 2,
                    },
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[1]["id"],
                        "qty": 3,
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(transfer_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            stock_from = db.execute(
                """
                SELECT variant_id, qty
                FROM stock
                WHERE product_id=? AND warehouse_id=1
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()
            stock_to = db.execute(
                """
                SELECT variant_id, qty
                FROM stock
                WHERE product_id=? AND warehouse_id=2
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()
            request_rows = db.execute(
                """
                SELECT variant_id, qty, status
                FROM requests
                WHERE product_id=?
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()

        self.assertEqual(len(stock_from), 2)
        self.assertEqual(stock_from[0]["qty"], 8)
        self.assertEqual(stock_from[1]["qty"], 7)
        self.assertEqual(len(stock_to), 2)
        self.assertEqual(stock_to[0]["qty"], 2)
        self.assertEqual(stock_to[1]["qty"], 3)
        self.assertEqual(len(request_rows), 2)
        self.assertEqual(request_rows[0]["status"], "approved")
        self.assertEqual(request_rows[1]["status"], "approved")

    def test_request_approval_updates_stock(self):
        self.create_user("leader_request", "pass1234", "leader", warehouse_id=2)
        self.create_user("super_req_approve", "pass1234", "super_admin")
        self.login("super_req_approve", "pass1234")
        _, product_id, variants_rows = self.create_product(variants="XL", warehouse_id="2")
        variant_id = variants_rows[0]["id"]
        self.logout()

        self.login()

        request_response = self.client.post(
            "/request/",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "from_warehouse": "1",
                "to_warehouse": "2",
                "qty": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_row = db.execute(
                "SELECT id, from_warehouse, to_warehouse, status FROM requests WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()

        self.assertEqual(request_row["status"], "pending")
        self.assertEqual(request_row["from_warehouse"], 2)
        self.assertEqual(request_row["to_warehouse"], 1)

        self.logout()
        self.login("leader_request", "pass1234")
        approve_response = self.client.post(
            f"/request/approve/{request_row['id']}",
            follow_redirects=False,
        )
        self.assertEqual(approve_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_after = db.execute(
                "SELECT status FROM requests WHERE id=?",
                (request_row["id"],),
            ).fetchone()
            stock_from = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=2",
                (product_id, variant_id),
            ).fetchone()
            stock_to = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product_id, variant_id),
            ).fetchone()

        self.assertEqual(request_after["status"], "approved")
        self.assertEqual(stock_from["qty"], 4)
        self.assertEqual(stock_to["qty"], 1)

    def test_destination_leader_cannot_approve_request(self):
        self.create_user("leader_dest_only", "pass1234", "leader", warehouse_id=1)
        self.create_user("super_req_dest", "pass1234", "super_admin")
        self.login("super_req_dest", "pass1234")
        _, product_id, variants_rows = self.create_product(variants="APR2", warehouse_id="2")
        variant_id = variants_rows[0]["id"]
        self.logout()

        self.login()

        request_response = self.client.post(
            "/request/",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "from_warehouse": "1",
                "to_warehouse": "2",
                "qty": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_row = db.execute(
                "SELECT id, from_warehouse, to_warehouse, status FROM requests WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()

        self.assertEqual(request_row["from_warehouse"], 2)
        self.assertEqual(request_row["to_warehouse"], 1)
        self.assertEqual(request_row["status"], "pending")

        self.logout()
        self.login("leader_dest_only", "pass1234")

        queue_response = self.client.get("/request/")
        self.assertEqual(queue_response.status_code, 200)
        self.assertNotIn(f'/request/approve/{request_row["id"]}', queue_response.get_data(as_text=True))

        approve_response = self.client.post(
            f"/request/approve/{request_row['id']}",
            follow_redirects=False,
        )
        self.assertEqual(approve_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_after = db.execute(
                "SELECT status FROM requests WHERE id=?",
                (request_row["id"],),
            ).fetchone()

        self.assertEqual(request_after["status"], "pending")

    def test_admin_cannot_approve_request(self):
        self.create_user("super_req_admin", "pass1234", "super_admin")
        self.login("super_req_admin", "pass1234")
        _, product_id, variants_rows = self.create_product(variants="APR", warehouse_id="2")
        variant_id = variants_rows[0]["id"]
        self.logout()

        self.login()

        request_response = self.client.post(
            "/request/",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "from_warehouse": "1",
                "to_warehouse": "2",
                "qty": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_row = db.execute(
                "SELECT id, status FROM requests WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()

        response = self.client.post(
            f"/request/approve/{request_row['id']}",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        request_page = self.client.get("/request/")
        html = request_page.get_data(as_text=True)
        self.assertNotIn(f'/request/approve/{request_row["id"]}', html)

        with self.app.app_context():
            db = get_db()
            request_after = db.execute(
                "SELECT status FROM requests WHERE id=?",
                (request_row["id"],),
            ).fetchone()

        self.assertEqual(request_after["status"], "pending")

    def test_import_preview_and_import_progress(self):
        self.login()
        sku = "IMP-" + uuid4().hex[:6].upper()
        csv_bytes = (
            "sku,name,category,variant,qty,price_retail,price_discount,price_nett\n"
            f"{sku},Produk Import Test,Testing,42,3,200000,180000,150000\n"
        ).encode()

        preview_response = self.client.post(
            "/products/import/preview",
            data={"file": (BytesIO(csv_bytes), "sample.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.get_json()["rows"][0]["sku"], sku)

        import_response = self.client.post(
            "/products/import",
            data={"file": (BytesIO(csv_bytes), "sample.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(import_response.status_code, 200)
        job_id = import_response.get_json()["job_id"]
        self.assertTrue(job_id)

        progress_response = self.client.get(f"/products/import/progress/{job_id}")
        self.assertEqual(progress_response.status_code, 200)
        self.assertEqual(progress_response.get_json()["status"], "done")

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()

        self.assertIsNotNone(product)

    def test_import_xlsx_template_works_without_openpyxl_dependency(self):
        self.login()
        sku = "BED PP-POWERSPIN-00001"
        xlsx_bytes = self.build_xlsx_bytes(
            [
                ["sku", "name", "category", "variant", "qty", "warehouse_id", "price_retail", "price_discount", "price_nett"],
                [sku, "POWERSPIN 0001", "POWERSPIN", "-", "1.0", "1.0", "0.0", "0.0", "0.0"],
            ]
        )

        preview_response = self.client.post(
            "/products/import/preview",
            data={"file": (BytesIO(xlsx_bytes), "template.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.get_json()["rows"][0]["sku"], sku)

        import_response = self.client.post(
            "/products/import",
            data={"file": (BytesIO(xlsx_bytes), "template.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(import_response.status_code, 200)

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()
            variant = db.execute(
                "SELECT id, variant FROM product_variants WHERE product_id=?",
                (product["id"],),
            ).fetchone()
            stock = db.execute(
                """
                SELECT qty
                FROM stock
                WHERE product_id=? AND variant_id=? AND warehouse_id=1
                """,
                (product["id"], variant["id"]),
            ).fetchone()

        self.assertIsNotNone(product)
        self.assertEqual(variant["variant"], "default")
        self.assertEqual(stock["qty"], 1)

    def test_forgot_password_creates_reset_code_without_error(self):
        self.create_user(
            "reset_user",
            "pass1234",
            "admin",
            warehouse_id=1,
            email="reset@example.test",
            notify_email=1,
        )

        response = self.client.post(
            "/forgot",
            data={"identifier": "reset@example.test"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            reset_row = db.execute(
                """
                SELECT pr.code
                FROM password_resets pr
                JOIN users u ON u.id = pr.user_id
                WHERE u.username=?
                ORDER BY pr.id DESC
                LIMIT 1
                """,
                ("reset_user",),
            ).fetchone()

        self.assertIsNotNone(reset_row)
        self.assertEqual(len(reset_row["code"]), 6)

    def test_products_page_respects_selected_warehouse_for_super_admin(self):
        self.create_user("superboss", "admin123", "super_admin")
        self.login("superboss", "admin123")
        response, _, _ = self.create_product(variants="WH2", warehouse_id="2")
        self.assertEqual(response.status_code, 302)

        page = self.client.get("/products/?warehouse=2")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        self.assertIn('<option value="2" selected>', html)

    def test_admin_adjust_requires_approval_and_leader_can_approve(self):
        self.create_user("leader_test", "pass1234", "leader", warehouse_id=1)
        self.login()
        _, product_id, variants_rows = self.create_product(variants="ADJ")
        variant_id = variants_rows[0]["id"]

        adjust_response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "-2",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(adjust_response.status_code, 200)
        self.assertEqual(adjust_response.get_json()["status"], "pending")

        with self.app.app_context():
            db = get_db()
            approval = db.execute(
                "SELECT id, status, type FROM approvals WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()

        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["type"], "ADJUST")

        self.logout()
        self.login("leader_test", "pass1234")
        approve_response = self.client.post(
            f"/approvals/approve/{approval['id']}",
            follow_redirects=False,
        )
        self.assertEqual(approve_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            approval_after = db.execute(
                "SELECT status FROM approvals WHERE id=?",
                (approval["id"],),
            ).fetchone()
            stock_after = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product_id, variant_id),
            ).fetchone()

        self.assertEqual(approval_after["status"], "approved")
        self.assertEqual(stock_after["qty"], 3)

    def test_leader_bulk_adjust_rejects_zero_qty(self):
        self.create_user("leader_zero", "pass1234", "leader", warehouse_id=1)
        self.login("leader_zero", "pass1234")
        _, product_id, variants_rows = self.create_product(variants="ZERO")
        variant_id = variants_rows[0]["id"]

        response = self.client.post(
            "/stock/bulk-adjust",
            json={
                "items": [
                    {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "warehouse_id": 1,
                        "qty": 0,
                    }
                ]
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "error")

    def test_scoped_role_pages_lock_warehouse_inputs(self):
        for username, role in [
            ("leader_scope", "leader"),
            ("staff_scope", "staff"),
        ]:
            employee_id = self.create_employee_record(
                employee_code=f"EMP-{role[:3].upper()}-SCOPE",
                full_name=f"{role.title()} Scope",
                warehouse_id=1,
                position=role.title(),
            )
            self.create_user(username, "pass1234", role, warehouse_id=1, employee_id=employee_id)
            self.login(username, "pass1234")

            for path, marker in [
                ("/schedule/", 'name="warehouse" disabled'),
                ("/products/", 'name="warehouse" disabled'),
                ("/request/", 'name="from_warehouse" required disabled'),
                ("/request/owner", 'name="warehouse_id" required disabled'),
                ("/inbound/", 'name="warehouse_id" required disabled'),
                ("/outbound/", 'name="warehouse_id" required disabled'),
                ("/transfers/", 'name="from_warehouse" required disabled'),
                ("/", 'id="warehouseSelect" class="pill-select" disabled'),
            ]:
                with self.subTest(role=role, path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(marker, response.get_data(as_text=True))

            schedule_response = self.client.get("/schedule/")
            self.assertEqual(schedule_response.status_code, 200)
            schedule_html = schedule_response.get_data(as_text=True)
            self.assertIn("View Only", schedule_html)
            self.assertNotIn("Atur Jadwal Manual", schedule_html)

            request_response = self.client.get("/request/")
            self.assertEqual(request_response.status_code, 200)
            request_html = request_response.get_data(as_text=True)
            self.assertIn('name="to_warehouse" required disabled', request_html)

            if role == "leader":
                crm_response = self.client.get("/crm/")
                self.assertEqual(crm_response.status_code, 200)
                crm_html = crm_response.get_data(as_text=True)
                self.assertIn('name="warehouse" disabled', crm_html)
                self.assertIn('name="warehouse_id" required disabled', crm_html)

                leave_response = self.client.get("/hris/leave")
                self.assertEqual(leave_response.status_code, 200)
                leave_html = leave_response.get_data(as_text=True)
                self.assertIn('name="warehouse" disabled', leave_html)
                self.assertIn(f'value="{employee_id}"', leave_html)

                helpdesk_response = self.client.get("/hris/helpdesk")
                self.assertEqual(helpdesk_response.status_code, 200)
                helpdesk_html = helpdesk_response.get_data(as_text=True)
                self.assertIn('name="warehouse" disabled', helpdesk_html)
                self.assertIn(f'value="{employee_id}"', helpdesk_html)

                biometric_response = self.client.get("/hris/biometric")
                self.assertEqual(biometric_response.status_code, 200)
                biometric_html = biometric_response.get_data(as_text=True)
                self.assertIn('name="warehouse" disabled', biometric_html)
                self.assertIn(f'value="{employee_id}"', biometric_html)

                for blocked_path in [
                    "/hris/employee",
                    "/hris/attendance",
                    "/hris/payroll",
                    "/hris/recruitment",
                    "/hris/onboarding",
                    "/hris/offboarding",
                    "/hris/pms",
                    "/hris/asset",
                    "/hris/project",
                    "/hris/announcement",
                    "/hris/documents",
                    "/hris/report",
                ]:
                    blocked_response = self.client.get(blocked_path, follow_redirects=False)
                    self.assertEqual(blocked_response.status_code, 302)
                    self.assertIn("/hris/leave", blocked_response.headers["Location"])
            else:
                dashboard_response = self.client.get("/")
                dashboard_html = dashboard_response.get_data(as_text=True)
                self.assertIn('/hris/leave', dashboard_html)
                self.assertNotIn('>CRM<', dashboard_html)

                staff_hris_root = self.client.get("/hris/", follow_redirects=False)
                self.assertEqual(staff_hris_root.status_code, 200)

                leave_response = self.client.get("/hris/leave")
                self.assertEqual(leave_response.status_code, 200)
                self.assertIn(f'value="{employee_id}"', leave_response.get_data(as_text=True))

                helpdesk_response = self.client.get("/hris/helpdesk")
                self.assertEqual(helpdesk_response.status_code, 200)
                self.assertIn(f'value="{employee_id}"', helpdesk_response.get_data(as_text=True))

                biometric_response = self.client.get("/hris/biometric")
                self.assertEqual(biometric_response.status_code, 200)
                self.assertIn(f'value="{employee_id}"', biometric_response.get_data(as_text=True))

                staff_hris_module = self.client.get("/hris/employee", follow_redirects=False)
                self.assertEqual(staff_hris_module.status_code, 302)
                self.assertIn("/hris/leave", staff_hris_module.headers["Location"])

                staff_crm_root = self.client.get("/crm/", follow_redirects=False)
                self.assertEqual(staff_crm_root.status_code, 302)
                self.assertIn("/schedule/", staff_crm_root.headers["Location"])
                self.assertIn("/hris/leave", schedule_html)
                self.assertNotIn("/hris/offboarding", schedule_html)

            self.logout()

    def test_scoped_hris_roles_are_limited_to_self_service_modules_and_own_employee(self):
        own_employee_id = self.create_employee_record(
            employee_code="EMP-STF-HRIS",
            full_name="Staff Self Service",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        other_employee_id = self.create_employee_record(
            employee_code="EMP-OTH-HRIS",
            full_name="Other Employee",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("staff_hris_self", "pass1234", "staff", warehouse_id=1, employee_id=own_employee_id)
        self.login("staff_hris_self", "pass1234")

        blocked_response = self.client.get("/hris/payroll", follow_redirects=False)
        self.assertEqual(blocked_response.status_code, 302)
        self.assertIn("/hris/leave", blocked_response.headers["Location"])

        leave_response = self.client.post(
            "/hris/leave/add",
            data={
                "employee_id": str(other_employee_id),
                "leave_type": "sick",
                "start_date": "2026-04-10",
                "end_date": "2026-04-10",
                "status": "pending",
                "reason": "Tes pembatasan",
                "note": "Tidak boleh untuk employee lain",
            },
            follow_redirects=False,
        )
        self.assertEqual(leave_response.status_code, 302)

        helpdesk_response = self.client.post(
            "/hris/helpdesk/add",
            data={
                "employee_id": str(own_employee_id),
                "ticket_title": "Scanner error",
                "category": "system",
                "priority": "medium",
                "status": "open",
                "channel": "WA",
                "assigned_to": "IT Support",
                "note": "Perlu dicek",
            },
            follow_redirects=False,
        )
        self.assertEqual(helpdesk_response.status_code, 302)

        biometric_response = self.client.post(
            "/hris/biometric/add",
            data={
                "employee_id": str(own_employee_id),
                "location_label": "Gudang Mataram - Self Service",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "10",
                "punch_time": "2026-09-01T08:10",
                "punch_type": "check_in",
                "sync_status": "synced",
                "note": "Check in staff",
            },
            follow_redirects=False,
        )
        self.assertEqual(biometric_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            leave_count = db.execute("SELECT COUNT(*) FROM leave_requests").fetchone()[0]
            helpdesk = db.execute(
                "SELECT employee_id, ticket_title FROM helpdesk_tickets ORDER BY id DESC LIMIT 1"
            ).fetchone()
            biometric = db.execute(
                "SELECT employee_id, location_label FROM biometric_logs ORDER BY id DESC LIMIT 1"
            ).fetchone()

        self.assertEqual(leave_count, 0)
        self.assertIsNotNone(helpdesk)
        self.assertEqual(helpdesk["employee_id"], own_employee_id)
        self.assertEqual(helpdesk["ticket_title"], "Scanner error")
        self.assertIsNotNone(biometric)
        self.assertEqual(biometric["employee_id"], own_employee_id)
        self.assertEqual(biometric["location_label"], "Gudang Mataram - Self Service")

    def test_staff_only_can_view_schedule_and_cannot_customize(self):
        self.create_user("staff_schedule_only", "pass1234", "staff", warehouse_id=1)
        employee_id = self.create_employee_record(
            employee_code="EMP-STF-SCH",
            full_name="Staff Jadwal",
            warehouse_id=1,
            position="Warehouse Staff",
        )

        self.login("staff_schedule_only", "pass1234")

        response = self.client.post(
            "/schedule/entry/save",
            data={
                "employee_id": str(employee_id),
                "shift_code": "P",
                "entry_start_date": "2026-03-30",
                "entry_end_date": "2026-03-30",
                "note": "Tidak boleh lolos",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/schedule/", response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            entry_count = db.execute(
                """
                SELECT COUNT(*)
                FROM schedule_entries
                WHERE employee_id=? AND schedule_date='2026-03-30'
                """,
                (employee_id,),
            ).fetchone()[0]

        self.assertEqual(entry_count, 0)

    def test_staff_cannot_access_admin_surfaces_and_adjust_creates_approval(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="STF")
        variant_id = variants_rows[0]["id"]
        self.logout()

        self.create_user("staff_ops", "pass1234", "staff", warehouse_id=1)
        self.login("staff_ops", "pass1234")

        for path in ["/admin/", "/admin/warehouses", "/audit/", "/approvals/"]:
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)

        adjust_response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "-1",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(adjust_response.status_code, 200)
        self.assertEqual(adjust_response.get_json()["status"], "pending")

        with self.app.app_context():
            db = get_db()
            approval = db.execute(
                """
                SELECT status, type
                FROM approvals
                WHERE product_id=? AND variant_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (product_id, variant_id),
            ).fetchone()

        self.assertIsNotNone(approval)
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["type"], "ADJUST")

    def test_request_check_new_ignores_restored_pending_requests(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="REQ")
        variant_id = variants_rows[0]["id"]
        self.logout()

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO requests(
                    product_id,
                    variant_id,
                    from_warehouse,
                    to_warehouse,
                    qty,
                    status
                )
                VALUES (?,?,?,?,?,?)
                """,
                (product_id, variant_id, 1, 2, 1, "pending"),
            )
            db.commit()

        self.create_user("leader_notify", "pass1234", "leader", warehouse_id=1)
        self.login("leader_notify", "pass1234")

        first_check = self.client.get("/request/check_new?last_id=0")
        self.assertEqual(first_check.status_code, 200)
        self.assertEqual(first_check.get_json()["status"], "no")

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO requests(
                    product_id,
                    variant_id,
                    from_warehouse,
                    to_warehouse,
                    qty,
                    status
                )
                VALUES (?,?,?,?,?,?)
                """,
                (product_id, variant_id, 1, 2, 2, "pending"),
            )
            db.commit()

        second_check = self.client.get("/request/check_new?last_id=0")
        self.assertEqual(second_check.status_code, 200)
        self.assertEqual(second_check.get_json()["status"], "yes")

    def test_restore_repair_creates_batches_for_legacy_stock(self):
        self.create_user("restore_super", "admin123", "super_admin")
        self.login("restore_super", "admin123")
        _, product_id, variants_rows = self.create_product(variants="LEGACY")
        variant_id = variants_rows[0]["id"]

        with self.app.app_context():
            db = get_db()
            db.execute(
                "DELETE FROM stock_batches WHERE product_id=? AND variant_id=? AND warehouse_id=?",
                (product_id, variant_id, 1),
            )
            db.execute(
                """
                UPDATE stock
                SET qty=?
                WHERE product_id=? AND variant_id=? AND warehouse_id=?
                """,
                (7, product_id, variant_id, 1),
            )
            db.commit()

        repair_restored_data(self.app)

        with self.app.app_context():
            db = get_db()
            batch = db.execute(
                """
                SELECT qty, remaining_qty
                FROM stock_batches
                WHERE product_id=? AND variant_id=? AND warehouse_id=?
                """,
                (product_id, variant_id, 1),
            ).fetchone()

        self.assertIsNotNone(batch)
        self.assertEqual(batch["qty"], 7)
        self.assertEqual(batch["remaining_qty"], 7)

        adjust_response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "-2",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(adjust_response.status_code, 200)
        self.assertEqual(adjust_response.get_json()["status"], "success")

    def test_restore_repair_promotes_rio_to_super_admin(self):
        self.create_user("Rio", "admin123", "admin", warehouse_id=1)

        repair_restored_data(self.app)

        with self.app.app_context():
            db = get_db()
            rio = db.execute(
                "SELECT role, warehouse_id FROM users WHERE username=?",
                ("Rio",),
            ).fetchone()

        self.assertIsNotNone(rio)
        self.assertEqual(rio["role"], "super_admin")
        self.assertIsNone(rio["warehouse_id"])

    def test_stock_page_renders_rupiah_prefix_and_export(self):
        self.login()
        response, _, _ = self.create_product(variants="PRC")
        self.assertEqual(response.status_code, 302)

        page = self.client.get("/stock/")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("money-input", html)
        self.assertIn(">Rp<", html)

        export = self.client.get("/stock/export")
        self.assertEqual(export.status_code, 200)
        self.assertIn("text/csv", export.content_type)
        self.assertIn("Harga Retail", export.get_data(as_text=True))

    def test_stock_page_supports_clickable_header_sorting(self):
        self.login()
        response, _, _ = self.create_product(sku="SORT-ZZZ", qty=1, variants="VZ")
        self.assertEqual(response.status_code, 302)
        response, _, _ = self.create_product(sku="SORT-AAA", qty=1, variants="VA")
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            older_product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                ("SORT-ZZZ",),
            ).fetchone()["id"]
            newer_product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                ("SORT-AAA",),
            ).fetchone()["id"]
            db.execute(
                "UPDATE stock_batches SET created_at=? WHERE product_id=?",
                ("2024-01-01 00:00:00", older_product),
            )
            db.execute(
                "UPDATE stock_batches SET created_at=? WHERE product_id=?",
                ("2026-01-01 00:00:00", newer_product),
            )
            db.commit()

        stock_sku_asc = self.client.get("/stock/?sort=sku_asc")
        self.assertEqual(stock_sku_asc.status_code, 200)
        html_sku_asc = stock_sku_asc.get_data(as_text=True)
        self.assertIn("sort=sku_desc", html_sku_asc)
        self.assertLess(html_sku_asc.find('value="SORT-AAA"'), html_sku_asc.find('value="SORT-ZZZ"'))

        stock_sku_desc = self.client.get("/stock/?sort=sku_desc")
        self.assertEqual(stock_sku_desc.status_code, 200)
        html_sku_desc = stock_sku_desc.get_data(as_text=True)
        self.assertLess(html_sku_desc.find('value="SORT-ZZZ"'), html_sku_desc.find('value="SORT-AAA"'))

        stock_age_desc = self.client.get("/stock/?sort=age_desc")
        self.assertEqual(stock_age_desc.status_code, 200)
        html_age_desc = stock_age_desc.get_data(as_text=True)
        self.assertIn("sort=age_asc", html_age_desc)
        self.assertLess(html_age_desc.find('value="SORT-ZZZ"'), html_age_desc.find('value="SORT-AAA"'))

        stock_age_asc = self.client.get("/stock/?sort=age_asc")
        self.assertEqual(stock_age_asc.status_code, 200)
        html_age_asc = stock_age_asc.get_data(as_text=True)
        self.assertLess(html_age_asc.find('value="SORT-AAA"'), html_age_asc.find('value="SORT-ZZZ"'))

    def test_owner_can_access_admin_page(self):
        self.create_user("owner_user", "pass1234", "owner")
        self.login("owner_user", "pass1234")
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_owner_admin_page_focuses_on_access_and_roles(self):
        self.create_user("owner_access", "pass1234", "owner")
        self.login("owner_access", "pass1234")
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Admin Access Center", html)
        self.assertIn("Role Guide", html)
        self.assertIn("Tambah User", html)
        self.assertNotIn("Tambah Gudang", html)
        self.assertNotIn("Daftar Gudang", html)

    def test_owner_can_access_admin_warehouse_page(self):
        self.create_user("owner_wh", "pass1234", "owner")
        self.login("owner_wh", "pass1234")
        response = self.client.get("/admin/warehouses")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Warehouse System Control", html)
        self.assertIn("Tambah Gudang", html)
        self.assertIn("Daftar Gudang", html)
        self.assertNotIn("Tambah User", html)

    def test_admin_cannot_access_admin_page(self):
        self.login()
        response = self.client.get("/admin/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_admin_cannot_access_admin_warehouse_page(self):
        self.login()
        response = self.client.get("/admin/warehouses", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_owner_can_access_audit_page(self):
        self.create_user("owner_audit", "pass1234", "owner")
        self.login("owner_audit", "pass1234")
        response = self.client.get("/audit/")
        self.assertEqual(response.status_code, 200)

    def test_stock_opname_page_supports_selected_warehouses_and_exports(self):
        self.login()
        response = self.client.get("/so/?display_id=1&gudang_id=2")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="display_id"', html)
        self.assertIn('name="gudang_id"', html)
        self.assertIn("/so/export?display_id=1&gudang_id=2", html)
        self.assertIn("Simpan Hasil SO", html)

        export = self.client.get("/so/export?display_id=1&gudang_id=2")
        self.assertEqual(export.status_code, 200)
        self.assertIn("Display System Qty", export.get_data(as_text=True))

    def test_stock_opname_summary_counts_all_filtered_rows_not_just_current_page(self):
        self.login()

        for index in range(21):
            response, _, _ = self.create_product(
                sku=f"SO-SUM-{index:02d}",
                qty=1,
                variants=f"VAR{index}",
                warehouse_id="1",
            )
            self.assertEqual(response.status_code, 302)

        response = self.client.get(
            "/so/?display_id=1&gudang_id=2",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertEqual(len(payload["data"]), 20)
        self.assertEqual(payload["summary"]["items"], 21)
        self.assertEqual(payload["summary"]["display_qty"], 21)
        self.assertEqual(payload["summary"]["gudang_qty"], 0)
        self.assertEqual(payload["total_pages"], 2)

    def test_role_refresh_allows_promoted_user_to_adjust_directly(self):
        self.create_user("Rio", "admin123", "admin", warehouse_id=1)
        self.login("Rio", "admin123")
        _, product_id, variants_rows = self.create_product(variants="RIO")
        variant_id = variants_rows[0]["id"]

        with self.app.app_context():
            db = get_db()
            db.execute(
                "UPDATE users SET role=? WHERE username=?",
                ("super_admin", "Rio"),
            )
            db.commit()

        stock_page = self.client.get("/stock/", follow_redirects=False)
        self.assertEqual(stock_page.status_code, 200)

        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("role"), "super_admin")

        adjust_response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "-2",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(adjust_response.status_code, 200)
        self.assertEqual(adjust_response.get_json()["status"], "success")

        with self.app.app_context():
            db = get_db()
            approvals = db.execute(
                "SELECT COUNT(*) FROM approvals WHERE product_id=?",
                (product_id,),
            ).fetchone()[0]
            stock_after = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product_id, variant_id),
            ).fetchone()

        self.assertEqual(approvals, 0)
        self.assertEqual(stock_after["qty"], 3)

    def test_stock_opname_submit_updates_stock_and_history(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="SO")
        variant_id = variants_rows[0]["id"]

        response = self.client.post(
            "/so/submit",
            json={
                "display_id": 1,
                "gudang_id": 2,
                "items": [
                    {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "display_system": 5,
                        "display_physical": 3,
                        "gudang_system": 0,
                        "gudang_physical": 2,
                    }
                ],
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            db = get_db()
            display_stock = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product_id, variant_id),
            ).fetchone()
            gudang_stock = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=2",
                (product_id, variant_id),
            ).fetchone()
            so_rows = db.execute(
                "SELECT COUNT(*) FROM stock_opname_results WHERE product_id=? AND variant_id=?",
                (product_id, variant_id),
            ).fetchone()[0]
            history_rows = db.execute(
                "SELECT COUNT(*) FROM stock_history WHERE product_id=? AND variant_id=? AND action='STOCK_OPNAME'",
                (product_id, variant_id),
            ).fetchone()[0]

        self.assertEqual(display_stock["qty"], 3)
        self.assertEqual(gudang_stock["qty"], 2)
        self.assertEqual(so_rows, 2)
        self.assertEqual(history_rows, 2)


if __name__ == "__main__":
    unittest.main()
