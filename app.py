#!/usr/bin/env python3
"""Trainer Ops Dashboard - deployable (Render / any host).
Data persists in SQLite (trainerops.db) so it survives restarts.
Run locally:  python app.py
Run on host:  gunicorn -b 0.0.0.0:$PORT app:app
"""
import json, os, datetime, sqlite3
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DATABASE_URL", os.path.join(BASE, "trainerops.db"))

TRAINERS = [
    "Linu Raju", "Sandeepkumar S", "Gaddam Vamsidhar Reddy", "Naga Sandeep Kumar",
    "Tejas", "Sabin Peter", "Vinay", "Vimal", "Rasiq", "Sagar", "Kalai", "Faizan"
]
ACTIVITY_OPTIONS = [
    "NHT Day 1", "NHT Day 2", "NHT Day 3", "NHT Day 4", "NHT Day 5", "NHT Day 6",
    "NHT Day 7", "NHT Day 8", "NHT Day 9", "NHT Day 10", "NHT Day 11", "NHT Day 12",
    "Technical Training Day 1", "Technical Training Day 2", "Technical Training Day 3",
    "Visit Barge", "Visit Barge New Process", "MIS Update", "NHT & Calender Block",
    "Attendance Regularization", "Help Desk RM Support", "Weekly Off", "Leave", "Other"
]
OPERATIONS = [
    {"id": "mis",    "label": "MIS Update"},
    {"id": "nhtcal", "label": "NHT & Calender Block"},
    {"id": "att",    "label": "Attendance Regularization"},
    {"id": "vb",     "label": "Visit Barge"},
    {"id": "rm",     "label": "Help Desk RM Support"}
]
OP_STATUS = ["Done", "Pending", "Blocked", "NA"]
OP_READINESS = ["Ready", "Not Ready", "NA"]


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        date TEXT,
        trainer TEXT,
        activities TEXT,
        operations TEXT
    )""")
    conn.commit()
    conn.close()


init_db()


def today():
    return datetime.date.today().isoformat()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config")
def api_config():
    return jsonify({
        "trainers": TRAINERS,
        "activities": ACTIVITY_OPTIONS,
        "operations": OPERATIONS,
        "opStatus": OP_STATUS,
        "opReadiness": OP_READINESS,
        "today": today()
    })


@app.route("/api/submit", methods=["POST"])
def api_submit():
    e = request.get_json(force=True, silent=True) or {}
    if not e.get("date") or not e.get("trainer"):
        return jsonify({"status": "error", "message": "Missing date or trainer"}), 400
    if e["trainer"] not in TRAINERS:
        return jsonify({"status": "error", "message": "Unknown trainer"}), 400

    activities = [{"activity": a["activity"], "comment": str(a.get("comment", ""))[:300]}
                  for a in e.get("activities", []) if a and a.get("activity")]
    ops = {}
    for op in OPERATIONS:
        o = (e.get("operations") or {}).get(op["id"])
        if o:
            ops[op["id"]] = {
                "status": o.get("status", "NA"),
                "checks": str(o.get("checks", ""))[:100],
                "readiness": o.get("readiness", "NA"),
                "comment": str(o.get("comment", ""))[:300]
            }
    conn = get_db()
    cur = conn.execute("SELECT id FROM entries WHERE date=? AND trainer=?", (e["date"], e["trainer"]))
    row = cur.fetchone()
    payload = (datetime.datetime.now().isoformat(timespec="seconds"), e["date"], e["trainer"],
               json.dumps(activities, ensure_ascii=False), json.dumps(ops, ensure_ascii=False))
    if row:
        conn.execute("UPDATE entries SET timestamp=?, date=?, trainer=?, activities=?, operations=? WHERE id=?",
                     payload + (row["id"],))
        updated = True
    else:
        conn.execute("INSERT INTO entries (timestamp, date, trainer, activities, operations) VALUES (?,?,?,?,?)", payload)
        updated = False
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "updated": updated})


@app.route("/api/report")
def api_report():
    date_str = request.args.get("date", today())
    conn = get_db()
    rows = conn.execute("SELECT * FROM entries WHERE date=?", (date_str,)).fetchall()
    conn.close()
    by_trainer = {r["trainer"]: r for r in rows}
    out = []
    for t in TRAINERS:
        r = by_trainer.get(t)
        out.append({
            "trainer": t,
            "submitted": r is not None,
            "activities": json.loads(r["activities"]) if r else [],
            "operations": json.loads(r["operations"]) if r else {}
        })
    return jsonify({"rows": out, "date": date_str, "operations": OPERATIONS})


@app.route("/api/whatsapp")
def api_whatsapp():
    date_str = request.args.get("date", today())
    conn = get_db()
    rows = conn.execute("SELECT * FROM entries WHERE date=?", (date_str,)).fetchall()
    conn.close()
    by_trainer = {r["trainer"]: r for r in rows}
    submitted = [t for t in TRAINERS if t in by_trainer]
    L = []
    L.append("\U0001F4CB *Trainer Ops Update \u2014 " + fmt(date_str) + "*")
    L.append("\u2501" * 20)
    L.append("Submitted: %d/%d" % (len(submitted), len(TRAINERS)))
    for t in TRAINERS:
        r = by_trainer.get(t)
        L.append("")
        L.append("\U0001F464 *" + t + "*")
        if not r:
            L.append("\u26AA Yet to update")
            L.append("\u2501" * 20)
            continue
        acts = json.loads(r["activities"])
        ops = json.loads(r["operations"])
        if acts:
            L.append("\U0001F4CC *Activity:*")
            for a in acts:
                L.append('  \u2022 ' + a["activity"] + (' \u2014 "' + a["comment"] + '"' if a.get("comment") else ""))
        if ops:
            L.append("\U0001F527 *Operations:*")
            for op in OPERATIONS:
                o = ops.get(op["id"])
                if not o:
                    continue
                s_icon = {"Done": "\u2705", "Pending": "\u25F1", "Blocked": "\U0001F534", "NA": "\u2796"}.get(o["status"], "\u2796")
                r_icon = {"Ready": "\U0001F7E2", "Not Ready": "\U0001F534", "NA": "\u26AA"}.get(o["readiness"], "\u26AA")
                L.append("  " + s_icon + " " + op["label"] +
                         (" [" + o["checks"] + "]" if o.get("checks") else "") +
                         " " + r_icon + " " + o["readiness"] +
                         ((" \u2014 " + o["comment"]) if o.get("comment") else ""))
        L.append("\u2501" * 20)
    return jsonify({"text": "\n".join(L)})


def fmt(d):
    try:
        y, m, day = d.split("-")
        return "%s %s %s" % (day, ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][int(m)-1], y)
    except Exception:
        return d


if __name__ == "__main__":
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]
    except Exception:
        ip = "localhost"
    finally:
        s.close()
    port = int(os.environ.get("PORT", 5000))
    print("Trainer Ops Dashboard running at http://%s:%d" % (ip, port))
    app.run(host="0.0.0.0", port=port, debug=False)
