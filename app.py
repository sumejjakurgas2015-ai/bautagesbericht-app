
import os
import sqlite3
from functools import wraps
from datetime import datetime

import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

# OBAVEZNO na Renderu stavi SECRET_KEY kao Environment Variable
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")


# -----------------------------
# DB helpers: Postgres (Render) or SQLite (local)
# -----------------------------
def is_postgres() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def get_pg_conn():
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(db_url)


SQLITE_PATH = os.path.join(BASE_DIR, "bautagesbericht.db")


def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_execute(sql: str, params=None, fetchone=False, fetchall=False):
    params = params or ()

    if is_postgres():
        with get_pg_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                if fetchone:
                    return cur.fetchone()
                if fetchall:
                    return cur.fetchall()
                return None
    else:
        with get_sqlite_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            if fetchone:
                row = cur.fetchone()
                return dict(row) if row else None
            if fetchall:
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            return None


# -----------------------------
# DB init
# -----------------------------
def init_db():
    # USERS (radnici + admin)
    if is_postgres():
        db_execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'worker',
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        db_execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP DEFAULT NOW(),
                created_by INTEGER,
                datum TEXT,
                arbeitszeit_von TEXT,
                arbeitszeit_bis TEXT,
                pause_stunden REAL,
                netto_stunden REAL,
                wetter TEXT,
                baustelle TEXT,
                team TEXT,
                polier_name TEXT,
                polier_stunden REAL,
                vorarbeiter_name TEXT,
                vorarbeiter_stunden REAL,
                facharbeiter_name TEXT,
                facharbeiter_stunden REAL,
                elektriker_name TEXT,
                elektriker_stunden REAL,
                helfer_name TEXT,
                helfer_stunden REAL,
                lkw_fahrer_name TEXT,
                lkw_fahrer_stunden REAL,
                arbeit TEXT,
                material TEXT,
                bemerkung TEXT
            );
        """)
    else:
        db_execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'worker',
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        db_execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT (datetime('now')),
                created_by INTEGER,
                datum TEXT,
                arbeitszeit_von TEXT,
                arbeitszeit_bis TEXT,
                pause_stunden REAL,
                netto_stunden REAL,
                wetter TEXT,
                baustelle TEXT,
                team TEXT,
                polier_name TEXT,
                polier_stunden REAL,
                vorarbeiter_name TEXT,
                vorarbeiter_stunden REAL,
                facharbeiter_name TEXT,
                facharbeiter_stunden REAL,
                elektriker_name TEXT,
                elektriker_stunden REAL,
                helfer_name TEXT,
                helfer_stunden REAL,
                arbeit TEXT,
                material TEXT,
                bemerkung TEXT
            );
        """)

    # auto-create ADMIN user (prvi put) preko env varijabli
    admin_name = os.environ.get("ADMIN_NAME", "Admin")
    admin_pin = os.environ.get("ADMIN_PIN", "").strip()

    # napravi admina samo ako postoji ADMIN_PIN
    if admin_pin:
        existing = db_execute("SELECT * FROM users WHERE role = %s" if is_postgres() else "SELECT * FROM users WHERE role = ?",
                              ("admin",), fetchone=True)
        if not existing:
            pin_hash = generate_password_hash(admin_pin)
            if is_postgres():
                db_execute("INSERT INTO users (name, pin_hash, role) VALUES (%s, %s, %s)",
                           (admin_name, pin_hash, "admin"))
            else:
                db_execute("INSERT INTO users (name, pin_hash, role) VALUES (?, ?, ?)",
                           (admin_name, pin_hash, "admin"))


@app.before_request
def _ensure_db():
    init_db()


# -----------------------------
# Auth helpers
# -----------------------------
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    if is_postgres():
        return db_execute("SELECT id, name, role FROM users WHERE id = %s", (uid,), fetchone=True)
    return db_execute("SELECT id, name, role FROM users WHERE id = ?", (uid,), fetchone=True)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u or u.get("role") != "admin":
            flash("Kein Zugriff (Admin benötigt).", "error")
            return redirect(url_for("index"))
        return fn(*args, **kwargs)
    return wrapper


# -----------------------------
# Netto time helpers
# -----------------------------
def parse_time_to_minutes(hhmm: str):
    s = (hhmm or "").strip()
    if not s or ":" not in s:
        return None
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def to_float_nonneg(val: str):
    s = (val or "").strip().replace(",", ".")
    if not s:
        return 0.0
    try:
        n = float(s)
        return 0.0 if n < 0 else n
    except ValueError:
        return 0.0


def calc_netto_stunden(von: str, bis: str, pause_stunden: float):
    mv = parse_time_to_minutes(von)
    mb = parse_time_to_minutes(bis)
    if mv is None or mb is None:
        return None

    diff = mb - mv
    if diff < 0:
        diff += 24 * 60

    netto = (diff / 60.0) - (pause_stunden or 0.0)
    if netto < 0:
        netto = 0.0
    return round(netto, 2)



@app.route("/")
def home():
    return redirect(url_for("login"))  # ako imaš /login
    # ako nemaš /login, stavi: return redirect(url_for("index"))

# -----------------------------
# Routes: LOGIN / LOGOUT
# -----------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        pin = (request.form.get("pin") or "").strip()

        if not name or not pin:
            flash("Bitte Name und PIN eingeben.", "error")
            return redirect(url_for("login"))

        if is_postgres():
            user = db_execute("SELECT * FROM users WHERE name = %s", (name,), fetchone=True)
        else:
            user = db_execute("SELECT * FROM users WHERE name = ?", (name,), fetchone=True)

        if not user or not check_password_hash(user["pin_hash"], pin):
            flash("Falscher Name oder PIN.", "error")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        flash(f"Willkommen, {user['name']}!", "success")
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Abgemeldet.", "success")
    return redirect(url_for("login"))


# -----------------------------
# Admin: Manage users (radnici)
# -----------------------------
@app.route("/admin/users", methods=["GET", "POST"])
@login_required
@admin_required
def admin_users():
    if request.method == "POST":
        new_name = (request.form.get("new_name") or "").strip()
        new_pin = (request.form.get("new_pin") or "").strip()
        new_role = (request.form.get("new_role") or "worker").strip()

        if not new_name or not new_pin:
            flash("Name und PIN sind Pflicht.", "error")
            return redirect(url_for("admin_users"))

        pin_hash = generate_password_hash(new_pin)

        # provjeri da li ime već postoji
        if is_postgres():
            exists = db_execute("SELECT id FROM users WHERE name = %s", (new_name,), fetchone=True)
        else:
            exists = db_execute("SELECT id FROM users WHERE name = ?", (new_name,), fetchone=True)

        if exists:
            flash("Dieser Name existiert bereits.", "error")
            return redirect(url_for("admin_users"))

        if is_postgres():
            db_execute("INSERT INTO users (name, pin_hash, role) VALUES (%s, %s, %s)", (new_name, pin_hash, new_role))
        else:
            db_execute("INSERT INTO users (name, pin_hash, role) VALUES (?, ?, ?)", (new_name, pin_hash, new_role))

        flash("Benutzer erstellt.", "success")
        return redirect(url_for("admin_users"))

    users = db_execute("SELECT id, name, role, created_at FROM users ORDER BY id DESC", fetchall=True)
    return render_template("users.html", users=users, me=current_user())


# -----------------------------
# App pages
# -----------------------------
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    heute = datetime.now().strftime("%d.%m.%Y")
    me = current_user()

    if request.method == "POST":
        datum = (request.form.get("datum") or "").strip()
        arbeitszeit_von = (request.form.get("arbeitszeit_von") or "").strip()
        arbeitszeit_bis = (request.form.get("arbeitszeit_bis") or "").strip()
        pause_stunden = to_float_nonneg(request.form.get("pause_stunden"))
        netto_stunden = calc_netto_stunden(arbeitszeit_von, arbeitszeit_bis, pause_stunden)

        wetter = (request.form.get("wetter") or "").strip()
        baustelle = (request.form.get("baustelle") or "").strip()
        team = (request.form.get("team") or "").strip()

        polier_name = (request.form.get("polier_name") or "").strip()
        polier_stunden = to_float_nonneg(request.form.get("polier_stunden"))
        vorarbeiter_name = (request.form.get("vorarbeiter_name") or "").strip()
        vorarbeiter_stunden = to_float_nonneg(request.form.get("vorarbeiter_stunden"))
        facharbeiter_name = (request.form.get("facharbeiter_name") or "").strip()
        facharbeiter_stunden = to_float_nonneg(request.form.get("facharbeiter_stunden"))
        elektriker_name = (request.form.get("elektriker_name") or "").strip()
        elektriker_stunden = to_float_nonneg(request.form.get("elektriker_stunden"))
        helfer_name = (request.form.get("helfer_name") or "").strip()
        helfer_stunden = to_float_nonneg(request.form.get("helfer_stunden"))

        arbeit = (request.form.get("arbeit") or "").strip()
        material = (request.form.get("material") or "").strip()
        bemerkung = (request.form.get("bemerkung") or "").strip()

        if not datum or not baustelle:
            flash("Bitte Datum und Baustelle ausfüllen.", "error")
            return redirect(url_for("index"))

        if is_postgres():
            db_execute("""
                INSERT INTO reports (
                    created_by, datum, arbeitszeit_von, arbeitszeit_bis, pause_stunden, netto_stunden,
                    wetter, baustelle, team,
                    polier_name, polier_stunden, vorarbeiter_name, vorarbeiter_stunden,
                    facharbeiter_name, facharbeiter_stunden, elektriker_name, elektriker_stunden,
                    helfer_name, helfer_stunden,lkw_fahrer_name,
                    lkw_fahrer_stunden, arbeit, material, bemerkung
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
            """, (
                me["id"], datum, arbeitszeit_von, arbeitszeit_bis, pause_stunden, netto_stunden,
                wetter, baustelle, team,
                polier_name, polier_stunden, vorarbeiter_name, vorarbeiter_stunden,
                facharbeiter_name, facharbeiter_stunden, elektriker_name, elektriker_stunden,
                helfer_name, helfer_stunden, lkw_fahrer_name, lkw_fahrer_stunden, 
                arbeit, material, bemerkung
            ))
        else:
            db_execute("""
                INSERT INTO reports (
                    created_by, datum, arbeitszeit_von, arbeitszeit_bis, pause_stunden, netto_stunden,
                    wetter, baustelle, team,
                    polier_name, polier_stunden, vorarbeiter_name, vorarbeiter_stunden,
                    facharbeiter_name, facharbeiter_stunden, elektriker_name, elektriker_stunden,
                    helfer_name, helfer_stunden, arbeit, material, bemerkung
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
            """, (
                me["id"], datum, arbeitszeit_von, arbeitszeit_bis, pause_stunden, netto_stunden,
                wetter, baustelle, team,
                polier_name, polier_stunden, vorarbeiter_name, vorarbeiter_stunden,
                facharbeiter_name, facharbeiter_stunden, elektriker_name, elektriker_stunden,
                helfer_name, helfer_stunden, arbeit, material, bemerkung
            ))

        flash("Bautagesbericht wurde gespeichert.", "success")
        return redirect(url_for("list_reports"))

    return render_template("index.html", heute=heute, me=me)


@app.route("/list")
@login_required
def list_reports():
    # join sa users za "erstellt von"
    if is_postgres():
        reports = db_execute("""
            SELECT r.*, u.name AS created_by_name
            FROM reports r
            LEFT JOIN users u ON u.id = r.created_by
            ORDER BY r.id DESC
        """, fetchall=True)
    else:
        reports = db_execute("""
            SELECT r.*, u.name AS created_by_name
            FROM reports r
            LEFT JOIN users u ON u.id = r.created_by
            ORDER BY r.id DESC
        """, fetchall=True)

    return render_template("list.html", reports=reports, me=current_user())


@app.route("/report/<int:report_id>")
@login_required
def report_detail(report_id):
    if is_postgres():
        report = db_execute("""
            SELECT r.*, u.name AS created_by_name
            FROM reports r
            LEFT JOIN users u ON u.id = r.created_by
            WHERE r.id = %s
        """, (report_id,), fetchone=True)
    else:
        report = db_execute("""
            SELECT r.*, u.name AS created_by_name
            FROM reports r
            LEFT JOIN users u ON u.id = r.created_by
            WHERE r.id = ?
        """, (report_id,), fetchone=True)

    if not report:
        flash("Bericht nicht gefunden.", "error")
        return redirect(url_for("list_reports"))

    return render_template("detail.html", report=report, me=current_user())


@app.route("/edit/<int:report_id>", methods=["GET", "POST"])
@login_required
def edit_report(report_id):
    me = current_user()

    if is_postgres():
        report = db_execute("SELECT * FROM reports WHERE id = %s", (report_id,), fetchone=True)
    else:
        report = db_execute("SELECT * FROM reports WHERE id = ?", (report_id,), fetchone=True)

    if not report:
        flash("Bericht nicht gefunden.", "error")
        return redirect(url_for("list_reports"))

    if request.method == "POST":
        datum = (request.form.get("datum") or "").strip()
        arbeitszeit_von = (request.form.get("arbeitszeit_von") or "").strip()
        arbeitszeit_bis = (request.form.get("arbeitszeit_bis") or "").strip()
        pause_stunden = to_float_nonneg(request.form.get("pause_stunden"))
        netto_stunden = calc_netto_stunden(arbeitszeit_von, arbeitszeit_bis, pause_stunden)

        wetter = (request.form.get("wetter") or "").strip()
        baustelle = (request.form.get("baustelle") or "").strip()
        team = (request.form.get("team") or "").strip()

        polier_name = (request.form.get("polier_name") or "").strip()
        polier_stunden = to_float_nonneg(request.form.get("polier_stunden"))
        vorarbeiter_name = (request.form.get("vorarbeiter_name") or "").strip()
        vorarbeiter_stunden = to_float_nonneg(request.form.get("vorarbeiter_stunden"))
        facharbeiter_name = (request.form.get("facharbeiter_name") or "").strip()
        facharbeiter_stunden = to_float_nonneg(request.form.get("facharbeiter_stunden"))
        elektriker_name = (request.form.get("elektriker_name") or "").strip()
        elektriker_stunden = to_float_nonneg(request.form.get("elektriker_stunden"))
        helfer_name = (request.form.get("helfer_name") or "").strip()
        helfer_stunden = to_float_nonneg(request.form.get("helfer_stunden"))
        lkw_fahrer_name = (request.form.get("lkw_fahrer_name") or "").strip()
        lkw_fahrer_stunden = to_float_nonneg(request.form.get("lkw_fahrer_stunden"))

        arbeit = (request.form.get("arbeit") or "").strip()
        material = (request.form.get("material") or "").strip()
        bemerkung = (request.form.get("bemerkung") or "").strip()

        if not datum or not baustelle:
            flash("Bitte Datum und Baustelle ausfüllen.", "error")
            return redirect(url_for("edit_report", report_id=report_id))

        # admin može editovati sve, worker može editovati samo svoje (ako želiš strogo)
        # ako hoćeš strogo: uncomment:
        # if me["role"] != "admin" and report.get("created_by") != me["id"]:
        #     flash("Kein Zugriff (nur eigener Bericht).", "error")
        #     return redirect(url_for("list_reports"))

        if is_postgres():
            db_execute("""
                UPDATE reports SET
                    datum=%s, arbeitszeit_von=%s, arbeitszeit_bis=%s, pause_stunden=%s, netto_stunden=%s,
                    wetter=%s, baustelle=%s, team=%s,
                    polier_name=%s, polier_stunden=%s,
                    vorarbeiter_name=%s, vorarbeiter_stunden=%s,
                    facharbeiter_name=%s, facharbeiter_stunden=%s,
                    elektriker_name=%s, elektriker_stunden=%s,
                    helfer_name=%s, helfer_stunden=%s,
                    arbeit=%s, material=%s, bemerkung=%s
                WHERE id=%s
            """, (
                datum, arbeitszeit_von, arbeitszeit_bis, pause_stunden, netto_stunden,
                wetter, baustelle, team,
                polier_name, polier_stunden,
                vorarbeiter_name, vorarbeiter_stunden,
                facharbeiter_name, facharbeiter_stunden,
                elektriker_name, elektriker_stunden,
                helfer_name, helfer_stunden,
                arbeit, material, bemerkung,
                report_id
            ))
        else:
            db_execute("""
                UPDATE reports SET
                    datum=?, arbeitszeit_von=?, arbeitszeit_bis=?, pause_stunden=?, netto_stunden=?,
                    wetter=?, baustelle=?, team=?,
                    polier_name=?, polier_stunden=?,
                    vorarbeiter_name=?, vorarbeiter_stunden=?,
                    facharbeiter_name=?, facharbeiter_stunden=?,
                    elektriker_name=?, elektriker_stunden=?,
                    helfer_name=?, helfer_stunden=?,
                    arbeit=?, material=?, bemerkung=?
                WHERE id=?
            """, (
                datum, arbeitszeit_von, arbeitszeit_bis, pause_stunden, netto_stunden,
                wetter, baustelle, team,
                polier_name, polier_stunden,
                vorarbeiter_name, vorarbeiter_stunden,
                facharbeiter_name, facharbeiter_stunden,
                elektriker_name, elektriker_stunden,
                helfer_name, helfer_stunden,
                arbeit, material, bemerkung,
                report_id
            ))

        flash("Bericht wurde aktualisiert.", "success")
        return redirect(url_for("report_detail", report_id=report_id))

    return render_template("edit.html", report=report, me=me)


@app.route("/delete/<int:report_id>", methods=["POST"])
@login_required
@admin_required
def delete_report(report_id):
    if is_postgres():
        db_execute("DELETE FROM reports WHERE id = %s", (report_id,))
    else:
        db_execute("DELETE FROM reports WHERE id = ?", (report_id,))

    flash("Bericht wurde gelöscht.", "success")
    return redirect(url_for("list_reports"))
@app.route("/health")
def health():
    return "OK", 200

@app.route("/")
def home():
    # ako imaš login rutu, prebaci na nju:
    return redirect(url_for("login"))  # ako nema login, reci mi pa stavimo na index


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)