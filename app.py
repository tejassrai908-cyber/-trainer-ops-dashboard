#!/usr/bin/env python3
"""Trainer - Day Activity dashboard (deployable on Render / any host).

Operations model (per trainer, per day):
  - MIS Update            : status "Updated" + mandatory date
  - Attendance Regular.   : status (Regularized till date / Pending from date) + mandatory date
  - Help Desk RM Support  : status "I Will Support at least" + count (2RM/4RM/6RM/10RM)

Data persists in SQLite (trainerops.db) within the running instance.
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
    {"id": "mis", "label": "MIS Update", "statusOptions": ["Updated"], "requireDate": True},
    {"id": "att", "label": "Attendance Regularization",
     "statusOptions": ["Regularized till date", "Pending from date"], "requireDate": True},
    {"id": "rm", "label": "Help Desk RM Support",
     "statusOptions": ["I Will Support at least"], "countOptions": ["2RM", "4RM", "6RM", "10RM"]},
]


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, date TEXT, trainer TEXT, activities TEXT, operations TEXT
    )""")
    conn.commit()
    conn.close()


init_db()


def today():
    return datetime.date.today().isoformat()


def fmt(d):
    try:
        y, m, day = d.split("-")
        return "%s %s %s" % (day, ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(m) - 1], y)
    except Exception:
        return d


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config")
def api_config():
    return jsonify({
        "trainers": TRAINERS,
        "activities": ACTIVITY_OPTIONS,
        "operations": OPERATIONS,
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
        o = (e.get("operations") or {}).get(op["id"]) or {}
        status = (o.get("status") or "").strip()
        if not status:
            continue
        entry = {"status": status}
        if op.get("requireDate"):
            d = (o.get("date") or "").strip()
            if not d:
                return jsonify({"status": "error",
                                "message": op["label"] + " needs a date"}), 400
            entry["date"] = d
        if op.get("countOptions"):
            c = (o.get("count") or "").strip()
            if not c:
                return jsonify({"status": "error",
                                "message": op["label"] + " needs a count (e.g. 4RM)"}), 400
            entry["count"] = c
        ops[op["id"]] = entry

    conn = get_db()
    cur = conn.execute("SELECT id FROM entries WHERE date=? AND trainer=?",
                       (e["date"], e["trainer"]))
    row = cur.fetchone()
    payload = (datetime.datetime.now().isoformat(timespec="seconds"), e["date"], e["trainer"],
               json.dumps(activities, ensure_ascii=False), json.dumps(ops, ensure_ascii=False))
    if row:
        conn.execute("UPDATE entries SET timestamp=?, date=?, trainer=?, activities=?, operations=? WHERE id=?",
                     payload + (row["id"],))
        updated = True
    else:
        conn.execute("INSERT INTO entries (timestamp,date,trainer,activities,operations) VALUES (?,?,?,?,?)",
                     payload)
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

    data = []
    for t in TRAINERS:
        r = by_trainer.get(t)
        data.append({
            "trainer": t,
            "submitted": r is not None,
            "activities": json.loads(r["activities"]) if r else [],
            "operations": json.loads(r["operations"]) if r else {}
        })

    submitted = [d for d in data if d["submitted"]]

    # Classification for the alert block
    blockers = []  # attendance pending from date
    for d in data:
        att = d["operations"].get("att")
        if att and att.get("status") == "Pending from date":
            blockers.append((d["trainer"], fmt(att.get("date", ""))))
    clear = [d["trainer"] for d in data
             if d["submitted"]
             and not (d["operations"].get("att", {}).get("status") == "Pending from date")]

    L = []
    L.append("📋 *Trainer - Day Activity — " + fmt(date_str) + "*")
    L.append("━━━━━━━━━━━━━━━━━━━━")
    L.append("📊 Submitted: %d/%d" % (len(submitted), len(TRAINERS)))

    if blockers:
        L.append("\n🔴 *Needs attention (%d):*" % len(blockers))
        for n, dt in blockers:
            L.append("  • %s — Attendance Pending from %s" % (n, dt))
    if clear:
        L.append("\n✅ *All clear (%d):* %s" % (len(clear), ", ".join(clear)))

    L.append("\n━━━━━━━━━━━━━━━━━━━━")
    L.append("*Per trainer:*")
    for d in data:
        if not d["submitted"]:
            L.append("⚪ *%s* — Yet to update" % d["trainer"])
            continue
        acts = ", ".join(a["activity"] for a in d["activities"]) or "—"
        L.append("✅ *%s* — %s" % (d["trainer"], acts))
        parts = []
        mis = d["operations"].get("mis")
        if mis:
            parts.append("📅 MIS Updated (%s)" % fmt(mis.get("date", "")))
        att = d["operations"].get("att")
        if att:
            icon = "✅" if att["status"] == "Regularized till date" else "◱"
            parts.append("%s ATT %s (%s)" % (icon, att["status"].split()[0], fmt(att.get("date", ""))))
        rm = d["operations"].get("rm")
        if rm:
            parts.append("✅ RM %s" % rm.get("count", ""))
        if parts:
            L.append("   " + " | ".join(parts))

    return jsonify({"text": "\n".join(L)})


if __name__ == "__main__":
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "localhost"
    finally:
        s.close()
    port = int(os.environ.get("PORT", 5000))
    print("Trainer - Day Activity running at http://%s:%d" % (ip, port))
    app.run(host="0.0.0.0", port=port, debug=False)
