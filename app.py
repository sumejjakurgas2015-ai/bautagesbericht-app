import os
from datetime import date
from io import BytesIO

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_file,
)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
DEFAULT_COMPANY_ID = int(os.environ.get("COMPANY_ID", "1"))


def get_db():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)


def add_column_if_missing(cur, table_name, column_name, column_def):
    cur.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name=%s AND column_name=%s
        """,
        (table_name, column_name),
    )
    if not cur.fetchone():
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT,
            pin TEXT,
            role TEXT,
            company_id INTEGER REFERENCES companies(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            datum TEXT,
            wetter TEXT,
            arbeitszeit_von TEXT,
            arbeitszeit_bis TEXT,
            pause_stunden NUMERIC,
            netto_stunden NUMERIC,
            baustelle TEXT,
            team TEXT,
            arbeit TEXT,
            material TEXT,
            bemerkung TEXT
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


init_db()


@app.route("/health")
def health():
    return "OK", 200


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        company = request.form.get("company")
        name = request.form.get("name")
        pin = request.form.get("pin")

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT u.id, u.company_id FROM users u
            JOIN companies c ON u.company_id=c.id
            WHERE LOWER(c.name)=LOWER(%s)
            AND LOWER(u.name)=LOWER(%s)
            AND u.pin=%s
        """, (company, name, pin))

        user = cur.fetchone()

        if user:
            session["user_id"] = user["id"]
            session["company_id"] = user["company_id"]
            return redirect("/")

        flash("Login failed")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.context_processor
def inject_user():
    return dict(user=session.get("user_id"))


@app.route("/", methods=["GET", "POST"])
def index():
    if "user_id" not in session:
        return redirect("/login")

    company_id = session["company_id"]

    if request.method == "POST":
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO reports (
                company_id, datum, wetter,
                arbeitszeit_von, arbeitszeit_bis,
                pause_stunden, netto_stunden,
                baustelle, team, arbeit, material, bemerkung
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            company_id,
            request.form.get("datum"),
            request.form.get("wetter"),
            request.form.get("arbeitszeit_von"),
            request.form.get("arbeitszeit_bis"),
            request.form.get("pause_stunden"),
            request.form.get("netto_stunden"),
            request.form.get("baustelle"),
            request.form.get("team"),
            request.form.get("arbeit"),
            request.form.get("material"),
            request.form.get("bemerkung"),
        ))

        conn.commit()
        cur.close()
        conn.close()

        return redirect("/")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM reports WHERE company_id=%s", (company_id,))
    reports = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("index.html", reports=reports)


if __name__ == "__main__":
    app.run()