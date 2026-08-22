import os
import uuid
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
import requests

app = FastAPI(title="Chemical Inventory Pro API")

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
  headers = {
      "Content-Type": "application/json",
      "Authorization": f"Bearer {LINE_TOKEN}",
  }
  payload = {"messages": [{"type": "text", "text": message}]}
  try:
    requests.post(url, json=payload, headers=headers, timeout=5)
  except Exception as e:
    print("LINE Error:", e)


# Pydantic Schemas
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
  items: List[RequisitionItem]


class ActionRequisition(BaseModel):
  admin_name: str


@app.get("/")
def read_root():
  return {"status": "Chemical API Pro Active"}


# ดึงรายการสารเคมีที่อนุมัติแล้วเท่านั้น
@app.get("/chemicals")
def get_chemicals():
  conn = get_db()
  cursor = conn.cursor()
  cursor.execute(
      "SELECT * FROM chemicals WHERE status = 'APPROVED' OR status IS NULL"
      " ORDER BY id DESC"
  )
  rows = cursor.fetchall()
  cursor.close()
  conn.close()
  return [dict(r) for r in rows]


# ดึงรายการสารเคมีที่รออนุมัติเข้าคลัง
@app.get("/chemicals/pending")
def get_pending_chemicals():
  conn = get_db()
  cursor = conn.cursor()
  cursor.execute(
      "SELECT * FROM chemicals WHERE status = 'PENDING_ADD' ORDER BY id DESC"
  )
  rows = cursor.fetchall()
  cursor.close()
  conn.close()
  return [dict(r) for r in rows]


# เพิ่มสารเคมีแบบ Batch (เพิ่มได้หลายรายการพร้อมกัน)
@app.post("/chemicals/batch")
def add_chemicals_batch(batch: ChemicalBatchCreate):
  conn = get_db()
  cursor = conn.cursor()
  try:
    for item in batch.items:
      exp = (
          item.expiry_date.strip()
          if item.expiry_date and item.expiry_date.strip()
          else None
      )
      unit_str = f"{item.capacity_value} {item.capacity_unit}/{item.package_unit}"

      cursor.execute(
          """
                INSERT INTO chemicals 
                (name, brand, cas_number, capacity_value, capacity_unit, quantity, unit, package_unit, location, expiry_date, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING_ADD')
            """,
          (
              item.name.strip(),
              item.brand.strip() if item.brand else None,
              item.cas_number.strip() if item.cas_number else None,
              item.capacity_value,
              item.capacity_unit,
              item.quantity,
              unit_str,
              item.package_unit,
              item.location,
              exp,
          ),
      )

    msg = f"🧪 มีการขอเพิ่มสารเคมีใหม่ {len(batch.items)} รายการเข้าคลัง\nสถานะ: รอการอนุมัติรับเข้า"
    send_line_notify(msg)
    return {"message": "ส่งรายการขอเพิ่มสารเคมีเรียบร้อยแล้ว รอการอนุมัติ"}
  finally:
    cursor.close()
    conn.close()


# แก้ไขรายการสารเคมีก่อนรับการอนุมัติ
@app.put("/chemicals/{chem_id}")
def update_pending_chemical(chem_id: int, chem: ChemicalUpdate):
  conn = get_db()
  cursor = conn.cursor()
  try:
    cursor.execute(
        "SELECT status FROM chemicals WHERE id = %s", (chem_id,)
    )
    row = cursor.fetchone()
    if not row or row["status"] == "APPROVED":
      raise HTTPException(
          status_code=400, detail="รายการนี้อนุมัติไปแล้ว ไม่สามารถแก้ไขได้"
      )

    exp = (
        chem.expiry_date.strip()
        if chem.expiry_date and chem.expiry_date.strip()
        else None
    )
    unit_str = f"{chem.capacity_value} {chem.capacity_unit}/{chem.package_unit}"

    cursor.execute(
        """
            UPDATE chemicals 
            SET name=%s, brand=%s, cas_number=%s, capacity_value=%s, capacity_unit=%s, 
                quantity=%s, unit=%s, package_unit=%s, location=%s, expiry_date=%s
            WHERE id=%s
        """,
        (
            chem.name.strip(),
            chem.brand,
            chem.cas_number,
            chem.capacity_value,
            chem.capacity_unit,
            chem.quantity,
            unit_str,
            chem.package_unit,
            chem.location,
            exp,
            chem_id,
        ),
    )
    return {"message": "แก้ไขรายการสารเคมีเรียบร้อยแล้ว"}
  finally:
    cursor.close()
    conn.close()


# Storekeeper อนุมัติการนำเข้าสารเคมี (ปั๊ม Timestamp รับเข้า)
@app.post("/chemicals/{chem_id}/approve-add")
def approve_chemical_add(chem_id: int, action: ActionRequisition):
  conn = get_db()
  cursor = conn.cursor()
  try:
    cursor.execute(
        """
            UPDATE chemicals 
            SET status = 'APPROVED', approved_at = CURRENT_TIMESTAMP 
            WHERE id = %s
        """,
        (chem_id,),
    )
    send_line_notify(f"✅ อนุมัติการนำเข้าสารเคมี ID #{chem_id} เรียบร้อยแล้ว")
    return {"message": "อนุมัตินำเข้าสารเคมีและบันทึก Timestamp เรียบร้อย"}
  finally:
    cursor.close()
    conn.close()


# เบิกสารเคมีแบบตะกร้า (หลายรายการพร้อมกัน)
@app.post("/requisitions/basket")
def create_requisition_basket(basket: RequisitionBasket):
  conn = get_db()
  cursor = conn.cursor()
  batch_id = str(uuid.uuid4())[:8]
  try:
    for item in basket.items:
      cursor.execute(
          """
                INSERT INTO requisitions (user_id, chemical_id, requested_quantity, status, batch_id)
                VALUES (%s, %s, %s, 'PENDING', %s)
            """,
          (basket.user_id, item.chemical_id, item.requested_quantity, batch_id),
      )

    msg = f"🛒 มีคำขอเบิกสารเคมีใหม่ (กลุ่มใบเบิก #{batch_id})\nจำนวน: {len(basket.items)} รายการ\nสถานะ: รอการอนุมัติ"
    send_line_notify(msg)
    return {
        "message": "ส่งคำขอเบิกสารเคมีแบบกลุ่มเรียบร้อยแล้ว",
        "batch_id": batch_id,
    }
  finally:
    cursor.close()
    conn.close()


@app.get("/requisitions")
def get_requisitions():
  conn = get_db()
  cursor = conn.cursor()
  cursor.execute("""
        SELECT r.id, u.full_name as requester_name, c.name as chemical_name, c.brand,
               r.requested_quantity, c.package_unit as unit, r.status, r.approved_by, r.created_at, r.batch_id
        FROM requisitions r
        LEFT JOIN users u ON r.user_id = u.id
        JOIN chemicals c ON r.chemical_id = c.id
        ORDER BY r.id DESC
    """)
  rows = cursor.fetchall()
  cursor.close()
  conn.close()
  return [dict(r) for r in rows]


@app.post("/requisitions/{req_id}/approve")
def approve_requisition(req_id: int, action: ActionRequisition):
  conn = get_db()
  cursor = conn.cursor()
  try:
    cursor.execute(
        "SELECT chemical_id, requested_quantity, status FROM requisitions WHERE"
        " id = %s",
        (req_id,),
    )
    req = cursor.fetchone()
    if not req or req["status"] != "PENDING":
      raise HTTPException(status_code=400, detail="รายการนี้ถูกดำเนินการไปแล้ว")

    chem_id = req["chemical_id"]
    req_qty = float(req["requested_quantity"])

    cursor.execute(
        "SELECT name, quantity, package_unit FROM chemicals WHERE id = %s",
        (chem_id,),
    )
    chem = cursor.fetchone()
    if float(chem["quantity"]) < req_qty:
      raise HTTPException(status_code=400, detail="สต็อกไม่เพียงพอ")

    new_qty = float(chem["quantity"]) - req_qty
    cursor.execute(
        "UPDATE chemicals SET quantity = %s WHERE id = %s", (new_qty, chem_id)
    )
    cursor.execute(
        """
            UPDATE requisitions 
            SET status = 'APPROVED', approved_by = %s 
            WHERE id = %s
        """,
        (action.admin_name, req_id),
    )

    send_line_notify(
        f"✅ อนุมัติคำขอเบิก #{req_id} ({chem['name']}) จำนวน {req_qty}"
        f" {chem['package_unit']} เรียบร้อยแล้ว"
    )
    return {"message": "อนุมัติและตัดสต็อกเรียบร้อยแล้ว"}
  finally:
    cursor.close()
    conn.close()


@app.post("/requisitions/{req_id}/reject")
def reject_requisition(req_id: int, action: ActionRequisition):
  conn = get_db()
  cursor = conn.cursor()
  try:
    cursor.execute(
        """
            UPDATE requisitions 
            SET status = 'REJECTED', approved_by = %s 
            WHERE id = %s
        """,
        (action.admin_name, req_id),
    )
    return {"message": "ปฏิเสธคำขอเบิกเรียบร้อยแล้ว"}
  finally:
    cursor.close()
    conn.close()
