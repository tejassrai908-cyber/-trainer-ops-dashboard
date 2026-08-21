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
import json, os, datetime, sqlite3, re
from flask import (Flask, request, jsonify, render_template,
                   send_from_directory)

app = Flask(__name__)
# Reject absurd payloads (abuse protection); 1 MB is far more than needed.
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

BASE = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB = os.path.join(BASE, "trainerops.db")

# --- Database selection ---------------------------------------------------
# If DATABASE_URL looks like a Postgres URL (set automatically by Render when
# you attach a Postgres service), we use Postgres. Otherwise we fall back to a
# local SQLite file. This keeps local dev simple and production on Render's
# free Postgres (persists across deploys — no more data loss on redeploy).
_RAW_DB_URL = os.environ.get("DATABASE_URL", "")
USE_PG = bool(_RAW_DB_URL) and _RAW_DB_URL.startswith("postgres")
# Normalize "postgres://" -> "postgresql://" for older psycopg2 builds.
DB_URL = _RAW_DB_URL.replace("postgres://", "postgresql://", 1) if USE_PG else ""


def _pg_conn():
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(DB_URL, connect_timeout=30)
    # RealDictCursor so rows behave like dicts (row["trainer_id"]) — same as
    # sqlite3.Row, so the rest of the code doesn't need to change.
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def q(sql):
    """Normalize '?' placeholders to the active dialect's placeholder."""
    return sql.replace("?", "%s") if USE_PG else sql


def _is_unique_err(e):
    s = str(e).lower()
    return "unique" in s or "duplicate" in s

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

# Admin trainer who may unlock any trainer's submission so it can be re-done.
# (Rai Tejas.) Gated by trainer id so only he gets the unlock action.
ADMIN_TRAINER_ID = "T06"

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
        {"activity": "Day 1 Attendance by 12pm", "execution": "Mark all Day 1 attendance before noon", "caution": "Inform manager if there is any dropout and mark as induction dropout"},
        {"activity": "Sent – Daily Summary Report", "execution": "Update Attendance, Quiz Score & Topics Covered", "caution": "Update the trainees' names as per Aadhar card"},
    ]},
    {"id": "nht2", "name": "NHT Day 2", "tasks": [
        {"activity": "Shared Batch Details for Merchandize", "execution": "Delivery Address should be as per DTDC Pincodes", "caution": "Update the trainees' names as per Aadhar card"},
        {"activity": "NHT Travel & Accommodation – Heads-up", "execution": "Get the hotel checkout date from trainees & Travel plan", "caution": ""},
        {"activity": "Sent – Daily Summary Report", "execution": "Update Attendance, Quiz Score & Topics Covered", "caution": "Update the trainees' names as per Aadhar card"},
    ]},
    {"id": "nht3", "name": "NHT Day 3", "tasks": [
        {"activity": "Updated NHT Travel & Accommodation", "execution": "Check for the google sheet/form in DSF training Group", "caution": "Inform Manager if no update by EOD & Avoid for supervisors"},
        {"activity": "Sent – Daily Summary Report", "execution": "Update Attendance, Quiz Score & Topics Covered", "caution": "Update the trainees' names as per Aadhar card"},
    ]},
    {"id": "nht4", "name": "NHT Day 4", "tasks": [
        {"activity": "Updated the Buddy Up sheet shared by Manager", "execution": "Share the details with trainees", "caution": "Ensure the trainees contact RMs and have a plan by EOD"},
        {"activity": "Covered the Topics and Trained them for Mid Mock Call", "execution": "Give heads-up and assignment for Mid Mock call after buddy up", "caution": ""},
        {"activity": "Planned your visit with NHT RM or JS RM", "execution": "Inform the manager about your plan", "caution": ""},
        {"activity": "Sent – Daily Summary Report", "execution": "Update Attendance, Quiz Score & Topics Covered", "caution": "Update the trainees' names as per Aadhar card"},
    ]},
    {"id": "buddy1", "name": "Buddy Up – Day 1", "tasks": [
        {"activity": "Ensured the trainees meet their RMs", "execution": "Inform how they should plan to meet their RM by 8.30am", "caution": "Ensure every trainee meet his RM and update the same to manager"},
        {"activity": "Planned Visit Barge with", "execution": "Do Evaluation and Record Every Visit", "caution": "Fill the Matrix Go One day Prior for RM Assignment", "comment": True},
        {"activity": "Sent – Visit Barge email on same day", "execution": "", "caution": "Highlight the reason if recording is not done"},
    ]},
    {"id": "buddy2", "name": "Buddy Up – Day 2", "tasks": [
        {"activity": "Ensured the trainees meet their RMs", "execution": "Inform how they should plan to meet their RM by 8.30am", "caution": "Ensure every trainee meet his RM and update the same to manager"},
        {"activity": "Planned Visit Barge with", "execution": "Do Evaluation and Record Every Visit", "caution": "Fill the Matrix Go One day Prior for RM Assignment", "comment": True},
        {"activity": "Sent – Email for Mid Mock Call Certification", "execution": "", "caution": ""},
        {"activity": "Sent – Visit Barge email on same day", "execution": "", "caution": "Highlight the reason if recording is not done"},
    ]},
    {"id": "nht5", "name": "NHT Day 5", "tasks": [
        {"activity": "Conducted Debriefing Session about buddy up experience", "execution": "Do an activity and collect feedback", "caution": ""},
        {"activity": "Conducted Mid Mock Call Certification", "execution": "Do follow-up to complete on the same day", "caution": "Ensure the assessor fills the form after the mock call"},
        {"activity": "Sent – Matrix ID creation request email", "execution": "Follow the standard format", "caution": "Do follow up if it is not done"},
        {"activity": "Sent – Daily Summary Report", "execution": "Update Attendance, Quiz Score & Topics Covered", "caution": "Update the trainees' names as per Aadhar card"},
    ]},
    {"id": "nht6", "name": "NHT Day 6", "tasks": [
        {"activity": "Filled the RAG Report", "execution": "Complete by EOD without deviation", "caution": ""},
        {"activity": "Sent – Progressive Dialer Request Email", "execution": "Follow the standard format", "caution": ""},
        {"activity": "Sent – Daily Summary Report", "execution": "Update Attendance, Quiz Score & Topics Covered", "caution": "Update the trainees' names as per Aadhar card"},
    ]},
    {"id": "nht7", "name": "NHT Day 7", "tasks": [
        {"activity": "Supported for Trainee - NPS Account Creation", "execution": "Collect the PRAN and updated in the sheet", "caution": "Error should be shared in the NPS what's group for support"},
        {"activity": "Sent – Progressive Dialer Request Email", "execution": "Follow the standard format", "caution": "Do follow up if it is not done"},
        {"activity": "Conducted Ops Leader Connect with Batch", "execution": "Inform manager if there is any change in plan", "caution": "Do follow up and send MOM via email with picture"},
        {"activity": "Sent – Daily Summary Report", "execution": "Update Attendance, Quiz Score & Topics Covered", "caution": "Update the trainees' names as per Aadhar card"},
    ]},
    {"id": "nht8", "name": "NHT Day 8", "tasks": [
        {"activity": "Sent – Lead Assignment Request Email", "execution": "Follow the standard format", "caution": "Do follow up if it is not done"},
        {"activity": "Checked for NHT Travel & Accommodation Tickets", "execution": "Find the tickets in the attachment & Hotel extension status", "caution": "Share the tickets with the trainees personally"},
        {"activity": "Sent – Daily Summary Report", "execution": "Update Attendance, Quiz Score & Topics Covered", "caution": "Update the trainees' names as per Aadhar card"},
    ]},
    {"id": "nht9", "name": "NHT Day 9", "tasks": [
        {"activity": "Provided System Matrix Login for Feature Exploration", "execution": "Exploration on Quick Action Tools, Service and more", "caution": "Highlight to Matrix team if it is a Login Issue"},
        {"activity": "Checked for NHT Travel & Accommodation Tickets", "execution": "Find the tickets in the attachment & Hotel extension status", "caution": ""},
        {"activity": "Sent – Daily Summary Report", "execution": "Update Attendance, Quiz Score & Topics Covered", "caution": "Update the trainees' names as per Aadhar card"},
    ]},
    {"id": "nht10", "name": "NHT Day 10", "tasks": [
        {"activity": "Assisted Trainees with Assigned Lead Calls", "execution": "Ensure all leads are answered", "caution": "Highlight to Matrix team if it is a Login Issue"},
        {"activity": "Sent – Daily Summary Report", "execution": "Update Attendance, Quiz Score & Topics Covered", "caution": "Update the trainees' names as per Aadhar card"},
    ]},
    {"id": "nht11", "name": "NHT Day 11", "tasks": [
        {"activity": "Sent – Email for Final Mock Call Certification", "execution": "", "caution": ""},
        {"activity": "Sent – Daily Summary Report", "execution": "Update Attendance, Quiz Score & Topics Covered", "caution": "Update the trainees' names as per Aadhar card"},
        {"activity": "Blocked the Calendar for LatLong Session – Jayashankar", "execution": "Inform the manager or check in the group for status", "caution": ""},
    ]},
    {"id": "nht12", "name": "NHT Day 12", "tasks": [
        {"activity": "Conducted Final Mock Call Certification", "execution": "Do follow-up to complete on the same day", "caution": "Ensure the assessor fills the form after the mock call"},
        {"activity": "Sent – Handover Email", "execution": "Update with Mock Call & Theoretical Assessment Scores", "caution": "Update the Handover Date accordingly"},
        {"activity": "Planned Visit Barge with NHT RMs", "execution": "Send an email if there is no trainee from base location", "caution": "Inform manager about the visit plan firstly"},
    ]},
    {"id": "buddy3", "name": "Buddy Up – Day 3", "tasks": [
        {"activity": "Ensured the trainees meet their RMs", "execution": "Inform how they should plan to meet their RM by 8.30am", "caution": "Ensure every trainee meet his RM and update the same to manager"},
        {"activity": "Planned Visit Barge with", "execution": "Do Evaluation and Record Every Visit", "caution": "Fill the Matrix Go One day Prior for RM Assignment", "comment": True},
        {"activity": "Sent – Visit Barge email on same day", "execution": "", "caution": "Highlight the reason if recording is not done"},
    ]},
    {"id": "tt1", "name": "Technical Training Day 1", "tasks": [
        {"activity": "Coordinated with IT for Asset collection", "execution": "Share email address & System Password with IT", "caution": "Inform the manager if there is any delay"},
        {"activity": "Conducted Debriefing Session about buddy up experience", "execution": "Collected feedback", "caution": ""},
        {"activity": "Sent – Email for Cake on Occasion of Graduation", "execution": "", "caution": ""},
        {"activity": "Assisted Trainees with PB Compliance Courses", "execution": "Inform the trainees to log into PB Connect", "caution": "Ensure every Trainee completes before leaving"},
        {"activity": "Added the Trainees in the South Broadcast Group", "execution": "Share the invite with them", "caution": ""},
        {"activity": "Checked for NHT Handover Calendar Block", "execution": "Check with the SPOC person for an Update", "caution": ""},
    ]},
    {"id": "tt2", "name": "Technical Training Day 2", "tasks": [
        {"activity": "Follow-Up is Done for NHT Handover Connect", "execution": "Check for the Invite shared in Groups", "caution": "Inform SPOC if there is any deviation"},
        {"activity": "Follow-Up for Graduation Ceremony Connect", "execution": "Check for the Invite link or calendar blocked", "caution": "Inform Manager if there is no update"},
        {"activity": "Uploaded Graduation Photos", "execution": "Check for the Google Form to upload", "caution": "Ensure it is done on the same day"},
        {"activity": "Conducted LinkedIn Post Activity", "execution": "Ensure the trainee post a picture tagging leaders", "caution": "This activity should be done without deviation"},
    ]},
    {"id": "visitbarge", "name": "Visit Barge", "tasks": [
        {"activity": "Planned Visit Barge with", "execution": "Do Evaluation and Record Every Visit", "caution": "Fill the Matrix Go One day Prior for RM Assignment", "comment": True},
        {"activity": "Sent – Visit Barge email on same day", "execution": "", "caution": "Highlight the reason if recording is not done"},
    ]},
    {"id": "weekoff", "name": "Weekly Off", "tasks": [
        {"activity": "Weekly Off", "execution": "", "caution": ""},
    ]},
    {"id": "holiday", "name": "Holiday", "tasks": [
        {"activity": "Holiday", "execution": "", "caution": "", "no_box": True},
    ]},
    {"id": "leave", "name": "Leave", "tasks": [
        {"activity": "Leave", "execution": "", "caution": "", "no_box": True},
    ]},
    {"id": "audit", "name": "Audit", "tasks": [
        {"activity": "Audit", "execution": "Check for Non-Audited Leads Using the Duplicate Tracker Link", "caution": ""},
    ]},
    {"id": "fostravel", "name": "FOS Visit – Travel", "tasks": [
        {"activity": "FOS Visit – Travel", "execution": "", "caution": "", "comment": True},
    ]},
]

# NHT batch sequence used to compute "Next Day Activity" after a submission.
# After the submitted activity, only the CURRENT day + the NEXT day in this
# order are shown (no day-after). Standalone items (visitbarge, audit,
# weekoff, holiday, leave, fostravel) just show themselves as next.
NHT_SEQUENCE = [
    "nht1","nht2","nht3","nht4","buddy1","buddy2","nht5","nht6","nht7","nht8",
    "nht9","nht10","nht11","nht12","buddy3","tt1","tt2"
]

# Execution note shown in the Next Day Activity section for a given activity id.
NEXT_DAY_NOTE = {a["id"]: "; ".join([t["execution"] for t in a["tasks"] if t["execution"]]) for a in ACTIVITIES}

def next_day_for(activity_id):
    """Return the next activity id in the NHT sequence, or the same id for
    standalone items. Returns None if there is no defined next (end of chain)."""
    if activity_id in ("visitbarge","audit","weekoff","holiday","leave","fostravel"):
        return activity_id  # stand-alone: show itself only
    try:
        idx = NHT_SEQUENCE.index(activity_id)
    except ValueError:
        return None
    if idx + 1 < len(NHT_SEQUENCE):
        return NHT_SEQUENCE[idx + 1]
    return None

ACTIVITY_BY_ID = {a["id"]: a for a in ACTIVITIES}


def get_db():
    if USE_PG:
        return _pg_conn()
    conn = sqlite3.connect(SQLITE_DB, timeout=30)
    # WAL = safe for many concurrent writers (14 trainers submitting at once)
    # without the whole DB locking up.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    if USE_PG:
        conn.execute("""CREATE TABLE IF NOT EXISTS submissions (
            id SERIAL PRIMARY KEY,
            trainer_id TEXT,
            trainer_name TEXT,
            date TEXT,
            activity_id TEXT,
            activity_name TEXT,
            tasks TEXT,
            submitted_at TEXT,
            status TEXT,
            UNIQUE(trainer_id, date))""")
    else:
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


@app.route("/healthz")
def healthz():
    """Lightweight liveness probe for Render / uptime checks."""
    return jsonify({"status": "ok", "time": datetime.datetime.now().isoformat(timespec="seconds")})


@app.errorhandler(500)
def handle_500(err):
    return jsonify({"status": "error", "message": "Server error. Please retry."}), 500


@app.errorhandler(413)
def handle_413(err):
    return jsonify({"status": "error", "message": "Payload too large."}), 413


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
        "next_day_sequence": NHT_SEQUENCE,
        "next_day_note": NEXT_DAY_NOTE,
        "admin_trainer_id": ADMIN_TRAINER_ID,
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
    if not DATE_RE.match(date):
        return jsonify({"status": "error", "message": "Invalid date format"}), 400
    t = TRAINER_BY_ID.get(trainer_id)
    if not t:
        return jsonify({"status": "error", "message": "Unknown trainer"}), 400
    a = ACTIVITY_BY_ID.get(activity_id)
    if not a:
        return jsonify({"status": "error", "message": "Unknown activity"}), 400

    # Normalise tasks to the configured task list (ignore anything extra the
    # client sends) and capture the per-task completion flag + comment.
    done_flags = {str(i): bool(task.get("done")) for i, task in enumerate(e.get("tasks", []))}
    comment_text = {str(i): (task.get("comment") or "") for i, task in enumerate(e.get("tasks", []))}
    tasks = []
    for i, task in enumerate(a["tasks"]):
        tasks.append({
            "activity": task["activity"],
            "execution": task.get("execution", ""),
            "caution": task.get("caution", ""),
            "done": True if task.get("no_box") else done_flags.get(str(i), False),
            "comment": comment_text.get(str(i), "")
        })

    conn = get_db()
    # Duplicate check first (defence in depth alongside the UNIQUE constraint).
    existing = conn.execute(
        q("SELECT id FROM submissions WHERE trainer_id=? AND date=?"),
        (trainer_id, date)).fetchone()
    if existing:
        conn.close()
        return jsonify({"status": "error",
                        "message": "You have already submitted your activity for %s. One submission per day only." % fmt_date(date)}), 409

    try:
        conn.execute(
            q("""INSERT INTO submissions
               (trainer_id, trainer_name, date, activity_id, activity_name, tasks, submitted_at, status)
               VALUES (?,?,?,?,?,?,?,?)"""),
            (trainer_id, t["name"], date, a["id"], a["name"],
             json.dumps(tasks, ensure_ascii=False),
             datetime.datetime.now().isoformat(timespec="seconds"), "submitted"))
        conn.commit()
    except Exception as e:
        if _is_unique_err(e):
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            return jsonify({"status": "error",
                            "message": "You have already submitted your activity for %s." % fmt_date(date)}), 409
        conn.close()
        raise
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
        q("SELECT * FROM submissions WHERE trainer_id=? AND date=?"),
        (trainer_id, date)).fetchone()
    conn.close()
    if not row:
        return jsonify({"submission": None})
    return jsonify({"submission": _row_to_dict(row)})


def _row_to_dict(row):
    d = {
        "trainer_id": row["trainer_id"],
        "trainer_name": row["trainer_name"],
        "date": row["date"],
        "activity_id": row["activity_id"],
        "activity_name": row["activity_name"],
        "tasks": json.loads(row["tasks"]),
        "submitted_at": row["submitted_at"],
        "status": row["status"],
    }
    nid = next_day_for(row["activity_id"])
    if nid and nid in ACTIVITY_BY_ID:
        a = ACTIVITY_BY_ID[nid]
        d["next_activity"] = {
            "id": a["id"], "name": a["name"],
            "execution": NEXT_DAY_NOTE.get(a["id"], "")
        }
    else:
        d["next_activity"] = None
    return d


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
        q("SELECT * FROM submissions WHERE trainer_id=? AND date=?"),
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
        act = tk["activity"]
        comment = tk.get("comment")
        # For tasks whose name ends with " with" (e.g. "Planned Visit Barge
        # with"), show the typed value right after the name (e.g.
        # "Planned Visit Barge with NHT") and drop the separate "Note:" line.
        if comment and act.rstrip().endswith(" with"):
            act = act.rstrip() + " " + comment
            comment = None
        L.append("%d. %s" % (i, act))
        if tk.get("execution"):
            L.append("   Execution: %s" % tk["execution"])
        if tk.get("caution"):
            L.append("   Caution: %s" % tk["caution"])
        if comment:
            L.append("   Note: %s" % comment)
        L.append("   Status: %s" % ("Completed" if tk.get("done") else "Not completed"))
    return jsonify({"text": "\n".join(L)})


@app.route("/api/admin/unlock", methods=["POST"])
def api_admin_unlock():
    """Admin (Rai Tejas) deletes a trainer's submission for a date so it can be
    re-submitted. Gated to ADMIN_TRAINER_ID only; rejects everyone else."""
    e = request.get_json(force=True, silent=True) or {}
    admin_id = (e.get("admin_id") or "").strip()
    trainer_id = (e.get("trainer_id") or "").strip()
    date = (e.get("date") or "").strip()
    if admin_id != ADMIN_TRAINER_ID:
        return jsonify({"status": "error",
                        "message": "Only the admin (Rai Tejas) can unlock submissions."}), 403
    if not trainer_id or not date or not TRAINER_BY_ID.get(trainer_id):
        return jsonify({"status": "error", "message": "Missing or unknown trainer/date"}), 400
    conn = get_db()
    conn.execute(q("DELETE FROM submissions WHERE trainer_id=? AND date=?"),
                 (trainer_id, date))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok",
                    "message": "Unlocked — trainer can now re-submit for %s." % fmt_date(date)})


# ---------------------------------------------------------------------------
# MANAGER VIEW - overall submissions across all trainers (kept separate from
# the individual trainer interface so the two views are never mixed).
# ---------------------------------------------------------------------------
@app.route("/api/report")
def api_report():
    date = (request.args.get("date") or today()).strip()
    conn = get_db()
    rows = conn.execute(
        q("SELECT * FROM submissions WHERE date=? ORDER BY submitted_at"),
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
