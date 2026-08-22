import os
import re
import uuid
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
import requests

app = FastAPI(title="Chemical Inventory Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

def get_db():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="DATABASE_URL is missing")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn.autocommit = True
    return conn

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

# Pydantic Schemas
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
    created_by_name: Optional[str] = "ไม่ระบุ"

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

class RequisitionItem(BaseModel):
    chemical_id: int
    requested_quantity: float

class RequisitionBasket(BaseModel):
    user_id: int
    requester_name: str
    items: List[RequisitionItem]

class ActionPayload(BaseModel):
    admin_name: str

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

# --- DASHBOARD & NOTIFICATIONS ---
@app.get("/dashboard/metrics")
def get_dashboard_metrics():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            COUNT(*) as total_items,
            COUNT(*) FILTER (WHERE quantity = 0) as out_of_stock,
            COUNT(*) FILTER (WHERE expiry_date IS NOT NULL AND expiry_date < CURRENT_DATE) as expired,
            COUNT(*) FILTER (WHERE expiry_date IS NOT NULL AND expiry_date >= CURRENT_DATE AND expiry_date <= CURRENT_DATE + INTERVAL '1 day') as exp_1d,
            COUNT(*) FILTER (WHERE expiry_date IS NOT NULL AND expiry_date > CURRENT_DATE + INTERVAL '1 day' AND expiry_date <= CURRENT_DATE + INTERVAL '3 days') as exp_3d,
            COUNT(*) FILTER (WHERE expiry_date IS NOT NULL AND expiry_date > CURRENT_DATE + INTERVAL '3 days' AND expiry_date <= CURRENT_DATE + INTERVAL '7 days') as exp_7d,
            COUNT(*) FILTER (WHERE expiry_date IS NOT NULL AND expiry_date > CURRENT_DATE + INTERVAL '7 days' AND expiry_date <= CURRENT_DATE + INTERVAL '30 days') as exp_30d
        FROM chemicals 
        WHERE status = 'APPROVED' OR status IS NULL;
    """)
    metrics = cursor.fetchone()
    cursor.close()
    conn.close()
    return dict(metrics)

@app.get("/notifications")
def get_notifications():
    conn = get_db()
    cursor = conn.cursor()
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
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]

# --- CHEMICALS ENDPOINTS ---
@app.get("/chemicals")
def get_chemicals():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chemicals WHERE status = 'APPROVED' OR status IS NULL ORDER BY id ASC;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/chemicals/pending")
def get_pending_chemicals():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chemicals WHERE status = 'PENDING_ADD' OR status = 'REJECTED_ADD' ORDER BY id DESC;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/chemicals/batch")
def add_chemicals_batch(batch: ChemicalBatchCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        for item in batch.items:
            exp = item.expiry_date.strip() if item.expiry_date and item.expiry_date.strip() else None
            unit_str = f"{item.capacity_value} {item.capacity_unit}/{item.package_unit}"
            
            cursor.execute("""
                INSERT INTO chemicals 
                (name, brand, cas_number, capacity_value, capacity_unit, quantity, unit, package_unit, location, expiry_date, status, created_by_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING_ADD', %s)
            """, (item.name.strip(), item.brand, item.cas_number, item.capacity_value, item.capacity_unit, 
                  item.quantity, unit_str, item.package_unit, item.location, exp, item.created_by_name))
        
        send_line_notify(f"🧪 คำขอเพิ่มสารเคมีใหม่ {len(batch.items)} รายการ โดยคุณ {batch.items[0].created_by_name}")
        return {"message": "ส่งรายการขอเพิ่มสารเคมีเรียบร้อยแล้ว"}
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
                quantity=%s, unit=%s, package_unit=%s, location=%s, expiry_date=%s
            WHERE id=%s
        """, (chem.name.strip(), chem.brand, chem.cas_number, chem.capacity_value, chem.capacity_unit, 
              chem.quantity, unit_str, chem.package_unit, chem.location, exp, chem_id))
        return {"message": "อัปเดตข้อมูลสารเคมีเรียบร้อยแล้ว"}
    finally:
        cursor.close()
        conn.close()

@app.post("/chemicals/{chem_id}/approve-add")
def approve_chemical_add(chem_id: int, action: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE chemicals SET status = 'APPROVED', approved_at = CURRENT_TIMESTAMP WHERE id = %s", (chem_id,))
    cursor.close()
    conn.close()
    send_line_notify(f"✅ อนุมัตินำเข้าสารเคมี ID #{chem_id} โดย {action.admin_name}")
    return {"message": "อนุมัตินำเข้าสารเคมีเรียบร้อยแล้ว"}

@app.post("/chemicals/{chem_id}/reject-add")
def reject_chemical_add(chem_id: int, action: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE chemicals SET status = 'REJECTED_ADD', approved_at = CURRENT_TIMESTAMP WHERE id = %s", (chem_id,))
    cursor.close()
    conn.close()
    send_line_notify(f"❌ ปฏิเสธคำขอนำเข้าสารเคมี ID #{chem_id} โดย {action.admin_name}")
    return {"message": "ปฏิเสธคำขอนำเข้าสารเคมีแล้ว"}

# --- REQUISITIONS ENDPOINTS ---
@app.post("/requisitions/basket")
def create_requisition_basket(basket: RequisitionBasket):
    conn = get_db()
    cursor = conn.cursor()
    batch_id = str(uuid.uuid4())[:8]
    try:
        for item in basket.items:
            cursor.execute("SELECT quantity, name FROM chemicals WHERE id = %s", (item.chemical_id,))
            chem = cursor.fetchone()
            if not chem or float(chem["quantity"]) < item.requested_quantity:
                raise HTTPException(status_code=400, detail=f"สารเคมี {chem['name'] if chem else ''} มีสต็อกไม่พอ")
            
            cursor.execute("""
                INSERT INTO requisitions (user_id, chemical_id, requested_quantity, status, batch_id)
                VALUES (%s, %s, %s, 'PENDING', %s)
            """, (basket.user_id, item.chemical_id, item.requested_quantity, batch_id))
            
        send_line_notify(f"🛒 คำขอเบิกสารเคมี (#{batch_id}) โดยคุณ {basket.requester_name}")
        return {"message": "ส่งคำขอเบิกสารเคมีเรียบร้อยแล้ว", "batch_id": batch_id}
    finally:
        cursor.close()
        conn.close()

@app.get("/requisitions")
def get_requisitions():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, COALESCE(u.full_name, 'ไม่ระบุ') as requester_name, c.name as chemical_name, c.brand,
               r.requested_quantity, c.package_unit as unit, r.status, r.approved_by, r.created_at, r.approved_at, r.batch_id
        FROM requisitions r
        LEFT JOIN users u ON r.user_id = u.id
        JOIN chemicals c ON r.chemical_id = c.id
        ORDER BY r.id DESC;
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/requisitions/{req_id}/approve")
def approve_requisition(req_id: int, action: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT chemical_id, requested_quantity, status FROM requisitions WHERE id = %s", (req_id,))
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
        
        send_line_notify(f"✅ อนุมัติการเบิก #{req_id} โดย {action.admin_name}")
        return {"message": "อนุมัติและตัดสต็อกเรียบร้อยแล้ว"}
    finally:
        cursor.close()
        conn.close()

@app.post("/requisitions/{req_id}/reject")
def reject_requisition(req_id: int, action: ActionPayload):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE requisitions SET status = 'REJECTED', approved_by = %s, approved_at = CURRENT_TIMESTAMP WHERE id = %s", (action.admin_name, req_id))
    cursor.close()
    conn.close()
    send_line_notify(f"❌ ปฏิเสธการเบิก #{req_id} โดย {action.admin_name}")
    return {"message": "ปฏิเสธรายการเบิกเรียบร้อยแล้ว"}
