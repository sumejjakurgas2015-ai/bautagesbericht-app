from flask import Flask, render_template, request, redirect, url_for, flash
import os
import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL nije postavljen (Render Environment).")
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            datum TEXT,
            baustelle TEXT,
            wetter TEXT,
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

        if not baustelle:
            flash("Baustelle je obavezno polje!", "error")
            return redirect(url_for("index"))

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO reports (datum, baustelle, wetter, team, arbeit, material, bemerkung)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (datum, baustelle, wetter, team, arbeit, material, bemerkung))

        conn.commit()
        cur.close()
        conn.close()

        flash("Bautagesbericht je sačuvan ✅", "success")
        return redirect(url_for("list_reports"))

    return render_template("index.html")


@app.route("/list")
def list_reports():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM reports ORDER BY id DESC")
    reports = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("list.html", reports=reports)


@app.route("/report/<int:report_id>")
def report_detail(report_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM reports WHERE id = %s", (report_id,))
    report = cur.fetchone()

    cur.close()
    conn.close()

    if report is None:
        flash("Izvještaj nije pronađen.", "error")
        return redirect(url_for("list_reports"))

    return render_template("detail.html", report=report)


@app.route("/delete/<int:report_id>", methods=["POST"])
def delete_report(report_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM reports WHERE id = %s", (report_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Izvještaj obrisan 🗑️", "success")
    return redirect(url_for("list_reports"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

    



