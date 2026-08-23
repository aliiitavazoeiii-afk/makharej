from __future__ import annotations

import csv
import io
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import jdatetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

APP_NAME = os.getenv("APP_NAME", "خرج")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")
SECRET_KEY = os.getenv("APP_SECRET_KEY", "change-this-secret")
DB_PATH = os.getenv("DB_PATH", "/data/kharj.db")
TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Tehran"))
STATIC_DIR = Path(__file__).resolve().parent / "static"

MONTH_NAMES = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]
WEEKDAY_NAMES = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"]
DEFAULT_CATEGORIES = [
    ("خوراک و رستوران", "🍽", "#5b8cff"),
    ("حمل و نقل", "🚕", "#ffad45"),
    ("خرید", "🛍", "#9b7cff"),
    ("قبوض و شارژ", "⚡", "#57d3a4"),
    ("تفریح", "🎮", "#f87878"),
    ("سلامت", "💊", "#66c5e8"),
    ("خانه", "🏠", "#8dd36f"),
    ("سایر", "◌", "#8190aa"),
]


def db() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS categories (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          icon TEXT NOT NULL DEFAULT '◌',
          color TEXT NOT NULL DEFAULT '#5b8cff',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS expenses (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          amount INTEGER NOT NULL CHECK(amount > 0),
          category_id INTEGER NOT NULL,
          note TEXT NOT NULL DEFAULT '',
          expense_date TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);
        CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category_id);
        CREATE TABLE IF NOT EXISTS budgets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          category_id INTEGER NOT NULL,
          jyear INTEGER NOT NULL,
          jmonth INTEGER NOT NULL,
          amount INTEGER NOT NULL CHECK(amount >= 0),
          UNIQUE(category_id, jyear, jmonth),
          FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS bills (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          amount INTEGER NOT NULL CHECK(amount > 0),
          category_id INTEGER,
          due_date TEXT NOT NULL,
          recurring_monthly INTEGER NOT NULL DEFAULT 0,
          paid INTEGER NOT NULL DEFAULT 0,
          paid_at TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )
    count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    if count == 0:
        conn.executemany("INSERT INTO categories(name,icon,color) VALUES(?,?,?)", DEFAULT_CATEGORIES)
    conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('display_name','علی')")
    conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('monthly_budget','0')")
    conn.commit()
    conn.close()


def now_local() -> datetime:
    return datetime.now(TIMEZONE)


def today_local() -> date:
    return now_local().date()


def parse_amount(v: Any) -> int:
    s = str(v or "").strip().replace(",", "").replace("٬", "").replace(" ", "")
    fa = "۰۱۲۳۴۵۶۷۸۹"
    ar = "٠١٢٣٤٥٦٧٨٩"
    for i, d in enumerate(fa):
        s = s.replace(d, str(i))
    for i, d in enumerate(ar):
        s = s.replace(d, str(i))
    try:
        n = int(float(s))
    except Exception:
        raise HTTPException(400, "مبلغ نامعتبر است")
    if n <= 0:
        raise HTTPException(400, "مبلغ باید بیشتر از صفر باشد")
    return n


def to_jalali(d: date) -> jdatetime.date:
    return jdatetime.date.fromgregorian(date=d)


def format_jdate(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    j = to_jalali(d)
    return f"{j.day} {MONTH_NAMES[j.month - 1]} {j.year}"


def format_jdate_short(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    j = to_jalali(d)
    return f"{j.year}/{j.month:02d}/{j.day:02d}"


def parse_user_date(value: str | None) -> date:
    if not value:
        return today_local()
    raw = value.strip().replace(".", "/").replace("-", "/")
    fa = "۰۱۲۳۴۵۶۷۸۹"
    for i, d in enumerate(fa):
        raw = raw.replace(d, str(i))
    parts = raw.split("/")
    if len(parts) != 3:
        raise HTTPException(400, "تاریخ را مثل ۱۴۰۵/۰۶/۰۱ وارد کنید")
    try:
        y, m, d = map(int, parts)
        if y < 1700:
            return jdatetime.date(y, m, d).togregorian()
        return date(y, m, d)
    except Exception:
        raise HTTPException(400, "تاریخ نامعتبر است")


def jalali_month_bounds(jy: int, jm: int) -> tuple[date, date]:
    try:
        start = jdatetime.date(jy, jm, 1).togregorian()
        if jm == 12:
            next_start = jdatetime.date(jy + 1, 1, 1).togregorian()
        else:
            next_start = jdatetime.date(jy, jm + 1, 1).togregorian()
        return start, next_start - timedelta(days=1)
    except Exception:
        raise HTTPException(400, "ماه نامعتبر است")


def previous_jmonth(jy: int, jm: int) -> tuple[int, int]:
    return (jy - 1, 12) if jm == 1 else (jy, jm - 1)


def month_title(jy: int, jm: int) -> str:
    return f"{MONTH_NAMES[jm - 1]} {jy}"


def current_jmonth() -> tuple[int, int]:
    j = to_jalali(today_local())
    return j.year, j.month


def setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def require_admin(request: Request) -> None:
    if not request.session.get("admin"):
        raise HTTPException(status_code=401, detail="ابتدا وارد حساب شوید")


def rowdict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


class LoginIn(BaseModel):
    username: str
    password: str


class ExpenseIn(BaseModel):
    amount: Any
    category_id: int
    note: str = ""
    expense_date: str | None = None


class CategoryIn(BaseModel):
    name: str
    icon: str = "◌"
    color: str = "#5b8cff"


class BudgetIn(BaseModel):
    category_id: int
    amount: Any
    jyear: int | None = None
    jmonth: int | None = None


class BillIn(BaseModel):
    title: str
    amount: Any
    category_id: int | None = None
    due_date: str | None = None
    recurring_monthly: bool = False


class SettingsIn(BaseModel):
    display_name: str = "علی"
    monthly_budget: Any = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="strict",
    https_only=False,
    max_age=60 * 60 * 24 * 30,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
def health():
    return {"ok": True, "service": APP_NAME}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/me")
def me(request: Request):
    if not request.session.get("admin"):
        return {"authenticated": False}
    conn = db()
    name = setting(conn, "display_name", "علی")
    conn.close()
    return {"authenticated": True, "username": request.session.get("admin"), "display_name": name}


@app.post("/api/login")
def login(payload: LoginIn, request: Request):
    user_ok = secrets.compare_digest(payload.username.strip(), ADMIN_USERNAME)
    pass_ok = secrets.compare_digest(payload.password, ADMIN_PASSWORD)
    if not (user_ok and pass_ok):
        raise HTTPException(401, "نام کاربری یا رمز عبور اشتباه است")
    request.session["admin"] = ADMIN_USERNAME
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard(request: Request, jyear: int | None = None, jmonth: int | None = None):
    require_admin(request)
    jy, jm = current_jmonth()
    jy = jyear or jy
    jm = jmonth or jm
    start, end = jalali_month_bounds(jy, jm)
    prev_y, prev_m = previous_jmonth(jy, jm)
    prev_start, prev_end = jalali_month_bounds(prev_y, prev_m)
    today = today_local()

    conn = db()
    month_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()),
    ).fetchone()[0]
    today_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date=?",
        (today.isoformat(),),
    ).fetchone()[0]
    today_count = conn.execute("SELECT COUNT(*) FROM expenses WHERE expense_date=?", (today.isoformat(),)).fetchone()[0]
    prev_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date BETWEEN ? AND ?",
        (prev_start.isoformat(), prev_end.isoformat()),
    ).fetchone()[0]
    budget_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM budgets WHERE jyear=? AND jmonth=?", (jy, jm)
    ).fetchone()[0]
    fallback_budget = int(setting(conn, "monthly_budget", "0") or 0)
    budget_basis = budget_total if budget_total > 0 else fallback_budget
    remaining = budget_basis - month_total if budget_basis > 0 else 0
    current_j = to_jalali(today)
    elapsed_days = current_j.day if (jy, jm) == (current_j.year, current_j.month) else (end - start).days + 1
    elapsed_days = max(1, elapsed_days)
    avg_daily = round(month_total / elapsed_days)
    change_pct = round(((month_total - prev_total) / prev_total) * 100, 1) if prev_total else None

    cat_rows = conn.execute(
        """
        SELECT c.id,c.name,c.icon,c.color,COALESCE(SUM(e.amount),0) amount
        FROM categories c
        LEFT JOIN expenses e ON e.category_id=c.id AND e.expense_date BETWEEN ? AND ?
        GROUP BY c.id ORDER BY amount DESC,c.id
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    categories = []
    for r in cat_rows:
        item = dict(r)
        item["percentage"] = round(item["amount"] * 100 / month_total, 1) if month_total else 0
        categories.append(item)

    daily = []
    for offset in range(6, -1, -1):
        d = today - timedelta(days=offset)
        total = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date=?", (d.isoformat(),)).fetchone()[0]
        daily.append({
            "date": d.isoformat(),
            "label": "امروز" if offset == 0 else WEEKDAY_NAMES[d.weekday()],
            "short": format_jdate_short(d),
            "amount": total,
        })

    recent_rows = conn.execute(
        """
        SELECT e.id,e.amount,e.note,e.expense_date,e.created_at,c.name category,c.icon,c.color
        FROM expenses e JOIN categories c ON c.id=e.category_id
        ORDER BY e.expense_date DESC,e.id DESC LIMIT 8
        """
    ).fetchall()
    recent = []
    for r in recent_rows:
        item = dict(r)
        item["date_label"] = format_jdate(item["expense_date"])
        recent.append(item)

    bill_rows = conn.execute(
        """
        SELECT b.id,b.title,b.amount,b.due_date,b.recurring_monthly,c.name category,c.icon,c.color
        FROM bills b LEFT JOIN categories c ON c.id=b.category_id
        WHERE b.paid=0 ORDER BY b.due_date ASC LIMIT 6
        """
    ).fetchall()
    bills = []
    for r in bill_rows:
        item = dict(r)
        item["date_label"] = format_jdate(item["due_date"])
        item["overdue"] = item["due_date"] < today.isoformat()
        bills.append(item)

    budget_rows = conn.execute(
        """
        SELECT b.id,b.amount,c.id category_id,c.name,c.icon,c.color,
               COALESCE((SELECT SUM(e.amount) FROM expenses e WHERE e.category_id=c.id AND e.expense_date BETWEEN ? AND ?),0) spent
        FROM budgets b JOIN categories c ON c.id=b.category_id
        WHERE b.jyear=? AND b.jmonth=? ORDER BY b.amount DESC LIMIT 6
        """,
        (start.isoformat(), end.isoformat(), jy, jm),
    ).fetchall()
    budgets = []
    for r in budget_rows:
        item = dict(r)
        item["percentage"] = min(100, round(item["spent"] * 100 / item["amount"], 1)) if item["amount"] else 0
        budgets.append(item)

    top = next((c for c in categories if c["amount"] > 0), None)
    insight = None
    if top:
        prev_cat = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE category_id=? AND expense_date BETWEEN ? AND ?",
            (top["id"], prev_start.isoformat(), prev_end.isoformat()),
        ).fetchone()[0]
        delta = round(((top["amount"] - prev_cat) / prev_cat) * 100, 1) if prev_cat else None
        insight = {"category": top["name"], "amount": top["amount"], "change_pct": delta}

    display_name = setting(conn, "display_name", "علی")
    conn.close()
    return {
        "period": {"jyear": jy, "jmonth": jm, "title": month_title(jy, jm)},
        "display_name": display_name,
        "summary": {
            "today": today_total,
            "today_count": today_count,
            "month": month_total,
            "previous_month": prev_total,
            "change_pct": change_pct,
            "budget": budget_basis,
            "remaining": remaining,
            "average_daily": avg_daily,
        },
        "daily": daily,
        "categories": categories,
        "recent": recent,
        "bills": bills,
        "budgets": budgets,
        "insight": insight,
    }


@app.get("/api/expenses")
def list_expenses(request: Request, q: str = "", category_id: int | None = None, limit: int = 250):
    require_admin(request)
    conn = db()
    sql = """
      SELECT e.id,e.amount,e.note,e.expense_date,e.created_at,e.category_id,
             c.name category,c.icon,c.color
      FROM expenses e JOIN categories c ON c.id=e.category_id WHERE 1=1
    """
    params: list[Any] = []
    if q.strip():
        sql += " AND (e.note LIKE ? OR c.name LIKE ?)"
        term = f"%{q.strip()}%"
        params.extend([term, term])
    if category_id:
        sql += " AND e.category_id=?"
        params.append(category_id)
    sql += " ORDER BY e.expense_date DESC,e.id DESC LIMIT ?"
    params.append(min(max(limit, 1), 1000))
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["date_label"] = format_jdate(item["expense_date"])
        out.append(item)
    conn.close()
    return out


@app.post("/api/expenses")
def create_expense(payload: ExpenseIn, request: Request):
    require_admin(request)
    amount = parse_amount(payload.amount)
    exp_date = parse_user_date(payload.expense_date)
    note = payload.note.strip()[:250]
    conn = db()
    cat = conn.execute("SELECT id FROM categories WHERE id=?", (payload.category_id,)).fetchone()
    if not cat:
        conn.close()
        raise HTTPException(400, "دسته‌بندی پیدا نشد")
    cur = conn.execute(
        "INSERT INTO expenses(amount,category_id,note,expense_date) VALUES(?,?,?,?)",
        (amount, payload.category_id, note, exp_date.isoformat()),
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return {"ok": True, "id": item_id}


@app.delete("/api/expenses/{expense_id}")
def delete_expense(expense_id: int, request: Request):
    require_admin(request)
    conn = db()
    conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/categories")
def list_categories(request: Request):
    require_admin(request)
    conn = db()
    rows = conn.execute(
        """
        SELECT c.*,COUNT(e.id) expense_count,COALESCE(SUM(e.amount),0) total_spent
        FROM categories c LEFT JOIN expenses e ON e.category_id=c.id
        GROUP BY c.id ORDER BY c.id
        """
    ).fetchall()
    out = [dict(r) for r in rows]
    conn.close()
    return out


@app.post("/api/categories")
def create_category(payload: CategoryIn, request: Request):
    require_admin(request)
    name = payload.name.strip()[:50]
    if not name:
        raise HTTPException(400, "نام دسته‌بندی خالی است")
    color = payload.color if payload.color.startswith("#") and len(payload.color) in (4, 7) else "#5b8cff"
    conn = db()
    try:
        cur = conn.execute("INSERT INTO categories(name,icon,color) VALUES(?,?,?)", (name, payload.icon[:8] or "◌", color))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400, "این دسته‌بندی قبلاً وجود دارد")
    item_id = cur.lastrowid
    conn.close()
    return {"ok": True, "id": item_id}


@app.delete("/api/categories/{category_id}")
def delete_category(category_id: int, request: Request):
    require_admin(request)
    conn = db()
    used = conn.execute("SELECT COUNT(*) FROM expenses WHERE category_id=?", (category_id,)).fetchone()[0]
    if used:
        conn.close()
        raise HTTPException(400, "این دسته‌بندی تراکنش دارد و قابل حذف نیست")
    conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/budgets")
def list_budgets(request: Request, jyear: int | None = None, jmonth: int | None = None):
    require_admin(request)
    jy, jm = current_jmonth()
    jy, jm = jyear or jy, jmonth or jm
    start, end = jalali_month_bounds(jy, jm)
    conn = db()
    rows = conn.execute(
        """
        SELECT c.id category_id,c.name,c.icon,c.color,COALESCE(b.amount,0) amount,
               COALESCE((SELECT SUM(e.amount) FROM expenses e WHERE e.category_id=c.id AND e.expense_date BETWEEN ? AND ?),0) spent
        FROM categories c LEFT JOIN budgets b ON b.category_id=c.id AND b.jyear=? AND b.jmonth=?
        ORDER BY c.id
        """,
        (start.isoformat(), end.isoformat(), jy, jm),
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["remaining"] = item["amount"] - item["spent"]
        item["percentage"] = round(item["spent"] * 100 / item["amount"], 1) if item["amount"] else 0
        out.append(item)
    conn.close()
    return {"period": {"jyear": jy, "jmonth": jm, "title": month_title(jy, jm)}, "items": out}


@app.post("/api/budgets")
def save_budget(payload: BudgetIn, request: Request):
    require_admin(request)
    jy, jm = current_jmonth()
    jy, jm = payload.jyear or jy, payload.jmonth or jm
    amount = parse_amount(payload.amount) if str(payload.amount).strip() not in {"", "0"} else 0
    conn = db()
    conn.execute(
        """
        INSERT INTO budgets(category_id,jyear,jmonth,amount) VALUES(?,?,?,?)
        ON CONFLICT(category_id,jyear,jmonth) DO UPDATE SET amount=excluded.amount
        """,
        (payload.category_id, jy, jm, amount),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/bills")
def list_bills(request: Request):
    require_admin(request)
    conn = db()
    rows = conn.execute(
        """
        SELECT b.*,c.name category,c.icon,c.color FROM bills b
        LEFT JOIN categories c ON c.id=b.category_id
        ORDER BY b.paid ASC,b.due_date ASC,b.id DESC
        """
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["date_label"] = format_jdate(item["due_date"])
        out.append(item)
    conn.close()
    return out


@app.post("/api/bills")
def create_bill(payload: BillIn, request: Request):
    require_admin(request)
    title = payload.title.strip()[:80]
    if not title:
        raise HTTPException(400, "عنوان قبض خالی است")
    amount = parse_amount(payload.amount)
    due = parse_user_date(payload.due_date)
    conn = db()
    cur = conn.execute(
        "INSERT INTO bills(title,amount,category_id,due_date,recurring_monthly) VALUES(?,?,?,?,?)",
        (title, amount, payload.category_id, due.isoformat(), 1 if payload.recurring_monthly else 0),
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return {"ok": True, "id": item_id}


@app.post("/api/bills/{bill_id}/pay")
def pay_bill(bill_id: int, request: Request):
    require_admin(request)
    conn = db()
    bill = conn.execute("SELECT * FROM bills WHERE id=?", (bill_id,)).fetchone()
    if not bill:
        conn.close()
        raise HTTPException(404, "قبض پیدا نشد")
    if bill["paid"]:
        conn.close()
        return {"ok": True}
    category_id = bill["category_id"]
    if not category_id:
        category_id = conn.execute("SELECT id FROM categories ORDER BY id LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO expenses(amount,category_id,note,expense_date) VALUES(?,?,?,?)",
        (bill["amount"], category_id, f"پرداخت: {bill['title']}", today_local().isoformat()),
    )
    conn.execute("UPDATE bills SET paid=1,paid_at=CURRENT_TIMESTAMP WHERE id=?", (bill_id,))
    if bill["recurring_monthly"]:
        due_g = date.fromisoformat(bill["due_date"])
        due_j = to_jalali(due_g)
        if due_j.month == 12:
            next_j = jdatetime.date(due_j.year + 1, 1, min(due_j.day, 31))
        else:
            day = due_j.day
            while True:
                try:
                    next_j = jdatetime.date(due_j.year, due_j.month + 1, day)
                    break
                except ValueError:
                    day -= 1
        conn.execute(
            "INSERT INTO bills(title,amount,category_id,due_date,recurring_monthly) VALUES(?,?,?,?,1)",
            (bill["title"], bill["amount"], bill["category_id"], next_j.togregorian().isoformat()),
        )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/bills/{bill_id}")
def delete_bill(bill_id: int, request: Request):
    require_admin(request)
    conn = db()
    conn.execute("DELETE FROM bills WHERE id=?", (bill_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/report")
def report(request: Request, months: int = 6):
    require_admin(request)
    months = min(max(months, 1), 24)
    jy, jm = current_jmonth()
    periods: list[tuple[int, int]] = []
    cy, cm = jy, jm
    for _ in range(months):
        periods.append((cy, cm))
        cy, cm = previous_jmonth(cy, cm)
    periods.reverse()
    conn = db()
    monthly = []
    for py, pm in periods:
        start, end = jalali_month_bounds(py, pm)
        total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()[0]
        monthly.append({"jyear": py, "jmonth": pm, "label": MONTH_NAMES[pm - 1], "title": month_title(py, pm), "amount": total})
    cat = conn.execute(
        """
        SELECT c.name,c.icon,c.color,COALESCE(SUM(e.amount),0) amount
        FROM categories c LEFT JOIN expenses e ON e.category_id=c.id
        GROUP BY c.id ORDER BY amount DESC
        """
    ).fetchall()
    total_all = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses").fetchone()[0]
    count_all = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    biggest = conn.execute(
        """SELECT e.amount,e.note,e.expense_date,c.name category,c.icon
           FROM expenses e JOIN categories c ON c.id=e.category_id ORDER BY e.amount DESC LIMIT 1"""
    ).fetchone()
    conn.close()
    biggest_d = rowdict(biggest)
    if biggest_d:
        biggest_d["date_label"] = format_jdate(biggest_d["expense_date"])
    return {
        "monthly": monthly,
        "categories": [dict(r) for r in cat],
        "total": total_all,
        "count": count_all,
        "average": round(total_all / count_all) if count_all else 0,
        "biggest": biggest_d,
    }


@app.get("/api/settings")
def get_settings(request: Request):
    require_admin(request)
    conn = db()
    out = {
        "display_name": setting(conn, "display_name", "علی"),
        "monthly_budget": int(setting(conn, "monthly_budget", "0") or 0),
        "today_jalali": format_jdate_short(today_local()),
    }
    conn.close()
    return out


@app.post("/api/settings")
def save_settings(payload: SettingsIn, request: Request):
    require_admin(request)
    name = payload.display_name.strip()[:40] or "علی"
    raw = str(payload.monthly_budget or 0).strip()
    amount = 0 if raw in {"", "0"} else parse_amount(raw)
    conn = db()
    conn.execute("INSERT INTO settings(key,value) VALUES('display_name',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (name,))
    conn.execute("INSERT INTO settings(key,value) VALUES('monthly_budget',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(amount),))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/export.csv")
def export_csv(request: Request):
    require_admin(request)
    conn = db()
    rows = conn.execute(
        """
        SELECT e.expense_date,c.name category,e.note,e.amount
        FROM expenses e JOIN categories c ON c.id=e.category_id
        ORDER BY e.expense_date DESC,e.id DESC
        """
    ).fetchall()
    conn.close()
    stream = io.StringIO()
    stream.write("\ufeff")
    writer = csv.writer(stream)
    writer.writerow(["تاریخ میلادی", "تاریخ شمسی", "دسته‌بندی", "شرح", "مبلغ تومان"])
    for r in rows:
        writer.writerow([r["expense_date"], format_jdate_short(r["expense_date"]), r["category"], r["note"], r["amount"]])
    return Response(
        stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=kharj-expenses.csv"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
