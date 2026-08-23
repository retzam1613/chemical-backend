import os, re, psycopg2, requests
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

DATABASE_URL = os.getenv("DATABASE_URL")
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

def get_db():
    if not DATABASE_URL: raise HTTPException(status_code=500, detail="DATABASE_URL missing")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn.autocommit = True; return conn

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        if DATABASE_URL:
            conn = get_db(); cursor = conn.cursor()
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS remark TEXT;")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS order_code VARCHAR(50);")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS created_by_name VARCHAR(100);")
            cursor.execute("ALTER TABLE chemicals ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'APPROVED';")
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS remark TEXT;")
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS order_code VARCHAR(50);")
            cursor.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS batch_id VARCHAR(50);")
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
            cursor.close(); conn.close()
    except Exception as e: print("Migration Warning:", e)
    yield

app = FastAPI(title="CIMs API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def send_line(msg: str):
    if not LINE_TOKEN: return
    try: requests.post("https://api.line.me/v2/bot/message/broadcast", json={"messages": [{"type": "text", "text": msg}]}, headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}, timeout=5)
    except: pass

def add_notif(user_id: Optional[int], role: Optional[str], msg: str):
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("INSERT INTO user_notifications (user_id, role_target, message) VALUES (%s, %s, %s);", (user_id, role, msg))
        cursor.close(); conn.close()
    except Exception as e: print("Notif error:", e)

def gen_code(prefix: str):
    conn = get_db(); cursor = conn.cursor()
    today = datetime.now().strftime("%Y%m%d"); pat = f"{prefix}-{today}-%"
    tbl = "chemicals" if prefix == "IN" else "requisitions"
    cursor.execute(f"SELECT order_code FROM {tbl} WHERE order_code LIKE %s ORDER BY id DESC LIMIT 1;", (pat,))
    row = cursor.fetchone(); cursor.close(); conn.close()
    num = int(row["order_code"].split("-")[-1]) + 1 if row and row.get("order_code") else 1
    return f"{prefix}-{today}-{num:03d}"

class UserReg(BaseModel): full_name: str; email: str; phone: str; username: str; password: str
class UserLog(BaseModel): username: str; password: str
class ChemItem(BaseModel): name: str; brand: Optional[str]=None; cas_number: Optional[str]=None; capacity_value: float; capacity_unit: str; quantity: float; package_unit: str; location: Optional[str]=None; expiry_date: Optional[str]=None; remark: Optional[str]=None; created_by_name: Optional[str]="ไม่ระบุ"; user_id: Optional[int]=None
class ChemBatch(BaseModel): items: List[ChemItem]
class ChemUpd(BaseModel): name: str; brand: Optional[str]=None; cas_number: Optional[str]=None; capacity_value: float; capacity_unit: str; quantity: float; package_unit: str; location: Optional[str]=None; expiry_date: Optional[str]=None; remark: Optional[str]=None
class QtyAdj(BaseModel): quantity_change: float
class ReqItem(BaseModel): chemical_id: int; requested_quantity: float; remark: Optional[str]=None
class ReqBasket(BaseModel): user_id: int; requester_name: str; items: List[ReqItem]
class ActionPayload(BaseModel): admin_name: str
class IssuePayload(BaseModel): user_id: int; reporter_name: str; issue_text: str

@app.get("/")
def root(): return {"status": "CIMs API Active"}

@app.post("/auth/register")
def register(u: UserReg):
    if not re.match(r'^[a-zA-Z0-9]+$', u.username) or u.username.lower() == 'admin': raise HTTPException(400, "Invalid Username")
    conn = get_db(); cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (full_name, email, phone, username, password, role) VALUES (%s,%s,%s,%s,%s,'requester') RETURNING id, full_name, username, role;", (u.full_name, u.email, u.phone, u.username, u.password))
        return {"message": "Success", "user": dict(cursor.fetchone())}
    except: raise HTTPException(400, "Username/Email exists")
    finally: cursor.close(); conn.close()

@app.post("/auth/login")
def login(u: UserLog):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT id, full_name, username, role, password FROM users WHERE username = %s", (u.username,))
    user = cursor.fetchone(); cursor.close(); conn.close()
    if not user or user["password"] != u.password: raise HTTPException(401, "Invalid Credentials")
    d = dict(user); del d["password"]; return {"message": "Success", "user": d}

@app.get("/dashboard/analytics")
def analytics():
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT TO_CHAR(created_at, 'YYYY-MM-DD') as day_key, COALESCE(SUM(quantity), 0) as total FROM chemicals WHERE (status = 'APPROVED' OR status IS NULL) AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day_key ORDER BY day_key ASC;")
    imp = cursor.fetchall()
    cursor.execute("SELECT TO_CHAR(created_at, 'YYYY-MM-DD') as day_key, COALESCE(SUM(requested_quantity), 0) as total FROM requisitions WHERE status = 'APPROVED' AND created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY day_key ORDER BY day_key ASC;")
    exp = cursor.fetchall(); cursor.close(); conn.close()
    return {"imports": [dict(r) for r in imp], "exports": [dict(r) for r in exp]}

@app.get("/notifications/user/{user_id}")
def get_notifs(user_id: int, role: str):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT id, name, brand, location, expiry_date, CASE WHEN expiry_date < CURRENT_DATE THEN 'EXPIRED' WHEN expiry_date <= CURRENT_DATE + INTERVAL '1 day' THEN '1_DAY' WHEN expiry_date <= CURRENT_DATE + INTERVAL '3 days' THEN '3_DAYS' WHEN expiry_date <= CURRENT_DATE + INTERVAL '7 days' THEN '7_DAYS' WHEN expiry_date <= CURRENT_DATE + INTERVAL '30 days' THEN '30_DAYS' END as alert_level FROM chemicals WHERE (status = 'APPROVED' OR status IS NULL) AND expiry_date IS NOT NULL AND expiry_date <= CURRENT_DATE + INTERVAL '30 days' ORDER BY expiry_date ASC;")
    exp = [dict(r) for r in cursor.fetchall()]
    cursor.execute("SELECT id, message, is_read, TO_CHAR(created_at, 'DD/MM/YYYY HH24:MI') as time_str FROM user_notifications WHERE (user_id = %s OR role_target = %s) ORDER BY id DESC LIMIT 20;", (user_id, role))
    act = [dict(r) for r in cursor.fetchall()]; cursor.close(); conn.close()
    unread = sum(1 for n in act if not n['is_read']) + len(exp)
    return {"expiry_notifs": exp, "activity_notifs": act, "unread_count": unread}

@app.post("/notifications/read")
def read_notifs(p: dict):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("UPDATE user_notifications SET is_read = TRUE WHERE user_id = %s OR role_target = %s;", (p.get("user_id"), p.get("role")))
    cursor.close(); conn.close(); return {"status": "ok"}

@app.get("/chemicals")
def chemicals():
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT *, CASE WHEN expiry_date < CURRENT_DATE THEN 'EXPIRED' WHEN expiry_date <= CURRENT_DATE + INTERVAL '3 days' THEN '3_DAYS' WHEN expiry_date <= CURRENT_DATE + INTERVAL '7 days' THEN '7_DAYS' WHEN expiry_date <= CURRENT_DATE + INTERVAL '30 days' THEN '30_DAYS' ELSE 'NORMAL' END as expiry_status FROM chemicals WHERE status = 'APPROVED' OR status IS NULL ORDER BY id ASC;")
    items = cursor.fetchall()
    cursor.execute("SELECT COALESCE(SUM(quantity), 0) as total_qty, COUNT(id) as total_count FROM chemicals WHERE status = 'APPROVED' OR status IS NULL;")
    sum_data = cursor.fetchone(); cursor.close(); conn.close()
    return {"items": [dict(r) for r in items], "total_quantity": sum_data["total_qty"] if sum_data else 0, "total_items": sum_data["total_count"] if sum_data else 0}

@app.post("/chemicals/batch")
def add_batch(b: ChemBatch):
    conn = get_db(); cursor = conn.cursor(); code = gen_code("IN")
    for item in b.items:
        exp = item.expiry_date.strip() if item.expiry_date and item.expiry_date.strip() else None
        cursor.execute("INSERT INTO chemicals (name, brand, cas_number, capacity_value, capacity_unit, quantity, unit, package_unit, location, expiry_date, remark, status, created_by_name, order_code) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING_ADD',%s,%s)", (item.name.strip(), item.brand, item.cas_number, item.capacity_value, item.capacity_unit, item.quantity, f"{item.capacity_value} {item.capacity_unit}/{item.package_unit}", item.package_unit, item.location, exp, item.remark, item.created_by_name, code))
    cursor.close(); conn.close()
    msg = f"📥 [คำขอนำเข้าใหม่] Order #{code} โดย {b.items[0].created_by_name}"
    add_notif(None, "storekeeper", msg); send_line(msg); return {"message": "Success", "order_code": code}

@app.put("/chemicals/{cid}")
def upd_chem(cid: int, c: ChemUpd):
    conn = get_db(); cursor = conn.cursor()
    exp = c.expiry_date.strip() if c.expiry_date and c.expiry_date.strip() else None
    cursor.execute("UPDATE chemicals SET name=%s, brand=%s, cas_number=%s, capacity_value=%s, capacity_unit=%s, quantity=%s, unit=%s, package_unit=%s, location=%s, expiry_date=%s, remark=%s WHERE id=%s", (c.name.strip(), c.brand, c.cas_number, c.capacity_value, c.capacity_unit, c.quantity, f"{c.capacity_value} {c.capacity_unit}/{c.package_unit}", c.package_unit, c.location, exp, c.remark, cid))
    cursor.close(); conn.close(); return {"message": "Updated"}

@app.patch("/chemicals/{cid}/adjust")
def adjust_qty(cid: int, payload: QtyAdj):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("UPDATE chemicals SET quantity = GREATEST(0, quantity + %s) WHERE id = %s RETURNING quantity;", (payload.quantity_change, cid))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return {"message": "Success", "new_quantity": res["quantity"] if res else 0}

@app.delete("/chemicals/{cid}")
def del_chem(cid: int):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("DELETE FROM chemicals WHERE id = %s", (cid,))
    cursor.close(); conn.close(); return {"message": "Deleted"}

@app.get("/all-approvals")
def get_all_approvals():
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("""
        SELECT 'IMPORT' as type, id, COALESCE(order_code, '#' || id) as order_code, COALESCE(created_by_name, 'ไม่ระบุ') as requester_name, name as chemical_name, brand, quantity as qty, package_unit as unit, COALESCE(status, 'PENDING_ADD') as status, remark, TO_CHAR(COALESCE(created_at, CURRENT_TIMESTAMP), 'DD/MM/YYYY HH24:MI') as created_at_str
        FROM chemicals WHERE status = 'PENDING_ADD'
        UNION ALL
        SELECT 'EXPORT' as type, r.id, COALESCE(r.order_code, '#' || r.id) as order_code, COALESCE(u.full_name, 'ไม่ระบุ') as requester_name, c.name as chemical_name, c.brand, r.requested_quantity as qty, c.package_unit as unit, r.status, r.remark, TO_CHAR(COALESCE(r.created_at, CURRENT_TIMESTAMP), 'DD/MM/YYYY HH24:MI') as created_at_str
        FROM requisitions r LEFT JOIN users u ON r.user_id = u.id JOIN chemicals c ON r.chemical_id = c.id WHERE r.status = 'PENDING'
        ORDER BY id DESC;
    """)
    pending = cursor.fetchall()
    cursor.execute("""
        SELECT 'IMPORT' as type, id, COALESCE(order_code, '#' || id) as order_code, COALESCE(created_by_name, 'ไม่ระบุ') as requester_name, name as chemical_name, brand, quantity as qty, package_unit as unit, COALESCE(status, 'APPROVED') as status, COALESCE(approved_by, 'Admin') as approved_by, remark, TO_CHAR(COALESCE(approved_at, created_at), 'DD/MM/YYYY HH24:MI') as approved_at_str
        FROM chemicals WHERE status IN ('APPROVED', 'REJECTED_ADD') OR status IS NULL
        UNION ALL
        SELECT 'EXPORT' as type, r.id, COALESCE(r.order_code, '#' || r.id) as order_code, COALESCE(u.full_name, 'ไม่ระบุ') as requester_name, c.name as chemical_name, c.brand, r.requested_quantity as qty, c.package_unit as unit, r.status, r.approved_by, r.remark, TO_CHAR(COALESCE(r.approved_at, r.created_at), 'DD/MM/YYYY HH24:MI') as approved_at_str
        FROM requisitions r LEFT JOIN users u ON r.user_id = u.id JOIN chemicals c ON r.chemical_id = c.id WHERE r.status IN ('APPROVED', 'REJECTED')
        ORDER BY id DESC LIMIT 200;
    """)
    history = cursor.fetchall(); cursor.close(); conn.close()
    return {"pending": [dict(r) for r in pending], "history": [dict(r) for r in history]}

@app.post("/chemicals/{cid}/approve-add")
def approve_add(cid: int, a: ActionPayload):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT name, order_code FROM chemicals WHERE id = %s", (cid,)); chem = cursor.fetchone()
    cursor.execute("UPDATE chemicals SET status = 'APPROVED', approved_at = CURRENT_TIMESTAMP WHERE id = %s", (cid,))
    cursor.close(); conn.close()
    msg = f"✅ [อนุมัตินำเข้า] {chem['name'] if chem else ''} (#{chem['order_code'] if chem else cid})"
    add_notif(None, "requester", msg); send_line(msg); return {"message": "Approved"}

@app.post("/chemicals/{cid}/reject-add")
def reject_add(cid: int, a: ActionPayload):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT name, order_code FROM chemicals WHERE id = %s", (cid,)); chem = cursor.fetchone()
    cursor.execute("UPDATE chemicals SET status = 'REJECTED_ADD', approved_at = CURRENT_TIMESTAMP WHERE id = %s", (cid,))
    cursor.close(); conn.close()
    msg = f"❌ [ปฏิเสธนำเข้า] {chem['name'] if chem else ''} (#{chem['order_code'] if chem else cid})"
    add_notif(None, "requester", msg); send_line(msg); return {"message": "Rejected"}

@app.post("/requisitions/basket")
def req_basket(b: ReqBasket):
    conn = get_db(); cursor = conn.cursor(); code = gen_code("OUT")
    for item in b.items:
        cursor.execute("SELECT quantity, name FROM chemicals WHERE id = %s", (item.chemical_id,)); c = cursor.fetchone()
        if not c or float(c["quantity"]) < item.requested_quantity: raise HTTPException(400, "Insufficient stock")
        cursor.execute("INSERT INTO requisitions (user_id, chemical_id, requested_quantity, remark, status, order_code, batch_id) VALUES (%s,%s,%s,%s,'PENDING',%s,%s)", (b.user_id, item.chemical_id, item.requested_quantity, item.remark, code, code))
    cursor.close(); conn.close()
    msg = f"📤 [คำขอเบิกใหม่] Order #{code} โดย {b.requester_name}"
    add_notif(None, "storekeeper", msg); send_line(msg); return {"message": "Success", "order_code": code}

@app.post("/requisitions/{rid}/approve")
def approve_req(rid: int, a: ActionPayload):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT user_id, chemical_id, requested_quantity, status, order_code FROM requisitions WHERE id = %s", (rid,)); req = cursor.fetchone()
    if not req or req["status"] != "PENDING": raise HTTPException(400, "Invalid order")
    cursor.execute("SELECT name, quantity FROM chemicals WHERE id = %s", (req["chemical_id"],)); chem = cursor.fetchone()
    if float(chem["quantity"]) < float(req["requested_quantity"]): raise HTTPException(400, "Stock too low")
    cursor.execute("UPDATE chemicals SET quantity = quantity - %s WHERE id = %s", (req["requested_quantity"], req["chemical_id"]))
    cursor.execute("UPDATE requisitions SET status = 'APPROVED', approved_by = %s, approved_at = CURRENT_TIMESTAMP WHERE id = %s", (a.admin_name, rid))
    cursor.close(); conn.close()
    msg = f"✅ [อนุมัติการเบิก] {chem['name'] if chem else ''} (#{req['order_code'] or rid})"
    add_notif(req["user_id"], None, msg); send_line(msg); return {"message": "Approved"}

@app.post("/requisitions/{rid}/reject")
def reject_req(rid: int, a: ActionPayload):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT user_id, order_code FROM requisitions WHERE id = %s", (rid,)); req = cursor.fetchone()
    cursor.execute("UPDATE requisitions SET status = 'REJECTED', approved_by = %s, approved_at = CURRENT_TIMESTAMP WHERE id = %s", (a.admin_name, rid))
    cursor.close(); conn.close()
    msg = f"❌ [ปฏิเสธการเบิก] Order (#{req['order_code'] if req else rid})"
    add_notif(req["user_id"] if req else None, None, msg); send_line(msg); return {"message": "Rejected"}

@app.post("/issues/report")
def report_issue(p: IssuePayload):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("INSERT INTO system_issues (user_id, reporter_name, issue_text) VALUES (%s, %s, %s);", (p.user_id, p.reporter_name, p.issue_text))
    cursor.close(); conn.close()
    msg = f"⚠️ [แจ้งปัญหาใหม่] โดยคุณ {p.reporter_name}: {p.issue_text}"
    add_notif(None, "storekeeper", msg); return {"message": "Success"}
