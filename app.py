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

@app.route("/test-static")
def test_static():
    return app.send_static_file("icon-192.png")

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
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND column_name = %s
        """,
        (table_name, column_name),
    )
    if not cur.fetchone():
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def reset_sequences(cur):
    cur.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('companies', 'id'),
            COALESCE((SELECT MAX(id) FROM companies), 1),
            true
        );
        """
    )

    cur.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('users', 'id'),
            COALESCE((SELECT MAX(id) FROM users), 1),
            true
        );
        """
    )

    cur.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('reports', 'id'),
            COALESCE((SELECT MAX(id) FROM reports), 1),
            true
        );
        """
    )


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            pin TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'worker',
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )

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

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            datum TEXT,
            wetter TEXT,
            arbeitszeit_von TEXT,
            arbeitszeit_bis TEXT,
            pause_stunden NUMERIC,
            netto_stunden NUMERIC,
            baustelle TEXT,
            team TEXT,
            polier_name TEXT,
            polier_stunden NUMERIC,
            vorarbeiter_name TEXT,
            vorarbeiter_stunden NUMERIC,
            facharbeiter_name TEXT,
            facharbeiter_stunden NUMERIC,
            elektriker_name TEXT,
            elektriker_stunden NUMERIC,
            helfer_name TEXT,
            helfer_stunden NUMERIC,
            lkw_fahrer_name TEXT,
            lkw_fahrer_stunden NUMERIC,
            arbeit TEXT,
            material TEXT,
            bemerkung TEXT,
            bauleiter TEXT,
            ersteller TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )

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
    add_column_if_missing(cur, "reports", "arbeit", "TEXT")
    add_column_if_missing(cur, "reports", "material", "TEXT")
    add_column_if_missing(cur, "reports", "bemerkung", "TEXT")
    add_column_if_missing(cur, "reports", "bauleiter", "TEXT")
    add_column_if_missing(cur, "reports", "ersteller", "TEXT")

    reset_sequences(cur)

    conn.commit()
    cur.close()
    conn.close()


init_db()


def is_logged_in():
    return "user_id" in session and "company_id" in session


def current_company_id():
    return int(session.get("company_id", DEFAULT_COMPANY_ID))


def to_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def calculate_netto_hours(von, bis, pause_hours):
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


def get_reports_for_company(company_id, limit=None):
    conn = get_db()
    cur = conn.cursor()

    if limit:
        cur.execute(
            """
            SELECT *
            FROM reports
            WHERE company_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (company_id, limit),
        )
    else:
        cur.execute(
            """
            SELECT *
            FROM reports
            WHERE company_id = %s
            ORDER BY created_at DESC, id DESC
            """,
            (company_id,),
        )

    reports = cur.fetchall()
    cur.close()
    conn.close()
    return reports


@app.route("/health")
def health():
    return "OK", 200


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
            reset_sequences(cur)

            cur.execute(
                "SELECT id FROM companies WHERE LOWER(name) = LOWER(%s) LIMIT 1",
                (company,),
            )
            existing_company = cur.fetchone()

            if existing_company:
                flash("Diese Firma existiert bereits. Bitte loggen Sie sich ein.", "error")
                return render_template("register.html")

            cur.execute(
                """
                INSERT INTO companies (name)
                VALUES (%s)
                RETURNING id
                """,
                (company,),
            )
            company_row = cur.fetchone()
            company_id = int(company_row["id"])

            cur.execute(
                """
                INSERT INTO users (name, pin, role, company_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (name, pin, "admin", company_id),
            )
            user_row = cur.fetchone()
            user_id = int(user_row["id"])

            conn.commit()

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


@app.context_processor
def inject_user():
    return dict(
        user_id=session.get("user_id"),
        user_name=session.get("name"),
    )


@app.route("/routes")
def routes():
    return "<br>".join(sorted([str(r) for r in app.url_map.iter_rules()]))


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
        bauleiter = request.form.get("bauleiter")
        ersteller = request.form.get("ersteller")

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
                    arbeit, material, bemerkung,
                    bauleiter, ersteller
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
                    %s, %s, %s,
                    %s, %s
                )
                RETURNING id
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
                    bauleiter,
                    ersteller,
                ),
            )
            saved_report = cur.fetchone()
            conn.commit()

            if saved_report:
                flash(f"Bericht gespeichert. ID: {saved_report['id']}", "success")
            else:
                flash("Bericht gespeichert.", "success")

        except Exception as e:
            conn.rollback()
            flash(f"Fehler: {str(e)}", "error")
        finally:
            cur.close()
            conn.close()

        return redirect(url_for("list_reports"))

    reports = get_reports_for_company(company_id, limit=30)

    return render_template(
        "index.html",
        reports=reports,
        heute=date.today().isoformat(),
    )


@app.route("/list")
def list_reports():
    if not is_logged_in():
        return redirect(url_for("login"))

    company_id = current_company_id()
    reports = get_reports_for_company(company_id)

    return render_template("list.html", reports=reports)


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
            reset_sequences(cur)
            cur.execute(
                """
                INSERT INTO users (name, pin, role, company_id)
                VALUES (%s, %s, %s, %s)
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

    red = (237 / 255, 28 / 255, 36 / 255)
    dark_grey = (107 / 255, 107 / 255, 107 / 255)
    light_grey = (242 / 255, 242 / 255, 242 / 255)
    medium_grey = (217 / 255, 217 / 255, 217 / 255)

    p.setFillColorRGB(*red)
    p.rect(0, height - 72, width, 72, fill=1, stroke=0)

    logo_path = os.path.join(BASE_DIR, "static", "logo-pejo.png")
    if os.path.exists(logo_path):
        try:
            p.drawImage(
                logo_path,
                18,
                height - 64,
                width=78,
                height=46,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass

    p.setFillColorRGB(1, 1, 1)
    p.setFont("Helvetica-Bold", 20)
    p.drawString(110, height - 42, "BAUTAGESBERICHT")
    p.setFont("Helvetica", 10)
    p.drawString(110, height - 60, "Digitaler Tagesbericht")

    p.setStrokeColorRGB(*medium_grey)
    p.rect(25, 25, width - 50, height - 122, stroke=1, fill=0)

    y = height - 98

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Allgemeine Angaben")
    y -= 18

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 78, width - 70, 78, fill=1, stroke=0)

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(45, y - 14, "Datum:")
    p.drawString(220, y - 14, "Baustelle:")
    p.drawString(45, y - 38, "Wetter:")
    p.drawString(220, y - 38, "Arbeitszeit:")
    p.drawString(45, y - 62, "Bauleiter:")

    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)
    p.drawString(95, y - 14, str(report.get("datum") or ""))
    p.drawString(295, y - 14, str(report.get("baustelle") or ""))
    p.drawString(95, y - 38, str(report.get("wetter") or ""))
    p.drawString(
        295,
        y - 38,
        f"{report.get('arbeitszeit_von') or ''} - {report.get('arbeitszeit_bis') or ''}",
    )
    p.drawString(115, y - 62, str(report.get("bauleiter") or ""))

    y -= 92

    p.setFont("Helvetica", 10)
    p.drawString(45, y, f"Pause: {report.get('pause_stunden') or 0} h")
    p.drawString(220, y, f"Netto: {report.get('netto_stunden') or 0} h")

    y -= 24
    p.setStrokeColorRGB(*medium_grey)
    p.line(35, y, width - 35, y)

    y -= 24
    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Personal")
    y -= 18

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 14, width - 70, 20, fill=1, stroke=0)

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(45, y, "Funktion")
    p.drawString(180, y, "Name")
    p.drawString(430, y, "Stunden")
    y -= 20

    workers = [
        ("Polier", report.get("polier_name"), report.get("polier_stunden")),
        ("Vorarbeiter", report.get("vorarbeiter_name"), report.get("vorarbeiter_stunden")),
        ("Facharbeiter", report.get("facharbeiter_name"), report.get("facharbeiter_stunden")),
        ("Elektriker", report.get("elektriker_name"), report.get("elektriker_stunden")),
        ("Helfer", report.get("helfer_name"), report.get("helfer_stunden")),
        ("LKW Fahrer", report.get("lkw_fahrer_name"), report.get("lkw_fahrer_stunden")),
    ]

    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)

    for role, name, hours in workers:
        p.drawString(45, y, str(role))
        p.drawString(180, y, str(name or "-"))
        p.drawString(430, y, f"{hours or 0} h")
        p.setStrokeColorRGB(*medium_grey)
        p.line(40, y - 6, width - 40, y - 6)
        y -= 18

    y -= 12
    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Team")
    y -= 18

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 16, width - 70, 24, fill=1, stroke=0)
    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)
    p.drawString(45, y, str(report.get("team") or ""))
    y -= 34

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Taetigkeiten")
    y -= 18

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 40, width - 70, 48, fill=1, stroke=0)
    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)
    p.drawString(45, y, str(report.get("arbeit") or ""))
    y -= 58

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Material")
    y -= 18

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 24, width - 70, 32, fill=1, stroke=0)
    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)
    p.drawString(45, y, str(report.get("material") or ""))
    y -= 42

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Bemerkung")
    y -= 18

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 32, width - 70, 40, fill=1, stroke=0)
    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)
    p.drawString(45, y, str(report.get("bemerkung") or ""))
    y -= 50

    p.setStrokeColorRGB(*dark_grey)
    p.line(300, 80, width - 50, 80)
    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica", 9)
    p.drawString(300, 65, f"Erstellt von: {report.get('ersteller') or ''}")

    p.showPage()
    p.save()

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"bautagesbericht_{report_id}.pdf",
        mimetype="application/pdf",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)