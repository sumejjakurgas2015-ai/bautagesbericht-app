import os
import sqlite3
from datetime import datetime
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

# Lokalno: koristi SQLite fajl (tvoj postojeći .db)
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "bautagesbericht.db")


def is_postgres():
    return bool(os.environ.get("DATABASE_URL"))


def get_pg_conn():
    """
    Render Postgres obično daje DATABASE_URL.
    Ponekad je scheme 'postgres://', a psycopg2 očekuje 'postgresql://'.
    Ovdje to ispravljamo i spajamo se.
    """
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    # psycopg2 može direktno preko DSN stringa
    return psycopg2.connect(db_url)


def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_execute(sql, params=None, fetchone=False, fetchall=False):
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


def init_db():
    if is_postgres():
        db_execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP DEFAULT NOW(),
                datum DATE,
                baustelle TEXT,
                wetter TEXT,
                team TEXT,
                arbeit TEXT,
                material TEXT,
                bemerkung TEXT
            );
            """
        )
    else:
        db_execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT (datetime('now')),
                datum TEXT,
                baustelle TEXT,
                wetter TEXT,
                team TEXT,
                arbeit TEXT,
                material TEXT,
                bemerkung TEXT
            );
            """
        )


@app.before_request
def _ensure_db():
    # osiguraj da tabela postoji
    init_db()


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        datum = request.form.get("datum", "").strip()
        baustelle = request.form.get("baustelle", "").strip()
        wetter = request.form.get("wetter", "").strip()
        team = request.form.get("team", "").strip()
        arbeit = request.form.get("arbeit", "").strip()
        material = request.form.get("material", "").strip()
        bemerkung = request.form.get("bemerkung", "").strip()

        if not datum or not baustelle:
            flash("Bitte Datum und Baustelle ausfüllen.", "error")
            return redirect(url_for("index"))

        if is_postgres():
            db_execute(
                """
                INSERT INTO reports (datum, baustelle, wetter, team, arbeit, material, bemerkung)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (datum, baustelle, wetter, team, arbeit, material, bemerkung),
            )
        else:
            db_execute(
                """
                INSERT INTO reports (datum, baustelle, wetter, team, arbeit, material, bemerkung)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (datum, baustelle, wetter, team, arbeit, material, bemerkung),
            )

        flash("Bautagesbericht wurde gespeichert.", "success")
        return redirect(url_for("list_reports"))

    return render_template("index.html")


@app.route("/list")
def list_reports():
    rows = db_execute("SELECT * FROM reports ORDER BY id DESC", fetchall=True)

    # Sigurno formatiranje datuma za prikaz u listi
    for r in rows:
        d = r.get("datum")
        if not d:
            r["datum_fmt"] = ""
            continue

        try:
            r["datum_fmt"] = d.strftime("%d.%m.%Y")  # ako je date/datetime
        except Exception:
            s = str(d)  # ako je string "YYYY-MM-DD"
            if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                r["datum_fmt"] = f"{s[8:10]}.{s[5:7]}.{s[0:4]}"
            else:
                r["datum_fmt"] = s

    return render_template("list.html", reports=rows)


    # dodaj formatirani datum koji ne baca grešku
    for r in rows:
        d = r.get("datum")
        if not d:
            r["datum_fmt"] = ""
            continue

        # Postgres može vratiti date ili string; oba podržavamo
        try:
            r["datum_fmt"] = d.strftime("%d.%m.%Y")
        except Exception:
            s = str(d)
            # očekujemo "YYYY-MM-DD"
            if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                r["datum_fmt"] = f"{s[8:10]}.{s[5:7]}.{s[0:4]}"
            else:
                r["datum_fmt"] = s

    return render_template("list.html", reports=rows)


@app.route("/report/<int:report_id>")
def report_detail(report_id):
    if is_postgres():
        row = db_execute(
            "SELECT * FROM reports WHERE id = %s",
            (report_id,),
            fetchone=True,
        )
    else:
        row = db_execute(
            "SELECT * FROM reports WHERE id = ?",
            (report_id,),
            fetchone=True,
        )

    if not row:
        flash("Bericht nicht gefunden.", "error")
        return redirect(url_for("list_reports"))

    return render_template("detail.html", report=row)


@app.route("/delete/<int:report_id>", methods=["POST"])
def delete_report(report_id):
    if is_postgres():
        db_execute("DELETE FROM reports WHERE id = %s", (report_id,))
    else:
        db_execute("DELETE FROM reports WHERE id = ?", (report_id,))

    flash("Bericht wurde gelöscht.", "success")
    return redirect(url_for("list_reports"))


# Lokalno pokretanje (Render koristi gunicorn iz Procfile)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
