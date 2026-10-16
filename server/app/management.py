"""Session-authenticated desktop management; upload tokens never grant management access."""
import secrets
import sqlite3
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from .models import StrictModel
from .security import password_hash, token_hash, valid_username, verify_password


class Login(StrictModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=256)


class NewUser(Login):
    is_admin: bool = False


class UserState(StrictModel):
    enabled: bool


class RuntimeSettings(StrictModel):
    retention_days: int = Field(ge=1, le=365, strict=True)


def management_router(database, settings, require_user, require_admin, limiter, cookie, notify):
    router = APIRouter(prefix="/api/v1/management")

    def authenticated(request, admin=False, mutation=False):
        user = require_admin(request) if admin else require_user(request)
        if mutation and not secrets.compare_digest(user["csrf"], request.headers.get("x-csrf-token", "")):
            raise HTTPException(403, "管理会话已失效，请重新登录")
        return user

    @router.post("/login")
    def login(body: Login, request: Request):
        # JSON plus a custom header prevents browsers from treating this as a cross-site form login.
        if request.headers.get("x-focusledger-client") != "desktop":
            raise HTTPException(403, "请通过客户端登录")
        if not limiter.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(429, "尝试过于频繁，请一分钟后重试")
        with database.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=? AND enabled=1", (body.username,)).fetchone()
        if not row or not verify_password(body.password, row["password_hash"]):
            raise HTTPException(401, "用户名或密码错误，或账户已停用")
        raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with database.connect() as db:
            old = request.cookies.get(cookie)
            if old:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(old),))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (token_hash(raw), row["id"], csrf, time.time() + 43200))
        response = JSONResponse({"account_id": row["id"], "username": row["username"],
                                 "is_admin": bool(row["is_admin"]), "csrf": csrf})
        response.set_cookie(cookie, raw, httponly=True, secure=settings.secure_cookies, samesite="strict", max_age=43200)
        return response

    @router.post("/logout")
    def logout(request: Request):
        user = authenticated(request, mutation=True)
        with database.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (user["session_hash"],))
        notify(user["id"])
        response = JSONResponse({"ok": True})
        response.delete_cookie(cookie)
        return response

    @router.get("/users")
    def users(request: Request):
        authenticated(request, admin=True)
        with database.connect() as db:
            rows = db.execute("SELECT id,username,is_admin,enabled FROM users ORDER BY id").fetchall()
        return {"users": [dict(row) for row in rows]}

    @router.post("/users")
    def create_user(body: NewUser, request: Request):
        authenticated(request, admin=True, mutation=True)
        if not valid_username(body.username):
            raise HTTPException(422, "用户名须为 3–40 个英文字母、数字、下划线、点或连字符")
        try:
            encoded = password_hash(body.password)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        try:
            with database.connect() as db:
                cursor = db.execute("INSERT INTO users(username,password_hash,is_admin,created_at) VALUES(?,?,?,?)",
                    (body.username, encoded, int(body.is_admin), time.time()))
                identity = cursor.lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(409, "用户名已存在") from None
        notify(identity, history=True)
        return {"id": identity, "username": body.username, "is_admin": body.is_admin, "enabled": True}

    @router.patch("/users/{user_id}")
    def set_user_state(user_id: int, body: UserState, request: Request):
        user = authenticated(request, admin=True, mutation=True)
        if user_id == user["id"] and not body.enabled:
            raise HTTPException(400, "不能停用当前账户")
        with database.connect() as db:
            if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
                raise HTTPException(404, "账户不存在")
            db.execute("UPDATE users SET enabled=? WHERE id=?", (int(body.enabled), user_id))
            if not body.enabled:
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                db.execute("UPDATE users SET upload_hash=NULL WHERE id=?", (user_id,))
        notify(user_id, history=True)
        return {"id": user_id, "enabled": body.enabled}

    @router.get("/settings")
    def get_settings(request: Request):
        authenticated(request, admin=True)
        return {"retention_days": database.retention_days, "secure_cookies": settings.secure_cookies,
                "schema_version": 1, "management_version": 1}

    @router.put("/settings")
    def update_settings(body: RuntimeSettings, request: Request):
        authenticated(request, admin=True, mutation=True)
        database.set_retention_days(body.retention_days)
        notify(0, history=True, metadata=True)
        return get_settings(request)

    @router.post("/token")
    def rotate_token(request: Request):
        user = authenticated(request, mutation=True)
        raw = secrets.token_urlsafe(32)
        with database.connect() as db:
            db.execute("UPDATE users SET upload_hash=? WHERE id=?", (token_hash(raw), user["id"]))
        return {"api_key": raw, "account_id": user["id"], "username": user["username"]}

    return router
