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


def add_column_if_missing(cur, table_name: str, column_name: str, column_def: str):
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND column_name = %s
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
    # 1) Companies
    # -------------------------------------------------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            name VARCHAR(200) NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    # -------------------------------------------------
    # 2) Users
    # -------------------------------------------------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            pin TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    add_column_if_missing(cur, "users", "role", "TEXT DEFAULT 'admin'")

    # unique user name inside one company
    cur.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'users'
                  AND c.conname = 'users_company_id_name_key'
            ) THEN
                ALTER TABLE users
                ADD CONSTRAINT users_company_id_name_key UNIQUE (company_id, name);
            END IF;
        END $$;
        """
    )

    # -------------------------------------------------
    # 3) Reports
    # -------------------------------------------------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            datum TEXT,
            baustelle TEXT,
            arbeit TEXT,
            material TEXT,
            bemerkung TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    # extra columns used in templates/forms
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

    # -------------------------------------------------
    # 4) Demo company + demo user
    # -------------------------------------------------
    cur.execute(
        """
        INSERT INTO companies (id, name)
        VALUES (1, 'Firma1')
        ON CONFLICT (id) DO NOTHING;
        """
    )

    cur.execute(
        """
        INSERT INTO users (name, pin, role, company_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (company_id, name) DO NOTHING;
        """,
    )
    # demo user iskljucen
    pass

    conn.commit()
    cur.close()
    conn.close()


# init once on startup
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
# Register
# -------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        company = (request.form.get("company") or "").strip()
        name = (request.form.get("name") or "").strip()
        pin = (request.form.get("pin") or "").strip()

        if not company or not name or not pin:
            flash("Bitte Firma, Name und PIN eingeben.", "error")
            return render_template("register.html")

        conn = get_db()
        cur = conn.cursor()

        try:
            # provjera da li firma već postoji
            cur.execute(
                "SELECT id FROM companies WHERE LOWER(name) = LOWER(%s) LIMIT 1",
                (company,),
            )
            existing_company = cur.fetchone()

            if existing_company:
                flash("Diese Firma existiert bereits. Bitte loggen Sie sich ein.", "error")
                return render_template("register.html")

            # ručno postavi novi company id
            cur.execute(
                """
                INSERT INTO companies (id, name)
                VALUES (
                    (SELECT COALESCE(MAX(id), 0) + 1 FROM companies),
                    %s
                )
                RETURNING id
                """,
                (company,),
            )
            company_row = cur.fetchone()
            company_id = int(company_row["id"])

            # ručno postavi novi user id
            cur.execute(
                """
                INSERT INTO users (id, name, pin, role, company_id)
                VALUES (
                    (SELECT COALESCE(MAX(id), 0) + 1 FROM users),
                    %s, %s, %s, %s
                )
                RETURNING id
                """,
                (name, pin, "admin", company_id),
            )
            user_row = cur.fetchone()
            user_id = int(user_row["id"])

            conn.commit()

            # automatski login
            session.clear()
            session["user_id"] = user_id
            session["name"] = name
            session["company_id"] = company_id

            flash("Firma und Admin wurden erfolgreich erstellt.", "success")
            return redirect(url_for("index"))

        except Exception as e:
            conn.rollback()
            flash(f"Fehler bei der Registrierung: {str(e)}", "error")
        finally:
            cur.close()
            conn.close()

    return render_template("register.html")


# -------------------------------------------------
# Login
# -------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        company = (request.form.get("company") or "").strip()
        name = (request.form.get("name") or "").strip()
        pin = (request.form.get("pin") or "").strip()

        if not company or not name or not pin:
            flash("Bitte Firma, Name und PIN eingeben.", "error")
            return render_template("login.html")

        conn = get_db()
        cur = conn.cursor()

        try:
            cur.execute(
                """
                SELECT u.id, u.name, u.company_id
                FROM users u
                JOIN companies c ON u.company_id = c.id
                WHERE LOWER(c.name) = LOWER(%s)
                  AND LOWER(u.name) = LOWER(%s)
                  AND u.pin = %s
                LIMIT 1
                """,
                (company, name, pin),
            )

            user = cur.fetchone()

            if user:
                session.clear()
                session["user_id"] = int(user["id"])
                session["name"] = user["name"]
                session["company_id"] = int(user["company_id"])
                return redirect(url_for("index"))

            flash("Falsche Firma, falscher Name oder PIN.", "error")
        finally:
            cur.close()
            conn.close()

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


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
        try:
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
                    company_id,
                    datum,
                    wetter,
                    arbeitszeit_von,
                    arbeitszeit_bis,
                    pause_stunden,
                    netto_stunden,
                    baustelle,
                    team,
                    polier_name,
                    polier_stunden,
                    vorarbeiter_name,
                    vorarbeiter_stunden,
                    facharbeiter_name,
                    facharbeiter_stunden,
                    elektriker_name,
                    elektriker_stunden,
                    helfer_name,
                    helfer_stunden,
                    lkw_fahrer_name,
                    lkw_fahrer_stunden,
                    arbeit,
                    material,
                    bemerkung,
                ),
            )
            conn.commit()
            flash("Bericht gespeichert.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Fehler: {str(e)}", "error")
        finally:
            cur.close()
            conn.close()

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
        SELECT id, name, role, company_id, created_at
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
                INSERT INTO users (id, name, pin, role, company_id)
                VALUES (
                    (SELECT COALESCE(MAX(id), 0) + 1 FROM users),
                    %s, %s, %s, %s
                )
                ON CONFLICT (company_id, name) DO UPDATE
                SET pin = EXCLUDED.pin
                """,
                (name, pin, "worker", company_id),
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
        50,
        y,
        f"Polier: {report.get('polier_name') or '-'} ({report.get('polier_stunden') or 0} h)",
    )
    y -= 18
    p.drawString(
        50,
        y,
        f"Vorarbeiter: {report.get('vorarbeiter_name') or '-'} ({report.get('vorarbeiter_stunden') or 0} h)",
    )
    y -= 18
    p.drawString(
        50,
        y,
        f"Facharbeiter: {report.get('facharbeiter_name') or '-'} ({report.get('facharbeiter_stunden') or 0} h)",
    )
    y -= 18
    p.drawString(
        50,
        y,
        f"Elektriker: {report.get('elektriker_name') or '-'} ({report.get('elektriker_stunden') or 0} h)",
    )
    y -= 18
    p.drawString(
        50,
        y,
        f"Helfer: {report.get('helfer_name') or '-'} ({report.get('helfer_stunden') or 0} h)",
    )
    y -= 18
    p.drawString(
        50,
        y,
        f"LKW Fahrer: {report.get('lkw_fahrer_name') or '-'} ({report.get('lkw_fahrer_stunden') or 0} h)",
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