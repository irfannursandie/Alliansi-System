from fastapi import FastAPI, APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
import os, logging, random, io, csv, jwt, bcrypt, asyncpg, ssl, calendar
from pathlib import Path
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

JWT_SECRET = os.environ.get('JWT_SECRET', 'raja-digital-secret-2025')
JWT_ALGORITHM = 'HS256'
JAKARTA_TZ = ZoneInfo('Asia/Jakarta')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Alliansi SMF")
api_router = APIRouter(prefix="/api")
security = HTTPBearer()


@app.get("/")
async def root_health():
    build_index = Path(__file__).parent.parent / "frontend" / "build" / "index.html"
    if build_index.exists():
        return FileResponse(str(build_index))
    return {"status": "API is running"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

pool: asyncpg.Pool = None


async def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return pool


def detect_shift() -> str:
    now = datetime.now(JAKARTA_TZ)
    return "Shift1" if 7 <= now.hour < 17 else "Shift2"


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(
    security)) -> dict:
    try:
        return jwt.decode(credentials.credentials,
                          JWT_SECRET,
                          algorithms=[JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Token tidak valid")


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get('role') not in ['admin', 'superadmin']:
        raise HTTPException(status_code=403, detail="Akses ditolak")
    return user


async def require_superadmin(user: dict = Depends(get_current_user)) -> dict:
    if user.get('role') != 'superadmin':
        raise HTTPException(status_code=403,
                            detail="Hanya SuperAdmin yang dapat mengakses")
    return user


class LoginRequest(BaseModel):
    email: str
    password: str


class SIJCreateRequest(BaseModel):
    driver_id: str
    sheets: int = 5
    qris_ref: str
    date: Optional[str] = None


class PrintNetworkRequest(BaseModel):
    ip: str
    port: int = 9100
    hex_data: str


class DriverCreateRequest(BaseModel):
    driver_id: str
    name: str
    phone: str = ""
    plate: str = ""
    category: str = "standar"
    status: str = "active"
    kendaraan: str = ""
    no_stiker_bandara: str = ""


class DriverUpdateRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    plate: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None


class SIJUpdateRequest(BaseModel):
    driver_id: Optional[str] = None
    sheets: Optional[int] = None
    qris_ref: Optional[str] = None
    date: Optional[str] = None
    amount: Optional[int] = None


class RitaseCreateRequest(BaseModel):
    driver_id: str
    date: str
    waktu_ritase: str = ""
    notes: str = ""


class RitaseUpdateRequest(BaseModel):
    driver_id: Optional[str] = None
    date: Optional[str] = None
    waktu_ritase: Optional[str] = None
    notes: Optional[str] = None


ABSENCE_REASONS = [
    "SAKIT", "IZIN", "GANTI UNIT", "PINDAH PREMIUM", "CUTI", "GANGGUAN G.A.",
    "TAKEDOWN", "RESIGN", "TANPA KETERANGAN", "AKUN BLOKIR", "UNIT MAINTENANCE"
]


class AbsenceRequest(BaseModel):
    driver_id: str
    date: str
    reason: str


class UserCreateRequest(BaseModel):
    user_id: str
    name: str
    email: str
    password: str
    role: str # admin, superadmin, viewer
    shift: Optional[str] = None


class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None # admin, superadmin, viewer
    shift: Optional[str] = None


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    return [dict(r) for r in rows]


# =================== AUTH ===================


@api_router.post("/auth/login")
async def login(req: LoginRequest):
    row = await pool.fetchrow("SELECT * FROM users WHERE email = $1",
                              req.email)
    if not row:
        raise HTTPException(status_code=401,
                            detail="Email atau password salah")
    user_doc = dict(row)
    stored_hash = user_doc.get('password_hash', '')
    if not bcrypt.checkpw(req.password.encode(), stored_hash.encode()):
        raise HTTPException(status_code=401,
                            detail="Email atau password salah")
    shift = detect_shift()
    token_data = {
        "user_id": user_doc['user_id'],
        "email": user_doc['email'],
        "role": user_doc['role'],
        "shift": shift,
        "name": user_doc['name'],
    }
    token = jwt.encode(token_data, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"token": token, "user": token_data}


@api_router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user


# =================== DRIVERS ===================

DRIVER_SORT_COLS = {
    "name", "driver_id", "plate", "category", "status", "mismatch_count",
    "total_sij_month"
}


@api_router.get("/drivers")
async def get_drivers(search: str = "",
                      status_filter: str = "",
                      sort_by: str = "name",
                      sort_dir: str = "asc",
                      user: dict = Depends(get_current_user)):
    conditions = []
    params = []
    idx = 1
    if search:
        conditions.append(
            f"(name ILIKE ${idx} OR driver_id ILIKE ${idx} OR plate ILIKE ${idx})"
        )
        params.append(f"%{search}%")
        idx += 1
    if status_filter:
        conditions.append(f"status = ${idx}")
        params.append(status_filter)
        idx += 1
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    col = sort_by if sort_by in DRIVER_SORT_COLS else "name"
    direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
    rows = await pool.fetch(
        f"SELECT driver_id, name, phone, plate, kendaraan, no_stiker_bandara, category, status, mismatch_count, total_sij_month FROM drivers {where} ORDER BY {col} {direction}",
        *params)
    return rows_to_list(rows)


@api_router.get("/drivers/active")
async def get_active_drivers(user: dict = Depends(get_current_user)):
    rows = await pool.fetch(
        "SELECT driver_id, name, phone, plate, category, status, mismatch_count, total_sij_month FROM drivers WHERE status = 'active' ORDER BY name"
    )
    return rows_to_list(rows)


@api_router.post("/drivers")
async def create_driver(data: DriverCreateRequest,
                        user: dict = Depends(require_superadmin)):
    existing = await pool.fetchrow(
        "SELECT driver_id FROM drivers WHERE driver_id = $1", data.driver_id)
    if existing:
        raise HTTPException(status_code=400, detail="Driver ID sudah ada")
    await pool.execute(
        "INSERT INTO drivers (driver_id, name, phone, plate, category, status, mismatch_count, total_sij_month, kendaraan, no_stiker_bandara) VALUES ($1, $2, $3, $4, $5, $6, 0, 0, $7, $8)",
        data.driver_id, data.name, data.phone, data.plate, data.category,
        data.status, data.kendaraan, data.no_stiker_bandara)
    return {
        "message": "Driver berhasil ditambahkan",
        "driver_id": data.driver_id
    }


@api_router.get("/drivers/export/csv")
async def export_drivers_csv(user: dict = Depends(get_current_user)):
    rows = await pool.fetch(
        "SELECT driver_id, name, phone, plate, kendaraan, no_stiker_bandara, category, status, mismatch_count, total_sij_month FROM drivers ORDER BY name"
    )
    drivers = rows_to_list(rows)
    output = io.StringIO()
    writer = csv.DictWriter(output,
                            fieldnames=[
                                "driver_id", "name", "phone", "plate",
                                "kendaraan", "no_stiker_bandara",
                                "category", "status", "mismatch_count",
                                "total_sij_month"
                            ])
    writer.writeheader()
    writer.writerows(drivers)
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=drivers.csv"})


@api_router.get("/drivers/export/pdf")
async def export_drivers_pdf(user: dict = Depends(get_current_user)):
    rows = await pool.fetch(
        "SELECT driver_id, name, phone, plate, kendaraan, no_stiker_bandara, category, status, mismatch_count, total_sij_month FROM drivers ORDER BY name"
    )
    drivers = rows_to_list(rows)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf,
                            pagesize=landscape(A4),
                            topMargin=15 * mm,
                            bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title2',
                                 parent=styles['Title'],
                                 fontSize=16,
                                 spaceAfter=10)
    elements = [
        Paragraph("Alliansi SMF - Data Driver", title_style),
        Spacer(1, 5 * mm)
    ]
    header = [
        "Driver ID", "Nama", "Telepon", "Plat", "Kendaraan",
        "No. Stiker", "Kategori", "Status", "Mismatch", "SIJ Bulan"
    ]
    data = [header]
    for d in drivers:
        data.append([
            d['driver_id'], d['name'], d['phone'], d['plate'],
            d.get('kendaraan', '') or '', d.get('no_stiker_bandara', '') or '',
            d['category'], d['status'],
            str(d['mismatch_count']),
            str(d['total_sij_month'])
        ])
    t = Table(data, repeatRows=1)
    t.setStyle(
        TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10b981')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#f5f5f5')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=drivers.pdf"})


@api_router.put("/drivers/{driver_id}")
async def update_driver(driver_id: str,
                        data: DriverUpdateRequest,
                        user: dict = Depends(require_superadmin)):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if update_data:
        sets = []
        params = []
        idx = 1
        for k, v in update_data.items():
            sets.append(f"{k} = ${idx}")
            params.append(v)
            idx += 1
        params.append(driver_id)
        await pool.execute(
            f"UPDATE drivers SET {', '.join(sets)} WHERE driver_id = ${idx}",
            *params)
    return {"message": "Driver diperbarui"}


@api_router.patch("/drivers/{driver_id}/suspend")
async def suspend_driver(driver_id: str,
                         user: dict = Depends(require_superadmin)):
    await pool.execute(
        "UPDATE drivers SET status = 'suspend' WHERE driver_id = $1",
        driver_id)
    return {"message": "Driver disuspend"}


@api_router.patch("/drivers/{driver_id}/activate")
async def activate_driver(driver_id: str,
                          user: dict = Depends(require_superadmin)):
    await pool.execute(
        "UPDATE drivers SET status = 'active' WHERE driver_id = $1", driver_id)
    return {"message": "Driver diaktifkan"}


@api_router.delete("/drivers/{driver_id}")
async def delete_driver(driver_id: str,
                        user: dict = Depends(require_superadmin)):
    existing = await pool.fetchrow(
        "SELECT driver_id FROM drivers WHERE driver_id = $1", driver_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Driver tidak ditemukan")
    await pool.execute("DELETE FROM drivers WHERE driver_id = $1", driver_id)
    return {"message": "Driver berhasil dihapus"}


# =================== SIJ TRANSACTIONS ===================


@api_router.post("/sij")
async def create_sij(req: SIJCreateRequest,
                     user: dict = Depends(require_admin)):
    driver_row = await pool.fetchrow(
        "SELECT * FROM drivers WHERE driver_id = $1 AND status = 'active'",
        req.driver_id)
    if not driver_row:
        raise HTTPException(status_code=400,
                            detail="Driver tidak ditemukan atau tidak aktif")
    driver = dict(driver_row)
    now = datetime.now(JAKARTA_TZ)

    PRICE_MAP = {"standar": 40000, "premium": 60000}
    category = driver.get("category", "standar")
    amount = PRICE_MAP.get(category, 40000)

    if req.date:
        try:
            target_date = datetime.strptime(req.date, "%Y-%m-%d")
            today_start = now.replace(hour=0,
                                      minute=0,
                                      second=0,
                                      microsecond=0)
            max_date = today_start + timedelta(days=7)
            if target_date.date() < today_start.date() or target_date.date(
            ) > max_date.date():
                raise HTTPException(
                    status_code=400,
                    detail="Tanggal harus antara hari ini dan 7 hari ke depan")
            date_iso = req.date
            date_str = target_date.strftime("%Y%m%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Format tanggal tidak valid (gunakan YYYY-MM-DD)")
    else:
        date_str = now.strftime("%Y%m%d")
        date_iso = now.strftime("%Y-%m-%d")

    time_str = now.strftime("%H:%M:%S")
    existing = await pool.fetchrow(
        "SELECT transaction_id FROM sij_transactions WHERE driver_id = $1 AND date = $2 AND status = 'active'",
        req.driver_id, date_iso)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=
            f"Driver {driver['name']} sudah memiliki SIJ aktif untuk tanggal {date_iso}"
        )

    random_suffix = str(random.randint(100, 999))
    transaction_id = f"{req.driver_id}{date_str}{random_suffix}"
    created_at = now.isoformat()

    await pool.execute(
        """INSERT INTO sij_transactions (transaction_id, driver_id, driver_name, category, date, time, sheets, amount, qris_ref, admin_id, admin_name, shift, status, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)""",
        transaction_id, req.driver_id, driver['name'], category, date_iso,
        time_str, req.sheets, amount, req.qris_ref, user['user_id'],
        user['name'], detect_shift(), "active", created_at)
    await pool.execute(
        "UPDATE drivers SET total_sij_month = total_sij_month + 1 WHERE driver_id = $1",
        req.driver_id)
    await pool.execute(
        """INSERT INTO audit_log (date, driver_id, has_sij, has_trip, mismatch)
        VALUES ($1, $2, true, false, false)
        ON CONFLICT (date, driver_id) DO UPDATE SET has_sij = true""",
        date_iso, req.driver_id)
    return {
        "transaction_id": transaction_id,
        "driver_id": req.driver_id,
        "driver_name": driver['name'],
        "category": category,
        "date": date_iso,
        "time": time_str,
        "sheets": req.sheets,
        "amount": amount,
        "qris_ref": req.qris_ref,
        "admin_id": user['user_id'],
        "admin_name": user['name'],
        "shift": detect_shift(),
        "status": "active",
        "created_at": created_at,
    }


SIJ_SORT_COLS = {
    "transaction_id", "driver_name", "driver_id", "date", "time", "admin_name",
    "shift", "amount", "sheets", "status", "created_at"
}


@api_router.get("/sij")
async def get_sij_transactions(date: Optional[str] = None,
                               date_from: Optional[str] = None,
                               date_to: Optional[str] = None,
                               shift: Optional[str] = None,
                               search: Optional[str] = None,
                               include_void: bool = False,
                               sort_by: str = "created_at",
                               sort_dir: str = "desc",
                               user: dict = Depends(get_current_user)):
    conditions = []
    params = []
    idx = 1
    if not include_void:
        conditions.append("status = 'active'")
    if date:
        conditions.append(f"date = ${idx}")
        params.append(date)
        idx += 1
    if date_from:
        conditions.append(f"date >= ${idx}")
        params.append(date_from)
        idx += 1
    if date_to:
        conditions.append(f"date <= ${idx}")
        params.append(date_to)
        idx += 1
    if shift:
        conditions.append(f"shift = ${idx}")
        params.append(shift)
        idx += 1
    if search:
        conditions.append(
            f"(driver_name ILIKE ${idx} OR driver_id ILIKE ${idx} OR transaction_id ILIKE ${idx})"
        )
        params.append(f"%{search}%")
        idx += 1
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    col = sort_by if sort_by in SIJ_SORT_COLS else "created_at"
    direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
    rows = await pool.fetch(
        f"SELECT transaction_id, driver_id, driver_name, category, date, time, sheets, amount, qris_ref, admin_id, admin_name, shift, status, created_at FROM sij_transactions {where} ORDER BY {col} {direction}",
        *params)
    return rows_to_list(rows)


@api_router.get("/sij/export/csv")
async def export_sij_csv(date_from: Optional[str] = None,
                         date_to: Optional[str] = None,
                         user: dict = Depends(get_current_user)):
    conditions = ["status = 'active'"]
    params = []
    idx = 1
    if date_from:
        conditions.append(f"date >= ${idx}")
        params.append(date_from)
        idx += 1
    if date_to:
        conditions.append(f"date <= ${idx}")
        params.append(date_to)
        idx += 1
    where = "WHERE " + " AND ".join(conditions)
    rows = await pool.fetch(
        f"SELECT transaction_id, driver_id, driver_name, category, date, time, sheets, amount, qris_ref, admin_name, shift, status FROM sij_transactions {where} ORDER BY date DESC, time DESC",
        *params)
    data = rows_to_list(rows)
    output = io.StringIO()
    fields = [
        "transaction_id", "driver_id", "driver_name", "category", "date",
        "time", "sheets", "amount", "qris_ref", "admin_name", "shift", "status"
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(data)
    output.seek(0)
    fname = f"sij_{date_from or 'all'}_{date_to or 'all'}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@api_router.get("/sij/export/pdf")
async def export_sij_pdf(date_from: Optional[str] = None,
                         date_to: Optional[str] = None,
                         user: dict = Depends(get_current_user)):
    conditions = ["status = 'active'"]
    params = []
    idx = 1
    if date_from:
        conditions.append(f"date >= ${idx}")
        params.append(date_from)
        idx += 1
    if date_to:
        conditions.append(f"date <= ${idx}")
        params.append(date_to)
        idx += 1
    where = "WHERE " + " AND ".join(conditions)
    rows = await pool.fetch(
        f"SELECT transaction_id, driver_id, driver_name, category, date, time, sheets, amount, qris_ref, admin_name, shift FROM sij_transactions {where} ORDER BY date DESC, time DESC",
        *params)
    data = rows_to_list(rows)
    total_amount = sum(d['amount'] for d in data)
    total_sheets = sum(d['sheets'] for d in data)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf,
                            pagesize=landscape(A4),
                            topMargin=15 * mm,
                            bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title2',
                                 parent=styles['Title'],
                                 fontSize=16,
                                 spaceAfter=6)
    sub_style = ParagraphStyle('Sub',
                               parent=styles['Normal'],
                               fontSize=10,
                               spaceAfter=10,
                               textColor=colors.grey)
    period = ""
    if date_from and date_to:
        period = f"Periode: {date_from} s/d {date_to}"
    elif date_from:
        period = f"Dari: {date_from}"
    elif date_to:
        period = f"Sampai: {date_to}"
    else:
        period = "Semua data"
    elements = [
        Paragraph("Alliansi SMF - Laporan SIJ", title_style),
        Paragraph(
            f"{period} | Total: {len(data)} transaksi | Revenue: Rp {total_amount:,} | Sheets: {total_sheets}",
            sub_style),
        Spacer(1, 3 * mm),
    ]
    header = [
        "No", "Transaction ID", "Driver", "Kategori", "Tanggal", "Jam",
        "Sheet", "Jumlah", "QRIS Ref", "Admin", "Shift"
    ]
    tdata = [header]
    for i, d in enumerate(data, 1):
        tdata.append([
            str(i), d['transaction_id'], d['driver_name'], d['category'],
            d['date'], d['time'],
            str(d['sheets']), f"Rp {d['amount']:,}", d['qris_ref'],
            d['admin_name'], d['shift']
        ])
    t = Table(tdata, repeatRows=1)
    t.setStyle(
        TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10b981')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (6, 0), (7, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#f5f5f5')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    fname = f"sij_report_{date_from or 'all'}_{date_to or 'all'}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@api_router.get("/revenue-report/export/csv")
async def export_revenue_csv(period: str = "monthly",
                             date: Optional[str] = None,
                             user: dict = Depends(get_current_user)):
    rows, meta = await _revenue_report_data(period, date)
    output = io.StringIO()
    fields = [
        "period_label", "qty_standar", "revenue_standar", "qty_premium",
        "revenue_premium", "total_revenue"
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "period_label": r["period_label"],
            "qty_standar": r["qty_standar"],
            "revenue_standar": r["revenue_standar"],
            "qty_premium": r["qty_premium"],
            "revenue_premium": r["revenue_premium"],
            "total_revenue": r["total_revenue"],
        })
    total_row = {
        "period_label": "GRAND TOTAL",
        "qty_standar": sum(r["qty_standar"] for r in rows),
        "revenue_standar": sum(r["revenue_standar"] for r in rows),
        "qty_premium": sum(r["qty_premium"] for r in rows),
        "revenue_premium": sum(r["revenue_premium"] for r in rows),
        "total_revenue": sum(r["total_revenue"] for r in rows),
    }
    writer.writerow(total_row)
    output.seek(0)
    fname = f"revenue_{period}_{meta['date_from']}_{meta['date_to']}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@api_router.get("/revenue-report/export/pdf")
async def export_revenue_pdf(period: str = "monthly",
                             date: Optional[str] = None,
                             user: dict = Depends(get_current_user)):
    rows, meta = await _revenue_report_data(period, date)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf,
                            pagesize=landscape(A4),
                            topMargin=15 * mm,
                            bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title2',
                                 parent=styles['Title'],
                                 fontSize=16,
                                 spaceAfter=6)
    sub_style = ParagraphStyle('Sub',
                               parent=styles['Normal'],
                               fontSize=10,
                               spaceAfter=10)
    elements = []
    period_labels = {
        "daily": "Harian",
        "weekly": "Mingguan",
        "monthly": "Bulanan"
    }
    elements.append(
        Paragraph(f"Revenue Report – {period_labels.get(period, period)}",
                  title_style))
    elements.append(
        Paragraph(f"Periode: {meta['date_from']} s/d {meta['date_to']}",
                  sub_style))
    header = [
        "Periode / Jam", "Qty Standar", "Revenue Standar", "Qty Premium",
        "Revenue Premium", "Total Revenue"
    ]
    data = [header]
    for r in rows:
        data.append([
            r["period_label"],
            str(r["qty_standar"]),
            f"Rp {r['revenue_standar']:,}",
            str(r["qty_premium"]),
            f"Rp {r['revenue_premium']:,}",
            f"Rp {r['total_revenue']:,}",
        ])
    total_qty_s = sum(r["qty_standar"] for r in rows)
    total_rev_s = sum(r["revenue_standar"] for r in rows)
    total_qty_p = sum(r["qty_premium"] for r in rows)
    total_rev_p = sum(r["revenue_premium"] for r in rows)
    total_rev = sum(r["total_revenue"] for r in rows)
    data.append([
        "GRAND TOTAL",
        str(total_qty_s), f"Rp {total_rev_s:,}",
        str(total_qty_p), f"Rp {total_rev_p:,}", f"Rp {total_rev:,}"
    ])
    col_widths = [70 * mm, 30 * mm, 50 * mm, 30 * mm, 50 * mm, 50 * mm]
    t = Table(data, colWidths=col_widths)
    t.setStyle(
        TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a2e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2),
             [colors.white, colors.HexColor('#f9f9f9')]),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#10b981')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    fname = f"revenue_{period}_{meta['date_from']}_{meta['date_to']}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


async def _revenue_report_data(period: str, date: Optional[str]):
    now = datetime.now(JAKARTA_TZ)
    target = datetime.strptime(date, "%Y-%m-%d") if date else now

    if period == "daily":
        date_from = date_to = target.strftime("%Y-%m-%d")
        rows = await pool.fetch(
            """SELECT LPAD(EXTRACT(HOUR FROM time::time)::int::text, 2, '0') || ':00' AS period_label,
                      COUNT(*) FILTER (WHERE category='standar') AS qty_standar,
                      COALESCE(SUM(amount) FILTER (WHERE category='standar'), 0) AS revenue_standar,
                      COUNT(*) FILTER (WHERE category='premium') AS qty_premium,
                      COALESCE(SUM(amount) FILTER (WHERE category='premium'), 0) AS revenue_premium
               FROM sij_transactions
               WHERE date = $1 AND status = 'active'
               GROUP BY EXTRACT(HOUR FROM time::time)
               ORDER BY EXTRACT(HOUR FROM time::time)""", date_from)
    elif period == "weekly":
        monday = target - timedelta(days=target.weekday())
        sunday = monday + timedelta(days=6)
        date_from = monday.strftime("%Y-%m-%d")
        date_to = sunday.strftime("%Y-%m-%d")
        rows = await pool.fetch(
            """SELECT date::text AS period_label,
                      COUNT(*) FILTER (WHERE category='standar') AS qty_standar,
                      COALESCE(SUM(amount) FILTER (WHERE category='standar'), 0) AS revenue_standar,
                      COUNT(*) FILTER (WHERE category='premium') AS qty_premium,
                      COALESCE(SUM(amount) FILTER (WHERE category='premium'), 0) AS revenue_premium
               FROM sij_transactions
               WHERE date >= $1 AND date <= $2 AND status = 'active'
               GROUP BY date
               ORDER BY date""", date_from, date_to)
    else:
        date_from = target.strftime("%Y-%m-01")
        last_day = (target.replace(day=28) +
                    timedelta(days=4)).replace(day=1) - timedelta(days=1)
        date_to = last_day.strftime("%Y-%m-%d")
        rows = await pool.fetch(
            """SELECT date::text AS period_label,
                      COUNT(*) FILTER (WHERE category='standar') AS qty_standar,
                      COALESCE(SUM(amount) FILTER (WHERE category='standar'), 0) AS revenue_standar,
                      COUNT(*) FILTER (WHERE category='premium') AS qty_premium,
                      COALESCE(SUM(amount) FILTER (WHERE category='premium'), 0) AS revenue_premium
               FROM sij_transactions
               WHERE date >= $1 AND date <= $2 AND status = 'active'
               GROUP BY date
               ORDER BY date""", date_from, date_to)

    result = []
    for r in rows:
        rv_s = int(r["revenue_standar"])
        rv_p = int(r["revenue_premium"])
        result.append({
            "period_label": r["period_label"],
            "qty_standar": int(r["qty_standar"]),
            "revenue_standar": rv_s,
            "qty_premium": int(r["qty_premium"]),
            "revenue_premium": rv_p,
            "total_revenue": rv_s + rv_p,
        })
    meta = {"period": period, "date_from": date_from, "date_to": date_to}
    return result, meta


@api_router.get("/revenue-report")
async def get_revenue_report(period: str = "monthly",
                             date: Optional[str] = None,
                             user: dict = Depends(get_current_user)):
    rows, meta = await _revenue_report_data(period, date)
    return {"rows": rows, "meta": meta}


@api_router.get("/sij/pending-ritase/{driver_id}")
async def check_pending_ritase(driver_id: str,
                               user: dict = Depends(require_admin)):
    today = datetime.now(JAKARTA_TZ).strftime("%Y-%m-%d")
    row = await pool.fetchrow(
        """
        SELECT COUNT(*) AS cnt
        FROM sij_transactions s
        WHERE s.driver_id = $1
          AND s.status = 'active'
          AND s.date < $2
          AND NOT EXISTS (
              SELECT 1 FROM ritase r
              WHERE r.driver_id = s.driver_id
                AND r.date = s.date
                AND r.waktu_ritase IS NOT NULL
                AND r.waktu_ritase != ''
                AND r.waktu_ritase != '0'
          )
        """,
        driver_id, today)
    count = row["cnt"]
    return {"has_pending": count > 0, "count": count}


@api_router.patch("/sij/{transaction_id}/void")
async def void_sij(transaction_id: str, user: dict = Depends(require_admin)):
    tx = await pool.fetchrow(
        "SELECT * FROM sij_transactions WHERE transaction_id = $1",
        transaction_id)
    if not tx:
        raise HTTPException(status_code=404,
                            detail="Transaksi tidak ditemukan")
    tx_dict = dict(tx)
    try:
        created_at = datetime.fromisoformat(tx_dict.get('created_at', ''))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=JAKARTA_TZ)
        if datetime.now(timezone.utc) - created_at.astimezone(
                timezone.utc) > timedelta(hours=24):
            raise HTTPException(
                status_code=400,
                detail="Tidak dapat void transaksi lebih dari 24 jam")
    except ValueError:
        pass
    await pool.execute(
        "UPDATE sij_transactions SET status = 'void' WHERE transaction_id = $1",
        transaction_id)
    return {"message": "Transaksi di-void"}


@api_router.put("/sij/{transaction_id}")
async def update_sij(transaction_id: str,
                     data: SIJUpdateRequest,
                     user: dict = Depends(require_superadmin)):
    existing = await pool.fetchrow(
        "SELECT * FROM sij_transactions WHERE transaction_id = $1",
        transaction_id)
    if not existing:
        raise HTTPException(status_code=404,
                            detail="Transaksi tidak ditemukan")
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if 'driver_id' in update_data:
        driver_row = await pool.fetchrow(
            "SELECT name, category FROM drivers WHERE driver_id = $1",
            update_data['driver_id'])
        if not driver_row:
            raise HTTPException(status_code=400,
                                detail="Driver tidak ditemukan")
        update_data['driver_name'] = driver_row['name']
        update_data['category'] = driver_row['category']
    if update_data:
        sets = []
        params = []
        idx = 1
        for k, v in update_data.items():
            sets.append(f"{k} = ${idx}")
            params.append(v)
            idx += 1
        params.append(transaction_id)
        await pool.execute(
            f"UPDATE sij_transactions SET {', '.join(sets)} WHERE transaction_id = ${idx}",
            *params)
    return {"message": "Transaksi SIJ diperbarui"}


@api_router.delete("/sij/{transaction_id}")
async def delete_sij(transaction_id: str,
                     user: dict = Depends(require_superadmin)):
    existing = await pool.fetchrow(
        "SELECT transaction_id FROM sij_transactions WHERE transaction_id = $1",
        transaction_id)
    if not existing:
        raise HTTPException(status_code=404,
                            detail="Transaksi tidak ditemukan")
    await pool.execute(
        "DELETE FROM sij_transactions WHERE transaction_id = $1",
        transaction_id)
    return {"message": "Transaksi berhasil dihapus"}


# =================== RITASE ===================

RITASE_SORT_COLS = {
    "id", "driver_name", "driver_id", "date", "waktu_ritase", "created_at"
}


@api_router.get("/ritase")
async def get_ritase(date_from: Optional[str] = None,
                     date_to: Optional[str] = None,
                     search: Optional[str] = None,
                     sort_by: str = "created_at",
                     sort_dir: str = "desc",
                     user: dict = Depends(require_admin)):
    conditions = []
    params = []
    idx = 1
    if date_from:
        conditions.append(f"date >= ${idx}")
        params.append(date_from)
        idx += 1
    if date_to:
        conditions.append(f"date <= ${idx}")
        params.append(date_to)
        idx += 1
    if search:
        conditions.append(
            f"(driver_name ILIKE ${idx} OR driver_id ILIKE ${idx})")
        params.append(f"%{search}%")
        idx += 1
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    col = sort_by if sort_by in RITASE_SORT_COLS else "created_at"
    direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
    rows = await pool.fetch(
        f"SELECT id, driver_id, driver_name, date, waktu_ritase, notes, admin_name, shift, created_at FROM ritase {where} ORDER BY {col} {direction}",
        *params)
    return rows_to_list(rows)


@api_router.post("/ritase")
async def create_ritase(data: RitaseCreateRequest,
                        user: dict = Depends(require_admin)):
    driver_row = await pool.fetchrow(
        "SELECT name FROM drivers WHERE driver_id = $1", data.driver_id)
    if not driver_row:
        raise HTTPException(status_code=400, detail="Driver tidak ditemukan")
    now = datetime.now(JAKARTA_TZ)
    created_at = now.isoformat()
    await pool.execute(
        """INSERT INTO ritase (driver_id, driver_name, date, waktu_ritase, notes, admin_id, admin_name, shift, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""", data.driver_id,
        driver_row['name'], data.date, data.waktu_ritase, data.notes,
        user['user_id'], user['name'], detect_shift(), created_at)
    await pool.execute(
        """INSERT INTO audit_log (date, driver_id, has_sij, has_trip, mismatch)
        VALUES ($1, $2, false, true, false)
        ON CONFLICT (date, driver_id) DO UPDATE SET has_trip = true""",
        data.date, data.driver_id)
    return {"message": "Ritase berhasil ditambahkan"}


@api_router.get("/ritase/export/csv")
async def export_ritase_csv(date_from: Optional[str] = None,
                            date_to: Optional[str] = None,
                            user: dict = Depends(require_admin)):
    conditions = []
    params = []
    idx = 1
    if date_from:
        conditions.append(f"date >= ${idx}")
        params.append(date_from)
        idx += 1
    if date_to:
        conditions.append(f"date <= ${idx}")
        params.append(date_to)
        idx += 1
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = await pool.fetch(
        f"SELECT id, driver_id, driver_name, date, waktu_ritase, notes, admin_name, shift FROM ritase {where} ORDER BY date DESC, created_at DESC",
        *params)
    data = rows_to_list(rows)
    output = io.StringIO()
    fields = [
        "id", "driver_id", "driver_name", "date", "waktu_ritase", "notes",
        "admin_name", "shift"
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(data)
    output.seek(0)
    fname = f"ritase_{date_from or 'all'}_{date_to or 'all'}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@api_router.get("/ritase/export/pdf")
async def export_ritase_pdf(date_from: Optional[str] = None,
                            date_to: Optional[str] = None,
                            user: dict = Depends(require_admin)):
    conditions = []
    params = []
    idx = 1
    if date_from:
        conditions.append(f"date >= ${idx}")
        params.append(date_from)
        idx += 1
    if date_to:
        conditions.append(f"date <= ${idx}")
        params.append(date_to)
        idx += 1
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = await pool.fetch(
        f"SELECT id, driver_id, driver_name, date, waktu_ritase, notes, admin_name, shift FROM ritase {where} ORDER BY date DESC, created_at DESC",
        *params)
    data = rows_to_list(rows)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf,
                            pagesize=landscape(A4),
                            topMargin=15 * mm,
                            bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('RitTitle',
                                 parent=styles['Title'],
                                 fontSize=16,
                                 spaceAfter=6)
    sub_style = ParagraphStyle('RitSub',
                               parent=styles['Normal'],
                               fontSize=10,
                               spaceAfter=10,
                               textColor=colors.grey)
    period = ""
    if date_from and date_to:
        period = f"Periode: {date_from} s/d {date_to}"
    elif date_from:
        period = f"Dari: {date_from}"
    elif date_to:
        period = f"Sampai: {date_to}"
    else:
        period = "Semua data"
    elements = [
        Paragraph("Alliansi SMF - Laporan Ritase", title_style),
        Paragraph(f"{period} | Total: {len(data)} ritase", sub_style),
        Spacer(1, 3 * mm),
    ]
    header = [
        "No", "Driver", "Driver ID", "Tanggal", "Waktu Ritase", "Catatan",
        "Admin", "Shift"
    ]
    tdata = [header]
    for i, d in enumerate(data, 1):
        tdata.append([
            str(i), d['driver_name'], d['driver_id'], d['date'],
            d.get('waktu_ritase', ''),
            d.get('notes', ''), d['admin_name'], d['shift']
        ])
    t = Table(tdata, repeatRows=1)
    t.setStyle(
        TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10b981')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#f5f5f5')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    fname = f"ritase_{date_from or 'all'}_{date_to or 'all'}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@api_router.put("/ritase/{ritase_id}")
async def update_ritase(ritase_id: int,
                        data: RitaseUpdateRequest,
                        user: dict = Depends(require_superadmin)):
    existing = await pool.fetchrow("SELECT id FROM ritase WHERE id = $1",
                                   ritase_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Ritase tidak ditemukan")
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if 'driver_id' in update_data:
        driver_row = await pool.fetchrow(
            "SELECT name FROM drivers WHERE driver_id = $1",
            update_data['driver_id'])
        if not driver_row:
            raise HTTPException(status_code=400,
                                detail="Driver tidak ditemukan")
        update_data['driver_name'] = driver_row['name']
    if update_data:
        sets = []
        params = []
        idx = 1
        for k, v in update_data.items():
            sets.append(f"{k} = ${idx}")
            params.append(v)
            idx += 1
        params.append(ritase_id)
        await pool.execute(
            f"UPDATE ritase SET {', '.join(sets)} WHERE id = ${idx}", *params)
    return {"message": "Ritase diperbarui"}


@api_router.delete("/ritase/{ritase_id}")
async def delete_ritase(ritase_id: int,
                        user: dict = Depends(require_superadmin)):
    existing = await pool.fetchrow("SELECT id FROM ritase WHERE id = $1",
                                   ritase_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Ritase tidak ditemukan")
    await pool.execute("DELETE FROM ritase WHERE id = $1", ritase_id)
    return {"message": "Ritase berhasil dihapus"}


# =================== USER MANAGEMENT ===================


@api_router.get("/users")
async def get_users(user: dict = Depends(require_superadmin)):
    rows = await pool.fetch(
        "SELECT user_id, name, role, shift, email FROM users ORDER BY role, name"
    )
    return rows_to_list(rows)


@api_router.post("/users")
async def create_user(data: UserCreateRequest,
                      user: dict = Depends(require_superadmin)):
    if data.role not in ["admin", "superadmin", "viewer"]:
        raise HTTPException(status_code=400, detail="Role tidak valid")
    existing = await pool.fetchrow(
        "SELECT user_id FROM users WHERE user_id = $1 OR email = $2",
        data.user_id, data.email)
    if existing:
        raise HTTPException(status_code=409,
                            detail="User ID atau email sudah digunakan")
    password_hash = bcrypt.hashpw(data.password.encode(),
                                  bcrypt.gensalt()).decode()
    await pool.execute(
        "INSERT INTO users (user_id, name, role, shift, email, password_hash) VALUES ($1, $2, $3, $4, $5, $6)",
        data.user_id, data.name, data.role, data.shift, data.email,
        password_hash)
    return {"message": "User berhasil dibuat"}


@api_router.put("/users/{user_id}")
async def update_user(user_id: str,
                      data: UserUpdateRequest,
                      current_user: dict = Depends(require_superadmin)):
    existing = await pool.fetchrow(
        "SELECT user_id FROM users WHERE user_id = $1", user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if 'password' in update_data:
        update_data['password_hash'] = bcrypt.hashpw(
            update_data.pop('password').encode(), bcrypt.gensalt()).decode()
    if 'role' in update_data and update_data['role'] not in [
            "admin", "superadmin", "viewer"
    ]:
        raise HTTPException(status_code=400, detail="Role tidak valid")
    if update_data:
        sets = []
        params = []
        idx = 1
        for k, v in update_data.items():
            sets.append(f"{k} = ${idx}")
            params.append(v)
            idx += 1
        params.append(user_id)
        await pool.execute(
            f"UPDATE users SET {', '.join(sets)} WHERE user_id = ${idx}",
            *params)
    return {"message": "User berhasil diperbarui"}


@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str,
                      current_user: dict = Depends(require_superadmin)):
    if user_id == current_user['user_id']:
        raise HTTPException(status_code=400,
                            detail="Tidak dapat menghapus akun sendiri")
    existing = await pool.fetchrow(
        "SELECT user_id FROM users WHERE user_id = $1", user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    await pool.execute("DELETE FROM users WHERE user_id = $1", user_id)
    return {"message": "User berhasil dihapus"}


# =================== DASHBOARD ===================


@api_router.get("/dashboard/admin")
async def admin_dashboard(user: dict = Depends(get_current_user)):
    shift = user.get('shift', detect_shift())
    today = datetime.now(JAKARTA_TZ).strftime("%Y-%m-%d")

    sij_today_shift = await pool.fetchval(
        "SELECT COUNT(*) FROM sij_transactions WHERE date = $1 AND shift = $2 AND status = 'active'",
        today, shift)
    revenue_shift = await pool.fetchval(
        "SELECT COALESCE(SUM(amount), 0) FROM sij_transactions WHERE date = $1 AND shift = $2 AND status = 'active'",
        today, shift)
    active_drivers = await pool.fetchval(
        "SELECT COUNT(*) FROM drivers WHERE status = 'active'")
    mismatch_rows = await pool.fetch(
        "SELECT driver_id, name, phone, plate, category, status, mismatch_count, total_sij_month FROM drivers WHERE mismatch_count > 0 ORDER BY mismatch_count DESC LIMIT 50"
    )
    recent_sij_rows = await pool.fetch(
        "SELECT transaction_id, driver_id, driver_name, category, date, time, sheets, amount, qris_ref, admin_id, admin_name, shift, status, created_at FROM sij_transactions WHERE date = $1 AND shift = $2 AND status = 'active' ORDER BY created_at DESC LIMIT 20",
        today, shift)
    return {
        "sij_today_shift": sij_today_shift,
        "revenue_shift": revenue_shift,
        "active_drivers": active_drivers,
        "shift": shift,
        "today": today,
        "mismatch_list": rows_to_list(mismatch_rows),
        "recent_sij": rows_to_list(recent_sij_rows),
    }


@api_router.get("/dashboard/superadmin")
async def superadmin_dashboard(date: Optional[str] = Query(None),
                               user: dict = Depends(get_current_user)):
    if user.get('role') not in ['superadmin', 'viewer']:
        raise HTTPException(status_code=403, detail="Akses ditolak")
    now = datetime.now(JAKARTA_TZ)
    today = now.strftime("%Y-%m-%d")
    selected_date = date if date else today
    current_month = now.strftime("%Y-%m")
    month_prefix = f"{current_month}%"

    total_sij_today = await pool.fetchval(
        "SELECT COUNT(*) FROM sij_transactions WHERE date = $1 AND status = 'active'",
        selected_date)
    total_revenue_today = await pool.fetchval(
        "SELECT COALESCE(SUM(amount), 0) FROM sij_transactions WHERE date = $1 AND status = 'active'",
        selected_date)
    monthly_row = await pool.fetchrow(
        "SELECT COUNT(*) as sij, COALESCE(SUM(amount), 0) as rev FROM sij_transactions WHERE date LIKE $1 AND status = 'active'",
        month_prefix)
    monthly_sij = monthly_row['sij'] if monthly_row else 0
    monthly_revenue = monthly_row['rev'] if monthly_row else 0
    total_drivers = await pool.fetchval("SELECT COUNT(*) FROM drivers")
    active_drivers = await pool.fetchval(
        "SELECT COUNT(*) FROM drivers WHERE status = 'active'")
    suspended_drivers = await pool.fetchval(
        "SELECT COUNT(*) FROM drivers WHERE status = 'suspend'")
    shift1_sij = await pool.fetchval(
        "SELECT COUNT(*) FROM sij_transactions WHERE date = $1 AND shift = 'Shift1' AND status = 'active'",
        selected_date)
    shift2_sij = await pool.fetchval(
        "SELECT COUNT(*) FROM sij_transactions WHERE date = $1 AND shift = 'Shift2' AND status = 'active'",
        selected_date)
    category_rows = await pool.fetch(
        "SELECT category, COUNT(*) as cnt FROM sij_transactions WHERE date = $1 AND status = 'active' GROUP BY category",
        selected_date)
    sij_by_category = {"standar": 0, "premium": 0}
    for r in category_rows:
        cat = (r['category'] or 'standar').lower()
        if cat in sij_by_category:
            sij_by_category[cat] = r['cnt']
    daily_trend = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        row = await pool.fetchrow(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total FROM sij_transactions WHERE date = $1 AND status = 'active'",
            day)
        daily_trend.append({
            "date": day[5:],
            "sij": row['cnt'],
            "revenue": row['total']
        })

    mismatch_list = await pool.fetch(
        "SELECT driver_id, name, phone, plate, category, status, mismatch_count, total_sij_month FROM drivers WHERE mismatch_count > 0 ORDER BY mismatch_count DESC LIMIT 100"
    )
    ritase_ranking = await pool.fetch(
        "SELECT r.driver_id, r.driver_name, COUNT(*) as trip_count FROM ritase r WHERE r.date LIKE $1 GROUP BY r.driver_id, r.driver_name ORDER BY trip_count DESC LIMIT 10",
        month_prefix)
    total_ritase_today = await pool.fetchval(
        "SELECT COUNT(*) FROM ritase WHERE date = $1", selected_date)
    return {
        "selected_date":
        selected_date,
        "total_sij_today":
        total_sij_today,
        "total_revenue_today":
        total_revenue_today,
        "monthly_sij":
        monthly_sij,
        "monthly_revenue":
        monthly_revenue,
        "total_drivers":
        total_drivers,
        "active_drivers":
        active_drivers,
        "suspended_drivers":
        suspended_drivers,
        "total_ritase_today":
        total_ritase_today,
        "sij_by_category":
        sij_by_category,
        "ritase_ranking":
        rows_to_list(ritase_ranking),
        "sij_per_shift": [
            {
                "name": "Shift 1",
                "value": shift1_sij,
                "fill": "#10b981"
            },
            {
                "name": "Shift 2",
                "value": shift2_sij,
                "fill": "#0ea5e9"
            },
        ],
        "daily_trend":
        daily_trend,
        "mismatch_list":
        rows_to_list(mismatch_list),
    }


@api_router.get("/pool-dashboard")
async def get_pool_dashboard():
    today = datetime.now(JAKARTA_TZ).strftime("%Y-%m-%d")

    # 1. Ambil semua driver aktif
    all_drivers_rows = await pool.fetch(
        "SELECT driver_id, name, plate FROM drivers WHERE status = 'active'")
    all_drivers = rows_to_list(all_drivers_rows)

    # 2. Ambil driver yang absen hari ini
    absent_rows = await pool.fetch(
        "SELECT driver_id, reason FROM driver_absences WHERE date = $1", today)
    absent_map = {r['driver_id']: r['reason'] for r in absent_rows}

    # 3. Ambil transaksi SIJ hari ini untuk cari yang On-Duty
    sij_rows = await pool.fetch(
        """
        SELECT driver_id, MIN(time) as first_sij 
        FROM sij_transactions 
        WHERE date = $1 AND status = 'active'
        GROUP BY driver_id
    """, today)
    sij_map = {r['driver_id']: r['first_sij'] for r in sij_rows}

    active_list = []
    absent_list = []
    unknown_list = []

    # 4. Kelompokkan driver ke 3 kolom
    for d in all_drivers:
        did = d['driver_id']
        if did in sij_map:
            active_list.append({
                "name": d['name'],
                "plate": d['plate'],
                "time": str(sij_map[did])[:5]  # Ambil Jam:Menit saja
            })
        elif did in absent_map:
            absent_list.append({"name": d['name'], "reason": absent_map[did]})
        else:
            unknown_list.append({"name": d['name'], "plate": d['plate']})

    # Urutkan yang aktif berdasarkan jam masuk terbaru
    active_list.sort(key=lambda x: x['time'], reverse=True)

    return {
        "active": active_list,
        "absent": absent_list,
        "unknown": unknown_list
    }


# =================== AUDIT LOG ===================

AUDIT_SORT_COLS = {"date", "driver_id", "has_sij", "has_trip", "mismatch"}


@api_router.get("/audit")
async def get_audit_log(date: Optional[str] = None,
                        search: Optional[str] = None,
                        sort_by: str = "date",
                        sort_dir: str = "desc",
                        user: dict = Depends(require_superadmin)):
    conditions = []
    params = []
    idx = 1
    if date:
        conditions.append(f"date = ${idx}")
        params.append(date)
        idx += 1
    if search:
        conditions.append(f"driver_id ILIKE ${idx}")
        params.append(f"%{search}%")
        idx += 1
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    col = sort_by if sort_by in AUDIT_SORT_COLS else "date"
    direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
    rows = await pool.fetch(
        f"SELECT date, driver_id, has_sij, has_trip, mismatch FROM audit_log {where} ORDER BY {col} {direction} LIMIT 1000",
        *params)
    return rows_to_list(rows)


@api_router.get("/audit/export")
async def export_audit_csv(date: Optional[str] = None,
                           user: dict = Depends(require_superadmin)):
    if date:
        rows = await pool.fetch(
            "SELECT date, driver_id, has_sij, has_trip, mismatch FROM audit_log WHERE date = $1 ORDER BY date DESC",
            date)
    else:
        rows = await pool.fetch(
            "SELECT date, driver_id, has_sij, has_trip, mismatch FROM audit_log ORDER BY date DESC LIMIT 10000"
        )
    logs = rows_to_list(rows)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["date", "driver_id", "has_sij", "has_trip", "mismatch"])
    writer.writeheader()
    writer.writerows(logs)
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={
            "Content-Disposition":
            f"attachment; filename=audit_{date or 'all'}.csv"
        })


# =================== DRIVER ABSENCES ===================


@api_router.get("/absences")
async def get_absences(start_date: str = Query(...),
                       end_date: str = Query(...),
                       user: dict = Depends(get_current_user)):
    rows = await pool.fetch(
        "SELECT driver_id, date, reason FROM driver_absences WHERE date >= $1 AND date <= $2",
        start_date, end_date)
    return rows_to_list(rows)


@api_router.post("/absences")
async def set_absence(data: AbsenceRequest,
                      user: dict = Depends(require_admin)):
    if data.reason and data.reason not in ABSENCE_REASONS:
        raise HTTPException(status_code=400, detail="Alasan absen tidak valid")
    existing = await pool.fetchrow(
        "SELECT id FROM driver_absences WHERE driver_id = $1 AND date = $2",
        data.driver_id, data.date)
    if data.reason == "":
        if existing:
            await pool.execute(
                "DELETE FROM driver_absences WHERE driver_id = $1 AND date = $2",
                data.driver_id, data.date)
        return {"message": "Keterangan absen dihapus"}
    if existing:
        await pool.execute(
            "UPDATE driver_absences SET reason = $1 WHERE driver_id = $2 AND date = $3",
            data.reason, data.driver_id, data.date)
    else:
        await pool.execute(
            "INSERT INTO driver_absences (driver_id, date, reason) VALUES ($1, $2, $3)",
            data.driver_id, data.date, data.reason)
    return {"message": "Keterangan absen disimpan"}


@api_router.get("/absence-reasons")
async def get_absence_reasons(user: dict = Depends(get_current_user)):
    return ABSENCE_REASONS


# =================== WEEKLY REPORT (LAPORAN MINGGUAN) ===================


class ManualRitaseRequest(BaseModel):
    driver_id: str
    date: str
    manual_rts: int


@api_router.post("/manual-ritase")
async def set_manual_ritase(data: ManualRitaseRequest,
                            user: dict = Depends(require_admin)):
    await pool.execute(
        """INSERT INTO manual_ritase_override (driver_id, date, manual_rts, updated_by, updated_at)
           VALUES ($1, $2, $3, $4, NOW())
           ON CONFLICT (driver_id, date) DO UPDATE
           SET manual_rts = $3, updated_by = $4, updated_at = NOW()""",
        data.driver_id, data.date, data.manual_rts, user['name'])
    return {
        "driver_id": data.driver_id,
        "date": data.date,
        "manual_rts": data.manual_rts,
        "updated_by": user['name']
    }


@api_router.get("/weekly-report")
async def get_weekly_report(start_date: str = Query(...),
                            end_date: str = Query(...),
                            user: dict = Depends(get_current_user)):
    drivers = await pool.fetch(
        "SELECT driver_id, name, plate, category FROM drivers ORDER BY name")
    sij_rows = await pool.fetch(
        "SELECT DISTINCT driver_id, date FROM sij_transactions WHERE date >= $1 AND date <= $2 AND status = 'active'",
        start_date, end_date)
    ritase_rows = await pool.fetch(
        "SELECT driver_id, date, COUNT(*) as cnt FROM ritase WHERE date >= $1 AND date <= $2 GROUP BY driver_id, date",
        start_date, end_date)
    absence_rows = await pool.fetch(
        "SELECT driver_id, date, reason FROM driver_absences WHERE date >= $1 AND date <= $2",
        start_date, end_date)
    manual_rows = await pool.fetch(
        "SELECT driver_id, date, manual_rts FROM manual_ritase_override WHERE date >= $1 AND date <= $2",
        start_date, end_date)

    sij_set = set()
    for r in sij_rows:
        sij_set.add((r['driver_id'], r['date']))

    ritase_map = {}
    for r in ritase_rows:
        ritase_map[(r['driver_id'], r['date'])] = r['cnt']

    absence_map = {}
    for r in absence_rows:
        absence_map[(r['driver_id'], r['date'])] = r['reason']

    manual_map = {}
    for r in manual_rows:
        manual_map[(r['driver_id'], r['date'])] = r['manual_rts']

    from datetime import date as date_type
    start = date_type.fromisoformat(start_date)
    end = date_type.fromisoformat(end_date)
    num_days = (end - start).days + 1
    if num_days < 1:
        num_days = 1
    elif num_days > 31:
        num_days = 31
    days = []
    for i in range(num_days):
        d = start + timedelta(days=i)
        days.append(d.isoformat())

    result = []
    for drv in drivers:
        did = drv['driver_id']
        daily = []
        total_khd = 0
        total_rts = 0
        for day_str in days:
            khd = 1 if (did, day_str) in sij_set else 0
            auto_rts = ritase_map.get((did, day_str), 0)
            is_manual = (did, day_str) in manual_map
            rts = manual_map[(did, day_str)] if is_manual else auto_rts
            reason = absence_map.get((did, day_str), "")
            total_khd += khd
            total_rts += rts
            daily.append({
                "date": day_str,
                "khd": khd,
                "rts": rts,
                "reason": reason,
                "is_manual": is_manual,
            })
        result.append({
            "driver_id": did,
            "name": drv['name'],
            "plate": drv['plate'],
            "category": drv['category'],
            "daily": daily,
            "total_khd": total_khd,
            "total_rts": total_rts,
        })

    return {
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
        "drivers": result
    }


@api_router.get("/weekly-report/export/csv")
async def export_weekly_csv(start_date: str = Query(...),
                            end_date: str = Query(...),
                            user: dict = Depends(get_current_user)):
    report = await get_weekly_report(start_date, end_date, user)
    days = report["days"]
    day_labels = [f"Tgl {int(d.split('-')[2])}" for d in days]
    output = io.StringIO()
    header = ["No", "Nama Driver", "Nopol"]
    for dl in day_labels:
        header.extend([f"{dl} KHD", f"{dl} RTS"])
    header.extend(["Total KHD", "Total RTS"])
    writer = csv.writer(output)

    standar = [
        d for d in report["drivers"]
        if (d.get("category") or "standar") == "standar"
    ]
    premium = [
        d for d in report["drivers"]
        if (d.get("category") or "standar") == "premium"
    ]

    for cat_label, cat_drivers in [("DRIVER STANDAR", standar),
                                   ("DRIVER PREMIUM", premium)]:
        writer.writerow([])
        writer.writerow([cat_label])
        writer.writerow(header)
        for idx, drv in enumerate(cat_drivers, 1):
            row = [idx, drv["name"], drv["plate"]]
            for d in drv["daily"]:
                cell = d["reason"] if d["khd"] == 0 and d.get(
                    "reason") else d["khd"]
                row.extend([cell, d["rts"]])
            row.extend([drv["total_khd"], drv["total_rts"]])
            writer.writerow(row)

    writer.writerow([])
    writer.writerow(["KESIMPULAN"])
    low_standar = [d["name"] for d in standar if d["total_khd"] < 5]
    low_premium = [d["name"] for d in premium if d["total_khd"] < 5]
    writer.writerow([
        f"Driver Standar (KHD < 5): {len(low_standar)} driver -> {', '.join(low_standar) if low_standar else '-'}"
    ])
    writer.writerow([
        f"Driver Premium (KHD < 5): {len(low_premium)} driver -> {', '.join(low_premium) if low_premium else '-'}"
    ])

    output.seek(0)
    fname = f"laporan_mingguan_{start_date}_{end_date}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@api_router.get("/weekly-report/export/pdf")
async def export_weekly_pdf(start_date: str = Query(...),
                            end_date: str = Query(...),
                            user: dict = Depends(get_current_user)):
    report = await get_weekly_report(start_date, end_date, user)
    days = report["days"]
    day_labels = [f"Tgl {int(d.split('-')[2])}" for d in days]
    num_days = len(days)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf,
                            pagesize=landscape(A4),
                            leftMargin=10 * mm,
                            rightMargin=10 * mm,
                            topMargin=15 * mm,
                            bottomMargin=10 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('WTitle',
                                 parent=styles['Title'],
                                 fontSize=14,
                                 textColor=colors.HexColor('#1a1a1a'))
    sub_style = ParagraphStyle('WSub',
                               parent=styles['Normal'],
                               fontSize=8,
                               textColor=colors.HexColor('#555555'))
    cell_style = ParagraphStyle('WCell',
                                parent=styles['Normal'],
                                fontSize=5,
                                leading=6,
                                alignment=1)
    header_style = ParagraphStyle('WHead',
                                  parent=styles['Normal'],
                                  fontSize=6,
                                  leading=7,
                                  alignment=1,
                                  textColor=colors.white)
    cat_title_style = ParagraphStyle('WCatTitle',
                                     parent=styles['Heading2'],
                                     fontSize=11,
                                     textColor=colors.HexColor('#1a1a1a'),
                                     spaceAfter=4 * mm)
    summary_style = ParagraphStyle('WSummary',
                                   parent=styles['Normal'],
                                   fontSize=9,
                                   leading=13,
                                   textColor=colors.HexColor('#1a1a1a'))

    elements = [
        Paragraph("LAPORAN MINGGUAN - Alliansi SMF", title_style),
        Paragraph(f"Periode: {start_date} s/d {end_date}", sub_style),
        Spacer(1, 6 * mm),
    ]

    standar_drivers = [
        d for d in report["drivers"]
        if (d.get("category") or "standar") == "standar"
    ]
    premium_drivers = [
        d for d in report["drivers"]
        if (d.get("category") or "standar") == "premium"
    ]

    page_width = landscape(A4)[0]
    fixed_cols_width = (10 + 10 + 12 + 35 + 20 + 14 + 14) * mm
    day_col_width = max(14 * mm,
                        (page_width - fixed_cols_width) / num_days)
    col_widths = [12 * mm, 35 * mm, 20 * mm
                  ] + [day_col_width] * num_days + [14 * mm, 14 * mm]

    def build_table(cat_drivers):
        header = [
            Paragraph("No", header_style),
            Paragraph("Nama Driver", header_style),
            Paragraph("Nopol", header_style)
        ]
        for dl in day_labels:
            header.append(Paragraph(f"{dl}<br/>KHD|RTS", header_style))
        header.extend([
            Paragraph("Tot<br/>KHD", header_style),
            Paragraph("Tot<br/>RTS", header_style)
        ])
        tdata = [header]
        row_colors = []
        name_style = ParagraphStyle('WName', parent=cell_style, alignment=0)
        for idx, drv in enumerate(cat_drivers, 1):
            row = [
                Paragraph(str(idx), cell_style),
                Paragraph(drv["name"], name_style),
                Paragraph(drv["plate"], cell_style)
            ]
            for d in drv["daily"]:
                reason = d.get("reason", "")
                if d["khd"] == 0 and reason:
                    cell_text = f"<font color='#666666' size='4'>{reason}</font>"
                elif d["khd"] == 0 and d["rts"] > 0:
                    cell_text = f"<font color='red'><b>{d['khd']}|{d['rts']}</b></font>"
                else:
                    cell_text = f"{d['khd']}|{d['rts']}"
                row.append(Paragraph(cell_text, cell_style))
            khd_text = str(drv["total_khd"])
            if drv["total_khd"] < 5:
                khd_text = f"<font color='red'><b>{drv['total_khd']}</b></font>"
            row.append(Paragraph(khd_text, cell_style))
            row.append(Paragraph(str(drv["total_rts"]), cell_style))
            tdata.append(row)
            for di, d in enumerate(drv["daily"]):
                if d["khd"] == 0 and d["rts"] > 0 and not d.get("reason"):
                    row_colors.append(
                        ('BACKGROUND', (3 + di, idx), (3 + di, idx),
                         colors.HexColor('#FFD9D9')))
                elif d["khd"] == 0 and d.get("reason"):
                    row_colors.append(
                        ('BACKGROUND', (3 + di, idx), (3 + di, idx),
                         colors.HexColor('#FFF3CD')))
            if drv["total_khd"] < 5:
                row_colors.append(('BACKGROUND', (3 + num_days, idx),
                                   (3 + num_days, idx),
                                   colors.HexColor('#FFD9D9')))
        table = Table(tdata, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a1a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 5),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.white, colors.HexColor('#f5f5f5')]),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]
        style_cmds.extend(row_colors)
        table.setStyle(TableStyle(style_cmds))
        return table

    elements.append(Paragraph("Driver Standar", cat_title_style))
    elements.append(build_table(standar_drivers))
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph("Driver Premium", cat_title_style))
    elements.append(build_table(premium_drivers))
    elements.append(Spacer(1, 8 * mm))

    low_standar = [d["name"] for d in standar_drivers if d["total_khd"] < 5]
    low_premium = [d["name"] for d in premium_drivers if d["total_khd"] < 5]
    elements.append(Paragraph("<b>KESIMPULAN</b>", cat_title_style))
    elements.append(
        Paragraph(
            f"Driver Standar (KHD &lt; 5): <b>{len(low_standar)}</b> driver &rarr; {', '.join(low_standar) if low_standar else '-'}",
            summary_style))
    elements.append(Spacer(1, 2 * mm))
    elements.append(
        Paragraph(
            f"Driver Premium (KHD &lt; 5): <b>{len(low_premium)}</b> driver &rarr; {', '.join(low_premium) if low_premium else '-'}",
            summary_style))

    doc.build(elements)
    buf.seek(0)
    fname = f"laporan_mingguan_{start_date}_{end_date}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


# =================== MONTHLY PERIOD REPORT ===================

def _get_monthly_periods(month: str):
    """Return the four fixed Periode boundaries for a given YYYY-MM month.

    Periode definitions (inclusive on both ends):
      Periode 1 : days  1 –  7   (exactly 7 days)
      Periode 2 : days  8 – 14   (exactly 7 days)
      Periode 3 : days 15 – 21   (exactly 7 days)
      Periode 4 : days 22 – last day of month  (6–10 days depending on month)

    Key boundary rules to keep in mind:
      - Day 7  is the last day of Periode 1; day  8 is the first of Periode 2.
      - Day 14 is the last day of Periode 2; day 15 is the first of Periode 3.
      - Day 21 is the last day of Periode 3; day 22 is the first of Periode 4.
      - The last day of the month closes Periode 4 (calendar.monthrange handles
        leap-year February and 30/31-day months automatically).

    Raises ValueError if the month string is malformed or the computed
    boundaries would be inconsistent (e.g. last_day < 22 is impossible for any
    real calendar month but is checked defensively).
    """
    try:
        parts = month.split('-')
        if len(parts) != 2:
            raise ValueError(f"Expected YYYY-MM, got {month!r}")
        year, mon = int(parts[0]), int(parts[1])
        if not (1 <= mon <= 12):
            raise ValueError(f"Month value {mon} is out of range 1–12")
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid month string for _get_monthly_periods: {month!r}") from exc

    last_day = calendar.monthrange(year, mon)[1]

    # Defensive guard: every real calendar month has at least 28 days, so
    # last_day is always >= 22.  If somehow it is not, Periode 4 would have a
    # start date after its end date, which is a logic error we must catch early.
    if last_day < 22:
        raise ValueError(
            f"last_day={last_day} for {month} is less than 22; "
            "Periode 4 boundary (day 22 – last_day) would be invalid."
        )

    # Periode 1: days 1–7 (inclusive).  Day 7 is the boundary; day 8 starts P2.
    p1 = {"label": "Periode 1", "start": f"{month}-01", "end": f"{month}-07"}

    # Periode 2: days 8–14 (inclusive).  Day 14 is the boundary; day 15 starts P3.
    p2 = {"label": "Periode 2", "start": f"{month}-08", "end": f"{month}-14"}

    # Periode 3: days 15–21 (inclusive).  Day 21 is the boundary; day 22 starts P4.
    p3 = {"label": "Periode 3", "start": f"{month}-15", "end": f"{month}-21"}

    # Periode 4: days 22–last_day (inclusive).  last_day is computed by
    # calendar.monthrange so it correctly handles Feb 28/29, 30-day and 31-day
    # months without any integer-division arithmetic.
    p4 = {"label": "Periode 4", "start": f"{month}-22", "end": f"{month}-{last_day:02d}"}

    return [p1, p2, p3, p4]


def _assert_periods_cover_month(periods: list, month: str) -> None:
    """Validate that *periods* are contiguous and exactly span the whole month.

    Raises RuntimeError (surfaced as HTTP 500 by the caller) when any of the
    following invariants is violated:

    1. The first period starts on day 1 of *month*.
    2. Every consecutive pair of periods is contiguous: the day after period[i]
       ends must equal the day that period[i+1] starts (no gap, no overlap).
    3. The last period ends on the final calendar day of *month*.

    These checks are intentionally strict so that a regression in the boundary
    logic raises an explicit error instead of producing a silently incomplete
    report.
    """
    from datetime import date as _date, timedelta as _td

    try:
        parts = month.split('-')
        year, mon = int(parts[0]), int(parts[1])
    except Exception as exc:
        raise RuntimeError(f"_assert_periods_cover_month: bad month {month!r}") from exc

    last_day = calendar.monthrange(year, mon)[1]
    expected_start = _date(year, mon, 1)
    expected_end = _date(year, mon, last_day)

    if not periods:
        raise RuntimeError(
            f"Period coverage error for {month}: no periods were returned."
        )

    actual_start = _date.fromisoformat(periods[0]['start'])
    if actual_start != expected_start:
        raise RuntimeError(
            f"Period coverage error for {month}: first period starts on "
            f"{actual_start} but expected {expected_start} (day 1)."
        )

    for i in range(len(periods) - 1):
        cur_end = _date.fromisoformat(periods[i]['end'])
        next_start = _date.fromisoformat(periods[i + 1]['start'])
        expected_next = cur_end + _td(days=1)
        if next_start != expected_next:
            raise RuntimeError(
                f"Period coverage error for {month}: gap or overlap between "
                f"{periods[i]['label']} (ends {cur_end}) and "
                f"{periods[i + 1]['label']} (starts {next_start}); "
                f"expected next period to start on {expected_next}."
            )

    actual_end = _date.fromisoformat(periods[-1]['end'])
    if actual_end != expected_end:
        raise RuntimeError(
            f"Period coverage error for {month}: last period ends on "
            f"{actual_end} but expected {expected_end} (last day of month)."
        )


async def _build_monthly_report(month: str):
    from datetime import date as date_type
    try:
        parts = month.split('-')
        if len(parts) != 2:
            raise ValueError
        year, mon = int(parts[0]), int(parts[1])
        if not (1 <= mon <= 12) or year < 2000 or year > 2100:
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Format bulan tidak valid, gunakan YYYY-MM (contoh: 2026-04)")

    periods = _get_monthly_periods(month)
    try:
        _assert_periods_cover_month(periods, month)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    month_start = f"{month}-01"
    last_day = calendar.monthrange(year, mon)[1]
    month_end = f"{month}-{last_day:02d}"

    drivers = await pool.fetch(
        "SELECT driver_id, name, plate, category FROM drivers ORDER BY name")
    sij_rows = await pool.fetch(
        "SELECT DISTINCT driver_id, date FROM sij_transactions WHERE date >= $1 AND date <= $2 AND status = 'active'",
        month_start, month_end)
    ritase_rows = await pool.fetch(
        "SELECT driver_id, date, COUNT(*) as cnt FROM ritase WHERE date >= $1 AND date <= $2 GROUP BY driver_id, date",
        month_start, month_end)
    manual_rows = await pool.fetch(
        "SELECT driver_id, date, manual_rts FROM manual_ritase_override WHERE date >= $1 AND date <= $2",
        month_start, month_end)

    sij_set = set()
    for r in sij_rows:
        sij_set.add((r['driver_id'], r['date']))

    ritase_map = {}
    for r in ritase_rows:
        ritase_map[(r['driver_id'], r['date'])] = r['cnt']

    manual_map = {}
    for r in manual_rows:
        manual_map[(r['driver_id'], r['date'])] = r['manual_rts']

    result = []
    for drv in drivers:
        did = drv['driver_id']
        drv_periods = []
        total_khd = 0
        total_rts = 0
        for period in periods:
            p_start = date_type.fromisoformat(period['start'])
            p_end = date_type.fromisoformat(period['end'])
            khd = 0
            rts = 0
            cur = p_start
            while cur <= p_end:
                day_str = cur.isoformat()
                if (did, day_str) in sij_set:
                    khd += 1
                auto_rts = ritase_map.get((did, day_str), 0)
                day_rts = manual_map[(did, day_str)] if (did, day_str) in manual_map else auto_rts
                rts += day_rts
                cur += timedelta(days=1)
            fraud = (khd == 0 and rts > 0)
            drv_periods.append({"label": period['label'], "khd": khd, "rts": rts, "fraud": fraud})
            total_khd += khd
            total_rts += rts
        result.append({
            "driver_id": did,
            "name": drv['name'],
            "plate": drv['plate'],
            "category": drv['category'],
            "periods": drv_periods,
            "total_khd": total_khd,
            "total_rts": total_rts,
        })

    return {"month": month, "periods": periods, "drivers": result}


@api_router.get("/monthly-report/export/csv")
async def export_monthly_csv(month: str = Query(...),
                             user: dict = Depends(get_current_user)):
    report = await _build_monthly_report(month)
    output = io.StringIO()
    writer = csv.writer(output)
    header = ["No", "Nama Driver", "Nopol",
              "P1 KHD", "P1 RTS",
              "P2 KHD", "P2 RTS",
              "P3 KHD", "P3 RTS",
              "P4 KHD", "P4 RTS",
              "Total KHD", "Total RTS"]

    standar = [d for d in report["drivers"] if (d.get("category") or "standar") == "standar"]
    premium = [d for d in report["drivers"] if (d.get("category") or "standar") == "premium"]

    for cat_label, cat_drivers in [("DRIVER STANDAR", standar), ("DRIVER PREMIUM", premium)]:
        writer.writerow([])
        writer.writerow([cat_label])
        writer.writerow(header)
        for idx, drv in enumerate(cat_drivers, 1):
            row = [idx, drv["name"], drv["plate"]]
            for p in drv["periods"]:
                row.extend([p["khd"], p["rts"]])
            row.extend([drv["total_khd"], drv["total_rts"]])
            writer.writerow(row)

    writer.writerow([])
    writer.writerow(["KESIMPULAN"])
    low_standar = [d["name"] for d in standar if d["total_khd"] < 20]
    low_premium = [d["name"] for d in premium if d["total_khd"] < 20]
    writer.writerow([f"Driver Standar (KHD < 20): {len(low_standar)} driver -> {', '.join(low_standar) if low_standar else '-'}"])
    writer.writerow([f"Driver Premium (KHD < 20): {len(low_premium)} driver -> {', '.join(low_premium) if low_premium else '-'}"])

    output.seek(0)
    fname = f"laporan_bulanan_{month}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@api_router.get("/monthly-report/export/pdf")
async def export_monthly_pdf(month: str = Query(...),
                             user: dict = Depends(get_current_user)):
    report = await _build_monthly_report(month)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf,
                            pagesize=landscape(A4),
                            leftMargin=10 * mm,
                            rightMargin=10 * mm,
                            topMargin=15 * mm,
                            bottomMargin=10 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('MTitle', parent=styles['Title'], fontSize=14,
                                 textColor=colors.HexColor('#1a1a1a'))
    sub_style = ParagraphStyle('MSub', parent=styles['Normal'], fontSize=8,
                               textColor=colors.HexColor('#555555'))
    cell_style = ParagraphStyle('MCell', parent=styles['Normal'], fontSize=6,
                                leading=7, alignment=1)
    header_style = ParagraphStyle('MHead', parent=styles['Normal'], fontSize=6,
                                  leading=7, alignment=1, textColor=colors.white)
    cat_title_style = ParagraphStyle('MCatTitle', parent=styles['Heading2'],
                                     fontSize=11, textColor=colors.HexColor('#1a1a1a'),
                                     spaceAfter=4 * mm)
    summary_style = ParagraphStyle('MSummary', parent=styles['Normal'], fontSize=9,
                                   leading=13, textColor=colors.HexColor('#1a1a1a'))

    period_defs = report["periods"]
    period_labels = [p["label"] for p in period_defs]
    period_ranges = [f"{p['start'].split('-')[2]}-{p['end'].split('-')[2]}" for p in period_defs]

    col_widths = [10 * mm, 40 * mm, 22 * mm] + [28 * mm] * 4 + [16 * mm, 16 * mm]

    def build_table(cat_drivers):
        header_row = [
            Paragraph("No", header_style),
            Paragraph("Nama Driver", header_style),
            Paragraph("Nopol", header_style),
        ]
        for i, lbl in enumerate(period_labels):
            header_row.append(Paragraph(f"{lbl}<br/><font size='5'>{period_ranges[i]}</font><br/>KHD|RTS", header_style))
        header_row.extend([
            Paragraph("Tot<br/>KHD", header_style),
            Paragraph("Tot<br/>RTS", header_style),
        ])

        tdata = [header_row]
        row_colors = []
        name_style = ParagraphStyle('MName', parent=cell_style, alignment=0)

        for idx, drv in enumerate(cat_drivers, 1):
            row = [
                Paragraph(str(idx), cell_style),
                Paragraph(drv["name"], name_style),
                Paragraph(drv["plate"], cell_style),
            ]
            for pi, p in enumerate(drv["periods"]):
                if p["fraud"]:
                    cell_text = f"<font color='red'><b>{p['khd']}|{p['rts']}</b></font>"
                    row_colors.append(('BACKGROUND', (3 + pi, idx), (3 + pi, idx), colors.HexColor('#FFD9D9')))
                else:
                    cell_text = f"{p['khd']}|{p['rts']}"
                row.append(Paragraph(cell_text, cell_style))
            khd_text = str(drv["total_khd"])
            if drv["total_khd"] < 20:
                khd_text = f"<font color='red'><b>{drv['total_khd']}</b></font>"
                row_colors.append(('BACKGROUND', (7, idx), (7, idx), colors.HexColor('#FFD9D9')))
            row.append(Paragraph(khd_text, cell_style))
            row.append(Paragraph(str(drv["total_rts"]), cell_style))
            tdata.append(row)

        table = Table(tdata, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a1a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 6),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]
        style_cmds.extend(row_colors)
        table.setStyle(TableStyle(style_cmds))
        return table

    standar_drivers = [d for d in report["drivers"] if (d.get("category") or "standar") == "standar"]
    premium_drivers = [d for d in report["drivers"] if (d.get("category") or "standar") == "premium"]

    elements = [
        Paragraph("LAPORAN BULANAN - Alliansi SMF", title_style),
        Paragraph(f"Bulan: {month}", sub_style),
        Spacer(1, 6 * mm),
    ]
    elements.append(Paragraph("Driver Standar", cat_title_style))
    elements.append(build_table(standar_drivers))
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph("Driver Premium", cat_title_style))
    elements.append(build_table(premium_drivers))
    elements.append(Spacer(1, 8 * mm))

    low_standar = [d["name"] for d in standar_drivers if d["total_khd"] < 20]
    low_premium = [d["name"] for d in premium_drivers if d["total_khd"] < 20]
    elements.append(Paragraph("<b>KESIMPULAN</b>", cat_title_style))
    elements.append(Paragraph(
        f"Driver Standar (KHD &lt; 20): <b>{len(low_standar)}</b> driver &rarr; {', '.join(low_standar) if low_standar else '-'}",
        summary_style))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        f"Driver Premium (KHD &lt; 20): <b>{len(low_premium)}</b> driver &rarr; {', '.join(low_premium) if low_premium else '-'}",
        summary_style))

    doc.build(elements)
    buf.seek(0)
    fname = f"laporan_bulanan_{month}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@api_router.get("/monthly-report")
async def get_monthly_report(month: str = Query(...),
                             user: dict = Depends(get_current_user)):
    return await _build_monthly_report(month)


# =================== SEED DATA ===================

ADMIN_NAMES = {
    "admin1": "Admin 1",
    "admin2": "Admin 2",
    "admin3": "Admin 3",
    "admin4": "Admin 4",
    "superadmin": "Super Admin"
}
DRIVER_NAMES = [
    "Ahmad Rizki", "Budi Santoso", "Cahyo Purnomo", "Dedi Kurniawan",
    "Eko Prasetyo", "Fajar Nugroho", "Gunawan Susilo", "Hendra Saputra",
    "Irwan Haryanto", "Joko Wibowo", "Kartono Wijaya", "Lukman Hakim",
    "Mulyadi Utomo", "Nur Hidayat", "Oki Firmansyah", "Prayoga Adi",
    "Qusyairi Rahman", "Rizal Maulana", "Slamet Raharjo", "Teguh Santoso",
    "Umar Bakri", "Vino Putranto", "Wahyu Setiawan", "Xaverius Hadi",
    "Yudi Pradipta", "Zainal Abidin", "Agus Salim", "Bambang Riyadi",
    "Cepi Hidayat", "Dadang Suhendar", "Edi Kurniawan", "Fandi Cahyono",
    "Gilang Ramadhan", "Hari Prabowo", "Ismail Hasyim", "Jajang Suparman",
    "Kusno Widjajanto", "Latif Maulana", "Mamat Suryadi", "Nanda Permana",
    "Opan Sugianto", "Parman Hartono", "Qodir Fauzan", "Rohman Effendi",
    "Subhan Hamdani", "Taufik Hidayah", "Ujang Sopandi", "Vieri Kusuma",
    "Wawan Hernawan", "Yanto Siswanto"
]


async def create_tables():
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id VARCHAR(50) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            role VARCHAR(20) NOT NULL,
            shift VARCHAR(10),
            email VARCHAR(100) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS drivers (
            driver_id VARCHAR(50) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            phone VARCHAR(30),
            plate VARCHAR(20),
            category VARCHAR(20) DEFAULT 'standar',
            status VARCHAR(20) DEFAULT 'active',
            mismatch_count INTEGER DEFAULT 0,
            total_sij_month INTEGER DEFAULT 0
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS sij_transactions (
            transaction_id VARCHAR(100) PRIMARY KEY,
            driver_id VARCHAR(50) NOT NULL,
            driver_name VARCHAR(100),
            category VARCHAR(20),
            date VARCHAR(10),
            time VARCHAR(10),
            sheets INTEGER DEFAULT 5,
            amount INTEGER DEFAULT 0,
            qris_ref VARCHAR(100),
            admin_id VARCHAR(50),
            admin_name VARCHAR(100),
            shift VARCHAR(10),
            status VARCHAR(20) DEFAULT 'active',
            created_at TEXT
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            date VARCHAR(10) NOT NULL,
            driver_id VARCHAR(50) NOT NULL,
            has_sij BOOLEAN DEFAULT false,
            has_trip BOOLEAN DEFAULT false,
            mismatch BOOLEAN DEFAULT false,
            UNIQUE(date, driver_id)
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS ritase (
            id SERIAL PRIMARY KEY,
            driver_id VARCHAR(50) NOT NULL,
            driver_name VARCHAR(100),
            date VARCHAR(10) NOT NULL,
            waktu_ritase VARCHAR(20) DEFAULT '',
            notes TEXT DEFAULT '',
            admin_id VARCHAR(50),
            admin_name VARCHAR(100),
            shift VARCHAR(10),
            created_at TEXT
        )
    """)
    for col in ["trip_details", "origin", "destination", "passengers"]:
        try:
            await pool.execute(
                f"ALTER TABLE ritase DROP COLUMN IF EXISTS {col}")
        except Exception:
            pass
    try:
        await pool.execute(
            "ALTER TABLE ritase ADD COLUMN IF NOT EXISTS waktu_ritase VARCHAR(20) DEFAULT ''"
        )
    except Exception:
        pass
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS driver_absences (
            id SERIAL PRIMARY KEY,
            driver_id VARCHAR(50) NOT NULL,
            date VARCHAR(10) NOT NULL,
            reason VARCHAR(50) NOT NULL,
            UNIQUE(driver_id, date)
        )
    """)


async def seed_initial_data():
    superadmin_pwd = bcrypt.hashpw("superadmin123".encode(), bcrypt.gensalt()).decode()
    await pool.execute(
        "INSERT INTO users (user_id, name, role, shift, email, password_hash) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (user_id) DO UPDATE SET email=EXCLUDED.email, password_hash=EXCLUDED.password_hash, role=EXCLUDED.role",
        "superadmin", "Super Admin", "superadmin", None, "superadmin@raja.id", superadmin_pwd)

    count = await pool.fetchval("SELECT COUNT(*) FROM users")
    if count > 1:
        return
    logger.info("Seeding initial data...")
    users = [
        ("admin1", "Admin 1", "admin", "Shift1", "admin1@raja.id", "admin123"),
        ("admin2", "Admin 2", "admin", "Shift1", "admin2@raja.id", "admin123"),
        ("admin3", "Admin 3", "admin", "Shift2", "admin3@raja.id", "admin123"),
        ("admin4", "Admin 4", "admin", "Shift2", "admin4@raja.id", "admin123"),
        ("superadmin", "Super Admin", "superadmin", None, "superadmin@raja.id",
         "superadmin123"),
    ]
    for user_id, name, role, shift, email, pwd in users:
        password_hash = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
        await pool.execute(
            "INSERT INTO users (user_id, name, role, shift, email, password_hash) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING",
            user_id, name, role, shift, email, password_hash)

    SUSPEND_IDS = {"driver003", "driver007", "driver015"}
    WARNING_IDS = {"driver010", "driver020", "driver030", "driver040"}
    MISMATCH_DATA = {
        "driver001": 3,
        "driver005": 2,
        "driver012": 1,
        "driver023": 2,
        "driver037": 1
    }

    for i in range(50):
        did = f"driver{str(i+1).zfill(3)}"
        status = "suspend" if did in SUSPEND_IDS else (
            "warning" if did in WARNING_IDS else "active")
        await pool.execute(
            "INSERT INTO drivers (driver_id, name, phone, plate, category, status, mismatch_count, total_sij_month) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT DO NOTHING",
            did, DRIVER_NAMES[i], f"0812{str(10000000+i).zfill(8)}",
            f"B {1000+i} XY", "premium" if i % 3 == 0 else "standar", status,
            MISMATCH_DATA.get(did, 0), 0)

    active_dids = [
        f"driver{str(i+1).zfill(3)}" for i in range(50)
        if f"driver{str(i+1).zfill(3)}" not in SUSPEND_IDS
    ]
    used_per_day = {}
    for i in range(7):
        day = (datetime.now(JAKARTA_TZ) -
               timedelta(days=i)).strftime("%Y-%m-%d")
        used_per_day[day] = set()

    tx_count = 0
    attempts = 0
    while tx_count < 200 and attempts < 3000:
        attempts += 1
        day_offset = random.randint(0, 6)
        now_j = datetime.now(JAKARTA_TZ)
        day = (now_j - timedelta(days=day_offset)).strftime("%Y-%m-%d")
        date_compact = (now_j - timedelta(days=day_offset)).strftime("%Y%m%d")
        did = random.choice(active_dids)
        if did in used_per_day[day]:
            continue
        used_per_day[day].add(did)
        shift = random.choice(["Shift1", "Shift2"])
        admin_id = random.choice(["admin1", "admin2"] if shift ==
                                 "Shift1" else ["admin3", "admin4"])
        sheets = random.randint(1, 7)
        hour = random.randint(7, 16) if shift == "Shift1" else random.choice(
            list(range(17, 24)) + list(range(0, 7)))
        time_str = f"{str(hour).zfill(2)}:{random.randint(0,59):02d}:00"
        tx_id = f"{did}{date_compact}{random.randint(100,999)}"
        driver_idx = int(did[6:]) - 1
        await pool.execute(
            """INSERT INTO sij_transactions (transaction_id, driver_id, driver_name, category, date, time, sheets, amount, qris_ref, admin_id, admin_name, shift, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14) ON CONFLICT DO NOTHING""",
            tx_id, did, DRIVER_NAMES[driver_idx],
            "premium" if driver_idx % 3 == 0 else "standar", day, time_str,
            sheets, 40000, f"QRIS{random.randint(100000,999999)}", admin_id,
            ADMIN_NAMES[admin_id], shift, "active", f"{day}T{time_str}+07:00")
        tx_count += 1

    current_month = datetime.now(JAKARTA_TZ).strftime("%Y-%m")
    month_prefix = f"{current_month}%"
    for did in active_dids:
        cnt = await pool.fetchval(
            "SELECT COUNT(*) FROM sij_transactions WHERE driver_id = $1 AND date LIKE $2 AND status = 'active'",
            did, month_prefix)
        await pool.execute(
            "UPDATE drivers SET total_sij_month = $1 WHERE driver_id = $2",
            cnt, did)

    for day_offset in range(7):
        day = (datetime.now(JAKARTA_TZ) -
               timedelta(days=day_offset)).strftime("%Y-%m-%d")
        for did in active_dids[:30]:
            has_sij = did in used_per_day.get(day, set())
            has_trip = random.choice([True, True, False])
            await pool.execute(
                """INSERT INTO audit_log (date, driver_id, has_sij, has_trip, mismatch)
                VALUES ($1, $2, $3, $4, $5) ON CONFLICT (date, driver_id) DO NOTHING""",
                day, did, has_sij, has_trip, has_trip and not has_sij)

    logger.info(
        f"Seed selesai: 5 users, 50 drivers, {tx_count} SIJ transactions")


@app.on_event("startup")
async def startup_event():
    global pool
    database_url = os.environ.get('SUPABASE_DATABASE_URL') or os.environ.get(
        'DATABASE_URL')
    if not database_url:
        logger.warning(
            "SUPABASE_DATABASE_URL or DATABASE_URL environment variable is not set. "
            "Database features will be unavailable until configured."
        )
        return
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        pool_kwargs = dict(min_size=2, max_size=10, ssl=ssl_ctx)
        if 'pgbouncer=true' in database_url:
            database_url = database_url.replace('?pgbouncer=true',
                                                '').replace('&pgbouncer=true', '')
            pool_kwargs['statement_cache_size'] = 0
        pool = await asyncpg.create_pool(database_url, **pool_kwargs)
        await create_tables()
        await seed_initial_data()
        logger.info("Database connection established successfully.")
    except Exception as e:
        logger.warning(
            f"Failed to connect to database during startup: {e}. "
            "Server will continue running but database features will be unavailable."
        )


@app.on_event("shutdown")
async def shutdown_event():
    global pool
    if pool:
        await pool.close()


app.include_router(api_router)


import json as json_module

def _esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def _build_pool_html(data):
    active = data.get("active", [])
    absent = data.get("absent", [])
    unknown = data.get("unknown", [])

    active_html = ""
    for d in active:
        active_html += f'<div class="item item-active"><div><div class="name">{_esc(d["name"])}</div><div class="plate">{_esc(d["plate"])}</div></div><div style="text-align:right"><div class="time-val">{_esc(d["time"])}</div><div class="time-label">Input SIJ</div></div></div>'

    absent_html = ""
    for d in absent:
        absent_html += f'<div class="item item-absent"><div class="name" style="color:#d4d4d8">{_esc(d["name"])}</div><span class="reason-badge">{_esc(d["reason"])}</span></div>'

    unknown_html = ""
    for d in unknown:
        unknown_html += f'<div class="item item-unknown"><div><div class="name name-unknown">{_esc(d["name"])}</div><div class="plate plate-unknown">{_esc(d["plate"])}</div></div><span class="check-badge">Cek Keberadaan</span></div>'

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alliansi SMF — Command Center</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#09090b;color:#fff;font-family:system-ui,-apple-system,sans-serif;overflow:hidden}}
.header{{display:flex;justify-content:space-between;align-items:center;padding:24px;background:#18181b;border-bottom:2px solid #27272a}}
.title{{font-size:1.875rem;font-weight:900;color:#10b981;letter-spacing:0.05em}}
.subtitle{{color:#a1a1aa;font-size:1.125rem;margin-top:4px}}
.clock{{font-size:3rem;font-family:monospace;font-weight:700;color:#38bdf8;text-align:right}}
.date{{color:#a1a1aa;font-size:1.125rem;margin-top:4px;text-align:right}}
.grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:24px;padding:24px;flex:1;overflow:hidden}}
.col{{background:#18181b;border-radius:12px;padding:16px;box-shadow:0 4px 6px rgba(0,0,0,0.3);overflow-y:auto;display:flex;flex-direction:column}}
.col-active{{border-top:4px solid #10b981}}
.col-absent{{border-top:4px solid #71717a}}
.col-unknown{{border-top:4px solid #f43f5e}}
.col-title{{font-size:1.25rem;font-weight:700;margin-bottom:16px;display:flex;align-items:center;gap:8px}}
.col-title-active{{color:#34d399}}
.col-title-absent{{color:#d4d4d8}}
.col-title-unknown{{color:#fb7185}}
.pulse{{width:12px;height:12px;border-radius:50%;background:#10b981;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:0.5}}}}
@keyframes marquee{{0%{{transform:translateX(100%)}}100%{{transform:translateX(-100%)}}}}
.items{{flex:1;overflow-y:auto;scrollbar-width:none}}
.items::-webkit-scrollbar{{display:none}}
.item{{display:flex;justify-content:space-between;align-items:center;padding:12px;border-radius:8px;margin-bottom:8px}}
.item-active{{background:rgba(39,39,42,0.5);border:1px solid #3f3f46}}
.item-absent{{background:rgba(39,39,42,0.3);border:1px solid #27272a;opacity:0.7}}
.item-unknown{{background:rgba(244,63,94,0.1);border:1px solid rgba(244,63,94,0.2)}}
.name{{font-weight:700;font-size:1.125rem}}
.name-unknown{{color:#fecdd3}}
.plate{{color:#a1a1aa;font-size:0.875rem}}
.plate-unknown{{color:rgba(244,63,94,0.6)}}
.time-val{{color:#34d399;font-family:monospace;font-weight:700}}
.time-label{{color:#71717a;font-size:0.75rem}}
.reason-badge{{padding:4px 12px;background:#3f3f46;border-radius:9999px;font-size:0.75rem;font-weight:700;color:#d4d4d8}}
.check-badge{{padding:4px 12px;background:rgba(244,63,94,0.2);border-radius:9999px;font-size:0.75rem;font-weight:700;color:#fb7185}}
.banner{{background:linear-gradient(90deg,#10b981,#0ea5e9);padding:12px;color:#fff;font-weight:700;text-align:center;font-size:1.25rem;white-space:nowrap;overflow:hidden;display:flex;align-items:center}}
.banner-text{{animation:marquee 45s linear infinite;display:inline-block}}
.page{{display:flex;flex-direction:column;height:100vh}}
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <div>
      <div class="title">ALLIANSI SMF — COMMAND CENTER</div>
      <div class="subtitle">Status Kehadiran Mitra</div>
    </div>
    <div>
      <div class="clock" id="clock"></div>
      <div class="date" id="date"></div>
    </div>
  </div>
  <div class="grid">
    <div class="col col-active">
      <div class="col-title col-title-active"><span class="pulse"></span> ON-DUTY (HADIR)</div>
      <div class="items" id="active-list">{active_html}</div>
    </div>
    <div class="col col-absent">
      <div class="col-title col-title-absent">KONFIRMASI TIDAK HADIR</div>
      <div class="items" id="absent-list">{absent_html}</div>
    </div>
    <div class="col col-unknown">
      <div class="col-title col-title-unknown">BELUM HADIR</div>
      <div class="items" id="unknown-list">{unknown_html}</div>
    </div>
  </div>
  <div class="banner"><span class="banner-text">INFO: Tetap utamakan keselamatan kerja | Cek kondisi unit sebelum berangkat | Selalu gunakan seragam yang rapi selama beroperasi. &nbsp;&nbsp;&nbsp;&nbsp; INFO: Tetap utamakan keselamatan kerja | Cek kondisi unit sebelum berangkat | Selalu gunakan seragam yang rapi selama beroperasi.</span></div>
</div>
<script>
function updateClock(){{
  var now=new Date();
  document.getElementById('clock').textContent=now.toLocaleTimeString('id-ID');
  document.getElementById('date').textContent=now.toLocaleDateString('id-ID',{{weekday:'long',year:'numeric',month:'long',day:'numeric'}});
}}
setInterval(updateClock,1000);
updateClock();

function esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}}

function renderData(data){{
  var al=document.getElementById('active-list');
  var html='';
  (data.active||[]).forEach(function(d){{
    html+='<div class="item item-active"><div><div class="name">'+esc(d.name)+'</div><div class="plate">'+esc(d.plate)+'</div></div><div style="text-align:right"><div class="time-val">'+esc(d.time)+'</div><div class="time-label">Input SIJ</div></div></div>';
  }});
  al.innerHTML=html;

  var bl=document.getElementById('absent-list');
  html='';
  (data.absent||[]).forEach(function(d){{
    html+='<div class="item item-absent"><div class="name" style="color:#d4d4d8">'+esc(d.name)+'</div><span class="reason-badge">'+esc(d.reason)+'</span></div>';
  }});
  bl.innerHTML=html;

  var ul=document.getElementById('unknown-list');
  html='';
  (data.unknown||[]).forEach(function(d){{
    html+='<div class="item item-unknown"><div><div class="name name-unknown">'+esc(d.name)+'</div><div class="plate plate-unknown">'+esc(d.plate)+'</div></div><span class="check-badge">Cek Keberadaan</span></div>';
  }});
  ul.innerHTML=html;
}}

function autoScroll(container){{
  if(!container)return;
  var scrollSpeed=1;
  setInterval(function(){{
    container.scrollTop+=scrollSpeed;
    if(container.scrollTop>=container.scrollHeight-container.clientHeight){{
      container.scrollTop=0;
    }}
  }},50);
}}

var activeList=document.getElementById('active-list');
var absentList=document.getElementById('absent-list');
var unknownList=document.getElementById('unknown-list');
autoScroll(activeList);
autoScroll(absentList);
autoScroll(unknownList);

function fetchData(){{
  var x=new XMLHttpRequest();
  x.open('GET','/api/pool-dashboard',true);
  x.onload=function(){{
    if(x.status===200){{try{{renderData(JSON.parse(x.responseText))}}catch(e){{}}}}
  }};
  x.send();
}}
setInterval(fetchData,30000);
</script>
</body>
</html>"""


@app.get("/pool-dashboard", response_class=HTMLResponse)
async def pool_dashboard_page():
    data = await get_pool_dashboard()
    return _build_pool_html(data)


BUILD_DIR = Path(__file__).parent.parent / "frontend" / "build"
if BUILD_DIR.exists():
    app.mount("/static",
              StaticFiles(directory=str(BUILD_DIR / "static")),
              name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = BUILD_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(BUILD_DIR / "index.html"))
