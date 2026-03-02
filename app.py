
import os

import psycopg2
from psycopg2.extras import RealDictCursor
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
DEFAULT_COMPANY_ID = int(os.environ.get("COMPANY_ID", "1"))


# -------------------------------------------------
# Database helpers
# -------------------------------------------------
def get_db():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)


def users_has_pin(cur) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='users' AND column_name='pin'
        """
    )
    return cur.fetchone() is not None


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # -------------------------------------------------
    # 1) Optional full reset (ONLY when RESET_DB == "1")
    # -------------------------------------------------
    if os.environ.get("RESET_DB") == "1":
        cur.execute("DROP TABLE IF EXISTS reports CASCADE;")
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")
        cur.execute("DROP TABLE IF EXISTS companies CASCADE;")
        conn.commit()

    # -------------------------------------------------
    # 2) Ensure companies exists (needed for FK)
    # -------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            contact_email TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # -------------------------------------------------
    # 3) If users exists but is old (no pin), self-heal by dropping users+reports
    # -------------------------------------------------
    cur.execute("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema='public' AND table_name='users'
    """)
    users_exists = cur.fetchone() is not None

    if users_exists and not users_has_pin(cur):
        # old schema -> drop and rebuild (prevents crash)
        cur.execute("DROP TABLE IF EXISTS reports CASCADE;")
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")
        conn.commit()
        users_exists = False  # will be recreated below

    # -------------------------------------------------
    # 4) Create users WITHOUT global unique(name)
    #    then add UNIQUE(company_id, name)
    # -------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            pin TEXT NOT NULL,
            company_id INTEGER NOT NULL REFERENCES companies(id),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Reports
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id),
            datum TEXT,
            baustelle TEXT,
            arbeit TEXT,
            material TEXT,
            bemerkung TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # -------------------------------------------------
    # 5) Migration: remove old UNIQUE(name) if present, then enforce UNIQUE(company_id, name)
    # -------------------------------------------------
    try:
        # Find and drop any unique constraint that is ONLY on (name)
        cur.execute("""
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'users'
              AND c.contype = 'u'
        """)
        constraints = [r["conname"] for r in cur.fetchall()]

        for conname in constraints:
            # Check which columns are inside this constraint
            cur.execute("""
                SELECT a.attname
                FROM pg_attribute a
                JOIN pg_index i ON i.indrelid = a.attrelid AND a.attnum = ANY(i.indkey)
                JOIN pg_constraint c ON c.conindid = i.indexrelid
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname='users' AND c.conname=%s
                ORDER BY a.attnum
            """, (conname,))
            cols = [x["attname"] for x in cur.fetchall()]

            # If it's exactly ['name'] -> drop it
            if cols == ["name"]:
                cur.execute(f'ALTER TABLE users DROP CONSTRAINT "{conname}";')
                conn.commit()

        # Create the correct unique constraint if not exists
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    WHERE t.relname='users' AND c.conname='users_company_id_name_key'
                ) THEN
                    ALTER TABLE users
                    ADD CONSTRAINT users_company_id_name_key UNIQUE (company_id, name);
                END IF;
            END $$;
        """)
        conn.commit()

    except Exception:
        # If migration fails for any reason, fallback: rebuild users+reports cleanly
        conn.rollback()
        cur.execute("DROP TABLE IF EXISTS reports CASCADE;")
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")
        conn.commit()

        # Recreate clean
        cur.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                pin TEXT NOT NULL,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                created_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT users_company_id_name_key UNIQUE (company_id, name)
            );
        """)
        cur.execute("""
            CREATE TABLE reports (
                id SERIAL PRIMARY KEY,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                datum TEXT,
                baustelle TEXT,
                arbeit TEXT,
                material TEXT,
                bemerkung TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        conn.commit()

    # -------------------------------------------------
    # 6) Seed demo company and demo user
    # -------------------------------------------------
    cur.execute("""
        INSERT INTO companies (id, name, contact_email)
        VALUES (1, 'Demo Firma', 'demo@firma.de')
        ON CONFLICT (id) DO NOTHING;
    """)

    cur.execute("""
        INSERT INTO users (name, pin, company_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (company_id, name) DO NOTHING;
    """, ("Suad", "1234", 1))

    conn.commit()
    cur.close()
    conn.close()


# Init once at startup
init_db()


# -------------------------------------------------
# Auth helpers
# -------------------------------------------------
def is_logged_in():
    return "user_id" in session and "company_id" in session


def current_company_id() -> int:
    return int(session.get("company_id", DEFAULT_COMPANY_ID))


# -------------------------------------------------
# Health
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

        if not name or not pin:
            flash("Bitte Name und PIN eingeben.", "error")
            return render_template("login.html")

        conn = get_db()
        cur = conn.cursor()
        # NOTE: name+pin can exist in multiple companies, but pin should differ.
        # We'll log in to the first match. Better UX later: ask for company or show list.
        cur.execute(
            "SELECT id, name, company_id FROM users WHERE name = %s AND pin = %s",
            (name, pin),
        )
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            session.clear()
            session["user_id"] = int(user["id"])
            session["name"] = user["name"]
            session["company_id"] = int(user["company_id"])
            return redirect(url_for("index"))

        flash("Falscher Name oder PIN.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------------------------------
# Register company + admin (protected)
# -------------------------------------------------
@app.route("/register-company", methods=["GET", "POST"])
def register_company():
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
            return "Bitte alle Pflichtfelder ausfüllen.", 400

        conn = get_db()
        cur = conn.cursor()

        # Create company
        cur.execute(
            """
            INSERT INTO companies (name, contact_email)
            VALUES (%s, %s)
            RETURNING id;
            """,
            (company_name, company_email or None),
        )
        company_id = int(cur.fetchone()["id"])

        # Create admin user for that company
        cur.execute(
            """
            INSERT INTO users (name, pin, company_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (company_id, name) DO UPDATE
            SET pin = EXCLUDED.pin;
            """,
            (admin_name, admin_pin, company_id),
        )

        conn.commit()
        cur.close()
        conn.close()

        return (
            f"OK ✅ Company created (id={company_id}). "
            f"Admin login: {admin_name} / PIN: {admin_pin}"
        )

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

    company_id = current_company_id()

    if request.method == "POST":
        datum = request.form.get("datum")
        baustelle = request.form.get("baustelle")
        arbeit = request.form.get("arbeit")
        material = request.form.get("material")
        bemerkung = request.form.get("bemerkung")

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO reports (company_id, datum, baustelle, arbeit, material, bemerkung)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (company_id, datum, baustelle, arbeit, material, bemerkung),
        )
        conn.commit()
        cur.close()
        conn.close()

        flash("Bericht gespeichert.", "success")
        return redirect(url_for("index"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM reports WHERE company_id = %s ORDER BY id DESC LIMIT 30",
        (company_id,),
    )
    reports = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("index.html", reports=reports)


# -------------------------------------------------
# List
# -------------------------------------------------
@app.route("/list")
def list_reports():
    if not is_logged_in():
        return redirect(url_for("login"))

    company_id = current_company_id()

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM reports WHERE company_id = %s ORDER BY id DESC",
        (company_id,),
    )
    reports = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("list.html", reports=reports)


# -------------------------------------------------
# Run locally
# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)