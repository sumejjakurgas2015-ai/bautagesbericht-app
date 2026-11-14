import os
import base64
import uuid
import json

from io import BytesIO
from datetime import date, timedelta
from dotenv import load_dotenv
load_dotenv()

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
    abort,
)

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from flask_wtf.csrf import CSRFProtect, generate_csrf, validate_csrf, CSRFError
from werkzeug.exceptions import HTTPException


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
DEFAULT_COMPANY_ID = int(os.environ.get("COMPANY_ID", "1"))

# CSRF-Schutz für Löschformulare
# Bestehende Formulare bleiben vorerst unverändert.
app.config["WTF_CSRF_ENABLED"] = True
app.config["WTF_CSRF_CHECK_DEFAULT"] = False

# CSRF-Token in HTML-Vorlagen verfügbar machen
app.jinja_env.globals["csrf_token"] = generate_csrf


@app.route("/radi-li")
def radi_li():
    return "RADI", 200


@app.route("/test-static")
def test_static():
    return send_file(os.path.join(BASE_DIR, "static", "icon-192.png"))


@app.route("/manifest")
def manifest_test():
    return send_file(
        os.path.join(BASE_DIR, "static", "manifest.json"),
        mimetype="application/manifest+json",
    )


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

        # Firmenfreigabe fuer PEJO BaustellenManager
    # Bestehende Firmen bleiben aktiv.
    cur.execute(
        """
        ALTER TABLE companies
        ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE
        """
    )

    # Neue Registrierungen werden spaeter auf FALSE gesetzt.
    # Bestehende Firmen bleiben unveraendert.

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

    add_column_if_missing(cur, "users", "role", "TEXT DEFAULT 'worker'")
    cur.execute("UPDATE users SET role = 'worker' WHERE role IS NULL")

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
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            datum TEXT,
            wetter TEXT,
            temperatur TEXT,
            signature TEXT,
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

    add_column_if_missing(cur, "reports", "user_id", "INTEGER")
    add_column_if_missing(cur, "reports", "wetter", "TEXT")
    add_column_if_missing(cur, "reports", "temperatur", "TEXT")
    add_column_if_missing(cur, "reports", "signature", "TEXT")
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
    
    # Abfahrtskontrolle - dnevne kontrole vozila
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS abfahrtskontrollen (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL
                REFERENCES companies(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            datum DATE NOT NULL,
            fahrzeug TEXT,
            kennzeichen TEXT,
            fahrer TEXT,
            ist_ok BOOLEAN DEFAULT FALSE,
            maengel TEXT,
            unterschrift TEXT,
            submission_id TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
           updated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    cur.execute(
    """
    ALTER TABLE abfahrtskontrollen
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()
    """
    )
    cur.execute(
    """
    ALTER TABLE abfahrtskontrollen
    ADD COLUMN IF NOT EXISTS submission_id TEXT
    """
    ) 

    conn.commit()
    cur.close()
    conn.close()


# init_db()


def is_logged_in():
    return "user_id" in session and "company_id" in session


def is_admin():
    return session.get("role") == "admin"


def current_company_id():
    return int(session.get("company_id", DEFAULT_COMPANY_ID))


def current_user_id():
    return int(session.get("user_id"))


PERMISSION_MODULES = ("bautagesbericht", "entsorgung", "abfahrtskontrolle")


def ensure_permissions_schema():
    """Idempotent schema update. NULL = legacy user with full module access."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions TEXT[]")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_permissions_schema_ready = False


@app.before_request
def prepare_permissions_schema():
    global _permissions_schema_ready
    if not _permissions_schema_ready and request.endpoint not in ("static", "health", "radi_li", "test_static", "manifest_test"):
        ensure_permissions_schema()
        _permissions_schema_ready = True


def allowed_modules():
    if not is_logged_in():
        return set()
    if is_admin():
        return set(PERMISSION_MODULES)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT permissions FROM users WHERE id = %s AND company_id = %s", (current_user_id(), current_company_id()))
            row = cur.fetchone()
        if not row:
            return set()
        value = row["permissions"]
        return set(PERMISSION_MODULES) if value is None else set(value) & set(PERMISSION_MODULES)
    finally:
        conn.close()


def require_module(module):
    if not is_logged_in():
        return redirect(url_for("login"))
    if module not in allowed_modules():
        abort(403, description="Keine Berechtigung für dieses Modul")
    return None


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


def pdf_text(value):
    text = str(value or "")

    replacements = {
        "•": "-",
        "▪": "-",
        "■": "-",
        "●": "-",
        "–": "-",
        "—": "-",
        "“": '"',
        "”": '"',
        "„": '"',
        "’": "'",
        "‘": "'",
        "\u00a0": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text.encode("latin-1", "replace").decode("latin-1")
    
def pdf_multiline(p, text, x, y, max_width, line_height=14):
    from reportlab.lib.utils import simpleSplit

    text = str(text or "")

    # Uklanjanje znakova koje Helvetica ne podrzava
    replacements = {
        "\u25a0": "-",
        "\u25aa": "-",
        "\u2022": "-",
        "\u200b": "",
        "\ufeff": "",
        "\t": "    ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    p.setFont("Helvetica", 10)

    for paragraph in text.split("\n"):
        if not paragraph.strip():
            y -= line_height
            continue

        clean_text = pdf_text(paragraph)

        lines = simpleSplit(
            clean_text,
            "Helvetica",
            10,
            max_width
        )

        for line in lines:
            p.drawString(x, y, line)
            y -= line_height

    return y


def draw_signature_on_pdf(p, signature_data, x, y, width=180, height=60):
    try:
        if not signature_data:
            return

        if "," in signature_data:
            signature_data = signature_data.split(",", 1)[1]

        img_bytes = base64.b64decode(signature_data)
        img = ImageReader(BytesIO(img_bytes))

        p.drawImage(
            img,
            x,
            y,
            width=width,
            height=height,
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception:
        pass


def get_reports_for_user(company_id, user_id, limit=None):
    conn = get_db()
    cur = conn.cursor()

    if limit:
        cur.execute(
            """
            SELECT r.*, u.name AS report_user_name
            FROM reports r
            LEFT JOIN users u ON r.user_id = u.id
            WHERE r.company_id = %s AND r.user_id = %s
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT %s
            """,
            (company_id, user_id, limit),
        )
    else:
        cur.execute(
            """
            SELECT r.*, u.name AS report_user_name
            FROM reports r
            LEFT JOIN users u ON r.user_id = u.id
            WHERE r.company_id = %s AND r.user_id = %s
            ORDER BY r.created_at DESC, r.id DESC
            """,
            (company_id, user_id),
        )

    reports = cur.fetchall()
    cur.close()
    conn.close()
    return reports


def get_reports_for_company(company_id, limit=None):
    conn = get_db()
    cur = conn.cursor()

    if limit:
        cur.execute(
            """
            SELECT r.*, u.name AS report_user_name
            FROM reports r
            LEFT JOIN users u ON r.user_id = u.id
            WHERE r.company_id = %s
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT %s
            """,
            (company_id, limit),
        )
    else:
        cur.execute(
            """
            SELECT r.*, u.name AS report_user_name
            FROM reports r
            LEFT JOIN users u ON r.user_id = u.id
            WHERE r.company_id = %s
            ORDER BY r.created_at DESC, r.id DESC
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


@app.context_processor
def inject_user():
    return dict(
        user_id=session.get("user_id"),
        user_name=session.get("name"),
        user_role=session.get("role"),
    )


@app.route("/routes")
def routes():
    return "<br>".join(sorted([str(r) for r in app.url_map.iter_rules()]))


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

            # Neue Firmen warten auf Freigabe durch PEJO
            cur.execute(
                """
                INSERT INTO companies (name, is_active)
                VALUES (%s, FALSE)
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
                RETURNING id, role
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
            session["role"] = user_row["role"]

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
                SELECT u.id, u.name, u.company_id, u.role
                FROM users u
                JOIN companies c ON u.company_id = c.id
                WHERE LOWER(c.name) = LOWER(%s)
                  AND LOWER(u.name) = LOWER(%s)
                  AND u.pin = %s
                  AND c.is_active = TRUE
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
                session["role"] = user["role"] or "worker"
                return redirect(url_for("dashboard"))

            flash("Falsche Firma, falscher Name oder PIN.", "error")
        finally:
            cur.close()
            conn.close()

    return render_template("login.html")
@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect(url_for("login"))

    return render_template("dashboard.html", allowed_modules=allowed_modules())
@app.route("/admin/abfahrtskontrollen")
def admin_abfahrtskontrollen():
    if not is_logged_in():
        return redirect(url_for("login"))

    if not is_admin():
        return "Zugriff verweigert", 403

    company_id = current_company_id()

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
           SELECT a.id, a.datum, a.fahrzeug, a.kennzeichen,
                   a.fahrer, a.ist_ok, a.maengel,
                   a.unterschrift
            FROM abfahrtskontrollen a
            WHERE a.company_id = %s
            ORDER BY a.datum DESC
            """,
            (company_id,)
        )
        kontrole = cur.fetchall()
    finally:
        cur.close()
        conn.close()
    

    return render_template("admin_abfahrtskontrollen.html", kontrole=kontrole)

@app.route("/admin/abfahrtskontrollen/pdf/<int:kontrola_id>")
def admin_abfahrtskontrolle_pdf(kontrola_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    if not is_admin():
        return "Zugriff verweigert", 403

    company_id = current_company_id()

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT id, datum, fahrzeug, kennzeichen,
                   fahrer, ist_ok, maengel, unterschrift
            FROM abfahrtskontrollen
            WHERE id = %s AND company_id = %s
            """,
            (kontrola_id, company_id),
        )
        kontrola = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not kontrola:
        return "Kontrolle nicht gefunden", 404

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    p.setTitle("Taegliche Abfahrtskontrolle")

    # PEJO Farben – identisch mit Bautagesbericht
    red = (237 / 255, 28 / 255, 36 / 255)
    dark_grey = (107 / 255, 107 / 255, 107 / 255)
    light_grey = (242 / 255, 242 / 255, 242 / 255)
    medium_grey = (217 / 255, 217 / 255, 217 / 255)

    # Roter Kopfbereich
    p.setFillColorRGB(*red)
    p.rect(0, height - 72, width, 72, fill=1, stroke=0)

    # PEJO Logo
    logo_path = os.path.join(BASE_DIR, "static", "logo.png")

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
            app.logger.exception("PEJO Logo konnte nicht geladen werden")

    # Titel
    p.setFillColorRGB(1, 1, 1)
    p.setFont("Helvetica-Bold", 18)
    p.drawString(110, height - 42, "ABFAHRTSKONTROLLE")

    p.setFont("Helvetica", 10)
    p.drawString(110, height - 60, "Taegliche Fahrzeugkontrolle")

    # Seitenrahmen
    p.setStrokeColorRGB(*medium_grey)
    p.rect(
        25,
        25,
        width - 50,
        height - 122,
        stroke=1,
        fill=0,
    )

    # Allgemeine Angaben
    y = height - 110

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Allgemeine Angaben")

    y -= 25

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 110, width - 70, 120, fill=1, stroke=0)

    datum = kontrola["datum"]
    datum_text = datum.strftime("%d.%m.%Y") if datum else "-"

    felder = [
        ("Datum", datum_text),
        ("Fahrzeug", kontrola["fahrzeug"] or "-"),
        ("Kennzeichen", kontrola["kennzeichen"] or "-"),
        ("Fahrer", kontrola["fahrer"] or "-"),
    ]

    for label, wert in felder:
        p.setFillColorRGB(*dark_grey)
        p.setFont("Helvetica-Bold", 10)
        p.drawString(45, y, label + ":")

        p.setFillColorRGB(0, 0, 0)
        p.setFont("Helvetica", 10)
        p.drawString(
            165,
            y,
            pdf_text(str(wert))[:65],
        )

        y -= 28

    # Kontrollstatus
    y -= 30

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Fahrzeugkontrolle")

    y -= 28

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 52, width - 70, 65, fill=1, stroke=0)

    status = "Ja" if kontrola["ist_ok"] else "Nein"

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(45, y, "Fahrzeug in Ordnung:")

    if kontrola["ist_ok"]:
        p.setFillColorRGB(0, 0.5, 0)
    else:
        p.setFillColorRGB(0.8, 0, 0)

    p.setFont("Helvetica-Bold", 11)
    p.drawString(205, y, status)

    y -= 30

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(45, y, "Kontrollstatus:")

    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)

    if kontrola["unterschrift"]:
        p.drawString(205, y, "Unterschrieben")
    else:
        p.drawString(205, y, "Nicht unterschrieben")

    # Maengel
    y -= 70

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Maengel / Bemerkungen")

    y -= 25

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 80, width - 70, 90, fill=1, stroke=0)

    maengel = pdf_text(kontrola["maengel"] or "Keine")

    from reportlab.lib.utils import simpleSplit

    zeilen = simpleSplit(
        maengel,
        "Helvetica",
        10,
        width - 110,
    )

    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)

    for zeile in zeilen[:5]:
        p.drawString(45, y, zeile)
        y -= 15

    # Elektronische Unterschrift
    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, 225, "Elektronische Unterschrift")

    if kontrola["unterschrift"]:
        draw_signature_on_pdf(
            p,
            kontrola["unterschrift"],
            x=45,
            y=125,
            width=220,
            height=85,
        )
    else:
        p.setFont("Helvetica", 10)
        p.drawString(45, 170, "Noch keine Unterschrift vorhanden.")

    p.setStrokeColorRGB(*dark_grey)
    p.line(45, 120, 285, 120)

    p.setFont("Helvetica", 9)
    p.setFillColorRGB(*dark_grey)
    p.drawString(
        45,
        105,
        pdf_text(kontrola["fahrer"] or "Fahrer"),
    )

    # Fusszeile
    p.setStrokeColorRGB(*medium_grey)
    p.line(40, 65, width - 40, 65)

    p.setFont("Helvetica", 9)
    p.setFillColorRGB(*dark_grey)

    p.drawString(
        40,
        50,
        "PEJO Elektrotechnik GmbH",
    )

    p.drawRightString(
        width - 40,
        50,
        f"Abfahrtskontrolle Nr. {kontrola_id}",
    )

    p.showPage()
    p.save()

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"abfahrtskontrolle_{kontrola_id}.pdf",
        mimetype="application/pdf",
    )
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"abfahrtskontrolle_{kontrola_id}.pdf",
        mimetype="application/pdf",
    )
@app.route("/admin/abfahrtskontrollen/loeschen/<int:kontrola_id>", methods=["POST"])
def admin_abfahrtskontrolle_loeschen(kontrola_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    if not is_admin():
        return "Zugriff verweigert", 403

    try:
        validate_csrf(request.form.get("csrf_token", ""))
    except Exception:
        abort(400, description="Ungültiger CSRF-Token")

    company_id = current_company_id()
    conn = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM abfahrtskontrollen
            WHERE id = %s AND company_id = %s
            """,
            (kontrola_id, company_id)
        )

        geloescht = cur.rowcount
        conn.commit()

        if geloescht:
            flash("Abfahrtskontrolle erfolgreich gelöscht.", "success")
        else:
            flash("Abfahrtskontrolle nicht gefunden.", "warning")

    except Exception:
        if conn:
            conn.rollback()
        app.logger.exception("Fehler beim Löschen der Abfahrtskontrolle")
        flash("Fehler beim Löschen der Abfahrtskontrolle.", "error")

    finally:
        if conn:
            conn.close()

    return redirect(url_for("admin_abfahrtskontrollen"))

@app.route("/admin/abfahrtskontrollen/bearbeiten/<int:kontrola_id>", methods=["GET", "POST"])
def admin_abfahrtskontrolle_bearbeiten(kontrola_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    if not is_admin():
        abort(403)

    company_id = current_company_id()
    conn = None

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, datum, fahrzeug, kennzeichen, fahrer,
                   ist_ok, maengel, unterschrift
            FROM abfahrtskontrollen
            WHERE id = %s AND company_id = %s
            """,
            (kontrola_id, company_id)
        )
        kontrola = cur.fetchone()

        if not kontrola:
            abort(404)

        if kontrola["unterschrift"]:
            flash("Unterschriebene Kontrollen können nicht bearbeitet werden.", "warning")
            return redirect(url_for("admin_abfahrtskontrollen"))

        if request.method == "POST":
            try:
                validate_csrf(request.form.get("csrf_token", ""))
            except Exception:
                abort(400, description="Ungültiger CSRF-Token")

            datum = (request.form.get("datum") or "").strip()
            fahrzeug = (request.form.get("fahrzeug") or "").strip()
            kennzeichen = (request.form.get("kennzeichen") or "").strip()
            fahrer = (request.form.get("fahrer") or "").strip()
            ist_ok = request.form.get("ist_ok") == "on"
            maengel = (request.form.get("maengel") or "").strip()

            if not datum:
                flash("Datum ist erforderlich.", "error")
                return redirect(url_for(
                    "admin_abfahrtskontrolle_bearbeiten",
                    kontrola_id=kontrola_id
                ))

            cur.execute(
                """
                UPDATE abfahrtskontrollen
                SET datum = %s,
                    fahrzeug = %s,
                    kennzeichen = %s,
                    fahrer = %s,
                    ist_ok = %s,
                    maengel = %s,
                    updated_at = NOW()
                WHERE id = %s
                  AND company_id = %s
                  AND (unterschrift IS NULL OR unterschrift = '')
                """,
                (
                    datum, fahrzeug, kennzeichen, fahrer,
                    ist_ok, maengel, kontrola_id, company_id
                )
            )

            if cur.rowcount == 0:
                conn.rollback()
                flash("Kontrolle wurde bereits unterschrieben oder nicht gefunden.", "warning")
                return redirect(url_for("admin_abfahrtskontrollen"))

            conn.commit()
            flash("Abfahrtskontrolle erfolgreich aktualisiert.", "success")
            return redirect(url_for("admin_abfahrtskontrollen"))

        return render_template(
            "admin_abfahrtskontrolle_bearbeiten.html",
            kontrola=kontrola
        )

    except HTTPException:
        raise

    except Exception:
        if conn:
            conn.rollback()
        app.logger.exception("Fehler beim Bearbeiten der Abfahrtskontrolle")
        flash("Fehler beim Bearbeiten der Abfahrtskontrolle.", "error")
        return redirect(url_for("admin_abfahrtskontrollen"))

    finally:
        if conn:
            conn.close()   

    return redirect(url_for("admin_abfahrtskontrollen"))    

@app.route("/abfahrtskontrolle", methods=["GET", "POST"])
def abfahrtskontrolle():
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("abfahrtskontrolle")
    if denied is not None:
        return denied

    company_id = current_company_id()
    user_id = current_user_id()
    godina, sedmica, _ = date.today().isocalendar()
    izabrana_sedmica = (
        request.form.get("kalenderwoche")
        if request.method == "POST"
        else request.args.get("kw")
    ) or f"{godina}-W{sedmica:02d}"

    if request.method == "POST":
        zapisi = []
        form_submission_id = (request.form.get("formSubmissionId") or "").strip()
        # Every form load gets its own UUID; never reuse a missing identifier.
        if not form_submission_id:
            form_submission_id = str(uuid.uuid4())

        for dan in ("Mo", "Di", "Mi", "Do", "Fr", "Sa"):
            kontrola_id = request.form.get(f"kontrola_id_{dan}") or None
            datum = request.form.get(f"datum_{dan}")
            fahrzeug = (request.form.get(f"fahrzeug_{dan}") or "").strip()
            kennzeichen = (request.form.get(f"kennzeichen_{dan}") or "").strip()
            fahrer = (request.form.get(f"fahrer_{dan}") or "").strip()
            ist_ok = request.form.get(f"ist_ok_{dan}") == "on"
            maengel = (request.form.get(f"maengel_{dan}") or "").strip()
            unterschrift = request.form.get(f"signature_{dan}") or ""

            if not datum:
                continue
            if not kontrola_id and not fahrzeug and not kennzeichen and not fahrer:
                continue
            zapisi.append((kontrola_id, datum, fahrzeug, kennzeichen,
                           fahrer, ist_ok, maengel, unterschrift))

        try:
            extra_count = min(max(int(request.form.get("extraVehicleCount") or 0), 0), 100)
        except (ValueError, TypeError):
            extra_count = 0

        for broj in range(1, extra_count + 1):
            datum = request.form.get(f"datum_extra_{broj}")
            fahrzeug = (request.form.get(f"fahrzeug_extra_{broj}") or "").strip()
            kennzeichen = (request.form.get(f"kennzeichen_extra_{broj}") or "").strip()
            fahrer = (request.form.get(f"fahrer_extra_{broj}") or "").strip()
            ist_ok = request.form.get(f"ist_ok_extra_{broj}") == "on"
            maengel = (request.form.get(f"maengel_extra_{broj}") or "").strip()
            unterschrift = request.form.get(f"signature_extra_{broj}") or ""
            if not datum or (not fahrzeug and not kennzeichen and not fahrer):
                continue
            zapisi.append((None, datum, fahrzeug, kennzeichen,
                           fahrer, ist_ok, maengel, unterschrift))

        postojeci_potpisi = {
            kljuc.split("existing_signature_", 1)[1]: vrijednost
            for kljuc, vrijednost in request.form.items()
            if kljuc.startswith("existing_signature_") and vrijednost
        }

        if zapisi or postojeci_potpisi:
            conn = get_db()
            cur = conn.cursor()
            try:
                broj_sacuvanih = 0
                broj_zakljucanih = 0
                for broj_zapisa, zapis in enumerate(zapisi, start=1):
                    (kontrola_id, datum, fahrzeug, kennzeichen,
                     fahrer, ist_ok, maengel, unterschrift) = zapis
                    podaci = (datum, fahrzeug, kennzeichen, fahrer,
                              ist_ok, maengel, unterschrift)
                    if kontrola_id:
                        cur.execute(
                            """
                            UPDATE abfahrtskontrollen
                            SET datum = %s, fahrzeug = %s, kennzeichen = %s,
                                fahrer = %s, ist_ok = %s, maengel = %s,
                                unterschrift = %s, updated_at = NOW()
                            WHERE id = %s AND company_id = %s AND user_id = %s
                              AND (unterschrift IS NULL OR unterschrift = '')
                            """,
                            podaci + (kontrola_id, company_id, user_id),
                        )
                    else:
                        submission_id = f"{form_submission_id}:{broj_zapisa}"
                        cur.execute(
                            """
                            INSERT INTO abfahrtskontrollen
                            (company_id, user_id, datum, fahrzeug, kennzeichen,
                             fahrer, ist_ok, maengel, unterschrift, submission_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (submission_id) DO NOTHING
                            """,
                            (company_id, user_id) + podaci + (submission_id,),
                        )
                    if cur.rowcount == 1:
                        broj_sacuvanih += 1
                    else:
                        broj_zakljucanih += 1

                for kontrola_id, potpis in postojeci_potpisi.items():
                    if not kontrola_id.isdigit():
                        continue
                    cur.execute(
                        """
                        UPDATE abfahrtskontrollen
                        SET unterschrift = %s, updated_at = NOW()
                        WHERE id = %s AND company_id = %s AND user_id = %s
                          AND (unterschrift IS NULL OR unterschrift = '')
                        """,
                        (potpis, int(kontrola_id), company_id, user_id),
                    )
                    if cur.rowcount == 1:
                        broj_sacuvanih += 1
                    else:
                        broj_zakljucanih += 1

                conn.commit()
                if broj_sacuvanih:
                    flash(f"{broj_sacuvanih} Abfahrtskontrolle(n) gespeichert.", "success")
                if broj_zakljucanih:
                    flash(f"{broj_zakljucanih} Kontrolle(n) nicht verändert (bereits unterschrieben oder doppelt gesendet).", "warning")
            except Exception as e:
                conn.rollback()
                flash(f"Fehler beim Speichern: {e}", "error")
            finally:
                cur.close()
                conn.close()

        return redirect(url_for("abfahrtskontrolle", kw=izabrana_sedmica))

    try:
        godina_kw, sedmica_kw = izabrana_sedmica.split("-W")
        pocetak = date.fromisocalendar(int(godina_kw), int(sedmica_kw), 1)
    except (ValueError, TypeError):
        flash("Ungültige Kalenderwoche.", "error")
        return redirect(url_for("abfahrtskontrolle"))

    kraj = pocetak + timedelta(days=6)
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT id, datum, fahrzeug, kennzeichen, fahrer, ist_ok,
                   maengel, unterschrift
            FROM abfahrtskontrollen
            WHERE company_id = %s AND user_id = %s
              AND datum BETWEEN %s AND %s
            ORDER BY datum, id
            """,
            (company_id, user_id, pocetak, kraj),
        )
        kontrole = cur.fetchall()
        kontrole_po_danima = {}
        dodatne_kontrole = []
        oznake_dana = ["Mo", "Di", "Mi", "Do", "Fr", "Sa"]
        for kontrola in kontrole:
            broj_dana = kontrola["datum"].weekday()
            if broj_dana < 6:
                oznaka = oznake_dana[broj_dana]
                if oznaka not in kontrole_po_danima:
                    kontrole_po_danima[oznaka] = kontrola
                else:
                    dodatne_kontrole.append(kontrola)
    except Exception:
        flash("Fehler beim Laden der Abfahrtskontrolle. Bitte erneut versuchen.", "error")
        kontrole = []
        kontrole_po_danima = {}
        dodatne_kontrole = []
    finally:
        cur.close()
        conn.close()

    return render_template(
        "abfahrtskontrolle.html",
        izabrana_sedmica=izabrana_sedmica,
        kontrole=kontrole,
        kontrole_po_danima=kontrole_po_danima,
        dodatne_kontrole=dodatne_kontrole,
        form_submission_id=str(uuid.uuid4()),
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/", methods=["GET", "POST"])
def index():
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("bautagesbericht")
    if denied is not None:
        return denied

    company_id = current_company_id()
    user_id = current_user_id()

    if request.method == "POST":
        datum = request.form.get("datum")
        wetter = (request.form.get("wetter") or "").strip()
        temperatur = (request.form.get("temperatur") or "").strip()
        signature = request.form.get("signature", "")

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
                    company_id, user_id, datum, wetter, temperatur, signature,
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
                    %s, %s, %s, %s, %s, %s,
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
                    user_id,
                    datum,
                    wetter,
                    temperatur,
                    signature,
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

    if is_admin():
        reports = get_reports_for_company(company_id, limit=30)
    else:
        reports = get_reports_for_user(company_id, user_id, limit=30)

    return render_template(
        "index.html",
        reports=reports,
        heute=date.today().isoformat(),
    )


@app.route("/list")
def list_reports():
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("bautagesbericht")
    if denied is not None:
        return denied

    company_id = current_company_id()
    user_id = current_user_id()

    if is_admin():
        reports = get_reports_for_company(company_id)
    else:
        reports = get_reports_for_user(company_id, user_id)

    return render_template("list.html", reports=reports)

@app.route("/bericht/loeschen/<int:bericht_id>", methods=["POST"])
def bericht_loeschen(bericht_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("bautagesbericht")
    if denied is not None:
        return denied

    try:
        validate_csrf(request.form.get("csrf_token", ""))
    except Exception:
        abort(400, description="Ungültiger CSRF-Token")

    company_id = current_company_id()
    user_id = current_user_id()

    conn = None

    try:
        conn = get_db()
        cur = conn.cursor()

        if is_admin():
            cur.execute(
                """
                DELETE FROM reports
                WHERE id = %s AND company_id = %s
                """,
                (bericht_id, company_id),
            )
        else:
            cur.execute(
                """
                DELETE FROM reports
                WHERE id = %s
                  AND company_id = %s
                  AND user_id = %s
                """,
                (bericht_id, company_id, user_id),
            )

        geloescht = cur.rowcount
        conn.commit()

        if geloescht:
            flash("Bautagesbericht erfolgreich gelöscht.", "success")
        else:
            flash("Bautagesbericht nicht gefunden oder keine Berechtigung.", "warning")

    except Exception:
        if conn:
            conn.rollback()

        app.logger.exception("Fehler beim Löschen des Bautagesberichts")
        flash("Fehler beim Löschen des Bautagesberichts.", "error")

    finally:
        if conn:
            conn.close()

    return redirect(url_for("list_reports"))

@app.route("/bericht/bearbeiten/<int:bericht_id>", methods=["GET", "POST"])
def bericht_bearbeiten(bericht_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("bautagesbericht")
    if denied is not None:
        return denied

    company_id = current_company_id()
    user_id = current_user_id()

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        if is_admin():
            cur.execute(
                """
                SELECT *
                FROM reports
                WHERE id = %s AND company_id = %s
                """,
                (bericht_id, company_id),
            )
        else:
            cur.execute(
                """
                SELECT *
                FROM reports
                WHERE id = %s AND company_id = %s AND user_id = %s
                """,
                (bericht_id, company_id, user_id),
            )

        report = cur.fetchone()

        if not report:
            flash("Bericht nicht gefunden oder keine Berechtigung.", "error")
            return redirect(url_for("list_reports"))

        if report["signature"]:
            flash(
                "Unterschriebene Bautagesberichte können nicht bearbeitet werden.",
                "warning",
            )
            return redirect(url_for("list_reports"))

        if request.method == "POST":
            try:
                validate_csrf(request.form.get("csrf_token", ""))
            except Exception:
                abort(400, description="Ungültiger CSRF-Token")

            datum = (request.form.get("datum") or "").strip()
            baustelle = (request.form.get("baustelle") or "").strip()

            if not datum or not baustelle:
                flash("Datum und Baustelle sind erforderlich.", "error")
                return redirect(
                    url_for("bericht_bearbeiten", bericht_id=bericht_id)
                )

            arbeitszeit_von = request.form.get("arbeitszeit_von") or None
            arbeitszeit_bis = request.form.get("arbeitszeit_bis") or None
            pause_stunden = to_float(
                request.form.get("pause_stunden"), 0.0
            )

            netto_stunden = calculate_netto_hours(
                arbeitszeit_von,
                arbeitszeit_bis,
                pause_stunden,
            )

            neue_unterschrift = (
                request.form.get("signature") or ""
            ).strip()

            signature = neue_unterschrift or report["signature"]

            daten = {
                "datum": datum,
                "wetter": (request.form.get("wetter") or "").strip(),
                "temperatur": (
                    request.form.get("temperatur") or ""
                ).strip(),
                "signature": signature,
                "arbeitszeit_von": arbeitszeit_von,
                "arbeitszeit_bis": arbeitszeit_bis,
                "pause_stunden": pause_stunden,
                "netto_stunden": netto_stunden,
                "baustelle": baustelle,
                "team": request.form.get("team") or "",
                "arbeit": request.form.get("arbeit") or "",
                "material": request.form.get("material") or "",
                "bemerkung": request.form.get("bemerkung") or "",
                "bauleiter": request.form.get("bauleiter") or "",
                "ersteller": request.form.get("ersteller") or "",
            }

            rollen = [
                "polier",
                "vorarbeiter",
                "facharbeiter",
                "elektriker",
                "helfer",
                "lkw_fahrer",
            ]

            for rolle in rollen:
                daten[f"{rolle}_name"] = (
                    request.form.get(f"{rolle}_name") or ""
                )
                daten[f"{rolle}_stunden"] = to_float(
                    request.form.get(f"{rolle}_stunden"), 0.0
                )

            spalten = list(daten.keys())

            set_sql = ", ".join(
                f"{spalte} = %s" for spalte in spalten
            )

            if is_admin():
                where_sql = (
                    "id = %s AND company_id = %s "
                    "AND (signature IS NULL OR signature = '')"
                )
                where_params = (bericht_id, company_id)
            else:
                where_sql = (
                    "id = %s AND company_id = %s AND user_id = %s "
                    "AND (signature IS NULL OR signature = '')"
                )
                where_params = (
                    bericht_id,
                    company_id,
                    user_id,
                )

            cur.execute(
                f"""
                UPDATE reports
                SET {set_sql}
                WHERE {where_sql}
                """,
                tuple(daten.values()) + where_params,
            )

            if cur.rowcount == 0:
                conn.rollback()
                flash("Bericht konnte nicht aktualisiert werden.", "error")
                return redirect(url_for("list_reports"))

            conn.commit()

            flash(
                "Bautagesbericht erfolgreich aktualisiert.",
                "success",
            )

            return redirect(url_for("list_reports"))

        return render_template(
            "index.html",
            report=report,
            heute=date.today().isoformat(),
        )

    except HTTPException:
        raise

    except Exception:
        conn.rollback()
        app.logger.exception(
            "Fehler beim Bearbeiten des Bautagesberichts"
        )
        flash(
            "Fehler beim Bearbeiten des Bautagesberichts.",
            "error",
        )
        return redirect(url_for("list_reports"))

    finally:
        cur.close()
        conn.close()


@app.route("/detail/<int:report_id>")
def detail(report_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("bautagesbericht")
    if denied is not None:
        return denied

    company_id = current_company_id()
    user_id = current_user_id()

    conn = get_db()
    cur = conn.cursor()

    if is_admin():
        cur.execute(
            """
            SELECT r.*, u.name AS report_user_name
            FROM reports r
            LEFT JOIN users u ON r.user_id = u.id
            WHERE r.id = %s AND r.company_id = %s
            """,
            (report_id, company_id),
        )
    else:
        cur.execute(
            """
            SELECT r.*, u.name AS report_user_name
            FROM reports r
            LEFT JOIN users u ON r.user_id = u.id
            WHERE r.id = %s AND r.company_id = %s AND r.user_id = %s
            """,
            (report_id, company_id, user_id),
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

    if not is_admin():
        abort(403)

    try:
        company_id = current_company_id()

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, name, role, permissions, company_id, created_at
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

    except Exception as e:
        return f"USERS ERROR: {str(e)}", 500


@app.route("/users/add", methods=["GET", "POST"])
def users_add():
    if not is_logged_in():
        return redirect(url_for("login"))

    if not is_admin():
        abort(403)

    try:
        company_id = current_company_id()

        if request.method == "POST":
            try:
                validate_csrf(request.form.get("csrf_token", ""))
            except Exception:
                abort(400, description="Ungültiger CSRF-Token")
            name = (request.form.get("name") or "").strip()
            pin = (request.form.get("pin") or "").strip()
            role = "worker"
            permissions = sorted(set(request.form.getlist("permissions")) & set(PERMISSION_MODULES))

            if not name or not pin:
                flash("Bitte Name und PIN eingeben.", "error")
                return redirect(url_for("users_add"))

            conn = get_db()
            cur = conn.cursor()

            try:
                reset_sequences(cur)
                cur.execute(
                    """
                    INSERT INTO users (name, pin, role, company_id, permissions)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (company_id, name) DO NOTHING
                    """,
                    (name, pin, role, company_id, permissions),
                )
                if cur.rowcount == 0:
                    conn.rollback()
                    flash("Name bereits vorhanden. Bitte vorhandenen Mitarbeiter bearbeiten.", "warning")
                    return redirect(url_for("users_list"))
                conn.commit()
                flash("Benutzer gespeichert.", "success")
            except Exception as e:
                conn.rollback()
                return f"USERS ADD POST ERROR: {str(e)}", 500
            finally:
                cur.close()
                conn.close()

            return redirect(url_for("users_list"))

        return render_template("users_add.html")

    except Exception as e:
        return f"USERS ADD ERROR: {str(e)}", 500


@app.route("/users/<int:user_id>/permissions", methods=["GET", "POST"])
def users_permissions(user_id):
    if not is_logged_in():
        return redirect(url_for("login"))
    if not is_admin():
        abort(403)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, role, permissions FROM users WHERE id = %s AND company_id = %s", (user_id, current_company_id()))
            employee = cur.fetchone()
            if not employee:
                abort(404)
            if employee["role"] == "admin":
                abort(403)
            if request.method == "POST":
                try:
                    validate_csrf(request.form.get("csrf_token", ""))
                except Exception:
                    abort(400, description="Ungültiger CSRF-Token")
                permissions = sorted(set(request.form.getlist("permissions")) & set(PERMISSION_MODULES))
                cur.execute("UPDATE users SET permissions = %s WHERE id = %s AND company_id = %s AND role <> 'admin'", (permissions, user_id, current_company_id()))
                conn.commit()
                flash("Berechtigungen gespeichert.", "success")
                return redirect(url_for("users_list"))
        effective = set(PERMISSION_MODULES) if employee["permissions"] is None else set(employee["permissions"])
        return render_template("users_permissions.html", employee=employee, permissions=effective)
    finally:
        conn.close()


@app.route("/report/pdf/<int:report_id>")
def report_pdf(report_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("bautagesbericht")
    if denied is not None:
        return denied

    company_id = current_company_id()
    user_id = current_user_id()

    conn = get_db()
    cur = conn.cursor()

    if is_admin():
        cur.execute(
            """
            SELECT r.*, u.name AS report_user_name
            FROM reports r
            LEFT JOIN users u ON r.user_id = u.id
            WHERE r.id = %s AND r.company_id = %s
            """,
            (report_id, company_id),
        )
    else:
        cur.execute(
            """
            SELECT r.*, u.name AS report_user_name
            FROM reports r
            LEFT JOIN users u ON r.user_id = u.id
            WHERE r.id = %s AND r.company_id = %s AND r.user_id = %s
            """,
            (report_id, company_id, user_id),
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

    logo_path = os.path.join(BASE_DIR, "static", "logo.png")
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

    wetter_text = report.get("wetter") or ""
    temperatur_text = report.get("temperatur") or ""

    if temperatur_text:
        wetter_text = f"{wetter_text} / {temperatur_text} °C"

    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)
    p.drawString(95, y - 14, pdf_text(report.get("datum")))
    p.drawString(295, y - 14, pdf_text(report.get("baustelle")))
    p.drawString(95, y - 38, pdf_text(wetter_text))
    p.drawString(
        295,
        y - 38,
        pdf_text(f"{report.get('arbeitszeit_von') or ''} - {report.get('arbeitszeit_bis') or ''}"),
    )
    p.drawString(115, y - 62, pdf_text(report.get("bauleiter")))

    y -= 92

    p.setFont("Helvetica", 10)
    p.drawString(45, y, pdf_text(f"Pause: {report.get('pause_stunden') or 0} h"))
    p.drawString(220, y, pdf_text(f"Netto: {report.get('netto_stunden') or 0} h"))

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
        p.drawString(45, y, pdf_text(role))
        p.drawString(180, y, pdf_text(name or "-"))
        p.drawString(430, y, pdf_text(f"{hours or 0} h"))
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
    p.drawString(45, y, pdf_text(report.get("team")))
    y -= 34

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Taetigkeiten")
    y -= 18

    # Tätigkeiten – Text mit Zeilenumbrüchen
    from reportlab.lib.utils import simpleSplit

    arbeit_text = str(report.get("arbeit") or "")
    arbeit_lines = []

    for paragraph in arbeit_text.replace("\r\n", "\n").split("\n"):
        if paragraph.strip():
            arbeit_lines.extend(
                simpleSplit(pdf_text(paragraph), "Helvetica", 10, width - 100)
            )
        else:
            arbeit_lines.append("")

    arbeit_height = max(48, len(arbeit_lines) * 14 + 16)

    p.setFillColorRGB(*light_grey)
    p.rect(35, y + 8 - arbeit_height, width - 70, arbeit_height, fill=1, stroke=0)

    p.setFillColorRGB(0, 0, 0)
    y = pdf_multiline(p, arbeit_text, 45, y, width - 100)

    y -= 16

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Material")
    y -= 18

    # Material – Text mit Zeilenumbrüchen
    material_text = str(report.get("material") or "")
    material_lines = []

    for paragraph in material_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if paragraph.strip():
            material_lines.extend(
                simpleSplit(pdf_text(paragraph), "Helvetica", 10, width - 100)
            )
        else:
            material_lines.append("")

    material_height = max(32, len(material_lines) * 14 + 16)

    p.setFillColorRGB(*light_grey)
    p.rect(
        35,
        y + 8 - material_height,
        width - 70,
        material_height,
        fill=1,
        stroke=0
    )

    p.setFillColorRGB(0, 0, 0)
    y = pdf_multiline(p, material_text, 45, y, width - 100)

    y -= 16

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Bemerkung")
    y -= 18

    # Bemerkung – Text mit Zeilenumbrüchen
    bemerkung_text = str(report.get("bemerkung") or "")
    bemerkung_lines = []

    for paragraph in bemerkung_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if paragraph.strip():
            bemerkung_lines.extend(
                simpleSplit(pdf_text(paragraph), "Helvetica", 10, width - 100)
            )
        else:
            bemerkung_lines.append("")

    bemerkung_height = max(40, len(bemerkung_lines) * 14 + 16)

    p.setFillColorRGB(*light_grey)
    p.rect(
        35,
        y + 8 - bemerkung_height,
        width - 70,
        bemerkung_height,
        fill=1,
        stroke=0
    )

    p.setFillColorRGB(0, 0, 0)
    y = pdf_multiline(p, bemerkung_text, 45, y, width - 100)

    y -= 16 

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(300, 145, "Elektronische Unterschrift:")

    draw_signature_on_pdf(
        p,
        report.get("signature"),
        x=300,
        y=82,
        width=190,
        height=55,
    )

    p.setStrokeColorRGB(*dark_grey)
    p.line(300, 80, width - 50, 80)

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica", 9)
    p.drawString(300, 65, pdf_text(f"Erstellt von: {report.get('ersteller') or ''}"))

    p.showPage()
    p.save()

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"bautagesbericht_{report_id}.pdf",
        mimetype="application/pdf",
    )
@app.route("/entsorgungsdokumentation", methods=["GET", "POST"])
def entsorgungsdokumentation():
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("entsorgung")
    if denied is not None:
        return denied

    if request.method == "POST":
        company_id = current_company_id()
        user_id = current_user_id()

        unterschrift_bv = (
            request.form.get("unterschrift_bv") or ""
        ).strip()

        unterschrift_fahrer = (
            request.form.get("unterschrift_fahrer") or ""
        ).strip()

        # Oba potpisa su obavezna.
        for unterschrift in (unterschrift_bv, unterschrift_fahrer):
            if not unterschrift.startswith("data:image/png;base64,"):
                flash("Beide Unterschriften sind erforderlich.")
                return redirect(url_for("entsorgungsdokumentation"))

            try:
                bild = base64.b64decode(
                    unterschrift.split(",", 1)[1],
                    validate=True
                )
                if len(bild) < 100 or len(bild) > 500000:
                    raise ValueError("Ungültige Bildgröße")
                if not bild.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("Ungültiges PNG")
            except (ValueError, base64.binascii.Error):
                flash("Ungültige Unterschrift.")
                return redirect(url_for("entsorgungsdokumentation"))

        schrottmaterialien = []
        kabelreste = []

        schrott_namen = [
            "Kabelgarnituren",
            "Kabelverteiler / Hausanschluss- und Zählerschränke",
            "Betriebsmittel",
            "Beleuchtung",
            "Stahl / Eisen",
            "Sonstige Materialien",
        ]

        kabel_namen = [
            "Kupferkabel / Kupferleitungen",
            "Aluminiumkabel",
            "Kabel mit Bleimantel / Massekabel",
            "Kabelschutzrohre / Abdeckhauben",
            "Sonstiges",
        ]

        for prefix, namen, ziel in (
            ("schrott", schrott_namen, schrottmaterialien),
            ("kabel", kabel_namen, kabelreste),
        ):
            for nummer, material in enumerate(namen, start=1):
                beschreibung = (
                    request.form.get(f"{prefix}_beschreibung_{nummer}") or ""
                ).strip()

                menge = (
                    request.form.get(f"{prefix}_menge_{nummer}") or ""
                ).strip()

                einheit = (
                    request.form.get(f"{prefix}_einheit_{nummer}") or ""
                ).strip()

                if menge or beschreibung:
                    ziel.append({
                        "material": material,
                        "beschreibung": beschreibung,
                        "menge": menge,
                        "einheit": einheit,
                    })

        felder = {
            "baustellenverantwortlicher": (
                request.form.get("baustellenverantwortlicher") or ""
            ).strip(),
            "baustelle": (
                request.form.get("baustelle") or ""
            ).strip(),
            "projekt_nr": (
                request.form.get("projekt_nr") or ""
            ).strip(),
            "datum": request.form.get("datum") or "",
            "entsorgungsweg": request.form.get("entsorgungsweg") or "",
            "fahrer": (request.form.get("fahrer") or "").strip(),
            "uebergabe_datum": request.form.get("uebergabe_datum") or "",
            "uebergabe_uhrzeit": request.form.get("uebergabe_uhrzeit") or "",
            "uebergabeort": (
                request.form.get("uebergabeort") or ""
            ).strip(),
        }

        pflichtfelder = (
            "baustellenverantwortlicher",
            "baustelle",
            "datum",
            "entsorgungsweg",
            "fahrer",
            "uebergabe_datum",
            "uebergabe_uhrzeit",
            "uebergabeort",
        )

        if any(not felder[name] for name in pflichtfelder):
            flash("Bitte alle Pflichtfelder ausfüllen.")
            return redirect(url_for("entsorgungsdokumentation"))

        if felder["entsorgungsweg"] not in (
            "PEJO-Fahrer LKW",
            "BV Firmenfahrzeug",
        ):
            flash("Ungültiger Entsorgungsweg.")
            return redirect(url_for("entsorgungsdokumentation"))

        conn = None

        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO entsorgungsdokumentationen (
                    company_id,
                    user_id,
                    baustellenverantwortlicher,
                    baustelle,
                    projekt_nr,
                    datum,
                    schrottmaterialien,
                    kabelreste,
                    entsorgungsweg,
                    fahrer,
                    uebergabe_datum,
                    uebergabe_uhrzeit,
                    uebergabeort,
                    unterschrift_bv,
                    unterschrift_fahrer
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    company_id,
                    user_id,
                    felder["baustellenverantwortlicher"],
                    felder["baustelle"],
                    felder["projekt_nr"],
                    felder["datum"],
                    json.dumps(schrottmaterialien),
                    json.dumps(kabelreste),
                    felder["entsorgungsweg"],
                    felder["fahrer"],
                    felder["uebergabe_datum"],
                    felder["uebergabe_uhrzeit"],
                    felder["uebergabeort"],
                    unterschrift_bv,
                    unterschrift_fahrer,
                ),
            )

            dokument_id = cur.fetchone()["id"]
            conn.commit()

            flash(
                f"Entsorgungsdokumentation Nr. {dokument_id} gespeichert."
            )

            return redirect(url_for("entsorgungsdokumentation"))

        except Exception:
            if conn:
                conn.rollback()

            app.logger.exception(
                "Fehler beim Speichern der Entsorgungsdokumentation"
            )

            flash("Fehler beim Speichern. Bitte erneut versuchen.")
            return redirect(url_for("entsorgungsdokumentation"))

        finally:
            if conn:
                conn.close()

    return render_template("entsorgungsdokumentation.html")

@app.route("/entsorgungsdokumentation/bearbeiten/<int:dokument_id>", methods=["GET", "POST"])
def entsorgungsdokumentation_bearbeiten(dokument_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("entsorgung")
    if denied is not None:
        return denied

    # Gespeicherte Dokumente dürfen nicht mehr bearbeitet werden.
    # Gilt für Mitarbeiter und Administratoren.
    flash("Dieses Dokument ist bereits gespeichert und kann nicht mehr bearbeitet werden.")
    return redirect(url_for("entsorgungsdokumentation_liste"))

    company_id = current_company_id()
    if not company_id:
        abort(403)

    if request.method == "POST":
        try:
            validate_csrf(request.form.get("csrf_token", ""))
        except Exception:
            abort(400)

    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM entsorgungsdokumentationen WHERE id = %s AND company_id = %s",
            (dokument_id, company_id),
        )
        dokument = cur.fetchone()
        if not dokument:
            abort(404)

        if request.method == "GET":
            # JSONB wird von psycopg2 normalerweise bereits als Liste geliefert.
            dokument = dict(dokument)
            for feld in ("schrottmaterialien", "kabelreste"):
                wert = dokument.get(feld)
                if isinstance(wert, str):
                    wert = json.loads(wert)
                dokument[feld] = wert if isinstance(wert, list) else []
            return render_template("entsorgungsdokumentation.html", dokument=dokument)

        felder = {
            "baustellenverantwortlicher": (request.form.get("baustellenverantwortlicher") or "").strip(),
            "baustelle": (request.form.get("baustelle") or "").strip(),
            "projekt_nr": (request.form.get("projekt_nr") or "").strip(),
            "datum": (request.form.get("datum") or "").strip(),
            "entsorgungsweg": (request.form.get("entsorgungsweg") or "").strip(),
            "fahrer": (request.form.get("fahrer") or "").strip(),
            "uebergabe_datum": (request.form.get("uebergabe_datum") or "").strip(),
            "uebergabe_uhrzeit": (request.form.get("uebergabe_uhrzeit") or "").strip(),
            "uebergabeort": (request.form.get("uebergabeort") or "").strip(),
        }
        pflichtfelder = (
            "baustellenverantwortlicher", "baustelle", "datum", "entsorgungsweg",
            "fahrer", "uebergabe_datum", "uebergabe_uhrzeit", "uebergabeort",
        )
        if any(not felder[feld] for feld in pflichtfelder):
            flash("Bitte alle Pflichtfelder ausfüllen.")
            return redirect(url_for("entsorgungsdokumentation_bearbeiten", dokument_id=dokument_id))
        if felder["entsorgungsweg"] not in ("PEJO-Fahrer LKW", "BV Firmenfahrzeug"):
            flash("Ungültiger Entsorgungsweg.")
            return redirect(url_for("entsorgungsdokumentation_bearbeiten", dokument_id=dokument_id))

        schrott_namen = [
            "Kabelgarnituren", "Kabelverteiler / Hausanschluss- und Zählerschränke",
            "Betriebsmittel", "Beleuchtung", "Stahl / Eisen", "Sonstige Materialien",
        ]
        kabel_namen = [
            "Kupferkabel / Kupferleitungen", "Aluminiumkabel",
            "Kabel mit Bleimantel / Massekabel", "Kabelschutzrohre / Abdeckhauben",
            "Sonstiges",
        ]
        schrottmaterialien = []
        kabelreste = []
        for prefix, namen, ziel in (
            ("schrott", schrott_namen, schrottmaterialien),
            ("kabel", kabel_namen, kabelreste),
        ):
            for nummer, material in enumerate(namen, start=1):
                beschreibung = (request.form.get(f"{prefix}_beschreibung_{nummer}") or "").strip()
                menge = (request.form.get(f"{prefix}_menge_{nummer}") or "").strip()
                einheit = (request.form.get(f"{prefix}_einheit_{nummer}") or "").strip()
                if menge or beschreibung:
                    ziel.append({
                        "material": material, "beschreibung": beschreibung,
                        "menge": menge, "einheit": einheit,
                    })

        potpisi = []
        for naziv in ("unterschrift_bv", "unterschrift_fahrer"):
            potpis = (request.form.get(naziv) or "").strip()
            if not potpis.startswith("data:image/png;base64,"):
                flash("Beide Unterschriften sind erforderlich.")
                return redirect(url_for("entsorgungsdokumentation_bearbeiten", dokument_id=dokument_id))
            try:
                bild = base64.b64decode(potpis.split(",", 1)[1], validate=True)
                if not (100 <= len(bild) <= 500000) or not bild.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("Ungültiges PNG")
            except (ValueError, base64.binascii.Error):
                flash("Ungültige Unterschrift.")
                return redirect(url_for("entsorgungsdokumentation_bearbeiten", dokument_id=dokument_id))
            potpisi.append(potpis)

        cur.execute(
            """
            UPDATE entsorgungsdokumentationen
            SET baustellenverantwortlicher = %s, baustelle = %s, projekt_nr = %s,
                datum = %s, schrottmaterialien = %s::jsonb, kabelreste = %s::jsonb,
                entsorgungsweg = %s, fahrer = %s, uebergabe_datum = %s,
                uebergabe_uhrzeit = %s, uebergabeort = %s,
                unterschrift_bv = %s, unterschrift_fahrer = %s
            WHERE id = %s AND company_id = %s
            RETURNING id
            """,
            (
                felder["baustellenverantwortlicher"], felder["baustelle"],
                felder["projekt_nr"], felder["datum"], json.dumps(schrottmaterialien),
                json.dumps(kabelreste), felder["entsorgungsweg"], felder["fahrer"],
                felder["uebergabe_datum"], felder["uebergabe_uhrzeit"],
                felder["uebergabeort"], potpisi[0], potpisi[1], dokument_id, company_id,
            ),
        )
        if not cur.fetchone():
            abort(404)
        conn.commit()
        flash(f"Entsorgungsdokumentation Nr. {dokument_id} aktualisiert.")
        return redirect(url_for("entsorgungsdokumentation_liste"))
    except Exception as fehler:
        from werkzeug.exceptions import HTTPException
        if isinstance(fehler, HTTPException):
            raise
        if conn:
            conn.rollback()
        app.logger.exception("Fehler beim Bearbeiten der Entsorgungsdokumentation")
        flash("Dokument konnte nicht bearbeitet werden.")
        return redirect(url_for("entsorgungsdokumentation_liste"))
    finally:
        if conn:
            conn.close()


@app.route("/entsorgungsdokumentation/liste")
def entsorgungsdokumentation_liste():
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("entsorgung")
    if denied is not None:
        return denied

    conn = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                id,
                baustellenverantwortlicher,
                baustelle,
                projekt_nr,
                datum,
                fahrer,
                erstellt_am
            FROM entsorgungsdokumentationen
            WHERE company_id = %s
            ORDER BY erstellt_am DESC, id DESC
            """,
            (current_company_id(),)
        )

        dokumente = cur.fetchall()

        return render_template(
            "entsorgungsdokumentation_liste.html",
            dokumente=dokumente
        )

    except Exception:
        app.logger.exception(
            "Fehler beim Laden der Entsorgungsdokumentationen"
        )
        flash("Dokumente konnten nicht geladen werden.")
        return redirect(url_for("entsorgungsdokumentation"))

    finally:
        if conn:
            conn.close()


@app.route("/entsorgungsdokumentation/loeschen/<int:dokument_id>", methods=["POST"])
def entsorgungsdokumentation_loeschen(dokument_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("entsorgung")
    if denied is not None:
        return denied
    # CSRF-Schutz vor dem Löschen prüfen
    try:
        validate_csrf(request.form.get("csrf_token", ""))
    except Exception:
        abort(400)
   

    company_id = current_company_id()

    if not company_id:
        abort(403)

    conn = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM entsorgungsdokumentationen
            WHERE id = %s AND company_id = %s
            RETURNING id
            """,
            (dokument_id, company_id)
        )

        geloescht = cur.fetchone()
        conn.commit()

        if geloescht:
            flash("Dokument wurde erfolgreich gelöscht.")
        else:
            flash("Dokument nicht gefunden oder keine Berechtigung.")

    except Exception:
        if conn:
            conn.rollback()

        app.logger.exception(
            "Fehler beim Löschen der Entsorgungsdokumentation"
        )
        flash("Dokument konnte nicht gelöscht werden.")

    finally:
        if conn:
            conn.close()

    return redirect(url_for("entsorgungsdokumentation_liste"))


@app.route("/entsorgungsdokumentation/pdf/<int:dokument_id>")
def entsorgungsdokumentation_pdf(dokument_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    denied = require_module("entsorgung")
    if denied is not None:
        return denied

    conn = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM entsorgungsdokumentationen
            WHERE id = %s AND company_id = %s
            """,
            (dokument_id, current_company_id())
        )

        dokument = cur.fetchone()

        if not dokument:
            flash("Dokument nicht gefunden.")
            return redirect(url_for("entsorgungsdokumentation_liste"))

    except Exception:
        app.logger.exception(
            "Fehler beim Laden der Entsorgungsdokumentation für PDF"
        )
        flash("PDF konnte nicht erstellt werden.")
        return redirect(url_for("entsorgungsdokumentation_liste"))

    finally:
        if conn:
            conn.close()
        # PDF erstellen
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50

    # PEJO Firmenlogo
    logo_pfad = os.path.join(
        app.static_folder,
        "logo.png"
    )

    if os.path.exists(logo_pfad):
        pdf.drawImage(
            logo_pfad,
            45,
            height - 95,
            width=75,
            height=45,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto"
        )

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(135, height - 70, "PEJO Elektrotechnik")

    y = height - 115 

    # Dokumenttitel
    pdf.setFillColorRGB(0.12, 0.16, 0.23)
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(45, y, "ENTSORGUNGSDOKUMENTATION")

    # Rote Trennlinie
    pdf.setStrokeColorRGB(0.77, 0.0, 0.0)
    pdf.setLineWidth(2)
    pdf.line(45, y - 12, width - 45, y - 12)

    # Standardfarbe für weiteren Text
    pdf.setFillColorRGB(0, 0, 0)

    y -= 40

    pdf.setFont("Helvetica", 10)

     # Abschnitt: Baustellendaten
    pdf.setFillColorRGB(0.12, 0.16, 0.23)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(45, y, "BAUSTELLENDATEN")

    pdf.setFillColorRGB(0, 0, 0)
    y -= 25 

    def zeile(titel, wert):
        nonlocal y

        # Feldbezeichnung
        pdf.setFont("Helvetica-Bold", 9)
        pdf.setFillColorRGB(0.25, 0.29, 0.35)
        pdf.drawString(45, y, f"{titel}:")

        # Feldwert
        pdf.setFont("Helvetica", 10)
        pdf.setFillColorRGB(0, 0, 0)
        pdf.drawString(210, y, str(wert) if wert is not None else "-")

        # Dezente Trennlinie
        pdf.setStrokeColorRGB(0.88, 0.88, 0.88)
        pdf.setLineWidth(0.5)
        pdf.line(45, y - 6, width - 45, y - 6)

        y -= 24

    zeile("Dokument-Nr.", dokument["id"])
    zeile("Baustellenverantwortlicher", dokument["baustellenverantwortlicher"])
    zeile("Baustelle", dokument["baustelle"])
    zeile("Projekt-Nr.", dokument["projekt_nr"])
    zeile("Datum", dokument["datum"].strftime("%d.%m.%Y"))
    zeile("Entsorgungsweg", dokument["entsorgungsweg"])
    zeile("Fahrer", dokument["fahrer"])
    zeile("Übergabedatum", dokument["uebergabe_datum"].strftime("%d.%m.%Y"))
    zeile("Übergabezeit", dokument["uebergabe_uhrzeit"].strftime("%H:%M"))
    zeile("Übergabeort", dokument["uebergabeort"])

        # Schrottmaterialien und Kabelreste
    def materialien_anzeigen(titel, daten):
        nonlocal y

        y -= 15

        if y < 100:
            pdf.showPage()
            y = height - 50

        # Abschnittsüberschrift
        pdf.setFillColorRGB(0.12, 0.16, 0.23)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(45, y, titel.upper())

        # Rote Linie unter der Überschrift
        pdf.setStrokeColorRGB(0.77, 0.0, 0.0)
        pdf.setLineWidth(1)
        pdf.line(45, y - 7, width - 45, y - 7)

        # Standardfarbe wiederherstellen
        pdf.setFillColorRGB(0, 0, 0)
        y -= 25

        if isinstance(daten, str):
            daten = json.loads(daten)

        if not isinstance(daten, list):
            daten = []

        if not daten:
            pdf.setFont("Helvetica", 9)
            pdf.drawString(55, y, "Keine Angaben")
            y -= 20
            return

        for material in daten:
            if y < 100:
                pdf.showPage()
                y = height - 50

            pdf.setFont("Helvetica", 9)

            if isinstance(material, dict):
                text = " | ".join(
                    f"{schluessel}: {wert}"
                    for schluessel, wert in material.items()
                    if wert is not None and str(wert).strip()
                )
            else:
                text = str(material)

            if not text:
                text = "-"

            # Lange Zeilen umbrechen
            from reportlab.lib.utils import simpleSplit

            zeilen = simpleSplit(text, "Helvetica", 9, width - 110)

            for textzeile in zeilen:
                if y < 80:
                    pdf.showPage()
                    y = height - 50

                pdf.drawString(55, y, textzeile)
                y -= 15

            # Trennlinie zwischen Materialien
            pdf.setStrokeColorRGB(0.88, 0.88, 0.88)
            pdf.setLineWidth(0.5)
            pdf.line(55, y - 2, width - 45, y - 2)

            y -= 12

    materialien_anzeigen(
        "Schrottmaterialien",
        dokument["schrottmaterialien"]
    )

    materialien_anzeigen(
        "Kabelreste",
        dokument["kabelreste"]
    )

    # Genug Platz für beide Unterschriften sicherstellen
    if y < 200:
        pdf.showPage()
        y = height - 50

    y -= 20

    # Abschnitt: Unterschriften
    pdf.setFillColorRGB(0.12, 0.16, 0.23)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(45, y, "UNTERSCHRIFTEN")

    # Rote Trennlinie
    pdf.setStrokeColorRGB(0.77, 0.0, 0.0)
    pdf.setLineWidth(1)
    pdf.line(45, y - 7, width - 45, y - 7)

    pdf.setFillColorRGB(0, 0, 0)
    y -= 30

    def zeichne_unterschrift(titel, daten, x, position_y):
                
        # Rahmen für die digitale Unterschrift
        pdf.setStrokeColorRGB(0.75, 0.78, 0.82)
        pdf.setLineWidth(0.8)

        pdf.roundRect(
            x,
            position_y - 105,
            230,
            115,
            6,
            stroke=1,
            fill=0
        )

        # Unterschriftslinie
        pdf.setStrokeColorRGB(0.55, 0.55, 0.55)
        pdf.line(
            x + 10,
            position_y - 90,
            x + 220,
            position_y - 90
        )

        pdf.setFillColorRGB(0, 0, 0)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(x, position_y, titel)

        if daten:
            try:
                bilddaten = base64.b64decode(daten.split(",", 1)[-1])
                bild = ImageReader(BytesIO(bilddaten))

                pdf.drawImage(
                    bild,
                    x + 10,
                    position_y - 80,
                    width=210,
                    height=65,
                    preserveAspectRatio=True,
                    anchor="c",
                    mask="auto"
                )
                
            except Exception:
                app.logger.exception("Unterschrift konnte nicht geladen werden")
                pdf.drawString(x, position_y - 25, "Unterschrift nicht darstellbar")

    zeichne_unterschrift(
        "Baustellenverantwortlicher",
        dokument["unterschrift_bv"],
        45,
        y
    )

    zeichne_unterschrift("Fahrer", dokument["unterschrift_fahrer"], 315, y) 

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"Entsorgungsdokumentation_{dokument_id}.pdf",
        mimetype="application/pdf"
    )        
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
