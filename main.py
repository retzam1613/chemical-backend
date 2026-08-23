import os
import re
from datetime import datetime, timedelta
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
import requests

DATABASE_URL = os.getenv("DATABASE_URL")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

def get_db():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL is missing")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn.autocommit = True
    return conn

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        if DATABASE_URL:
            conn = get_db()
            cursor = conn.cursor()
            # Migration Tables & Columns
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS remark TEXT;")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS order_code VARCHAR(50);")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS created_by_name VARCHAR(100);")
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS remark TEXT;")
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS order_code VARCHAR(50);")
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS batch_id VARCHAR(50);")
            
            # User Notification System Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_notifications (
                    id SERIAL PRIMARY KEY,
                    user_id INT,
                    role_target VARCHAR(20),
                    message TEXT,
                    is_read BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.close()
            conn.close()
            print("✅ Database Migration & Notification Table Ready")
    except Exception as e:
        print("⚠️ Migration Warning:", e)
    yield

app = FastAPI(title="CIMs API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def send_line_notify(message: str):
    if not LINE_TOKEN:
        return
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"messages": [{"type": "text", "text": message}]}
    try:
        requests.post(url, json=payload, headers=headers, timeout=5)
    except Exception as e:
        print("LINE Error:", e)

def create_notification(user_id: Optional[int], role_target: Optional[str], message: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO user_notifications (user_id, role_target, message) VALUES (%s, %s, %s);",
            (user_id, role_target, message)
        )
        cursor.close()
        conn.close()
    except Exception as e:
        print("Create Notif Error:", e)

def generate_order_code(prefix: str):
    conn = get_db()
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y%m%d")
    search_pattern = f"{prefix}-{today_str}-%"
    
    if prefix == "IN":
        cursor.execute("SELECT order_code FROM chemicals WHERE order_code LIKE %s ORDER BY id DESC LIMIT 1;", (search_pattern,))
    else:
        cursor.execute("SELECT order_code FROM requisitions WHERE order_code LIKE %s ORDER BY id DESC LIMIT 1;", (search_pattern,))
    
    last_row = cursor.fetchone()
    cursor.close()
    conn.close()

    if last_row and last_row.get("order_code"):
        last_code = last_row["order_code"]
        try:
            num = int(last_code.split("-")[-1]) + 1
        except Exception:
            num = 1
    else:
        num = 1
    return f"{prefix}-{today_str}-{num:03d}"

class UserRegister(BaseModel):
    full_name: str
    email: str
    phone: str
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class ChemicalItem(BaseModel):
    name: str
    brand: Optional[str] = None
    cas_number: Optional[str] = None
    capacity_value: float
    capacity_unit: str
    quantity: float
    package_unit: str
    location: Optional[str] = None
    expiry_date: Optional[str] = None
    remark: Optional[str] = None
    created_by_name: Optional[str] = "ไม่ระบุ"
    user_id: Optional[int] = None

class ChemicalBatchCreate(BaseModel):
    items: List[ChemicalItem]

class ChemicalUpdate(BaseModel):
    name: str
    brand: Optional[str] = None
    cas_number: Optional[str] = None
    capacity_value: float
    capacity_unit: str
    quantity: float
    package_unit: str
    location: Optional[str] = None
    expiry_date: Optional[str] = None
    remark: Optional[str] = None

class RequisitionItem(BaseModel):
    chemical_id: int
    requested_quantity: float
    remark: Optional[str] = None

class RequisitionBasket(BaseModel):
    user_id: int
    requester_name: str
    items: List[RequisitionItem]

class RequisitionUpdate(BaseModel):
    requested_quantity: float
    remark: Optional[str] = None

class ActionPayload(BaseModel):
    admin_name: str

@app.get("/")
def read_root():
    return {"status": "CIMs API Active"}

@app.get("/dashboard/metrics")
def get_legacy_dashboard_metrics():
    return {"total_chemicals": 0}

# --- AUTH ENDPOINTS ---
@app.post("/auth/register")
def register_user(u: UserRegister):
    if not re.match(r'^[a-zA-Z0-9]+$', u.username):
        raise HTTPException(status_code=400, detail="User ต้องเป็นภาษาอังกฤษและตัวเลขเท่านั้น")
    if u.username.lower() == 'admin':
        raise HTTPException(status_code=400, detail="ไม่อนุญาตให้ใช้ Username 'admin'")
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (full_name, email, phone, username, password, role)
            VALUES (%s, %s, %s, %s, %s, 'requester')
            RETURNING id, full_name, username, role;
        """, (u.full_name, u.email, u.phone, u.username, u.password))
        user = cursor.fetchone()
        return {"message": "ลงทะเบียนสำเร็จ", "user": dict(user)}
    except psycopg2.IntegrityError:
        raise HTTPException(status_code=400, detail="Username หรือ อีเมล นี้มีผู้ใช้งานแล้ว")
    finally:
        cursor.close()
        conn.close()

@app.post("/auth/login")
def login_user(u: UserLogin):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, full_name, username, role, password FROM users WHERE username = %s", (u.username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not user or user["password"] != u.password:
        raise HTTPException(status_code=401, detail="User หรือ Password ไม่ถูกต้อง")
    
    user_dict = dict(user)
    del user_dict["password"]
    return {"message": "เข้าสู่ระบบสำเร็จ", "user": user_dict}

# --- DASHBOARD & DAILY ANALYTICS (1 MONTH) ---
@app.get("/dashboard/analytics")
def get_dashboard_analytics():
    conn = get_db()
    cursor = conn.cursor()
    
    # 30 Days daily aggregated imports and exports
    cursor.execute("""
        SELECT 
            TO_CHAR(c.created_at, 'YYYY-MM-DD') as day_key,
            COALESCE(SUM(c.quantity), 0) as total_imported_qty
        FROM chemicals c
        WHERE c.status = 'APPROVED' AND c.created_at >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY TO_CHAR(c.created_at, 'YYYY-MM-DD')
        ORDER BY day_key ASC;
    """)
    imports_data = cursor.fetchall()

    cursor.execute("""
        SELECT 
            TO_CHAR(r.created_at, 'YYYY-MM-DD') as day_key,
            COALESCE(SUM(r.requested_quantity), 0) as total_exported_qty
        FROM requisitions r
        WHERE r.status = 'APPROVED' AND r.created_at >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY TO_CHAR(r.created_at, 'YYYY-MM-DD')
        ORDER BY day_key ASC;
    """)
    exports_data = cursor.fetchall()
    
    cursor.close()
    conn.close()

    return {
        "imports": [dict(r) for r in imports_data],
        "exports": [dict(r) for r in exports_data]
    }

# --- NOTIFICATION SYSTEM ---
@app.get("/notifications/user/{user_id}")
def get_user_notifications(user_id: int, role: str):
    conn = get_db()
    cursor = conn.cursor()
    
    # Expiry Notifications
    cursor.execute("""
        SELECT id, name, brand, location, expiry_date,
            CASE 
                WHEN expiry_date < CURRENT_DATE THEN 'EXPIRED'
                WHEN expiry_date <= CURRENT_DATE + INTERVAL '1 day' THEN '1_DAY'
                WHEN expiry_date <= CURRENT_DATE + INTERVAL '3 days' THEN '3_DAYS'
                WHEN expiry_date <= CURRENT_DATE + INTERVAL '7 days' THEN '7_DAYS'
                WHEN expiry_date <= CURRENT_DATE + INTERVAL '30 days' THEN '30_DAYS'
            END as alert_level
        FROM chemicals
        WHERE (status = 'APPROVED' OR status IS NULL)
          AND expiry_date IS NOT NULL
          AND expiry_date <= CURRENT_DATE + INTERVAL '30 days'
        ORDER BY expiry_date ASC;
    """)
    expiry_list = [dict(r) for r in cursor.fetchall()]

    # Custom Status Activity Notifications
    cursor.execute("""
        SELECT id, message, is_read, TO_CHAR(created_at, 'DD/MM/YYYY HH24:MI') as time_str
        FROM user_notifications
        WHERE (user_id = %s OR role_target = %s)
        ORDER BY id DESC LIMIT 20;
    """, (user_id, role))
    user_notifs = [dict(r) for r in cursor.fetchall()]

    cursor.close()
    conn.close()

    unread_count = sum(1 for n in user_notifs if not n['is_read']) + len(expiry_list)

    return {
        "expiry_notifs": expiry_list,
        "activity_notifs": user_notifs,
        "unread_count": unread_count
    }

@app.post("/notifications/read")
def mark_notifications_read(payload: dict):
    user_id = payload.get("user_id")
    role = payload.get("role")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE user_notifications SET is_read = TRUE WHERE user_id = %s OR role_target = %s;",
        (user_id, role)
    )
    cursor.close()
    conn.close()
    return {"status": "success"}

# --- CHEMICALS ENDPOINTS ---
@app.get("/chemicals")
def get_chemicals():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chemicals WHERE status = 'APPROVED' OR status IS NULL ORDER BY id ASC;")
    rows = cursor.fetchall()
    
    # Summary Metrics
    cursor.execute("SELECT COALESCE(SUM(quantity), 0) as total_qty, COUNT(id) as total_count FROM chemicals WHERE status = 'APPROVED' OR status IS NULL;")
    summary = cursor.fetchone()
    
    cursor.close()
    conn.close()
    return {
        "items": [dict(r) for r in rows],
        "total_quantity": summary["total_qty"] if summary else 0,
        "total_items": summary["total_count"] if summary else 0
    }

@app.get("/chemicals/import-history")
def get_import_history():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, brand, cas_number, capacity_value, capacity_unit, quantity, package_unit, unit,
               location, expiry_date, remark, created_by_name, order_code,
               TO_CHAR(created_at, 'DD/MM/YYYY-HH24:MI') as formatted_created_at
        FROM chemicals 
        WHERE status = 'APPROVED'
        ORDER BY id DESC;
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/chemicals/pending")
def get_pending_chemicals():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, brand, cas_number, capacity_value, capacity_unit, quantity, package_unit, unit,
               location, expiry_date, status, remark, created_by_name, order_code,
               TO_CHAR(created_at, 'DD/MM/YYYY-HH24:MI') as formatted_created_at
        FROM chemicals 
        WHERE status = 'PENDING_ADD' OR status = 'REJECTED_ADD' 
        ORDER BY id DESC;
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/chemicals/batch")
def add_chemicals_batch(batch: ChemicalBatchCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        order_code = generate_order_code("IN")
        for item in batch.items:
            exp = item.expiry_date.strip() if item.expiry_date and item.expiry_date.strip() else None
            unit_str = f"{item.capacity_value} {item.capacity_unit}/{item.package_unit}"
            
            cursor.execute("""
                INSERT INTO chemicals 
                (name, brand, cas_number, capacity_value, capacity_unit, quantity, unit, package_unit, location, expiry_date, remark, status, created_by_name, order_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING_ADD', %s, %s)
            """, (item.name.strip(), item.brand, item.cas_number, item.capacity_value, item.capacity_unit, 
                  item.quantity, unit_str, item.package_unit, item.location, exp, item.remark, item.created_by_name, order_code))
        
        # Notify Storekeepers
        msg = f"📥 มีคำขอนำเข้าสารเคมีใหม่ Order #{order_code} โดยคุณ {batch.items[0].created_by_name}"
        create_notification(None, "storekeeper", msg)
        send_line_notify(msg)
        
        return {"message": "ส่งรายการขอเพิ่มสารเคมีเรียบร้อยแล้ว", "order_code": order_code}
    finally:
        cursor.close()
        conn.close()

@app.put("/chemicals/{chem_id}")
def update_chemical(chem_id: int, chem: ChemicalUpdate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        exp = chem.expiry_date.strip() if chem.expiry_date and chem.expiry_date.strip() else None
        unit_str = f"{chem.capacity_value} {chem.capacity_unit}/{chem.package_unit}"
        
        cursor.execute("""
            UPDATE chemicals 
            SET name=%s, brand=%s, cas_number=%s, capacity_value=%s, capacity_unit=%s, 
                quantity=%s, unit=%s, package_unit=%s, location=%s, expiry_date=%s, remark=%s
            WHERE id=%s
        """, (chem.name.strip(), chem.brand, chem.cas_number, chem.capacity_value, chem.capacity_unit, 
              chem.quantity, unit_str, chem.package_unit, chem.location, exp, chem.remark, chem_id))
        return {"message": "อัปเดตข้อมูลสารเคมีเรียบร้อยแล้ว"}
    finally:
        cursor.close()
        conn.close()

@app.delete("/chemicals/{chem_id}")
def delete_chemical(chem_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM chemicals WHERE id = %s", (chem_id,))
        return {"message": "ลบสารเคมีออกจากคลังเรียบร้อยแล้ว"}
    finally:
        cursor.close()
        conn.close()

@app.post("/chemicals/{chem_id}/approve-add")
def approve_chemical_add(chem_id: int, action: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, order_code, created_by_name FROM chemicals WHERE id = %s", (chem_id,))
    chem = cursor.fetchone()
    
    cursor.execute("UPDATE chemicals SET status = 'APPROVED', approved_at = CURRENT_TIMESTAMP WHERE id = %s", (chem_id,))
    cursor.close()
    conn.close()
    
    msg = f"✅ คำขอนำเข้าสารเคมี {chem['name'] if chem else ''} (#{chem['order_code'] if chem else chem_id}) ได้รับการอนุมัติแล้ว"
    create_notification(None, "requester", msg)
    send_line_notify(msg)
    return {"message": "อนุมัตินำเข้าสารเคมีเรียบร้อยแล้ว"}

@app.post("/chemicals/{chem_id}/reject-add")
def reject_chemical_add(chem_id: int, action: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, order_code FROM chemicals WHERE id = %s", (chem_id,))
    chem = cursor.fetchone()
    
    cursor.execute("UPDATE chemicals SET status = 'REJECTED_ADD', approved_at = CURRENT_TIMESTAMP WHERE id = %s", (chem_id,))
    cursor.close()
    conn.close()
    
    msg = f"❌ คำขอนำเข้าสารเคมี {chem['name'] if chem else ''} (#{chem['order_code'] if chem else chem_id}) ถูกปฏิเสธ"
    create_notification(None, "requester", msg)
    send_line_notify(msg)
    return {"message": "ปฏิเสธคำขอนำเข้าสารเคมีแล้ว"}

# --- REQUISITIONS ENDPOINTS ---
@app.post("/requisitions/basket")
def create_requisition_basket(basket: RequisitionBasket):
    conn = get_db()
    cursor = conn.cursor()
    order_code = generate_order_code("OUT")
    try:
        for item in basket.items:
            cursor.execute("SELECT quantity, name FROM chemicals WHERE id = %s", (item.chemical_id,))
            chem = cursor.fetchone()
            if not chem or float(chem["quantity"]) < item.requested_quantity:
                raise HTTPException(status_code=400, detail=f"สารเคมี {chem['name'] if chem else ''} มีสต็อกไม่พอ")
            
            cursor.execute("""
                INSERT INTO requisitions (user_id, chemical_id, requested_quantity, remark, status, order_code, batch_id)
                VALUES (%s, %s, %s, %s, 'PENDING', %s, %s)
            """, (basket.user_id, item.chemical_id, item.requested_quantity, item.remark, order_code, order_code))
            
        msg = f"🛒 มีคำขอเบิกสารเคมีใหม่ Order #{order_code} โดยคุณ {basket.requester_name}"
        create_notification(None, "storekeeper", msg)
        send_line_notify(msg)
        return {"message": "ส่งคำขอเบิกสารเคมีเรียบร้อยแล้ว", "order_code": order_code}
    finally:
        cursor.close()
        conn.close()

@app.get("/requisitions")
def get_requisitions():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, COALESCE(u.full_name, 'ไม่ระบุ') as requester_name, c.name as chemical_name, c.brand,
               r.requested_quantity, c.package_unit as unit, r.status, r.approved_by, r.remark,
               r.order_code, r.batch_id,
               TO_CHAR(r.created_at, 'DD/MM/YYYY-HH24:MI') as formatted_created_at,
               TO_CHAR(r.approved_at, 'DD/MM/YYYY-HH24:MI') as formatted_approved_at
        FROM requisitions r
        LEFT JOIN users u ON r.user_id = u.id
        JOIN chemicals c ON r.chemical_id = c.id
        ORDER BY r.id DESC;
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]

@app.put("/requisitions/{req_id}")
def update_requisition(req_id: int, req: RequisitionUpdate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT status FROM requisitions WHERE id = %s", (req_id,))
        row = cursor.fetchone()
        if not row or row["status"] != "PENDING":
            raise HTTPException(status_code=400, detail="รายการนี้ไม่อยู่ในสถานะ Pending ไม่สามารถแก้ไขได้")

        cursor.execute("""
            UPDATE requisitions 
            SET requested_quantity = %s, remark = %s 
            WHERE id = %s
        """, (req.requested_quantity, req.remark, req_id))
        return {"message": "แก้ไขรายการเบิกเรียบร้อยแล้ว"}
    finally:
        cursor.close()
        conn.close()

@app.post("/requisitions/{req_id}/approve")
def approve_requisition(req_id: int, action: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id, chemical_id, requested_quantity, status, order_code FROM requisitions WHERE id = %s", (req_id,))
        req = cursor.fetchone()
        if not req or req["status"] != "PENDING":
            raise HTTPException(status_code=400, detail="รายการนี้ถูกดำเนินการไปแล้ว")
        
        chem_id = req["chemical_id"]
        req_qty = float(req["requested_quantity"])
        
        cursor.execute("SELECT name, quantity, package_unit FROM chemicals WHERE id = %s", (chem_id,))
        chem = cursor.fetchone()
        if float(chem["quantity"]) < req_qty:
            raise HTTPException(status_code=400, detail="สารเคมีในสต็อกไม่พอ")
        
        new_qty = float(chem["quantity"]) - req_qty
        cursor.execute("UPDATE chemicals SET quantity = %s WHERE id = %s", (new_qty, chem_id))
        cursor.execute("UPDATE requisitions SET status = 'APPROVED', approved_by = %s, approved_at = CURRENT_TIMESTAMP WHERE id = %s", (action.admin_name, req_id))
        
        msg = f"✅ คำขอเบิกสารเคมี {chem['name'] if chem else ''} (#{req['order_code'] or req_id}) ได้รับการอนุมัติแล้ว"
        create_notification(req["user_id"], None, msg)
        send_line_notify(msg)
        return {"message": "อนุมัติและตัดสต็อกเรียบร้อยแล้ว"}
    finally:
        cursor.close()
        conn.close()

@app.post("/requisitions/{req_id}/reject")
def reject_requisition(req_id: int, action: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, order_code FROM requisitions WHERE id = %s", (req_id,))
    req = cursor.fetchone()
    
    cursor.execute("UPDATE requisitions SET status = 'REJECTED', approved_by = %s, approved_at = CURRENT_TIMESTAMP WHERE id = %s", (action.admin_name, req_id))
    cursor.close()
    conn.close()
    
    msg = f"❌ คำขอเบิกสารเคมี (#{req['order_code'] if req else req_id}) ถูกปฏิเสธ"
    create_notification(req["user_id"] if req else None, None, msg)
    send_line_notify(msg)
    return {"message": "ปฏิเสธรายการเบิกเรียบร้อยแล้ว"}
