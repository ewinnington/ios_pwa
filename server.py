"""CloudPlush — PWA push notification micro-server."""

import html as html_mod
import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pywebpush import webpush, WebPushException

# ── config ──────────────────────────────────────────────────────────

VAPID_KEYS_FILE = Path("vapid_keys.json")
DB_PATH = Path("data/notifications.db")
VAPID_CLAIMS = {"sub": "mailto:admin@cloudplush.com"}

DB_PATH.parent.mkdir(exist_ok=True)

if not VAPID_KEYS_FILE.exists():
    raise SystemExit(
        "vapid_keys.json not found. Run:  python setup.py"
    )

_keys = json.loads(VAPID_KEYS_FILE.read_text())
VAPID_PRIVATE_KEY = _keys["privateKey"]
VAPID_PUBLIC_KEY = _keys["publicKey"]

# ── app ─────────────────────────────────────────────────────────────

app = FastAPI(title="CloudPlush")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── db helpers ──────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint    TEXT UNIQUE NOT NULL,
            sub_json    TEXT NOT NULL,
            device_name TEXT NOT NULL DEFAULT 'Device',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            title    TEXT NOT NULL,
            body     TEXT NOT NULL,
            sent_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # migrate: add device_name if missing (existing DBs)
    try:
        conn.execute(
            "ALTER TABLE subscriptions ADD COLUMN device_name TEXT NOT NULL DEFAULT 'Device'"
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.close()


init_db()

# ── page routes ─────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("static/index.html")


@app.get("/admin", response_class=HTMLResponse)
async def admin():
    return FileResponse("static/admin.html")


@app.get("/sw.js")
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(
        "static/manifest.json", media_type="application/manifest+json"
    )


# ── API routes ──────────────────────────────────────────────────────


@app.get("/api/vapid-public-key")
async def vapid_public_key():
    return {"publicKey": VAPID_PUBLIC_KEY}


@app.post("/api/subscribe")
async def subscribe(request: Request):
    data = await request.json()
    # Support both {subscription, device_name} wrapper and raw subscription
    if "subscription" in data:
        sub = data["subscription"]
        device_name = data.get("device_name", "Device")
    else:
        sub = data
        device_name = "Device"

    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO subscriptions (endpoint, sub_json, device_name) VALUES (?, ?, ?)",
        (sub["endpoint"], json.dumps(sub), device_name),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/unsubscribe")
async def unsubscribe(request: Request):
    data = await request.json()
    conn = get_db()
    conn.execute("DELETE FROM subscriptions WHERE endpoint = ?", (data["endpoint"],))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/devices", response_class=HTMLResponse)
async def list_devices():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, device_name, created_at FROM subscriptions ORDER BY id"
    ).fetchall()
    conn.close()

    if not rows:
        return '<p class="empty-sm">No devices subscribed yet</p>'

    parts = []
    for r in rows:
        name = html_mod.escape(r["device_name"])
        did = r["id"]
        parts.append(
            f'<label class="device-check">'
            f'<input type="checkbox" name="device_ids" value="{did}" checked>'
            f'<span class="device-name">{name}</span>'
            f"</label>"
        )
    return "\n".join(parts)


def _push_to(subs, payload: str) -> tuple[int, int]:
    """Send push to a list of subscription rows. Returns (sent, failed)."""
    sent = 0
    failed = 0
    for row in subs:
        try:
            webpush(
                subscription_info=json.loads(row["sub_json"]),
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
            sent += 1
        except WebPushException as exc:
            failed += 1
            if exc.response is not None and exc.response.status_code == 410:
                sub_data = json.loads(row["sub_json"])
                c = get_db()
                c.execute(
                    "DELETE FROM subscriptions WHERE endpoint = ?",
                    (sub_data["endpoint"],),
                )
                c.commit()
                c.close()
    return sent, failed


@app.post("/api/send")
async def send_notification(request: Request):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        title = str(data.get("title", "Notification")).strip()
        body = str(data.get("body", "")).strip()
        device_ids = data.get("device_ids", [])  # empty = all
    else:
        form = await request.form()
        title = str(form.get("title", "Notification")).strip()
        body = str(form.get("body", "")).strip()
        device_ids = form.getlist("device_ids")

    if not title:
        if request.headers.get("HX-Request"):
            return HTMLResponse('<div class="fail">Title is required</div>')
        return JSONResponse({"error": "title required"}, status_code=400)

    # save to log
    conn = get_db()
    conn.execute(
        "INSERT INTO notifications (title, body) VALUES (?, ?)", (title, body)
    )
    conn.commit()

    # fetch targeted subscriptions
    if device_ids:
        placeholders = ",".join("?" * len(device_ids))
        subs = conn.execute(
            f"SELECT sub_json FROM subscriptions WHERE id IN ({placeholders})",
            list(device_ids),
        ).fetchall()
    else:
        subs = conn.execute("SELECT sub_json FROM subscriptions").fetchall()
    conn.close()

    payload = json.dumps({"title": title, "body": body})
    sent, failed = _push_to(subs, payload)

    # respond based on caller
    if request.headers.get("HX-Request"):
        resp = HTMLResponse(
            f'<div class="success">Sent to {sent} device(s)'
            + (f", {failed} failed" if failed else "")
            + "</div>"
        )
        resp.headers["HX-Trigger"] = "notificationSent"
        return resp
    return {"sent": sent, "failed": failed}


@app.get("/api/notifications", response_class=HTMLResponse)
async def get_notifications():
    conn = get_db()
    rows = conn.execute(
        "SELECT title, body, sent_at FROM notifications ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()

    if not rows:
        return (
            '<p class="empty">No notifications yet. '
            'Send one from the <a href="/admin">admin page</a>!</p>'
        )

    parts = []
    for r in rows:
        t = html_mod.escape(r["title"])
        b = html_mod.escape(r["body"])
        ts = r["sent_at"]
        parts.append(
            f'<div class="notif-item">'
            f'<div class="notif-title">{t}</div>'
            f'<div class="notif-body">{b}</div>'
            f'<time class="notif-time" datetime="{ts}">{ts}</time>'
            f"</div>"
        )
    return "\n".join(parts)


@app.get("/api/subscriptions/count", response_class=HTMLResponse)
async def subscriptions_count(request: Request):
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
    conn.close()
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            f'<span>{count}</span> device{"s" if count != 1 else ""} subscribed'
        )
    return JSONResponse({"count": count})
