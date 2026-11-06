"""
System Monitor: CPU, memory, disk and network dashboard.

Features: live metrics, SQLite history with time-range filter, email alerts,
settings page (thresholds), Docker support.

Run:  pip install -r requirements.txt
      uvicorn app:app --reload      ->  http://localhost:8000
"""
import os
import smtplib
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from email.message import EmailMessage
from pathlib import Path

import psutil
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = os.getenv("DB_PATH", str(BASE / "monitor.db"))
SAMPLE_SECONDS = 2          # how often we read the system
RETENTION_DAYS = 7          # old readings are deleted after this

# SMTP login comes from environment variables (never hard-code passwords)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

DEFAULTS = {
    "cpu_threshold": 80,
    "mem_threshold": 85,
    "email_enabled": 0,
    "email_to": "",
    "cooldown_minutes": 10,
}

latest = {}                               # most recent reading (for live cards)
last_alert = {"CPU": 0.0, "Memory": 0.0}  # when each alert was last sent


# ---------------------------------------------------------------- database
def db():
    return sqlite3.connect(DB_PATH, timeout=10)


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS readings(
            ts REAL, cpu REAL, memory REAL, disk REAL, net_up REAL, net_down REAL)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts)")
        c.execute("""CREATE TABLE IF NOT EXISTS alerts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT,
            message TEXT, emailed INTEGER)""")
        c.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")


def get_settings():
    with db() as c:
        saved = dict(c.execute("SELECT key, value FROM settings").fetchall())
    s = dict(DEFAULTS)
    for k, default in DEFAULTS.items():
        if k in saved:
            s[k] = type(default)(saved[k]) if not isinstance(default, str) else saved[k]
    s["email_enabled"] = bool(s["email_enabled"])
    return s


# ------------------------------------------------------------------ email
def send_email(subject, body, to):
    """Returns (ok, error_message)."""
    if not (SMTP_USER and SMTP_PASS):
        return False, "SMTP_USER / SMTP_PASS environment variables are not set"
    try:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, SMTP_USER, to
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True, ""
    except Exception as e:
        return False, str(e)


def check_alerts(cpu, mem):
    s = get_settings()
    checks = (("CPU", cpu, s["cpu_threshold"]), ("Memory", mem, s["mem_threshold"]))
    for kind, value, limit in checks:
        cooled_down = time.time() - last_alert[kind] > s["cooldown_minutes"] * 60
        if value > limit and cooled_down:
            last_alert[kind] = time.time()
            message = f"High {kind} usage: {value}% (limit {limit}%)"
            emailed = 0
            if s["email_enabled"] and s["email_to"]:
                emailed = int(send_email(f"[System Monitor] {message}", message, s["email_to"])[0])
            with db() as c:
                c.execute("INSERT INTO alerts(ts, kind, message, emailed) VALUES(?,?,?,?)",
                          (time.time(), kind, message, emailed))


# -------------------------------------------------------------- collector
def collector():
    """Background thread: read the system every few seconds and store it."""
    prev_net, prev_t = psutil.net_io_counters(), time.time()
    psutil.cpu_percent(percpu=True)  # first call is always 0, so prime it
    last_cleanup = 0
    while True:
        time.sleep(SAMPLE_SECONDS)
        try:
            now = time.time()
            net = psutil.net_io_counters()
            dt = max(now - prev_t, 0.001)
            net_up = round((net.bytes_sent - prev_net.bytes_sent) / dt / 1024, 1)
            net_down = round((net.bytes_recv - prev_net.bytes_recv) / dt / 1024, 1)
            prev_net, prev_t = net, now

            cores = psutil.cpu_percent(percpu=True)
            cpu = round(sum(cores) / len(cores), 1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage(os.path.abspath(os.sep))

            latest.clear()
            latest.update({
                "ready": True, "cpu": cpu, "cpu_per_core": cores,
                "memory_percent": mem.percent,
                "memory_used_gb": round(mem.used / 1e9, 2),
                "memory_total_gb": round(mem.total / 1e9, 2),
                "disk_percent": disk.percent,
                "net_up": net_up, "net_down": net_down,
                "uptime_hours": round((now - psutil.boot_time()) / 3600, 1),
            })
            with db() as c:
                c.execute("INSERT INTO readings VALUES(?,?,?,?,?,?)",
                          (now, cpu, mem.percent, disk.percent, net_up, net_down))
                if now - last_cleanup > 1800:
                    c.execute("DELETE FROM readings WHERE ts < ?", (now - RETENTION_DAYS * 86400,))
                    last_cleanup = now
            check_alerts(cpu, mem.percent)
        except Exception as e:  # keep the thread alive no matter what
            print("collector error:", e)


@asynccontextmanager
async def lifespan(app):
    init_db()
    threading.Thread(target=collector, daemon=True).start()
    yield


app = FastAPI(title="System Monitor", lifespan=lifespan)


# -------------------------------------------------------------------- API
@app.get("/api/stats")
def stats():
    if not latest:
        return {"ready": False}
    s = get_settings()
    return {**latest, "cpu_threshold": s["cpu_threshold"], "mem_threshold": s["mem_threshold"]}


@app.get("/api/history")
def history(minutes: int = 5):
    minutes = max(1, min(minutes, RETENTION_DAYS * 1440))
    since = time.time() - minutes * 60
    bucket = max(SAMPLE_SECONDS, int(minutes * 60 / 300))  # ~300 points max
    with db() as c:
        rows = c.execute(
            """SELECT CAST(ts / ? AS INTEGER) * ? AS t, AVG(cpu), AVG(memory),
                      AVG(net_up), AVG(net_down)
               FROM readings WHERE ts >= ? GROUP BY t ORDER BY t""",
            (bucket, bucket, since)).fetchall()
    return [{"ts": r[0], "cpu": round(r[1], 1), "memory": round(r[2], 1),
             "net_up": round(r[3], 1), "net_down": round(r[4], 1)} for r in rows]


@app.get("/api/processes")
def top_processes():
    procs = []
    for p in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
        try:
            procs.append({"name": p.info["name"] or "unknown",
                          "cpu": round(p.info["cpu_percent"] or 0, 1),
                          "memory": round(p.info["memory_percent"] or 0, 1)})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return sorted(procs, key=lambda x: x["memory"], reverse=True)[:5]


@app.get("/api/alerts")
def alerts():
    with db() as c:
        rows = c.execute("SELECT ts, message, emailed FROM alerts ORDER BY id DESC LIMIT 10").fetchall()
    return [{"ts": r[0], "message": r[1], "emailed": bool(r[2])} for r in rows]


class SettingsIn(BaseModel):
    cpu_threshold: int = Field(80, ge=1, le=100)
    mem_threshold: int = Field(85, ge=1, le=100)
    email_enabled: bool = False
    email_to: str = ""
    cooldown_minutes: int = Field(10, ge=1, le=1440)


@app.get("/api/settings")
def read_settings():
    return get_settings()


@app.post("/api/settings")
def save_settings(new: SettingsIn):
    with db() as c:
        for k, v in new.model_dump().items():
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, int(v) if isinstance(v, bool) else str(v)))
    return get_settings()


@app.post("/api/test-email")
def test_email():
    s = get_settings()
    if not s["email_to"]:
        return {"ok": False, "error": "Save an email address first"}
    ok, err = send_email("[System Monitor] Test email", "Email alerts are working.", s["email_to"])
    return {"ok": ok, "error": err}


# ------------------------------------------------------------- web pages
@app.get("/chart.js")
def chart_js():
    return FileResponse(BASE / "chart.js", media_type="application/javascript")


@app.get("/")
def home():
    return FileResponse(BASE / "index.html")
