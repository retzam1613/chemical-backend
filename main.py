import os
import sqlite3
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
import requests

app = FastAPI(title="Chemical Inventory API")

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
  if DATABASE_URL:
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn
  else:
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
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


class ChemicalCreate(BaseModel):
  cas_number: Optional[str] = None
  name: str
  quantity: float
  unit: str
  location: Optional[str] = None
  expiry_date: Optional[str] = None


class RequisitionCreate(BaseModel):
  user_id: int
  chemical_id: int
  requested_quantity: float


class ActionRequisition(BaseModel):
  admin_name: str


@app.get("/")
def read_root():
  return {"status": "Chemical Inventory API is running!"}


@app.get("/chemicals")
def get_chemicals():
  conn = get_db()
  cursor = conn.cursor()
  cursor.execute("SELECT * FROM chemicals ORDER BY id ASC")
  rows = cursor.fetchall()
  conn.close()
  return [dict(row) for row in rows]


@app.post("/chemicals")
def add_chemical(chem: ChemicalCreate):
  conn = get_db()
  cursor = conn.cursor()
  cursor.execute(
      """
        INSERT INTO chemicals (cas_number, name, quantity, unit, location, expiry_date)
        VALUES (%s, %s, %s, %s, %s, %s)
    """,
      (
          chem.cas_number,
          chem.name,
          chem.quantity,
          chem.unit,
          chem.location,
          chem.expiry_date,
      ),
  )
  conn.commit()
  conn.close()
  return {"message": "เพิ่มสารเคมีเรียบร้อยแล้ว"}


@app.post("/requisitions")
def create_requisition(req: RequisitionCreate):
  conn = get_db()
  cursor = conn.cursor()

  cursor.execute(
      "SELECT name, quantity, unit FROM chemicals WHERE id = %s",
      (req.chemical_id,),
  )
  chem = cursor.fetchone()
  if not chem:
    conn.close()
    raise HTTPException(status_code=404, detail="ไม่พบสารเคมีนี้")

  chem_dict = dict(chem)
  chem_name = chem_dict["name"]
  unit = chem_dict["unit"]

  cursor.execute(
      """
        INSERT INTO requisitions (user_id, chemical_id, requested_quantity, status)
        VALUES (%s, %s, %s, 'PENDING')
    """,
      (req.user_id, req.chemical_id, req.requested_quantity),
  )

  conn.commit()
  conn.close()

  # ส่ง LINE แจ้งเตือนคลัง
  msg = f"🧪 มีคำขอเบิกสารเคมีใหม่!\nสารเคมี: {chem_name}\nจำนวน: {req.requested_quantity} {unit}\nสถานะ: รอการอนุมัติ"
  send_line_notify(msg)

  return {"message": "ส่งคำขอเบิกเรียบร้อยแล้ว", "status": "PENDING"}


@app.get("/requisitions")
def get_requisitions():
  conn = get_db()
  cursor = conn.cursor()
  cursor.execute("""
        SELECT r.id, u.full_name as requester_name, c.name as chemical_name, 
               r.requested_quantity, c.unit, r.status, r.approved_by, r.created_at
        FROM requisitions r
        JOIN users u ON r.user_id = u.id
        JOIN chemicals c ON r.chemical_id = c.id
        ORDER BY r.id DESC
    """)
  rows = cursor.fetchall()
  conn.close()
  return [dict(row) for row in rows]


@app.post("/requisitions/{req_id}/approve")
def approve_requisition(req_id: int, action: ActionRequisition):
  conn = get_db()
  cursor = conn.cursor()

  cursor.execute(
      "SELECT chemical_id, requested_quantity, status FROM requisitions WHERE"
      " id = %s",
      (req_id,),
  )
  req = cursor.fetchone()

  if not req:
    conn.close()
    raise HTTPException(status_code=404, detail="ไม่พบรายการเบิกนี้")

  req_dict = dict(req)
  chem_id = req_dict["chemical_id"]
  req_qty = float(req_dict["requested_quantity"])
  status = req_dict["status"]

  if status != "PENDING":
    conn.close()
    raise HTTPException(
        status_code=400, detail="รายการนี้ถูกดำเนินการไปแล้ว"
    )

  cursor.execute(
      "SELECT name, quantity, unit FROM chemicals WHERE id = %s", (chem_id,)
  )
  chem = dict(cursor.fetchone())
  current_qty = float(chem["quantity"])

  if current_qty < req_qty:
    conn.close()
    raise HTTPException(status_code=400, detail="สารเคมีในคลังไม่พอให้เบิก")

  new_qty = current_qty - req_qty
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

  conn.commit()
  conn.close()

  msg = f"✅ อนุมัติการเบิกสารเคมีแล้ว!\nสารเคมี: {chem['name']}\nจำนวน: {req_qty} {chem['unit']}\nผู้อนุมัติ: {action.admin_name}"
  send_line_notify(msg)

  return {"message": "อนุมัติการเบิกและตัดสต็อกเรียบร้อยแล้ว"}


@app.post("/requisitions/{req_id}/reject")
def reject_requisition(req_id: int, action: ActionRequisition):
  conn = get_db()
  cursor = conn.cursor()

  cursor.execute(
      """
        UPDATE requisitions 
        SET status = 'REJECTED', approved_by = %s 
        WHERE id = %s
    """,
      (action.admin_name, req_id),
  )

  conn.commit()
  conn.close()

  msg = f"❌ ปฏิเสธคำขอเบิกสารเคมี\nผู้อนุมัติ/ปฏิเสธ: {action.admin_name}"
  send_line_notify(msg)

  return {"message": "ปฏิเสธคำขอเบิกแล้ว"}
