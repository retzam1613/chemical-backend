import os
import re
import psycopg2
import requests
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from passlib.context import CryptContext

DATABASE_URL = os.getenv("DATABASE_URL")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

# Password Hashing Setup
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    if not hashed_password:
        return False
    # รองรับทั้งแบบ Plaintext เก่าและ Hashed ใหม่
    if not hashed_password.startswith("$2b$"):
        return plain_password == hashed_password
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def get_db():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL missing in environment variables")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn.autocommit = True
    return conn

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        if DATABASE_URL:
            conn = get_db()
            cursor = conn.cursor()
            
            # --- Auto Migrations สำหรับตาราง chemicals ---
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS item_type VARCHAR(20) DEFAULT 'CHEMICAL';")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS type VARCHAR(50);")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS category VARCHAR(100);")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS remark TEXT;")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS order_code VARCHAR(50);")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS created_by_name VARCHAR(100);")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'APPROVED';")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS approved_by VARCHAR(100);")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS first_aid TEXT;")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS spill_action TEXT;")

            # --- Auto Migrations สำหรับตาราง requisitions ---
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS remark TEXT;")
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS order_code VARCHAR(50);")
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS batch_id VARCHAR(50);")
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS approved_by VARCHAR(100);")
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;")
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS assigned_location VARCHAR(100);")

            # --- Auto Migrations สำหรับตาราง users ---
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP;")

            # --- สร้างตารางเสริมระบบ ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_notifications (
                    id SERIAL PRIMARY KEY, user_id INT, role_target VARCHAR(20),
                    message TEXT, is_read BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_issues (
                    id SERIAL PRIMARY KEY, user_id INT, reporter_name VARCHAR(100),
                    issue_text TEXT, is_resolved BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS login_logs (
                    id SERIAL PRIMARY KEY, user_id INT, username VARCHAR(100),
                    full_name VARCHAR(100), role VARCHAR(20), ip_address VARCHAR(50),
                    login_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.close()
            conn.close()
    except Exception as e:
        print("Migration Warning:", e)
    yield

app = FastAPI(title="CIMs Enterprise API", lifespan=lifespan)

# --- CORS Middleware Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def send_line(msg: str):
    if not LINE_TOKEN:
        return
    try:
        requests.post(
            "https://api.line.me/v2/bot/message/broadcast",
            json={"messages": [{"type": "text", "text": msg}]},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"},
            timeout=5
        )
    except Exception as e:
        print("LINE Notify Error:", e)

def add_notif(user_id: Optional[int], role: Optional[str], msg: str):
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO user_notifications (user_id, role_target, message) VALUES (%s, %s, %s);", (user_id, role, msg))
        cursor.close()
    except Exception as e:
        print("Notif Error:", e)
    finally:
        if conn: conn.close()

def gen_code(prefix: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        today = datetime.now().strftime("%Y%m%d")
        pat = f"{prefix}-{today}-%"
        tbl = "chemicals" if prefix == "IN" else "requisitions"
        cursor.execute(f"SELECT order_code FROM {tbl} WHERE order_code LIKE %s ORDER BY id DESC LIMIT 1;", (pat,))
        row = cursor.fetchone()
        num = int(row["order_code"].split("-")[-1]) + 1 if row and row.get("order_code") else 1
        return f"{prefix}-{today}-{num:03d}"
    finally:
        cursor.close()
        conn.close()

# --- Pydantic Data Models ---
class UserReg(BaseModel):
    full_name: str
    email: str
    phone: str
    username: str
    password: str
    role: Optional[str] = "requester"

class UserLog(BaseModel):
    username: str
    password: str

class ChemItem(BaseModel):
    item_type: Optional[str] = "CHEMICAL"
    name: str
    brand: Optional[str] = None
    cas_number: Optional[str] = None
    type: Optional[str] = "General Chemical"
    category: Optional[str] = "General"
    capacity_value: float
    capacity_unit: str
    quantity: float
    package_unit: str
    location: Optional[str] = None
    expiry_date: Optional[str] = None
    remark: Optional[str] = None
    created_by_name: Optional[str] = "ไม่ระบุ"
    user_id: Optional[int] = None

class ChemBatch(BaseModel):
    items: List[ChemItem]

class ChemUpd(BaseModel):
    item_type: Optional[str] = "CHEMICAL"
    name: str
    brand: Optional[str] = None
    cas_number: Optional[str] = None
    type: Optional[str] = "General Chemical"
    category: Optional[str] = "General"
    capacity_value: float
    capacity_unit: str
    quantity: float
    package_unit: str
    location: Optional[str] = None
    expiry_date: Optional[str] = None
    remark: Optional[str] = None

class QtyAdj(BaseModel):
    quantity_change: float

class ReqItem(BaseModel):
    chemical_id: int
    requested_quantity: float
    remark: Optional[str] = None

class ReqBasket(BaseModel):
    user_id: int
    requester_name: str
    items: List[ReqItem]

class ActionPayload(BaseModel):
    admin_name: str
    assigned_location: Optional[str] = None
    remark: Optional[str] = None

class IssuePayload(BaseModel):
    user_id: int
    reporter_name: str
    issue_text: str

# --- API Endpoints ---

@app.get("/")
def root():
    return {"status": "CIMs Enterprise API Active", "version": "3.0.0"}

@app.post("/auth/register")
def register(u: UserReg):
    if not re.match(r'^[a-zA-Z0-9_]+$', u.username) or u.username.lower() == 'admin':
        raise HTTPException(400, "Username ไม่ถูกต้อง หรือใช้ตัวอักษรต้องห้าม")
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        hashed_pwd = get_password_hash(u.password)
        cursor.execute(
            "INSERT INTO users (full_name, email, phone, username, password, role) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id, full_name, username, role;",
            (u.full_name, u.email, u.phone, u.username, hashed_pwd, u.role or 'requester')
        )
        new_user = dict(cursor.fetchone())
        return {"message": "Success", "user": new_user}
    except Exception as e:
        raise HTTPException(400, f"Username หรือ Email นี้มีอยู่ในระบบแล้ว ({str(e)})")
    finally:
        cursor.close()
        conn.close()

@app.post("/auth/login")
def login(u: UserLog, req: Request):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, full_name, username, role, password FROM users WHERE username = %s", (u.username,))
        user = cursor.fetchone()
        
        if not user or not verify_password(u.password, user.get("password")):
            raise HTTPException(401, "Username หรือ Password ไม่ถูกต้อง")

        ip = req.client.host if req.client else "Unknown"
        cursor.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s", (user["id"],))
        cursor.execute("INSERT INTO login_logs (user_id, username, full_name, role, ip_address) VALUES (%s, %s, %s, %s, %s)", (user["id"], user["username"], user["full_name"], user["role"], ip))
        
        user_data = dict(user)
        del user_data["password"]
        return {"message": "Success", "user": user_data}
    finally:
        cursor.close()
        conn.close()

@app.get("/dashboard/analytics")
def analytics():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT TO_CHAR(created_at, 'YYYY-MM-DD') as day_key, COALESCE(SUM(quantity), 0) as total FROM chemicals WHERE (status = 'APPROVED' OR status IS NULL) AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day_key ORDER BY day_key ASC;")
        imp = cursor.fetchall()
        cursor.execute("SELECT TO_CHAR(created_at, 'YYYY-MM-DD') as day_key, COALESCE(SUM(requested_quantity), 0) as total FROM requisitions WHERE status = 'APPROVED' AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day_key ORDER BY day_key ASC;")
        exp = cursor.fetchall()
        return {"imports": [dict(r) for r in imp], "exports": [dict(r) for r in exp]}
    finally:
        cursor.close()
        conn.close()

@app.get("/notifications/user/{user_id}")
def get_notifs(user_id: int, role: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name, brand, location, expiry_date, CASE WHEN expiry_date < CURRENT_DATE THEN 'EXPIRED' WHEN expiry_date <= CURRENT_DATE + INTERVAL '1 day' THEN '1_DAY' WHEN expiry_date <= CURRENT_DATE + INTERVAL '3 days' THEN '3_DAYS' WHEN expiry_date <= CURRENT_DATE + INTERVAL '7 days' THEN '7_DAYS' WHEN expiry_date <= CURRENT_DATE + INTERVAL '30 days' THEN '30_DAYS' END as alert_level FROM chemicals WHERE (status = 'APPROVED' OR status IS NULL) AND expiry_date IS NOT NULL AND expiry_date <= CURRENT_DATE + INTERVAL '30 days' ORDER BY expiry_date ASC;")
        exp = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT id, message, is_read, TO_CHAR(created_at, 'DD/MM/YYYY HH24:MI') as time_str FROM user_notifications WHERE (user_id = %s OR role_target = %s) ORDER BY id DESC LIMIT 20;", (user_id, role))
        act = [dict(r) for r in cursor.fetchall()]
        unread = sum(1 for n in act if not n['is_read']) + len(exp)
        return {"expiry_notifs": exp, "activity_notifs": act, "unread_count": unread}
    finally:
        cursor.close()
        conn.close()

@app.post("/notifications/read")
def read_notifs(p: dict):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE user_notifications SET is_read = TRUE WHERE user_id = %s OR role_target = %s;", (p.get("user_id"), p.get("role")))
        return {"status": "ok"}
    finally:
        cursor.close()
        conn.close()

@app.get("/chemicals")
def chemicals():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT *, CASE WHEN expiry_date < CURRENT_DATE THEN 'EXPIRED' WHEN expiry_date <= CURRENT_DATE + INTERVAL '3 days' THEN '3_DAYS' WHEN expiry_date <= CURRENT_DATE + INTERVAL '7 days' THEN '7_DAYS' WHEN expiry_date <= CURRENT_DATE + INTERVAL '30 days' THEN '30_DAYS' ELSE 'NORMAL' END as expiry_status FROM chemicals WHERE status = 'APPROVED' OR status IS NULL ORDER BY id ASC;")
        items = cursor.fetchall()
        cursor.execute("SELECT COALESCE(SUM(quantity), 0) as total_qty, COUNT(id) as total_count FROM chemicals WHERE status = 'APPROVED' OR status IS NULL;")
        sum_data = cursor.fetchone()
        return {"items": [dict(r) for r in items], "total_quantity": sum_data["total_qty"] if sum_data else 0, "total_items": sum_data["total_count"] if sum_data else 0}
    finally:
        cursor.close()
        conn.close()

@app.post("/chemicals/batch")
def add_batch(b: ChemBatch):
    code = gen_code("IN")
    conn = get_db()
    cursor = conn.cursor()
    try:
        for item in b.items:
            exp = item.expiry_date.strip() if item.expiry_date and item.expiry_date.strip() else None
            cursor.execute(
                """INSERT INTO chemicals 
                   (item_type, name, brand, cas_number, type, category, capacity_value, capacity_unit, quantity, unit, package_unit, location, expiry_date, remark, status, created_by_name, order_code) 
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING_ADD',%s,%s)""",
                (item.item_type or 'CHEMICAL', item.name.strip(), item.brand, item.cas_number, item.type, item.category, item.capacity_value, item.capacity_unit, item.quantity, f"{item.capacity_value} {item.capacity_unit}/{item.package_unit}", item.package_unit, item.location, exp, item.remark, item.created_by_name, code)
            )
        msg = f"📥 [คำขอนำเข้าใหม่] Order #{code} โดยคุณ {b.items[0].created_by_name}"
        add_notif(None, "storekeeper", msg)
        send_line(msg)
        return {"message": "Success", "order_code": code}
    finally:
        cursor.close()
        conn.close()

@app.put("/chemicals/{cid}")
def upd_chem(cid: int, c: ChemUpd):
    conn = get_db()
    cursor = conn.cursor()
    try:
        exp = c.expiry_date.strip() if c.expiry_date and c.expiry_date.strip() else None
        cursor.execute(
            """UPDATE chemicals 
               SET item_type=%s, name=%s, brand=%s, cas_number=%s, type=%s, category=%s, capacity_value=%s, capacity_unit=%s, quantity=%s, unit=%s, package_unit=%s, location=%s, expiry_date=%s, remark=%s 
               WHERE id=%s""",
            (c.item_type or 'CHEMICAL', c.name.strip(), c.brand, c.cas_number, c.type, c.category, c.capacity_value, c.capacity_unit, c.quantity, f"{c.capacity_value} {c.capacity_unit}/{c.package_unit}", c.package_unit, c.location, exp, c.remark, cid)
        )
        return {"message": "Updated"}
    finally:
        cursor.close()
        conn.close()

@app.patch("/chemicals/{cid}/adjust")
def adjust_qty(cid: int, payload: QtyAdj):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE chemicals SET quantity = GREATEST(0, quantity + %s) WHERE id = %s RETURNING quantity;", (payload.quantity_change, cid))
        res = cursor.fetchone()
        return {"message": "Success", "new_quantity": res["quantity"] if res else 0}
    finally:
        cursor.close()
        conn.close()

@app.delete("/chemicals/{cid}")
def del_chem(cid: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM chemicals WHERE id = %s", (cid,))
        return {"message": "Deleted"}
    finally:
        cursor.close()
        conn.close()

@app.get("/all-approvals")
def get_all_approvals():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT 'IMPORT' as type, id, COALESCE(order_code, '#' || id) as order_code, 
                   COALESCE(created_by_name, 'ไม่ระบุ') as requester_name, name as chemical_name, brand, cas_number, category,
                   quantity as qty, package_unit as unit, COALESCE(status, 'PENDING_ADD') as status, remark, location,
                   TO_CHAR(COALESCE(created_at, CURRENT_TIMESTAMP), 'DD/MM/YYYY HH24:MI') as created_at_str
            FROM chemicals WHERE status = 'PENDING_ADD'
            UNION ALL
            SELECT 'EXPORT' as type, r.id, COALESCE(r.order_code, '#' || r.id) as order_code, 
                   COALESCE(u.full_name, 'ไม่ระบุ') as requester_name, c.name as chemical_name, c.brand, c.cas_number, c.category,
                   r.requested_quantity as qty, c.package_unit as unit, COALESCE(r.status, 'PENDING') as status, r.remark, c.location,
                   TO_CHAR(COALESCE(r.created_at, CURRENT_TIMESTAMP), 'DD/MM/YYYY HH24:MI') as created_at_str
            FROM requisitions r 
            LEFT JOIN users u ON r.user_id = u.id 
            JOIN chemicals c ON r.chemical_id = c.id 
            WHERE r.status = 'PENDING' OR r.status IS NULL
            ORDER BY id DESC;
        """)
        pending = cursor.fetchall()
        
        cursor.execute("""
            SELECT 'IMPORT' as type, id, COALESCE(order_code, '#' || id) as order_code, 
                   COALESCE(created_by_name, 'ไม่ระบุ') as requester_name, name as chemical_name, brand, cas_number, category,
                   quantity as qty, package_unit as unit, COALESCE(status, 'APPROVED') as status, 
                   COALESCE(approved_by, 'Admin') as approved_by, remark, location,
                   TO_CHAR(COALESCE(approved_at, created_at), 'DD/MM/YYYY HH24:MI') as approved_at_str
            FROM chemicals WHERE status IN ('APPROVED', 'REJECTED_ADD')
            UNION ALL
            SELECT 'EXPORT' as type, r.id, COALESCE(r.order_code, '#' || r.id) as order_code, 
                   COALESCE(u.full_name, 'ไม่ระบุ') as requester_name, c.name as chemical_name, c.brand, c.cas_number, c.category,
                   r.requested_quantity as qty, c.package_unit as unit, r.status, 
                   COALESCE(r.approved_by, 'Admin') as approved_by, r.remark, COALESCE(r.assigned_location, c.location) as location,
                   TO_CHAR(COALESCE(r.approved_at, r.created_at), 'DD/MM/YYYY HH24:MI') as approved_at_str
            FROM requisitions r 
            LEFT JOIN users u ON r.user_id = u.id 
            JOIN chemicals c ON r.chemical_id = c.id 
            WHERE r.status IN ('APPROVED', 'REJECTED')
            ORDER BY id DESC LIMIT 500;
        """)
        history = cursor.fetchall()
        return {"pending": [dict(r) for r in pending], "history": [dict(r) for r in history]}
    finally:
        cursor.close()
        conn.close()

@app.post("/chemicals/{cid}/approve-add")
def approve_add(cid: int, a: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name, order_code FROM chemicals WHERE id = %s", (cid,))
        chem = cursor.fetchone()
        
        loc = a.assigned_location or 'Shelf A1L'
        cursor.execute(
            "UPDATE chemicals SET status = 'APPROVED', location = %s, approved_by = %s, approved_at = CURRENT_TIMESTAMP, remark = COALESCE(%s, remark) WHERE id = %s",
            (loc, a.admin_name, a.remark, cid)
        )
        
        msg = f"✅ [อนุมัตินำเข้า] {chem['name'] if chem else ''} (#{chem['order_code'] if chem else cid}) จัดเก็บที่: {loc}"
        add_notif(None, "requester", msg)
        send_line(msg)
        return {"message": "Approved"}
    finally:
        cursor.close()
        conn.close()

@app.post("/chemicals/{cid}/reject-add")
def reject_add(cid: int, a: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name, order_code FROM chemicals WHERE id = %s", (cid,))
        chem = cursor.fetchone()
        
        cursor.execute(
            "UPDATE chemicals SET status = 'REJECTED_ADD', approved_by = %s, approved_at = CURRENT_TIMESTAMP, remark = COALESCE(%s, remark) WHERE id = %s",
            (a.admin_name, a.remark, cid)
        )
        
        msg = f"❌ [ปฏิเสธนำเข้า] {chem['name'] if chem else ''} (#{chem['order_code'] if chem else cid})"
        add_notif(None, "requester", msg)
        send_line(msg)
        return {"message": "Rejected"}
    finally:
        cursor.close()
        conn.close()

@app.post("/requisitions/basket")
def req_basket(b: ReqBasket):
    code = gen_code("OUT")
    conn = get_db()
    cursor = conn.cursor()
    try:
        for item in b.items:
            cursor.execute("SELECT quantity, name FROM chemicals WHERE id = %s", (item.chemical_id,))
            c = cursor.fetchone()
            if not c or float(c["quantity"]) < item.requested_quantity:
                raise HTTPException(400, "Insufficient stock")
            cursor.execute(
                "INSERT INTO requisitions (user_id, chemical_id, requested_quantity, remark, status, order_code, batch_id) VALUES (%s,%s,%s,%s,'PENDING',%s,%s)",
                (b.user_id, item.chemical_id, item.requested_quantity, item.remark, code, code)
            )
        
        msg = f"📤 [คำขอเบิกใหม่] Order #{code} โดยคุณ {b.requester_name}"
        add_notif(None, "storekeeper", msg)
        send_line(msg)
        return {"message": "Success", "order_code": code}
    finally:
        cursor.close()
        conn.close()

@app.post("/requisitions/{rid}/approve")
def approve_req(rid: int, a: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id, chemical_id, requested_quantity, status, order_code FROM requisitions WHERE id = %s", (rid,))
        req = cursor.fetchone()
        
        if not req or req["status"] != "PENDING":
            raise HTTPException(400, "Invalid order or already processed")
            
        cursor.execute("SELECT name, quantity, location FROM chemicals WHERE id = %s", (req["chemical_id"],))
        chem = cursor.fetchone()
        
        if float(chem["quantity"]) < float(req["requested_quantity"]):
            raise HTTPException(400, "Stock too low for requested quantity")
            
        loc = a.assigned_location or chem["location"] or 'Shelf A1L'
        cursor.execute("UPDATE chemicals SET quantity = quantity - %s WHERE id = %s", (req["requested_quantity"], req["chemical_id"]))
        cursor.execute(
            "UPDATE requisitions SET status = 'APPROVED', approved_by = %s, approved_at = CURRENT_TIMESTAMP, assigned_location = %s, remark = COALESCE(%s, remark) WHERE id = %s",
            (a.admin_name, loc, a.remark, rid)
        )
        
        msg = f"✅ [อนุมัติการเบิก] {chem['name'] if chem else ''} (#{req['order_code'] or rid})"
        add_notif(req["user_id"], None, msg)
        send_line(msg)
        return {"message": "Approved"}
    finally:
        cursor.close()
        conn.close()

@app.post("/requisitions/{rid}/reject")
def reject_req(rid: int, a: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id, order_code FROM requisitions WHERE id = %s", (rid,))
        req = cursor.fetchone()
        
        cursor.execute(
            "UPDATE requisitions SET status = 'REJECTED', approved_by = %s, approved_at = CURRENT_TIMESTAMP, remark = COALESCE(%s, remark) WHERE id = %s",
            (a.admin_name, a.remark, rid)
        )
        
        msg = f"❌ [ปฏิเสธการเบิก] Order (#{req['order_code'] if req else rid})"
        add_notif(req["user_id"] if req else None, None, msg)
        send_line(msg)
        return {"message": "Rejected"}
    finally:
        cursor.close()
        conn.close()

@app.post("/issues/report")
def report_issue(p: IssuePayload):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO system_issues (user_id, reporter_name, issue_text) VALUES (%s, %s, %s);", (p.user_id, p.reporter_name, p.issue_text))
        
        msg = f"⚠️ [แจ้งปัญหาใหม่] โดยคุณ {p.reporter_name}: {p.issue_text}"
        add_notif(None, "storekeeper", msg)
        return {"message": "Success"}
    finally:
        cursor.close()
        conn.close()

@app.get("/issues/all")
def get_all_issues():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, user_id, reporter_name, issue_text, is_resolved, TO_CHAR(created_at, 'DD/MM/YYYY HH24:MI:SS') as created_at_str FROM system_issues ORDER BY id DESC LIMIT 200;")
        issues = cursor.fetchall()
        return {"issues": [dict(r) for r in issues]}
    finally:
        cursor.close()
        conn.close()

# --- STOREKEEPER SPECIAL LOGS & USERS ENDPOINTS ---

@app.get("/logs/login")
def get_login_logs():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, full_name, username, role, ip_address, TO_CHAR(login_at, 'DD/MM/YYYY HH24:MI:SS') as time_str FROM login_logs ORDER BY id DESC LIMIT 500;")
        logs = cursor.fetchall()
        return {"logs": [dict(r) for r in logs]}
    finally:
        cursor.close()
        conn.close()

@app.get("/logs/task-duration")
def get_task_duration_logs():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT 'IMPORT' as type, id, COALESCE(order_code, '#' || id) as order_code, COALESCE(created_by_name, 'ไม่ระบุ') as requester_name,
                   name as chemical_name, brand, quantity as qty, package_unit as unit, COALESCE(status, 'APPROVED') as status,
                   COALESCE(approved_by, 'Admin') as approved_by, remark,
                   TO_CHAR(created_at, 'DD/MM/YYYY HH24:MI:SS') as created_at_str,
                   TO_CHAR(approved_at, 'DD/MM/YYYY HH24:MI:SS') as approved_at_str,
                   EXTRACT(EPOCH FROM (approved_at - created_at))/60 as duration_minutes
            FROM chemicals WHERE approved_at IS NOT NULL
            UNION ALL
            SELECT 'EXPORT' as type, r.id, COALESCE(r.order_code, '#' || r.id) as order_code, COALESCE(u.full_name, 'ไม่ระบุ') as requester_name,
                   c.name as chemical_name, c.brand, r.requested_quantity as qty, c.package_unit as unit, r.status,
                   COALESCE(r.approved_by, 'Admin') as approved_by, r.remark,
                   TO_CHAR(r.created_at, 'DD/MM/YYYY HH24:MI:SS') as created_at_str,
                   TO_CHAR(r.approved_at, 'DD/MM/YYYY HH24:MI:SS') as approved_at_str,
                   EXTRACT(EPOCH FROM (r.approved_at - r.created_at))/60 as duration_minutes
            FROM requisitions r 
            LEFT JOIN users u ON r.user_id = u.id 
            JOIN chemicals c ON r.chemical_id = c.id 
            WHERE r.approved_at IS NOT NULL
            ORDER BY approved_at_str DESC LIMIT 500;
        """)
        logs = cursor.fetchall()
        return {"logs": [dict(r) for r in logs]}
    finally:
        cursor.close()
        conn.close()

@app.get("/users/status")
def get_users_status():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, full_name, username, role, TO_CHAR(last_login, 'DD/MM/YYYY HH24:MI:SS') as last_online_str FROM users ORDER BY last_login DESC NULLS LAST;")
        users = cursor.fetchall()
        return {"users": [dict(r) for r in users]}
    finally:
        cursor.close()
        conn.close()
