#!/usr/bin/env python3
"""Trainer - Daily Activity submission system (deployable on Render / any host).

Core rule:  ONE TRAINER + ONE DATE = ONE ACTIVITY SUBMISSION.

Each trainer selects exactly ONE activity for the day, completes its task checklist,
and submits. The submission is locked for that (trainer_id, date) pair: a second
submission for the same day is rejected at the data layer, so it survives refresh,
browser close/reopen, and any frontend tampering.

Submission record (table `submissions`):
    trainer_id, trainer_name, date, activity_id, activity_name,
    tasks (json), submitted_at, status

Configurable data lives in TRAINERS and ACTIVITIES below -- edit those to
add/remove trainers or activities without touching the rest of the code.

Persistence: SQLite (trainerops.db) inside the running instance.
Run locally:  python app.py
Run on host:  gunicorn -b 0.0.0.0:$PORT app:app
"""
import json, os, datetime, sqlite3
from flask import (Flask, request, jsonify, render_template,
                   send_from_directory)

app = Flask(__name__)

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DATABASE_URL", os.path.join(BASE, "trainerops.db"))

# ---------------------------------------------------------------------------
# CONFIGURABLE TRAINER LIST  (edit to add / remove trainers)
# id is the stable primary identifier; name is the display label.
# ---------------------------------------------------------------------------
TRAINER_NAMES = [
    "Sandeepkumar S", "Linu Raju", "Vysakh O", "Anand M Nair",
    "Maddineni Naga Sandeep", "Rai Tejas", "Gaddam Vamshidhar Reddy", "Kompelli Sagar",
    "Vinay M S", "Sabin Peter NS", "Mohammed Faizan", "Vimal Jesu Raj Arulanandam",
    "Mohamed Rasiq S", "Kalaiazhagan S", "Nalikatte Bhasker", "Abdul Ghani"
]
TRAINERS = [{"id": "T%02d" % (i + 1), "name": n} for i, n in enumerate(TRAINER_NAMES)]
TRAINER_BY_ID = {t["id"]: t for t in TRAINERS}
TRAINER_BY_NAME = {t["name"]: t for t in TRAINERS}

# ---------------------------------------------------------------------------
# CONFIGURABLE ACTIVITY LIST  (edit to add / remove activities or their tasks)
# Each activity: id, name, tasks[] where a task has:
#     activity  - what to do
#     execution - how to do it
#     caution   - warning / thing to watch (optional, can be "")
# Completion is captured per-task as a checkbox at submit time.
# ---------------------------------------------------------------------------
ACTIVITIES = [
    {"id": "nht1", "name": "NHT Day 1", "tasks": [
        {"activity": "Checked for NHT - Plotters Updates", "execution": "Follow the updated plotter", "caution": "Make sure the latest version is followed"},
        {"activity": "Day 1 Attendance by 12pm", "execution": "Mark all Day 1 attendance before noon", "caution": ""},
        {"activity": "Updated - Induction Dropout", "execution": "Keep manager informed before email is sent", "caution": "Inform manager before sending the dropout email"},
        {"activity": "Email - Language Proficiency Test", "execution": "Highlight as Good, Average & Poor", "caution": "Categorise correctly"},
        {"activity": "Handout & COC Printout", "execution": "Print the latest Handout", "caution": "Use the current version"},
    ]},
    {"id": "nht2", "name": "NHT Day 2", "tasks": [
        {"activity": "Merchandise Request - SENT", "execution": "Send the merchandise request", "caution": "Address should be as per DTDC Pincodes"},
        {"activity": "NHT Travel & Accommodation - Headsup", "execution": "Raise travel/accommodation heads-up", "caution": "Check for checkout date & distance"},
        {"activity": "Update employees details as per Aadhar", "execution": "Update employee records", "caution": "Check details in Day 1 attendance email"},
    ]},
    {"id": "nht3", "name": "NHT Day 3", "tasks": [
        {"activity": "NHT Travel & Accommodation", "execution": "Update the Google - Hotel & Travel sheet", "caution": "Keep the sheet in sync"},
    ]},
    {"id": "nht4", "name": "NHT Day 4", "tasks": [
        {"activity": "NHT Day 4 scheduled activities", "execution": "Follow the NHT Day 4 plan", "caution": ""},
    ]},
    {"id": "nht5", "name": "NHT Day 5", "tasks": [
        {"activity": "NHT Day 5 scheduled activities", "execution": "Follow the NHT Day 5 plan", "caution": ""},
    ]},
    {"id": "nht6", "name": "NHT Day 6", "tasks": [
        {"activity": "NHT Day 6 scheduled activities", "execution": "Follow the NHT Day 6 plan", "caution": ""},
    ]},
    {"id": "nht7", "name": "NHT Day 7", "tasks": [
        {"activity": "NHT Day 7 scheduled activities", "execution": "Follow the NHT Day 7 plan", "caution": ""},
    ]},
    {"id": "nht8", "name": "NHT Day 8", "tasks": [
        {"activity": "NHT Day 8 scheduled activities", "execution": "Follow the NHT Day 8 plan", "caution": ""},
    ]},
    {"id": "nht9", "name": "NHT Day 9", "tasks": [
        {"activity": "NHT Day 9 scheduled activities", "execution": "Follow the NHT Day 9 plan", "caution": ""},
    ]},
    {"id": "nht10", "name": "NHT Day 10", "tasks": [
        {"activity": "NHT Day 10 scheduled activities", "execution": "Follow the NHT Day 10 plan", "caution": ""},
    ]},
    {"id": "nht11", "name": "NHT Day 11", "tasks": [
        {"activity": "NHT Day 11 scheduled activities", "execution": "Follow the NHT Day 11 plan", "caution": ""},
    ]},
    {"id": "nht12", "name": "NHT Day 12", "tasks": [
        {"activity": "NHT Day 12 scheduled activities", "execution": "Follow the NHT Day 12 plan", "caution": ""},
    ]},
    {"id": "tt1", "name": "Technical Training Day 1", "tasks": [
        {"activity": "Technical Training Day 1 modules", "execution": "Deliver Day 1 technical training", "caution": ""},
    ]},
    {"id": "tt2", "name": "Technical Training Day 2", "tasks": [
        {"activity": "Technical Training Day 2 modules", "execution": "Deliver Day 2 technical training", "caution": ""},
    ]},
    {"id": "tt3", "name": "Technical Training Day 3", "tasks": [
        {"activity": "Technical Training Day 3 modules", "execution": "Deliver Day 3 technical training", "caution": ""},
    ]},
    {"id": "buddy", "name": "NHT Buddy Up", "tasks": [
        {"activity": "NHT Buddy Up session", "execution": "Conduct the buddy-up pairing activity", "caution": ""},
    ]},
    {"id": "midmock", "name": "Mid Mock - Certification", "tasks": [
        {"activity": "Mid Mock - Certification", "execution": "Run the mid mock and certification check", "caution": "Email was sent one day prior"},
    ]},
    {"id": "weekoff", "name": "Weekly Off", "tasks": [
        {"activity": "Weekly Off", "execution": "No activity scheduled", "caution": ""},
    ]},
    {"id": "leave", "name": "Leave", "tasks": [
        {"activity": "Leave", "execution": "On leave", "caution": ""},
    ]},
    {"id": "other", "name": "Other", "tasks": [
        {"activity": "Other activity", "execution": "Describe the activity performed", "caution": ""},
    ]},
]
ACTIVITY_BY_ID = {a["id"]: a for a in ACTIVITIES}

# ---------------------------------------------------------------------------
# CONFIGURABLE NEXT-DAY SCHEDULE  (edit to change what shows under
# "Next Day Activity" - the upcoming activities with their execution notes).
# Each item: activity_id (must exist in ACTIVITIES) + execution note.
# ---------------------------------------------------------------------------
NEXT_DAY_SCHEDULE = [
    {"activity_id": "nht1", "execution": "Follow the updated plotter"},
    {"activity_id": "nht2", "execution": "Send merchandise request as per DTDC Pincodes"},
    {"activity_id": "nht3", "execution": "Update the Google - Hotel & Travel sheet"},
    {"activity_id": "buddy", "execution": "Day 1 buddy-up pairing"},
    {"activity_id": "midmock", "execution": "Email was sent one day prior"},
]


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    # New single-activity-per-day submission model.
    conn.execute("""CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trainer_id TEXT,
        trainer_name TEXT,
        date TEXT,
        activity_id TEXT,
        activity_name TEXT,
        tasks TEXT,
        submitted_at TEXT,
        status TEXT,
        UNIQUE(trainer_id, date)
    )""")
    conn.commit()
    conn.close()


init_db()


def today():
    return datetime.date.today().isoformat()


def fmt_date(d):
    """ISO YYYY-MM-DD -> '19 Aug 2026'."""
    try:
        y, m, day = d.split("-")
        return "%s %s %s" % (day, ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(m) - 1], y)
    except Exception:
        return d


def fmt_time(iso):
    """ISO timestamp -> '10:32 AM'."""
    try:
        dt = datetime.datetime.fromisoformat(iso)
        return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return iso


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/manager")
def manager():
    return render_template("manager.html")


@app.route("/manifest.json")
def serve_manifest():
    return send_from_directory(BASE, "manifest.json", mimetype="application/manifest+json")


@app.route("/sw.js")
def serve_sw():
    return send_from_directory(BASE, "sw.js", mimetype="application/javascript")


@app.route("/icon-192.png")
def serve_icon192():
    return send_from_directory(BASE, "icon-192.png", mimetype="image/png")


@app.route("/icon-512.png")
def serve_icon512():
    return send_from_directory(BASE, "icon-512.png", mimetype="image/png")


@app.route("/favicon.ico")
def serve_favicon():
    return send_from_directory(BASE, "favicon.ico", mimetype="image/x-icon")


@app.route("/api/config")
def api_config():
    return jsonify({
        "trainers": TRAINERS,
        "activities": ACTIVITIES,
        "next_day": NEXT_DAY_SCHEDULE,
        "today": today()
    })


@app.route("/api/submit", methods=["POST"])
def api_submit():
    """Submit ONE activity for (trainer_id, date). Rejects duplicates at the
    data layer even if the client tries again."""
    e = request.get_json(force=True, silent=True) or {}
    trainer_id = (e.get("trainer_id") or "").strip()
    date = (e.get("date") or "").strip()
    activity_id = (e.get("activity_id") or "").strip()

    if not date or not trainer_id:
        return jsonify({"status": "error", "message": "Missing date or trainer"}), 400
    t = TRAINER_BY_ID.get(trainer_id)
    if not t:
        return jsonify({"status": "error", "message": "Unknown trainer"}), 400
    a = ACTIVITY_BY_ID.get(activity_id)
    if not a:
        return jsonify({"status": "error", "message": "Unknown activity"}), 400

    # Normalise tasks to the configured task list (ignore anything extra the
    # client sends) and capture the per-task completion flag.
    done_flags = {str(i): bool(task.get("done")) for i, task in enumerate(e.get("tasks", []))}
    tasks = []
    for i, task in enumerate(a["tasks"]):
        tasks.append({
            "activity": task["activity"],
            "execution": task.get("execution", ""),
            "caution": task.get("caution", ""),
            "done": done_flags.get(str(i), False)
        })

    conn = get_db()
    # Duplicate check first (defence in depth alongside the UNIQUE constraint).
    existing = conn.execute(
        "SELECT id FROM submissions WHERE trainer_id=? AND date=?",
        (trainer_id, date)).fetchone()
    if existing:
        conn.close()
        return jsonify({"status": "error",
                        "message": "You have already submitted your activity for %s. One submission per day only." % fmt_date(date)}), 409

    try:
        conn.execute(
            """INSERT INTO submissions
               (trainer_id, trainer_name, date, activity_id, activity_name, tasks, submitted_at, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (trainer_id, t["name"], date, a["id"], a["name"],
             json.dumps(tasks, ensure_ascii=False),
             datetime.datetime.now().isoformat(timespec="seconds"), "submitted"))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"status": "error",
                        "message": "You have already submitted your activity for %s." % fmt_date(date)}), 409
    conn.close()
    return jsonify({"status": "ok"})


@app.route("/api/submission")
def api_submission():
    """Return ONLY the requesting trainer's own submission for the given date.
    The trainer param must match; this endpoint never returns another
    trainer's data (data isolation for the individual trainer view)."""
    trainer_id = (request.args.get("trainer_id") or "").strip()
    date = (request.args.get("date") or today()).strip()
    if not TRAINER_BY_ID.get(trainer_id):
        return jsonify({"status": "error", "message": "Unknown trainer"}), 400
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM submissions WHERE trainer_id=? AND date=?",
        (trainer_id, date)).fetchone()
    conn.close()
    if not row:
        return jsonify({"submission": None})
    return jsonify({"submission": _row_to_dict(row)})


def _row_to_dict(row):
    return {
        "trainer_id": row["trainer_id"],
        "trainer_name": row["trainer_name"],
        "date": row["date"],
        "activity_id": row["activity_id"],
        "activity_name": row["activity_name"],
        "tasks": json.loads(row["tasks"]),
        "submitted_at": row["submitted_at"],
        "status": row["status"],
    }


@app.route("/api/whatsapp")
def api_whatsapp():
    """WhatsApp-ready text for ONE trainer's own submission only."""
    trainer_id = (request.args.get("trainer_id") or "").strip()
    date = (request.args.get("date") or today()).strip()
    t = TRAINER_BY_ID.get(trainer_id)
    if not t:
        return jsonify({"status": "error", "message": "Unknown trainer"}), 400
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM submissions WHERE trainer_id=? AND date=?",
        (trainer_id, date)).fetchone()
    conn.close()
    if not row:
        return jsonify({"text": "No submission found for %s on %s." % (t["name"], fmt_date(date))})

    s = _row_to_dict(row)
    L = []
    L.append("Trainer Daily Activity")
    L.append("Trainer: %s" % s["trainer_name"])
    L.append("Date: %s" % fmt_date(s["date"]))
    L.append("Activity: %s" % s["activity_name"])
    L.append("")
    for i, tk in enumerate(s["tasks"], 1):
        L.append("%d. %s" % (i, tk["activity"]))
        if tk.get("execution"):
            L.append("   Execution: %s" % tk["execution"])
        if tk.get("caution"):
            L.append("   Caution: %s" % tk["caution"])
        L.append("   Status: %s" % ("Completed" if tk.get("done") else "Not completed"))
    return jsonify({"text": "\n".join(L)})


# ---------------------------------------------------------------------------
# MANAGER VIEW - overall submissions across all trainers (kept separate from
# the individual trainer interface so the two views are never mixed).
# ---------------------------------------------------------------------------
@app.route("/api/report")
def api_report():
    date = (request.args.get("date") or today()).strip()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM submissions WHERE date=? ORDER BY submitted_at",
        (date,)).fetchall()
    conn.close()
    out = [_row_to_dict(r) for r in rows]
    return jsonify({"date": date, "submissions": out,
                    "submitted_count": len(out), "trainer_count": len(TRAINERS)})


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
    print("Trainer - Daily Activity running at http://%s:%d" % (ip, port))
    app.run(host="0.0.0.0", port=port, debug=False)
