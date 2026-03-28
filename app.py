import os
from io import BytesIO
from datetime import date

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


def add_column_if_missing(cur, table_name: str, column_name: str, column_def: str):
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s AND column_name=%s
        """,
        (table_name, column_name),
    )
    exists = cur.fetchone() is not None
    if not exists:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def};")


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # -------------------------------------------------
    # 1) Optional full reset
    # -------------------------------------------------
    if os.environ.get("RESET_DB") == "1":
        cur.execute("DROP TABLE IF EXISTS reports CASCADE;")
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")
        cur.execute("DROP TABLE IF EXISTS companies CASCADE;")
        conn.commit()

    # -------------------------------------------------
    # 2) Companies
    # -------------------------------------------------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            contact_email TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    # -------------------------------------------------
    # 3) Users
    # -------------------------------------------------
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema='public' AND table_name='users'
        """
    )
    users_exists = cur.fetchone() is not None

    if users_exists and not users_has_pin(cur):
        cur.execute("DROP TABLE IF EXISTS reports CASCADE;")
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")
        conn.commit()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            pin TEXT NOT NULL,
            company_id INTEGER NOT NULL REFERENCES companies(id),
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    # -------------------------------------------------
    # 4) Reports base table
    # -------------------------------------------------
    cur.execute(
        """
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
        """
    )

    # -------------------------------------------------
    # 5) Reports extra columns used in templates
    # -------------------------------------------------
    add_column_if_missing(cur, "reports", "wetter", "TEXT")
    add_column_if_missing(cur, "reports", "arbeitszeit_von", "TEXT")
    add_column_if_missing(cur, "reports", "arbeitszeit_bis", "TEXT")
    add_column_if_missing(cur, "reports", "pause_stunden", "NUMERIC")
    add_column_if_missing(cur, "reports", "netto_stunden", "NUMERIC")
    add_column_if_missing(cur, "reports", "team", "TEXT")

    add_column_if_missing(cur, "reports", "polier_name", "TEXT")
    add_column_if_missing(cur, "reports", "polier_stunden", "NUMERIC")
    add_column_if_missing(cur, "reports", "vorarbeiter_name", "TEXT")
    add_column_if_missing(cur, "reports", "vorarbeiter_stunden", "NUMERIC")
    add_column_if_missing(cur, "reports", "facharbeiter_name", "TEXT")
    add_column_if_missing(cur, "reports", "facharbeiter_stunden", "NUMERIC")
    add_column_if_missing(cur, "reports", "elektriker_name", "TEXT")
    add_column_if_missing(cur, "reports", "elektriker_stunden", "NUMERIC")
    add_column_if_missing(cur, "reports", "helfer_name", "TEXT")
    add_column_if_missing(cur, "reports", "helfer_stunden", "NUMERIC")
    add_column_if_missing(cur, "reports", "lkw_fahrer_name", "TEXT")
    add_column_if_missing(cur, "reports", "lkw_fahrer_stunden", "NUMERIC")

    conn.commit()

    # -------------------------------------------------
    # 6) Unique constraint users(company_id, name)
    # -------------------------------------------------
    try:
        cur.execute(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'users'
              AND c.contype = 'u'
            """
        )
        constraints = [r["conname"] for r in cur.fetchall()]

        for conname in constraints:
            cur.execute(
                """
                SELECT a.attname
                FROM pg_attribute a
                JOIN pg_index i ON i.indrelid = a.attrelid AND a.attnum = ANY(i.indkey)
                JOIN pg_constraint c ON c.conindid = i.indexrelid
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname='users' AND c.conname=%s
                ORDER BY a.attnum
                """,
                (conname,),
            )
            cols = [x["attname"] for x in cur.fetchall()]
            if cols == ["name"]:
                cur.execute(f'ALTER TABLE users DROP CONSTRAINT "{conname}";')
                conn.commit()

        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    WHERE t.relname='users'
                      AND c.conname='users_company_id_name_key'
                ) THEN
                    ALTER TABLE users
                    ADD CONSTRAINT users_company_id_name_key UNIQUE (company_id, name);
                END IF;
            END $$;
            """
        )
        conn.commit()

    except Exception:
        conn.rollback()

    # -------------------------------------------------
    # 7) Seed demo company and demo user
    # -------------------------------------------------
    cur.execute(
        """
        INSERT INTO companies (id, name, contact_email)
        VALUES (1, 'Demo Firma', 'demo@firma.de')
        ON CONFLICT (id) DO NOTHING;
        """
    )

    cur.execute(
        """
        INSERT INTO users (name, pin, company_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (company_id, name) DO NOTHING;
        """,
        ("Suad", "1234", 1),
    )

    conn.commit()
    cur.close()
    conn.close()


# Init once at startup
init_db()


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def is_logged_in():
    return "user_id" in session and "company_id" in session


def current_company_id() -> int:
    return int(session.get("company_id", DEFAULT_COMPANY_ID))


def to_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def calculate_netto_hours(von: str, bis: str, pause_hours: float) -> float:
    try:
        if not von or not bis:
            return 0.0
        h1, m1 = map(int, von.split(":"))
        h2, m2 = map(int, bis.split(":"))
        start = h1 * 60 + m1
        end = h2 * 60 + m2
        total = (end - start) / 60.0
        netto = total - pause_hours
        return round(max(netto, 0), 2)
    except Exception:
        return 0.0


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
# Register company + admin
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

        cur.execute(
            """
            INSERT INTO companies (name, contact_email)
            VALUES (%s, %s)
            RETURNING id;
            """,
            (company_name, company_email or None),
        )
        company_id = int(cur.fetchone()["id"])

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
        wetter = request.form.get("wetter")
        arbeitszeit_von = request.form.get("arbeitszeit_von")
        arbeitszeit_bis = request.form.get("arbeitszeit_bis")
        pause_stunden = to_float(request.form.get("pause_stunden"), 0.0)
        netto_stunden = calculate_netto_hours(
            arbeitszeit_von, arbeitszeit_bis, pause_stunden
        )

        baustelle = request.form.get("baustelle")
        team = request.form.get("team")

        polier_name = request.form.get("polier_name")
        polier_stunden = to_float(request.form.get("polier_stunden"), 0.0)
        vorarbeiter_name = request.form.get("vorarbeiter_name")
        vorarbeiter_stunden = to_float(request.form.get("vorarbeiter_stunden"), 0.0)
        facharbeiter_name = request.form.get("facharbeiter_name")
        facharbeiter_stunden = to_float(request.form.get("facharbeiter_stunden"), 0.0)
        elektriker_name = request.form.get("elektriker_name")
        elektriker_stunden = to_float(request.form.get("elektriker_stunden"), 0.0)
        helfer_name = request.form.get("helfer_name")
        helfer_stunden = to_float(request.form.get("helfer_stunden"), 0.0)
        lkw_fahrer_name = request.form.get("lkw_fahrer_name")
        lkw_fahrer_stunden = to_float(request.form.get("lkw_fahrer_stunden"), 0.0)

        arbeit = request.form.get("arbeit")
        material = request.form.get("material")
        bemerkung = request.form.get("bemerkung")

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO reports (
                company_id, datum, wetter,
                arbeitszeit_von, arbeitszeit_bis, pause_stunden, netto_stunden,
                baustelle, team,
                polier_name, polier_stunden,
                vorarbeiter_name, vorarbeiter_stunden,
                facharbeiter_name, facharbeiter_stunden,
                elektriker_name, elektriker_stunden,
                helfer_name, helfer_stunden,
                lkw_fahrer_name, lkw_fahrer_stunden,
                arbeit, material, bemerkung
            )
            VALUES (
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s
            )
            """,
            (
                company_id, datum, wetter,
                arbeitszeit_von, arbeitszeit_bis, pause_stunden, netto_stunden,
                baustelle, team,
                polier_name, polier_stunden,
                vorarbeiter_name, vorarbeiter_stunden,
                facharbeiter_name, facharbeiter_stunden,
                elektriker_name, elektriker_stunden,
                helfer_name, helfer_stunden,
                lkw_fahrer_name, lkw_fahrer_stunden,
                arbeit, material, bemerkung,
            ),
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

    return render_template(
        "index.html",
        reports=reports,
        heute=date.today().isoformat(),
    )


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
# Detail
# -------------------------------------------------
@app.route("/detail/<int:report_id>")
def detail(report_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    company_id = current_company_id()

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM reports WHERE id = %s AND company_id = %s",
        (report_id, company_id),
    )
    report = cur.fetchone()
    cur.close()
    conn.close()

    if not report:
        return "Bericht nicht gefunden", 404

    return render_template("detail.html", report=report)


# -------------------------------------------------
# Users
# -------------------------------------------------
@app.route("/users")
def users_list():
    if not is_logged_in():
        return redirect(url_for("login"))

    company_id = current_company_id()

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, company_id, created_at
        FROM users
        WHERE company_id = %s
        ORDER BY id DESC
        """,
        (company_id,),
    )
    users = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("users.html", users=users)


@app.route("/users/add", methods=["GET", "POST"])
def users_add():
    if not is_logged_in():
        return redirect(url_for("login"))

    company_id = current_company_id()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        pin = (request.form.get("pin") or "").strip()

        if not name or not pin:
            flash("Bitte Name und PIN eingeben.", "error")
            return redirect(url_for("users_add"))

        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO users (name, pin, company_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (company_id, name) DO UPDATE
                SET pin = EXCLUDED.pin
                """,
                (name, pin, company_id),
            )
            conn.commit()
            flash("Benutzer gespeichert.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Fehler: {str(e)}", "error")
        finally:
            cur.close()
            conn.close()

        return redirect(url_for("users_list"))

    return render_template("users_add.html")


# -------------------------------------------------
# PDF Export
# -------------------------------------------------
@app.route("/report/pdf/<int:report_id>")
def report_pdf(report_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    company_id = current_company_id()

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM reports
        WHERE id = %s AND company_id = %s
        """,
        (report_id, company_id),
    )
    report = cur.fetchone()
    cur.close()
    conn.close()

    if not report:
        return "Bericht nicht gefunden", 404

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, y, "Bautagesbericht")

    y -= 30
    p.setFont("Helvetica", 11)
    p.drawString(50, y, f"Datum: {report.get('datum') or ''}")

    y -= 20
    p.drawString(50, y, f"Baustelle: {report.get('baustelle') or ''}")

    y -= 20
    p.drawString(50, y, f"Wetter: {report.get('wetter') or ''}")

    y -= 20
    p.drawString(
        50,
        y,
        f"Arbeitszeit: {report.get('arbeitszeit_von') or ''} - {report.get('arbeitszeit_bis') or ''}",
    )

    y -= 20
    p.drawString(50, y, f"Pause: {report.get('pause_stunden') or 0} h")

    y -= 20
    p.drawString(50, y, f"Netto: {report.get('netto_stunden') or 0} h")

    y -= 25
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, y, "Personal")

    y -= 20
    p.setFont("Helvetica", 11)
    p.drawString(
        50, y,
        f"Polier: {report.get('polier_name') or '-'} ({report.get('polier_stunden') or 0} h)"
    )
    y -= 18
    p.drawString(
        50, y,
        f"Vorarbeiter: {report.get('vorarbeiter_name') or '-'} ({report.get('vorarbeiter_stunden') or 0} h)"
    )
    y -= 18
    p.drawString(
        50, y,
        f"Facharbeiter: {report.get('facharbeiter_name') or '-'} ({report.get('facharbeiter_stunden') or 0} h)"
    )
    y -= 18
    p.drawString(
        50, y,
        f"Elektriker: {report.get('elektriker_name') or '-'} ({report.get('elektriker_stunden') or 0} h)"
    )
    y -= 18
    p.drawString(
        50, y,
        f"Helfer: {report.get('helfer_name') or '-'} ({report.get('helfer_stunden') or 0} h)"
    )
    y -= 18
    p.drawString(
        50, y,
        f"LKW Fahrer: {report.get('lkw_fahrer_name') or '-'} ({report.get('lkw_fahrer_stunden') or 0} h)"
    )

    y -= 28
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, y, "Taetigkeiten")

    y -= 20
    p.setFont("Helvetica", 11)
    p.drawString(50, y, f"Arbeit: {report.get('arbeit') or ''}")

    y -= 20
    p.drawString(50, y, f"Material: {report.get('material') or ''}")

    y -= 20
    p.drawString(50, y, f"Bemerkung: {report.get('bemerkung') or ''}")

    p.showPage()
    p.save()

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"bautagesbericht_{report_id}.pdf",
        mimetype="application/pdf",
    )


# -------------------------------------------------
# Run locally
# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)