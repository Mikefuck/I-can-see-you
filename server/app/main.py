import asyncio
import logging
import math
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from .board import MAX_SPAN, board, find_person, person_view
from .config import Settings
from .database import Database
from .models import Batch, DeviceStatusEvent, UsageEvent
from .security import password_hash, token_hash, valid_username, verify_password


BASE = Path(__file__).parent
COOKIE = "focus_session"


class BodyLimit:
    """Bound request bytes before JSON/form parsing, including chunked requests."""
    def __init__(self, app, maximum=2 * 1024 * 1024):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.maximum:
                return await JSONResponse({"detail": "Request too large"}, 413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        sent = False

        async def bounded_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


class LoginLimiter:
    def __init__(self):
        self.attempts = defaultdict(deque)

    def allow(self, address):
        now = time.monotonic()
        if len(self.attempts) >= 4096:
            self.attempts = defaultdict(deque, {k: v for k, v in self.attempts.items() if v and v[-1] > now - 60})
            if len(self.attempts) >= 4096 and address not in self.attempts:
                return False
        recent = self.attempts[address]
        while recent and recent[0] <= now - 60:
            recent.popleft()
        if len(recent) >= 10:
            return False
        recent.append(now)
        return True


def create_app(settings=None):
    settings = settings or Settings.from_env()
    database = Database(settings)
    limiter = LoginLimiter()

    async def maintain():
        while True:
            await asyncio.sleep(60)
            try:
                await asyncio.to_thread(database.cleanup)
            except Exception:
                logging.exception("Retention cleanup failed; retrying in one minute")

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(database.initialize)
        task = asyncio.create_task(maintain())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="Focus Ledger", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.database = database
    app.add_middleware(BodyLimit)
    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    templates = Jinja2Templates(directory=BASE / "templates")
    # Pages print UTC; the browser script rewrites every <time> into the viewer's own zone.
    templates.env.filters["date"] = lambda stamp: datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    templates.env.filters["iso"] = lambda stamp: datetime.fromtimestamp(stamp, timezone.utc).isoformat()

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        # Pages and data behind a login are never stored; the public styles and script are revalidated (304) instead of re-sent.
        response.headers["Cache-Control"] = "no-cache" if request.url.path.startswith("/static/") else "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def error_page(request, exc):
        # Browsers get a page with a way back; devices and scripts keep the JSON body.
        if request.url.path.startswith("/api/") or "text/html" not in request.headers.get("accept", ""):
            return await http_exception_handler(request, exc)
        user = await asyncio.to_thread(session, request)
        return templates.TemplateResponse(request=request, name="error.html", status_code=exc.status_code,
            context={"user": user, "retention": settings.retention_days, "status": exc.status_code,
                     "message": {"Not Found": "没有这个页面", "Method Not Allowed": "这个地址不接受这种请求"}
                                .get(exc.detail, exc.detail)})

    def session(request):
        raw = request.cookies.get(COOKIE, "")
        if not raw:
            return None
        with database.connect() as db:
            row = db.execute(
                "SELECT u.*, s.csrf, s.token_hash AS session_hash FROM sessions s JOIN users u ON u.id=s.user_id "
                "WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1", (token_hash(raw), time.time())
            ).fetchone()
        return dict(row) if row else None

    def require_user(request):
        user = session(request)
        if not user:
            raise HTTPException(401, "请先登录")
        return user

    def require_admin(request):
        user = require_user(request)
        if not user["is_admin"]:
            raise HTTPException(403, "需要管理员权限")
        return user

    def csrf(user, form):
        if not secrets.compare_digest(user["csrf"], str(form.get("csrf", ""))):
            raise HTTPException(403, "表单已失效，请刷新重试")

    def api_user(request):
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or not 32 <= len(header[7:]) <= 256:
            raise HTTPException(401, "上传密钥无效")
        with database.connect() as db:
            row = db.execute("SELECT id,username FROM users WHERE upload_hash=? AND enabled=1",
                             (token_hash(header[7:]),)).fetchone()
        if not row:
            raise HTTPException(401, "上传密钥无效或账户已停用")
        return dict(row)

    def render(request, name, user=None, **context):
        return templates.TemplateResponse(request=request, name=name,
            context={"user": user, "retention": settings.retention_days, **context})

    @app.get("/healthz")
    def health():
        with database.connect() as db:
            db.execute("SELECT 1")
        return {"status": "ok", "schema_version": 1}

    @app.get("/login")
    def login_page(request: Request):
        if session(request):
            return RedirectResponse("/", 303)
        nonce = secrets.token_urlsafe(32)
        response = render(request, "login.html", nonce=nonce)
        response.set_cookie("focus_login_csrf", nonce, httponly=True, secure=settings.secure_cookies,
                            samesite="strict", max_age=600)
        return response

    @app.post("/login")
    async def login(request: Request):
        form = await request.form(max_fields=5)
        nonce = request.cookies.get("focus_login_csrf", "")
        if not nonce or not secrets.compare_digest(nonce, str(form.get("csrf", ""))):
            raise HTTPException(403, "请重新打开登录页")
        if not limiter.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(429, "尝试过于频繁，请一分钟后重试")
        username, password = str(form.get("username", "")), str(form.get("password", ""))
        with database.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=? AND enabled=1", (username,)).fetchone()
        if not row or not await asyncio.to_thread(verify_password, password, row["password_hash"]):
            return render(request, "login.html", nonce=nonce, error="用户名或密码错误，或账户已停用")
        raw = secrets.token_urlsafe(32)
        with database.connect() as db:
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)",
                       (token_hash(raw), row["id"], secrets.token_urlsafe(32), time.time() + 43200))
        response = RedirectResponse("/", 303)
        response.set_cookie(COOKIE, raw, httponly=True, secure=settings.secure_cookies,
                            samesite="strict", max_age=43200)
        response.delete_cookie("focus_login_csrf")
        return response

    @app.post("/logout")
    async def logout(request: Request):
        user = require_user(request)
        csrf(user, await request.form())
        with database.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (user["session_hash"],))
        response = RedirectResponse("/login", 303)
        response.delete_cookie(COOKIE)
        return response

    def member_rows(db):
        return db.execute(
            "SELECT u.id,u.username,u.is_admin,u.enabled,u.shared,u.created_at,COUNT(d.id) AS devices,"
            "MAX(d.last_seen) AS last_seen FROM users u LEFT JOIN devices d ON d.user_id=u.id AND d.last_seen>? "
            "GROUP BY u.id ORDER BY u.id", (database.cutoff(),)).fetchall()

    @app.get("/")
    def board_page(request: Request):
        user = session(request)
        if not user:
            return RedirectResponse("/login", 303)
        with database.connect() as db:
            data = board(db, user, time.time(), database.cutoff())
        return render(request, "board.html", user, nav="board", board=data)

    @app.get("/api/web/board")
    def board_data(request: Request, since: float | None = None):
        user = require_user(request)
        if since is not None and not math.isfinite(since):
            raise HTTPException(422, "时间无效")
        with database.connect() as db:
            return JSONResponse(board(db, user, time.time(), database.cutoff(), since))

    @app.get("/people/{username}")
    def person_page(username: str, request: Request):
        user = session(request)
        if not user:
            return RedirectResponse("/login", 303)
        with database.connect() as db:
            person = find_person(db, user, username)
        if not person:
            raise HTTPException(404, "没有这个成员，或对方没有公开记录")
        return render(request, "person.html", user, nav="mine" if person["id"] == user["id"] else "board",
                      person=dict(person))

    @app.get("/api/web/people/{username}")
    def person_data(username: str, request: Request, start: float, end: float, device: str = ""):
        user = require_user(request)
        if not (math.isfinite(start) and math.isfinite(end)) or not 0 < end - start <= MAX_SPAN:
            raise HTTPException(422, "时间范围无效")
        with database.connect() as db:
            person = find_person(db, user, username)
            if not person:
                raise HTTPException(404, "没有这个成员，或对方没有公开记录")
            if device and not db.execute("SELECT 1 FROM devices WHERE id=? AND user_id=?",
                                         (device, person["id"])).fetchone():
                raise HTTPException(404, "设备不存在")
            return JSONResponse(person_view(db, person, user, time.time(), database.cutoff(), start, end, device))

    def account_page(request, user, **context):
        with database.connect() as db:
            devices = db.execute("SELECT * FROM devices WHERE user_id=? AND last_seen>? ORDER BY first_seen",
                                 (user["id"], database.cutoff())).fetchall()
        return render(request, "settings.html", user, nav="account", devices=devices, **context)

    @app.get("/settings")
    def settings_page(request: Request):
        return account_page(request, require_user(request))

    @app.post("/settings/token")
    async def rotate_token(request: Request):
        user = require_user(request)
        csrf(user, await request.form())
        raw = secrets.token_urlsafe(32)
        with database.connect() as db:
            db.execute("UPDATE users SET upload_hash=? WHERE id=?", (token_hash(raw), user["id"]))
        user["upload_hash"] = token_hash(raw)
        return account_page(request, user, upload_token=raw)

    @app.post("/settings/sharing")
    async def set_sharing(request: Request):
        user = require_user(request)
        form = await request.form(max_fields=5)
        csrf(user, form)
        with database.connect() as db:
            db.execute("UPDATE users SET shared=? WHERE id=?", (int(form.get("shared") == "on"), user["id"]))
        return RedirectResponse("/settings", 303)

    @app.post("/settings/password")
    async def change_password(request: Request):
        user = require_user(request)
        form = await request.form(max_fields=5)
        csrf(user, form)
        if not await asyncio.to_thread(verify_password, str(form.get("old_password", "")), user["password_hash"]):
            return account_page(request, user, error="原密码错误")
        try:
            encoded = await asyncio.to_thread(password_hash, str(form.get("new_password", "")))
        except ValueError as exc:
            return account_page(request, user, error=str(exc))
        with database.connect() as db:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, user["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        response = RedirectResponse("/login", 303)
        response.delete_cookie(COOKIE)
        return response

    @app.get("/admin/users")
    def users_page(request: Request):
        user = require_admin(request)
        with database.connect() as db:
            users = member_rows(db)
        return render(request, "users.html", user, nav="members", users=users)

    @app.post("/admin/users")
    async def add_user(request: Request):
        user = require_admin(request)
        form = await request.form(max_fields=6)
        csrf(user, form)
        username = str(form.get("username", ""))
        try:
            if not valid_username(username):
                raise ValueError("用户名须为 3–40 个英文字母、数字、下划线、点或连字符")
            encoded = await asyncio.to_thread(password_hash, str(form.get("password", "")))
            with database.connect() as db:
                db.execute("INSERT INTO users(username,password_hash,is_admin,shared,created_at) VALUES(?,?,?,?,?)",
                    (username, encoded, int(form.get("is_admin") == "on"), int(form.get("shared") == "on"), time.time()))
        except (ValueError, sqlite3.IntegrityError) as exc:
            with database.connect() as db:
                users = member_rows(db)
            return render(request, "users.html", user, nav="members", users=users,
                          error="用户名已存在" if isinstance(exc, sqlite3.IntegrityError) else str(exc))
        return RedirectResponse("/admin/users", 303)

    @app.post("/admin/users/{user_id}/toggle")
    async def toggle_user(user_id: int, request: Request):
        user = require_admin(request)
        form = await request.form()
        csrf(user, form)
        if user_id == user["id"]:
            raise HTTPException(400, "不能停用当前账户")
        with database.connect() as db:
            row = db.execute("SELECT enabled FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise HTTPException(404, "账户不存在")
            db.execute("UPDATE users SET enabled=? WHERE id=?", (int(not row["enabled"]), user_id))
            if row["enabled"]:
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                db.execute("UPDATE users SET upload_hash=NULL WHERE id=?", (user_id,))
        return RedirectResponse("/admin/users", 303)

    @app.get("/api/v1/agent/check")
    def check(request: Request):
        user = api_user(request)
        return {"ok": True, "account_id": user["id"], "username": user["username"], "schema_version": 1,
                "features": ["app_usage", "device_status"], "retention_days": settings.retention_days}

    @app.post("/api/v1/usage/batches")
    def ingest(batch: Batch, request: Request):
        user = api_user(request)
        now, cutoff = time.time(), database.cutoff()
        device_id = str(batch.device.id)
        if any((event.ended_at if isinstance(event, UsageEvent) else event.occurred_at).timestamp() > now + 300
               for event in batch.events):
            raise HTTPException(422, "设备时间超前超过 5 分钟，请同步系统时钟")
        inserted, duplicates, expired, acknowledged = 0, 0, 0, []
        with database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            owner = db.execute("SELECT user_id FROM devices WHERE id=?", (device_id,)).fetchone()
            if owner and owner["user_id"] != user["id"]:
                raise HTTPException(409, "设备已属于其他账户，请在客户端更换设备身份")
            db.execute("INSERT INTO devices VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                       "name=excluded.name,platform=excluded.platform,agent_version=excluded.agent_version,last_seen=excluded.last_seen",
                       (device_id, user["id"], batch.device.name, batch.device.platform, batch.device.agent_version, now, now))
            for event in batch.events:
                event_id = str(event.id)
                acknowledged.append(event_id)
                if isinstance(event, UsageEvent):
                    start, end = event.started_at.timestamp(), event.ended_at.timestamp()
                else:
                    start = end = event.occurred_at.timestamp()
                if end <= cutoff:
                    expired += 1
                    continue
                if isinstance(event, UsageEvent):
                    cross_kind = db.execute("SELECT 1 FROM status_events WHERE user_id=? AND device_id=? AND event_id=?",
                                            (user["id"], device_id, event_id)).fetchone()
                    if cross_kind:
                        raise HTTPException(409, "记录 ID 冲突")
                    previous = db.execute("SELECT * FROM events WHERE user_id=? AND device_id=? AND event_id=?",
                                          (user["id"], device_id, event_id)).fetchone()
                    if previous:
                        if (previous["app_name"] != event.app_name or previous["process_name"] != event.process_name or
                                abs(previous["ended_at"] - end) > 0.001):
                            raise HTTPException(409, "记录 ID 冲突")
                        duplicates += 1
                        continue
                    start = max(start, cutoff)
                    db.execute("INSERT INTO events(event_id,user_id,device_id,kind,app_name,process_name,started_at,ended_at,duration_seconds) "
                               "VALUES(?,?,?,?,?,?,?,?,?)", (event_id, user["id"], device_id, event.kind, event.app_name,
                               event.process_name, start, end, end - start))
                else:
                    cross_kind = db.execute("SELECT 1 FROM events WHERE user_id=? AND device_id=? AND event_id=?",
                                            (user["id"], device_id, event_id)).fetchone()
                    if cross_kind:
                        raise HTTPException(409, "记录 ID 冲突")
                    previous = db.execute("SELECT * FROM status_events WHERE user_id=? AND device_id=? AND event_id=?",
                                          (user["id"], device_id, event_id)).fetchone()
                    if previous:
                        previous_charging = None if previous["charging"] is None else bool(previous["charging"])
                        previous_ac_online = None if previous["ac_online"] is None else bool(previous["ac_online"])
                        same = (previous["reason"] == event.reason and
                                previous["battery_percent"] == event.battery_percent and
                                previous_charging == event.charging and
                                previous_ac_online == event.ac_online and
                                previous["battery_life_seconds"] == event.battery_life_seconds and
                                abs(previous["occurred_at"] - end) <= 0.001)
                        if not same:
                            raise HTTPException(409, "状态记录 ID 冲突")
                        duplicates += 1
                        continue
                    db.execute("INSERT INTO status_events(event_id,user_id,device_id,occurred_at,reason,battery_percent,charging,ac_online,battery_life_seconds) "
                               "VALUES(?,?,?,?,?,?,?,?,?)", (event_id, user["id"], device_id, end, event.reason,
                               event.battery_percent, event.charging, event.ac_online, event.battery_life_seconds))
                inserted += 1
        return {"acknowledged_ids": acknowledged, "inserted": inserted, "duplicates": duplicates,
                "expired": expired, "server_time": datetime.now(timezone.utc).isoformat()}

    return app


app = create_app()
