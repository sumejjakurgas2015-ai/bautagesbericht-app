
import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session

# -------------------------------------------------
# App setup
# -------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

DATABASE = os.path.join(BASE_DIR, "bautagesbericht.db")

# For "multi-company" (Korak 1)
# Later ćemo ovo zamijeniti pravim login/company sistemom po firmi.
COMPANY_ID = int(os.environ.get("COMPANY_ID", "1"))


# -------------------------------------------------
# Database helpers
# -------------------------------------------------
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables + seed minimal data. Run once at startup."""
    conn = get_db()
    cur = conn.cursor()

    # Companies
    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact_email TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Users (each user belongs to a company)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            pin TEXT NOT NULL,
            company_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)

    # Reports (each report belongs to a company)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            datum TEXT,
            baustelle TEXT,
            arbeit TEXT,
            material TEXT,
            bemerkung TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)

    # Seed: default company (id=1 typically)
    cur.execute(
        "INSERT OR IGNORE INTO companies (id, name, contact_email) VALUES (?, ?, ?)",
        (1, "Demo Firma", "demo@firma.de")
    )

    # Seed: default user for demo (belongs to company 1)
    # PROMIJENI PIN kasnije!
    cur.execute(
        "INSERT OR IGNORE INTO users (name, pin, company_id) VALUES (?, ?, ?)",
        ("Suad", "1234", 1)
    )

    conn.commit()
    conn.close()


# Run DB init once when app starts (not on every request!)
init_db()


# -------------------------------------------------
# Auth helpers
# -------------------------------------------------
def is_logged_in():
    return "user_id" in session


# -------------------------------------------------
# Health route (Render test)
# -------------------------------------------------
@app.route("/health")
def health():
    return "OK", 200


# -------------------------------------------------
# Login / Logout
# -------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        pin = (request.form.get("pin") or "").strip()

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE name = ? AND pin = ?",
            (name, pin)
        ).fetchone()
        conn.close()

        if user:
            session["user_id"] = int(user["id"])
            session["name"] = user["name"]
            session["company_id"] = int(user["company_id"])
            return redirect(url_for("index"))
        else:
            flash("Falscher Name oder PIN.", "error")

    return render_template("login.html")
@app.route("/list")
def list_reports():
    if not is_logged_in():
        return redirect(url_for("login"))

    company_id = session.get("company_id", COMPANY_ID)

    conn = get_db()
    reports = conn.execute(
        "SELECT * FROM reports WHERE company_id = ? ORDER BY id DESC",
        (company_id,)
    ).fetchall()
    conn.close()

    return render_template("list.html", reports=reports)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
@app.route("/register-company", methods=["GET", "POST"])
def register_company():
    # jednostavna zaštita: samo ako znaš ADMIN_MASTER_KEY
    master_key = os.environ.get("ADMIN_MASTER_KEY", "")
    key = request.args.get("key", "")

    if not master_key or key != master_key:
        return "Forbidden", 403

    if request.method == "POST":
        company_name = (request.form.get("company_name") or "").strip()
        company_email = (request.form.get("company_email") or "").strip()
        admin_name = (request.form.get("admin_name") or "").strip()
        admin_pin = (request.form.get("admin_pin") or "").strip()

        if not company_name or not admin_name or not admin_pin:
            flash("Bitte alle Pflichtfelder ausfüllen.", "error")
            return redirect(url_for("register_company", key=key))

        conn = get_db()
        cur = conn.cursor()

        # 1) kreiraj firmu
        cur.execute(
            "INSERT INTO companies (name, contact_email) VALUES (?, ?)",
            (company_name, company_email if company_email else None)
        )
        company_id = cur.lastrowid

        # 2) kreiraj admin usera za tu firmu
        cur.execute(
            "INSERT INTO users (name, pin, company_id) VALUES (?, ?, ?)",
            (admin_name, admin_pin, company_id)
        )

        conn.commit()
        conn.close()

        return f"OK. Company created (id={company_id}). Admin login: {admin_name}"

    return """
    <h2>Register Company</h2>
    <form method="post">
      <label>Company Name*</label><br>
      <input name="company_name" required><br><br>

      <label>Company Email</label><br>
      <input name="company_email"><br><br>

      <label>Admin Name*</label><br>
      <input name="admin_name" required><br><br>

      <label>Admin PIN*</label><br>
      <input name="admin_pin" required><br><br>

      <button type="submit">Create</button>
    </form>
    """
@app.route("/routes")
def routes():
    return "<br>".join(sorted([str(r) for r in app.url_map.iter_rules()]))

# -------------------------------------------------
# Home / Index
# -------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if not is_logged_in():
        return redirect(url_for("login"))

    company_id = session.get("company_id", COMPANY_ID)

    if request.method == "POST":
        datum = request.form.get("datum")
        baustelle = request.form.get("baustelle")
        arbeit = request.form.get("arbeit")
        material = request.form.get("material")
        bemerkung = request.form.get("bemerkung")

        conn = get_db()
        conn.execute(
            """
            INSERT INTO reports (company_id, datum, baustelle, arbeit, material, bemerkung, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                datum,
                baustelle,
                arbeit,
                material,
                bemerkung,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        conn.close()

        flash("Bericht gespeichert.", "success")
        return redirect(url_for("index"))

    conn = get_db()
    reports = conn.execute(
        "SELECT * FROM reports WHERE company_id = ? ORDER BY id DESC",
        (company_id,)
    ).fetchall()
    conn.close()

    return render_template("index.html", reports=reports)


# -------------------------------------------------
# Create admin / demo user via ENV (optional)
# -------------------------------------------------
@app.route("/create-admin")
def create_admin():
    admin_name = os.environ.get("ADMIN_NAME")
    admin_pin = os.environ.get("ADMIN_PIN")

    if not admin_name or not admin_pin:
        return "ADMIN_NAME and ADMIN_PIN not set", 400

    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO users (name, pin, company_id) VALUES (?, ?, ?)",
        (admin_name, admin_pin, 1)
    )
    conn.commit()
    conn.close()

    return "Admin created or already exists.", 200


# -------------------------------------------------
# Run locally
# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)