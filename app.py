
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from pathlib import Path
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import sqlite3
import uuid
import os
import re
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

from utils.ocr import extract_text
from utils.expiry_detector import detect_dates
from utils.barcode_scanner import scan_barcode
from utils.product_rules import estimate_expiry, detect_category

app = Flask(__name__)
app.secret_key = "expirywatch-demo-secret-key"

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
DB_PATH = BASE_DIR / "expirywatch.db"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

CATEGORIES = [
    "Groceries / Food",
    "Dairy",
    "Cosmetics",
    "Personal Care",
    "Medicines",
    "Household",
    "Others",
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        category TEXT NOT NULL,
        photo TEXT,
        barcode TEXT,
        ocr_text TEXT,
        manufacturing_date TEXT,
        expiry_date TEXT,
        estimated_expiry TEXT,
        quantity INTEGER DEFAULT 1,
        purchase_date TEXT,
        confidence REAL DEFAULT 0,
        status TEXT DEFAULT 'Safe',
        notification_sent TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    conn.commit()
    conn.close()


def current_user_id():
    return session.get("user_id")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user_id():
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass
    for fmt in ("%m/%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def status_for(expiry_text):
    d = parse_date(expiry_text)
    if not d:
        return "Unknown"
    days = (d - date.today()).days
    if days < 0:
        return "Expired"
    if days <= 3:
        return "Expires Today" if days == 0 else "Expiring Soon"
    if days <= 10:
        return "Expiring Soon"
    return "Safe"


def days_left(expiry_text):
    d = parse_date(expiry_text)
    if not d:
        return None
    return (d - date.today()).days


def choose_expiry(result, estimated):
    return result.get("expiry_date") or estimated


def calculate_confidence(ocr_text, result):
    # Prefer the detector's evidence-based confidence.
    detector_score = result.get("confidence")
    if detector_score is not None:
        return round(float(detector_score), 2)
    return 0.0


def save_upload(file):
    if not file or not file.filename:
        return None
    ext = Path(file.filename).suffix.lower() or ".jpg"
    name = f"{uuid.uuid4().hex}{ext}"
    path = UPLOAD_FOLDER / name
    file.save(path)
    return f"uploads/{name}"


def email_settings_ready():
    return bool(os.getenv("EMAIL_USER") and os.getenv("EMAIL_PASSWORD"))


def send_email(to_email, subject, body):
    """Send a real email when SMTP credentials are configured."""
    user = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")
    if not user or not password or not to_email:
        return False
    host = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    port = int(os.getenv("EMAIL_PORT", "587"))
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)
        return True
    except Exception as exc:
        print("Email notification error:", exc)
        return False


def due_notice(row):
    expiry = row["expiry_date"] or row["estimated_expiry"]
    left = days_left(expiry)
    if left not in (10, 7, 3, 0):
        return None
    if left == 0:
        message = f"{row['product_name']} expires today."
        level = "urgent"
    elif left == 3:
        message = f"{row['product_name']} expires in 3 days."
        level = "urgent"
    else:
        message = f"{row['product_name']} expires in {left} days."
        level = "warning"
    return {"product": row["product_name"], "expiry": expiry, "days": left, "message": message, "level": level}


def process_email_notifications():
    """Check every user's due products and send each milestone only once."""
    if not email_settings_ready():
        return
    conn = get_db()
    users = conn.execute("SELECT id,name,email FROM users").fetchall()
    for user in users:
        rows = conn.execute("SELECT * FROM products WHERE user_id=?", (user["id"],)).fetchall()
        for row in rows:
            notice = due_notice(row)
            if not notice:
                continue
            token = str(notice["days"])
            sent = [x for x in (row["notification_sent"] or "").split(",") if x]
            if token in sent:
                continue
            subject = f"ExpiryWatch alert: {row['product_name']}"
            body = (
                f"Hello {user['name']},\n\n"
                f"ExpiryWatch reminder: {row['product_name']} {'expires today' if notice['days'] == 0 else 'expires in ' + str(notice['days']) + ' days'}.\n"
                f"Expiry date: {notice['expiry']}\n"
                f"Category: {row['category']}\n\n"
                "Open your ExpiryWatch dashboard to review your inventory.\n\n"
                "— ExpiryWatch"
            )
            if send_email(user["email"], subject, body):
                sent.append(token)
                conn.execute("UPDATE products SET notification_sent=? WHERE id=?", (",".join(sorted(set(sent))), row["id"]))
    conn.commit()
    conn.close()


def notification_worker():
    while True:
        try:
            process_email_notifications()
        except Exception as exc:
            print("Notification worker error:", exc)
        time.sleep(60)


@app.route("/")
@login_required
def index():
    user_id = current_user_id()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM products WHERE user_id=? ORDER BY id DESC", (user_id,)
    ).fetchall()
    conn.close()

    products = []
    for row in rows:
        item = dict(row)
        final_expiry = item["expiry_date"] or item["estimated_expiry"]
        item["days_left"] = days_left(final_expiry)
        item["status"] = status_for(final_expiry)
        products.append(item)

    return render_template(
        "index.html",
        products=products,
        categories=CATEGORIES,
        today=date.today().isoformat()
    )


@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    incoming = []

    # Front photo identifies the actual product and is always stored/displayed.
    front = request.files.get("front_product_image")
    additional = request.files.getlist("product_images")

    # Backward compatibility with the older UI.
    if not front or not front.filename:
        front = request.files.get("front_image")
    if not front or not front.filename:
        # If only the old multi-photo field is used, take its first image as front.
        if additional:
            front = additional[0]
            additional = additional[1:]

    if not front or not front.filename:
        return jsonify({"error": "Please upload the front product photo."}), 400

    incoming = [front] + [f for f in additional if f and f.filename]

    # Optional old date image field.
    date_img = request.files.get("date_image")
    if date_img and date_img.filename:
        incoming.append(date_img)

    ocr_parts = []
    barcode = None
    saved_photo = None

    for index, file in enumerate(incoming):
        saved = save_upload(file)
        if index == 0:
            saved_photo = saved  # front product photo

        disk_path = UPLOAD_FOLDER / Path(saved).name
        text = extract_text(str(disk_path))
        if text:
            ocr_parts.append(text)

        if not barcode:
            barcode = scan_barcode(str(disk_path))

    ocr_text = "\n".join(ocr_parts).strip()
    result = detect_dates(ocr_text)

    estimated = None
    if not result.get("expiry_date") and result.get("manufacturing_date"):
        estimated = estimate_expiry(ocr_text, result["manufacturing_date"])

    expiry = choose_expiry(result, estimated)
    confidence = calculate_confidence(ocr_text, result)

    product_name = request.form.get("product_name", "").strip()
    category = request.form.get("category", "").strip()

    if not product_name:
        product_name = detect_category(ocr_text)[1]

    if not category:
        category = detect_category(ocr_text)[0]

    response = {
        "ocr_text": ocr_text,
        "barcode": barcode,
        "product_name": product_name or "Unknown Product",
        "category": category or "Others",
        "expiry_date": result.get("expiry_date"),
        "manufacturing_date": result.get("manufacturing_date"),
        "estimated_expiry": estimated,
        "shelf_life_months": result.get("shelf_life_months"),
        "confidence": confidence,
        "status": status_for(expiry),
        "note": result.get("note"),
        "date_source": result.get("date_source", "none"),
        "photo": saved_photo,
    }
    return jsonify(response)


@app.route("/api/recalculate-expiry", methods=["POST"])
@login_required
def recalculate_expiry():
    data = request.get_json(silent=True) or {}
    mfg = (data.get("manufacturing_date") or "").strip()
    shelf = data.get("shelf_life_months")
    if not mfg or not shelf:
        return jsonify({"expiry_date": None, "error": "MFG date and package shelf life are required."}), 400
    try:
        from utils.product_rules import parse_manufacturing_date
        mfg_date = parse_manufacturing_date(mfg)
        months = int(shelf)
        if not mfg_date or not (1 <= months <= 120):
            raise ValueError
        expiry = (mfg_date + relativedelta(months=months)).strftime("%m/%Y")
        return jsonify({"expiry_date": expiry})
    except Exception:
        return jsonify({"expiry_date": None, "error": "Enter a valid MFG date such as 03/2024."}), 400


@app.route("/products", methods=["POST"])
@login_required
def add_product():
    user_id = current_user_id()
    product_name = request.form.get("product_name", "Unknown Product").strip() or "Unknown Product"
    category = request.form.get("category", "Others")
    barcode = request.form.get("barcode", "")
    mfg = request.form.get("manufacturing_date", "")
    expiry = request.form.get("expiry_date", "")
    estimated = request.form.get("estimated_expiry", "")
    quantity = max(1, int(request.form.get("quantity", 1) or 1))
    purchase_date = request.form.get("purchase_date") or date.today().isoformat()
    photo = request.form.get("photo", "")
    ocr_text = request.form.get("ocr_text", "")
    confidence = float(request.form.get("confidence", 0) or 0)

    final_expiry = expiry or estimated
    status = status_for(final_expiry)

    conn = get_db()
    conn.execute("""
        INSERT INTO products(
            user_id,product_name,category,photo,barcode,ocr_text,
            manufacturing_date,expiry_date,estimated_expiry,
            quantity,purchase_date,confidence,status,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        user_id, product_name, category, photo, barcode, ocr_text,
        mfg, expiry, estimated, quantity, purchase_date,
        confidence, status, datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

    return redirect(url_for("index"))


@app.route("/delete/<int:product_id>", methods=["POST"])
@login_required
def delete_product(product_id):
    conn = get_db()
    row = conn.execute(
        "SELECT photo FROM products WHERE id=? AND user_id=?",
        (product_id, current_user_id())
    ).fetchone()

    if row:
        conn.execute(
            "DELETE FROM products WHERE id=? AND user_id=?",
            (product_id, current_user_id())
        )
        conn.commit()

        if row["photo"]:
            p = BASE_DIR / "static" / row["photo"]
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

    conn.close()
    return redirect(url_for("index"))



@app.route("/edit/<int:product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM products WHERE id=? AND user_id=?", (product_id, current_user_id())).fetchone()
    if not row:
        conn.close()
        flash("Product not found.")
        return redirect(url_for("index"))

    if request.method == "POST":
        product_name = request.form.get("product_name", "").strip() or "Unknown Product"
        category = request.form.get("category", "Others").strip() or "Others"
        mfg = request.form.get("manufacturing_date", "").strip()
        expiry = request.form.get("expiry_date", "").strip()
        quantity = max(1, int(request.form.get("quantity", 1) or 1))
        status = status_for(expiry)
        conn.execute("""UPDATE products SET product_name=?, category=?, manufacturing_date=?, expiry_date=?, estimated_expiry=?, quantity=?, status=? WHERE id=? AND user_id=?""",
                     (product_name, category, mfg, expiry, "" if expiry else row["estimated_expiry"], quantity, status, product_id, current_user_id()))
        conn.commit()
        conn.close()
        flash("Product updated successfully.")
        return redirect(url_for("index"))

    product = dict(row)
    conn.close()
    return render_template("edit.html", product=product, categories=CATEGORIES)

@app.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    conn = get_db()
    sql = "SELECT * FROM products WHERE user_id=?"
    params = [current_user_id()]

    if q:
        sql += " AND (product_name LIKE ? OR barcode LIKE ? OR ocr_text LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    if category and category != "All":
        sql += " AND category=?"
        params.append(category)

    sql += " ORDER BY id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    products = []
    for row in rows:
        item = dict(row)
        final_expiry = item["expiry_date"] or item["estimated_expiry"]
        item["days_left"] = days_left(final_expiry)
        item["status"] = status_for(final_expiry)
        products.append(item)

    return render_template(
        "index.html",
        products=products,
        categories=CATEGORIES,
        today=date.today().isoformat(),
        query=q,
        selected_category=category
    )


@app.route("/api/stats")
@login_required
def stats():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM products WHERE user_id=?", (current_user_id(),)
    ).fetchall()
    conn.close()

    total = len(rows)
    safe = soon = expired = unknown = 0
    category_counts = {}

    for r in rows:
        status = status_for(r["expiry_date"] or r["estimated_expiry"])
        if status == "Safe":
            safe += 1
        elif status in ("Expiring Soon", "Expires Today"):
            soon += 1
        elif status == "Expired":
            expired += 1
        else:
            unknown += 1

        category_counts[r["category"]] = category_counts.get(r["category"], 0) + 1

    return jsonify({
        "total": total,
        "safe": safe,
        "soon": soon,
        "expired": expired,
        "unknown": unknown,
        "categories": category_counts
    })



@app.route("/api/notifications")
@login_required
def notifications():
    # Also checks email immediately, so alerts do not depend on a page refresh.
    process_email_notifications()
    conn = get_db()
    rows = conn.execute("SELECT * FROM products WHERE user_id=? ORDER BY id DESC", (current_user_id(),)).fetchall()
    user = conn.execute("SELECT email FROM users WHERE id=?", (current_user_id(),)).fetchone()
    conn.close()
    notices = []
    for r in rows:
        notice = due_notice(r)
        if notice:
            notices.append(notice)
    return jsonify({
        "notifications": notices,
        "email_configured": email_settings_ready(),
        "email": user["email"] if user else ""
    })



@app.route("/history")
@login_required
def history():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM products WHERE user_id=? AND status='Expired' ORDER BY id DESC",
        (current_user_id(),)
    ).fetchall()
    conn.close()
    return render_template("history.html", products=[dict(r) for r in rows])


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user_id():
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()

        valid = False
        if user:
            stored = user["password"] or ""
            try:
                valid = check_password_hash(stored, password)
            except ValueError:
                # Backward compatibility for older local databases that stored plain passwords.
                valid = stored == password
        if valid:
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("index"))

        flash("Email or password is incorrect. If you are new, create an account first.")
    return render_template("login.html", mode=request.args.get("mode", "login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user_id():
        return redirect(url_for("index"))
    if request.method == "GET":
        return render_template("login.html", mode="register")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if len(name) < 2 or "@" not in email or len(password) < 6:
        flash("Enter a valid name, email and password (6+ characters).")
        return redirect(url_for("register"))

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users(name,email,password,created_at) VALUES(?,?,?,?)",
            (name, email, generate_password_hash(password), datetime.now().isoformat())
        )
        conn.commit()
        session.clear()
        session["user_id"] = cur.lastrowid
        session["user_name"] = name
        return redirect(url_for("index"))
    except sqlite3.IntegrityError:
        flash("An account with this email already exists. Please sign in.")
        return redirect(url_for("login"))
    finally:
        conn.close()


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    init_db()
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        threading.Thread(target=notification_worker, daemon=True).start()
    app.run(debug=True)
