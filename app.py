#!/usr/bin/env python3
"""Trainer - Day Activity dashboard (deployable on Render / any host).

Deliverables model (per trainer, per day):
  - MIS Update              : status "Completed" + mandatory date
  - Attendance Regularization: status "Completed"/"Pending" + mandatory date
  - Help Desk Group - RM Support: number input 1-15 (stored as "N RM")
  - NHT & Calender Block    : status Checked / Aware / Need to check
  - Visit Barge             : status Following the updated process / Need to check for new process

Regularity bars: per-trainer MIS % and Attendance % across all stored dates.
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
    {"id": "mis", "label": "MIS Update", "statusOptions": ["Completed"], "requireDate": True},
    {"id": "att", "label": "Attendance Regularization",
     "statusOptions": ["Completed", "Pending"], "requireDate": True},
    {"id": "rm", "label": "Help Desk Group - RM Support", "number": True, "min": 1, "max": 15},
    {"id": "nhtcal", "label": "NHT & Calender Block",
     "statusOptions": ["Checked", "Aware", "Need to check"]},
    {"id": "vb", "label": "Visit Barge",
     "statusOptions": ["Following the updated process", "Need to check for new process"]},
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
        if op.get("number"):
            val = (o.get("number") or "").strip()
            if val:
                try:
                    n = int(val)
                    if not (op["min"] <= n <= op["max"]):
                        return jsonify({"status": "error",
                                        "message": op["label"] + " must be between %d and %d" % (op["min"], op["max"])}), 400
                    ops[op["id"]] = {"number": n}
                except ValueError:
                    return jsonify({"status": "error",
                                    "message": op["label"] + " must be a number"}), 400
            continue
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
        ops[op["id"]] = entry

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
        conn.execute("INSERT INTO entries (timestamp,date,trainer,activities,operations) VALUES (?,?,?,?,?)", payload)
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


def _month_bounds(ref):
    """Return (mis_start, mis_end, att_start, att_end) as YYYY-MM-DD strings.
    MIS window: 1st of current month -> last day of current month.
    Att window: 20th of previous month -> 20th of current month.
    """
    y, m, _ = ref.split("-")
    y = int(y); m = int(m)
    # current month: 1st -> last day
    if m == 12:
        nxt_y, nxt_m = y + 1, 1
    else:
        nxt_y, nxt_m = y, m + 1
    mis_start = "%04d-%02d-01" % (y, m)
    mis_end = "%04d-%02d-01" % (nxt_y, nxt_m)  # exclusive bound (day after last)
    # previous month
    if m == 1:
        py, pm = y - 1, 12
    else:
        py, pm = y, m - 1
    att_start = "%04d-%02d-20" % (py, pm)
    att_end = "%04d-%02d-20" % (y, m)
    return mis_start, mis_end, att_start, att_end


@app.route("/api/regularity")
def api_regularity():
    """Per-trainer MIS % (1st..end of current month) and Attendance % (20th prev month..20th current month)."""
    ref = request.args.get("ref", today())
    mis_start, mis_end, att_start, att_end = _month_bounds(ref)

    def days_between(a, b):
        d1 = datetime.date.fromisoformat(a)
        d2 = datetime.date.fromisoformat(b)
        return (d2 - d1).days  # mis window is [start, end_of_month] inclusive -> +1

    mis_window_days = days_between(mis_start, mis_end)  # = days in current month
    att_window_days = 21  # 20th prev month .. 20th current month inclusive

    conn = get_db()
    rows = conn.execute("SELECT trainer, date, operations FROM entries").fetchall()
    conn.close()

    mis_done = {}   # trainer -> days in MIS window with MIS Completed
    att_done = {}   # trainer -> days in ATT window with Attendance Completed
    for r in rows:
        t = r["trainer"]
        ops = json.loads(r["operations"])
        if mis_start <= r["date"] < mis_end and ops.get("mis", {}).get("status") == "Completed":
            mis_done[t] = mis_done.get(t, 0) + 1
        if att_start <= r["date"] <= att_end and ops.get("att", {}).get("status") == "Completed":
            att_done[t] = att_done.get(t, 0) + 1

    out = []
    tot_mis = tot_att = 0
    for t in TRAINERS:
        m = mis_done.get(t, 0)
        a = att_done.get(t, 0)
        out.append({
            "trainer": t,
            "misPct": round(100 * m / mis_window_days) if mis_window_days else 0,
            "attPct": round(100 * a / att_window_days) if att_window_days else 0,
            "misDone": m, "attDone": a,
            "misTotal": mis_window_days, "attTotal": att_window_days
        })
        tot_mis += m; tot_att += a
    return jsonify({
        "rows": out,
        "avgMisPct": round(100 * tot_mis / (mis_window_days * len(TRAINERS))) if mis_window_days else 0,
        "avgAttPct": round(100 * tot_att / (att_window_days * len(TRAINERS))) if att_window_days else 0,
        "misWindow": "%s to %s" % (mis_start, datetime.date.fromisoformat(mis_end) - datetime.timedelta(days=1)),
        "attWindow": "%s to %s" % (att_start, att_end),
        "misWindowDays": mis_window_days,
        "attWindowDays": att_window_days
    })


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
    blockers = []
    for d in data:
        att = d["operations"].get("att")
        if att and att.get("status") == "Pending":
            blockers.append((d["trainer"], fmt(att.get("date", ""))))
    clear = [d["trainer"] for d in data
             if d["submitted"] and not (d["operations"].get("att", {}).get("status") == "Pending")]

    L = []
    L.append("📋 *Trainer - Day Activity — " + fmt(date_str) + "*")
    L.append("━━━━━━━━━━━━━━━━━━━━")
    L.append("📊 Submitted: %d/%d" % (len(submitted), len(TRAINERS)))

    if blockers:
        L.append("\n🔴 *Needs attention (%d):*" % len(blockers))
        for n, dt in blockers:
            L.append("  • %s — Attendance Pending (%s)" % (n, dt))
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
            parts.append("📅 MIS Completed (%s)" % fmt(mis.get("date", "")))
        att = d["operations"].get("att")
        if att:
            icon = "✅" if att["status"] == "Completed" else "◱"
            parts.append("%s ATT %s (%s)" % (icon, att["status"], fmt(att.get("date", ""))))
        rm = d["operations"].get("rm")
        if rm:
            parts.append("✅ RM %d" % rm.get("number", 0))
        nht = d["operations"].get("nhtcal")
        if nht:
            parts.append("🗓 NHT %s" % nht["status"])
        vb = d["operations"].get("vb")
        if vb:
            parts.append("⛴ VB %s" % vb["status"])
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
