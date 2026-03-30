import os
import unittest
import json
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

        init_db_module.DB_PATH = self.db_path
        Config.DATABASE = self.db_path
        Config.SESSION_COOKIE_SECURE = False

        self.app = create_app()
        self.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = self.app.test_client()

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            db_file = self.db_path + suffix
            if os.path.exists(db_file):
                os.remove(db_file)

    def login(self, username="admin", password="admin123"):
        return self.client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def logout(self):
        return self.client.get("/logout", follow_redirects=False)

    def create_user(
        self,
        username,
        password,
        role,
        warehouse_id=None,
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
                    email,
                    phone,
                    notify_email,
                    notify_whatsapp
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    username,
                    generate_password_hash(password),
                    role,
                    warehouse_id,
                    email,
                    phone,
                    notify_email,
                    notify_whatsapp,
                ),
            )
            db.commit()

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

        admin_page = self.client.get("/admin/", follow_redirects=False)
        self.assertEqual(admin_page.status_code, 302)

    def test_hris_attendance_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/attendance")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Attendance", html)
        self.assertIn("Log Kehadiran", html)
        self.assertIn("Tambah Attendance", html)

    def test_hris_leave_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/leave")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Leave", html)
        self.assertIn("Leave Tracker", html)
        self.assertIn("Tambah Leave", html)

    def test_hris_payroll_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/payroll")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Payroll", html)
        self.assertIn("Payroll Register", html)
        self.assertIn("Tambah Payroll", html)

    def test_hris_recruitment_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/recruitment")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Recruitment", html)
        self.assertIn("Hiring Pipeline", html)
        self.assertIn("Tambah Kandidat", html)

    def test_hris_onboarding_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/onboarding")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Onboarding", html)
        self.assertIn("Onboarding Tracker", html)
        self.assertIn("Tambah Onboarding", html)

    def test_hris_offboarding_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/offboarding")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Offboarding", html)
        self.assertIn("Offboarding Tracker", html)
        self.assertIn("Tambah Offboarding", html)

    def test_hris_performance_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/pms")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Performance", html)
        self.assertIn("Performance Review", html)
        self.assertIn("Tambah Review", html)

    def test_hris_helpdesk_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/helpdesk")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Helpdesk", html)
        self.assertIn("Ticket Helpdesk", html)
        self.assertIn("Tambah Ticket", html)

    def test_hris_asset_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/asset")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Asset", html)
        self.assertIn("Asset Register", html)
        self.assertIn("Tambah Asset", html)

    def test_hris_project_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/project")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Project", html)
        self.assertIn("Project Register", html)
        self.assertIn("Tambah Project", html)

    def test_hris_report_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/report")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Report", html)
        self.assertIn("HR Analytics Report", html)
        self.assertIn("Workforce Snapshot", html)

    def test_hris_biometric_route_renders_operational_view(self):
        self.login()
        response = self.client.get("/hris/biometric")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Biometric", html)
        self.assertIn("Biometric Sync Log", html)
        self.assertIn("Tambah Log", html)

    def test_admin_can_manage_employee_records_in_hris(self):
        self.login()

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
        self.assertEqual(employee["warehouse_id"], 1)
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
        self.assertEqual(employee_after["warehouse_id"], 1)
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
        self.login()

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
        self.assertEqual(employee["warehouse_id"], 1)

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
        self.assertEqual(attendance["warehouse_id"], 1)
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
        self.login()

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
        self.assertEqual(employee["warehouse_id"], 1)

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
        self.assertEqual(leave_request["warehouse_id"], 1)
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
        self.login()

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
        self.assertEqual(employee["warehouse_id"], 1)

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
        self.assertEqual(payroll["warehouse_id"], 1)
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
        self.login()

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
        self.assertEqual(candidate["warehouse_id"], 1)
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
        self.assertEqual(candidate_after["warehouse_id"], 1)
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
        self.login()

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
        self.assertEqual(employee["warehouse_id"], 1)

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
        self.assertEqual(onboarding["warehouse_id"], 1)
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
        self.login()

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
        self.assertEqual(employee["warehouse_id"], 1)

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
        self.assertEqual(offboarding["warehouse_id"], 1)
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
        self.login()

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
        self.assertEqual(employee["warehouse_id"], 1)

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
        self.assertEqual(review["warehouse_id"], 1)
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
        self.login()

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
        self.assertEqual(employee["warehouse_id"], 1)

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
        self.assertEqual(ticket["warehouse_id"], 1)
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
        self.login()

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
        self.assertEqual(employee["warehouse_id"], 1)

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
        self.assertEqual(asset["warehouse_id"], 1)
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
        self.login()

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
        self.assertEqual(employee["warehouse_id"], 1)

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
        self.assertEqual(project["warehouse_id"], 1)
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
        self.login()

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
        self.assertEqual(employee["warehouse_id"], 1)

        create_response = self.client.post(
            "/hris/biometric/add",
            data={
                "employee_id": str(employee["id"]),
                "device_name": "ZKTeco F18",
                "device_user_id": "BIO-001",
                "punch_time": "2026-09-01T08:05",
                "punch_type": "check_in",
                "sync_status": "synced",
                "note": "Sinkron pagi",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric = db.execute(
                """
                SELECT id, employee_id, warehouse_id, device_name, device_user_id, punch_time,
                       punch_type, sync_status, note, handled_by
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
        self.assertEqual(biometric["warehouse_id"], 1)
        self.assertEqual(biometric["device_name"], "ZKTeco F18")
        self.assertEqual(biometric["device_user_id"], "BIO-001")
        self.assertEqual(biometric["punch_type"], "check_in")
        self.assertEqual(biometric["sync_status"], "synced")
        self.assertEqual(biometric["note"], "Sinkron pagi")
        self.assertIsNotNone(biometric["handled_by"])
        self.assertIsNotNone(attendance)
        self.assertEqual(attendance["attendance_date"], "2026-09-01")
        self.assertEqual(attendance["check_in"], "08:05")
        self.assertIsNone(attendance["check_out"])
        self.assertEqual(attendance["status"], "present")
        self.assertEqual(attendance["note"], "Synced from biometric")

        update_response = self.client.post(
            f"/hris/biometric/update/{biometric['id']}",
            data={
                "employee_id": str(employee["id"]),
                "device_name": "ZKTeco F18 Rev2",
                "device_user_id": "BIO-001",
                "punch_time": "2026-09-01T08:40",
                "punch_type": "check_in",
                "sync_status": "manual",
                "note": "Disesuaikan setelah audit punch",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric_after = db.execute(
                """
                SELECT device_name, punch_time, sync_status, note, handled_by
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

        self.assertEqual(biometric_after["device_name"], "ZKTeco F18 Rev2")
        self.assertEqual(biometric_after["sync_status"], "manual")
        self.assertEqual(biometric_after["note"], "Disesuaikan setelah audit punch")
        self.assertIsNotNone(biometric_after["handled_by"])
        self.assertEqual(attendance_after["check_in"], "08:40")
        self.assertEqual(attendance_after["status"], "late")
        self.assertEqual(attendance_after["note"], "Synced from biometric")

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
        self.login()
        response, product_id, variants_rows = self.create_product(qty=10, variants="41,42")
        self.assertEqual(response.status_code, 302)

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
                SELECT variant_id, qty, status
                FROM requests
                WHERE product_id=?
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()

        self.assertEqual(len(request_rows), 2)
        self.assertEqual(request_rows[0]["qty"], 2)
        self.assertEqual(request_rows[0]["status"], "pending")
        self.assertEqual(request_rows[1]["qty"], 3)
        self.assertEqual(request_rows[1]["status"], "pending")

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
        self.create_user("leader_request", "pass1234", "leader", warehouse_id=1)
        self.login()
        _, product_id, variants_rows = self.create_product(variants="XL")
        variant_id = variants_rows[0]["id"]

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

        self.assertEqual(request_row["status"], "pending")

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
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product_id, variant_id),
            ).fetchone()
            stock_to = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=2",
                (product_id, variant_id),
            ).fetchone()

        self.assertEqual(request_after["status"], "approved")
        self.assertEqual(stock_from["qty"], 4)
        self.assertEqual(stock_to["qty"], 1)

    def test_admin_cannot_approve_request(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="APR")
        variant_id = variants_rows[0]["id"]

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
            self.create_user(username, "pass1234", role, warehouse_id=1)
            self.login(username, "pass1234")

            for path, marker in [
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

            hris_response = self.client.get("/hris/employee")
            self.assertEqual(hris_response.status_code, 200)
            hris_html = hris_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse_id" required disabled', hris_html)
            else:
                self.assertIn("View Only", hris_html)
                self.assertNotIn("Tambah Karyawan", hris_html)

            attendance_response = self.client.get("/hris/attendance")
            self.assertEqual(attendance_response.status_code, 200)
            attendance_html = attendance_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse" disabled', attendance_html)
            else:
                self.assertIn("View Only", attendance_html)
                self.assertNotIn("Tambah Attendance", attendance_html)

            leave_response = self.client.get("/hris/leave")
            self.assertEqual(leave_response.status_code, 200)
            leave_html = leave_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse" disabled', leave_html)
            else:
                self.assertIn("View Only", leave_html)
                self.assertNotIn("Tambah Leave", leave_html)

            payroll_response = self.client.get("/hris/payroll")
            self.assertEqual(payroll_response.status_code, 200)
            payroll_html = payroll_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse" disabled', payroll_html)
            else:
                self.assertIn("View Only", payroll_html)
                self.assertNotIn("Tambah Payroll", payroll_html)

            recruitment_response = self.client.get("/hris/recruitment")
            self.assertEqual(recruitment_response.status_code, 200)
            recruitment_html = recruitment_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse_id" required disabled', recruitment_html)
            else:
                self.assertIn("View Only", recruitment_html)
                self.assertNotIn("Tambah Kandidat", recruitment_html)

            onboarding_response = self.client.get("/hris/onboarding")
            self.assertEqual(onboarding_response.status_code, 200)
            onboarding_html = onboarding_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse" disabled', onboarding_html)
            else:
                self.assertIn("View Only", onboarding_html)
                self.assertNotIn("Tambah Onboarding", onboarding_html)

            offboarding_response = self.client.get("/hris/offboarding")
            self.assertEqual(offboarding_response.status_code, 200)
            offboarding_html = offboarding_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse" disabled', offboarding_html)
            else:
                self.assertIn("View Only", offboarding_html)
                self.assertNotIn("Tambah Offboarding", offboarding_html)

            performance_response = self.client.get("/hris/pms")
            self.assertEqual(performance_response.status_code, 200)
            performance_html = performance_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse" disabled', performance_html)
            else:
                self.assertIn("View Only", performance_html)
                self.assertNotIn("Tambah Review", performance_html)

            helpdesk_response = self.client.get("/hris/helpdesk")
            self.assertEqual(helpdesk_response.status_code, 200)
            helpdesk_html = helpdesk_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse" disabled', helpdesk_html)
            else:
                self.assertIn("View Only", helpdesk_html)
                self.assertNotIn("Tambah Ticket", helpdesk_html)

            asset_response = self.client.get("/hris/asset")
            self.assertEqual(asset_response.status_code, 200)
            asset_html = asset_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse" disabled', asset_html)
            else:
                self.assertIn("View Only", asset_html)
                self.assertNotIn("Tambah Asset", asset_html)

            project_response = self.client.get("/hris/project")
            self.assertEqual(project_response.status_code, 200)
            project_html = project_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse" disabled', project_html)
            else:
                self.assertIn("View Only", project_html)
                self.assertNotIn("Tambah Project", project_html)

            biometric_response = self.client.get("/hris/biometric")
            self.assertEqual(biometric_response.status_code, 200)
            biometric_html = biometric_response.get_data(as_text=True)
            if role == "leader":
                self.assertIn('name="warehouse" disabled', biometric_html)
            else:
                self.assertIn("View Only", biometric_html)
                self.assertNotIn("Tambah Log", biometric_html)

            report_response = self.client.get("/hris/report")
            self.assertEqual(report_response.status_code, 200)
            report_html = report_response.get_data(as_text=True)
            self.assertIn('name="warehouse" disabled', report_html)

            self.logout()

    def test_staff_cannot_access_admin_surfaces_and_adjust_creates_approval(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="STF")
        variant_id = variants_rows[0]["id"]
        self.logout()

        self.create_user("staff_ops", "pass1234", "staff", warehouse_id=1)
        self.login("staff_ops", "pass1234")

        for path in ["/admin/", "/audit/", "/approvals/"]:
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

    def test_admin_cannot_access_admin_page(self):
        self.login()
        response = self.client.get("/admin/", follow_redirects=False)
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
