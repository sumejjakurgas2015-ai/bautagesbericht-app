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


# -------------------------------------------------
# Database
# -------------------------------------------------
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    # ----------------------------
    # USERS tabela (reset jednom)
    # ----------------------------
    conn.execute("DROP TABLE IF EXISTS Users;")   # stara tabela
    conn.execute("DROP TABLE IF EXISTS users;")   # ako postoji neka druga

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            pin TEXT NOT NULL
        )
    """)

    # default user
    conn.execute(
        "INSERT OR IGNORE INTO users (name, pin) VALUES (?, ?)",
        ("Suad", "1234")
    )

    conn.commit()

    # (ostali CREATE TABLE za reports ostaju kako već imaš)
    conn.close()


@app.before_request
def before_request():
    init_db()


# -------------------------------------------------
# Helper
# -------------------------------------------------
def login_required():
    return "user_id" in session


# -------------------------------------------------
# Health route (Render test)
# -------------------------------------------------
@app.route("/health")
def health():
    return "OK", 200


# -------------------------------------------------
# Login
# -------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name")
        pin = request.form.get("pin")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE name=? AND pin=?",
            (name, pin)
        ).fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            return redirect(url_for("index"))
        else:
            flash("Falscher Name oder PIN.", "error")

    return render_template("login.html")


# -------------------------------------------------
# Initialize database
# -------------------------------------------------
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # Companies table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS companies (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        contact_email TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)

    # Reports table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        ...
    );
    """)

    conn.commit()
    cur.close()
    conn.close()


    if user:
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            return redirect(url_for("index"))
    else:
            flash("Falscher Name oder PIN.", "error")

    return render_template("login.html")


# -------------------------------------------------
# Logout
# -------------------------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------------------------------
# Home / Index
# -------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if not login_required():
        return redirect(url_for("login"))

    if request.method == "POST":
        datum = request.form.get("datum")
        baustelle = request.form.get("baustelle")
        arbeit = request.form.get("arbeit")

        conn = get_db()
        conn.execute(
            "INSERT INTO reports (datum, baustelle, arbeit, created_at) VALUES (?, ?, ?, ?)",
            (datum, baustelle, arbeit, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
        conn.close()

        flash("Bericht gespeichert.", "success")
        return redirect(url_for("index"))

    conn = get_db()
    reports = conn.execute("SELECT * FROM reports ORDER BY id DESC").fetchall()
    def init_db():
    conn = get_db()

    # ----------------------------
    # USERS tabela (reset jednom)
    # ----------------------------
    conn.execute("DROP TABLE IF EXISTS Users;")   # stara tabela
    conn.execute("DROP TABLE IF EXISTS users;")   # ako postoji neka druga

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            pin TEXT NOT NULL
        )
    """)

    # default user
    conn.execute(
        "INSERT OR IGNORE INTO users (name, pin) VALUES (?, ?)",
        ("Suad", "1234")
    )

    conn.commit()

    # (ostali CREATE TABLE za reports ostaju kako već imaš)
    conn.close()
    conn.close()

    return render_template("index.html", reports=reports)


# -------------------------------------------------
# Add user (admin only via env)
# -------------------------------------------------
@app.route("/create-admin")
def create_admin():
    admin_name = os.environ.get("ADMIN_NAME")
    admin_pin = os.environ.get("ADMIN_PIN")

    if not admin_name or not admin_pin:
        return "ADMIN_NAME and ADMIN_PIN not set", 400

    conn = get_db()
        # RESET USERS tabela (samo jednom)
    
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            pin TEXT
        )
    """)
        conn.commit()
        conn.execute("""
        INSERT OR IGNORE INTO users (name, pin)
        VALUES (?, ?)
    """, ("Suad", "1234"))
    except:
        pass
    conn.close()

    return "Admin created or already exists."


# -------------------------------------------------
# Run locally
# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
