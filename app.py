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
)

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
DEFAULT_COMPANY_ID = int(os.environ.get("COMPANY_ID", "1"))


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

    return render_template("dashboard.html")
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
            (kontrola_id, company_id)
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

    p.setFont("Helvetica-Bold", 18)
    p.drawString(50, height - 60, "Taegliche Abfahrtskontrolle")

    p.setFont("Helvetica", 11)
    p.drawString(50, height - 100, "PEJO Elektrotechnik GmbH")

    p.setFont("Helvetica", 11)

    p.drawString(50, height - 150, f"Datum: {kontrola['datum'].strftime('%d.%m.%Y')}")
    p.drawString(50, height - 175, f"Fahrzeug: {pdf_text(kontrola['fahrzeug'] or '')}")
    p.drawString(50, height - 200, f"Kennzeichen: {pdf_text(kontrola['kennzeichen'] or '')}")
    p.drawString(50, height - 225, f"Fahrer: {pdf_text(kontrola['fahrer'] or '')}")

    status = "Ja" if kontrola["ist_ok"] else "Nein"

    p.drawString(50, height - 260, f"Fahrzeug in Ordnung: {status}")

    maengel = pdf_text(kontrola["maengel"] or "Keine")
    p.drawString(50, height - 285, f"Maengel: {maengel[:75]}")

    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, height - 340, "Unterschrift des Fahrers:")

    draw_signature_on_pdf(
        p,
        kontrola["unterschrift"],
        50,
        height - 430,
        width=180,
        height=70
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

@app.route("/abfahrtskontrolle", methods=["GET", "POST"])
def abfahrtskontrolle():
    if not is_logged_in():
        return redirect(url_for("login"))

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

    company_id = current_company_id()
    user_id = current_user_id()

    if is_admin():
        reports = get_reports_for_company(company_id)
    else:
        reports = get_reports_for_user(company_id, user_id)

    return render_template("list.html", reports=reports)


@app.route("/detail/<int:report_id>")
def detail(report_id):
    if not is_logged_in():
        return redirect(url_for("login"))

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

    try:
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

    except Exception as e:
        return f"USERS ERROR: {str(e)}", 500


@app.route("/users/add", methods=["GET", "POST"])
def users_add():
    if not is_logged_in():
        return redirect(url_for("login"))

    try:
        company_id = current_company_id()

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            pin = (request.form.get("pin") or "").strip()
            role = (request.form.get("role") or "worker").strip().lower()

            if role not in ("worker", "admin"):
                role = "worker"

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
                    SET pin = EXCLUDED.pin,
                        role = EXCLUDED.role
                    """,
                    (name, pin, role, company_id),
                )
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


@app.route("/report/pdf/<int:report_id>")
def report_pdf(report_id):
    if not is_logged_in():
        return redirect(url_for("login"))

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

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 40, width - 70, 48, fill=1, stroke=0)
    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)
    p.drawString(45, y, pdf_text(report.get("arbeit")))
    y -= 58

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Material")
    y -= 18

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 24, width - 70, 32, fill=1, stroke=0)
    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)
    p.drawString(45, y, pdf_text(report.get("material")))
    y -= 42

    p.setFillColorRGB(*dark_grey)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Bemerkung")
    y -= 18

    p.setFillColorRGB(*light_grey)
    p.rect(35, y - 32, width - 70, 40, fill=1, stroke=0)
    p.setFillColorRGB(0, 0, 0)
    p.setFont("Helvetica", 10)
    p.drawString(45, y, pdf_text(report.get("bemerkung")))

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

@app.route("/entsorgungsdokumentation/liste")
def entsorgungsdokumentation_liste():
    if not is_logged_in():
        return redirect(url_for("login"))

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


@app.route("/entsorgungsdokumentation/pdf/<int:dokument_id>")
def entsorgungsdokumentation_pdf(dokument_id):
    if not is_logged_in():
        return redirect(url_for("login"))

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
    if y < 180:
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
        pdf.setFont("Helvetica", 9)
        pdf.drawString(x, position_y, titel)

        if daten:
            try:
                bilddaten = base64.b64decode(daten.split(",", 1)[-1])
                bild = ImageReader(BytesIO(bilddaten))

                pdf.drawImage(
                    bild,
                    x,
                    position_y - 95,
                    width=220,
                    height=80,
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

    zeichne_unterschrift(
        "Fahrer",
        dokument["unterschrift_fahrer"],
        310,
        y
    )

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
