"""Revocable, read-only widget grants, deliberately separate from upload and login tokens."""
import math
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from .board import board
from .security import token_hash

WIDGET_TOKEN_SECONDS = 180 * 86400


def widget_router(database, require_user):
    router = APIRouter()

    @router.post("/api/v1/management/widget-token")
    def authorize(request: Request):
        user = require_user(request)
        if not secrets.compare_digest(user["csrf"], request.headers.get("x-csrf-token", "")):
            raise HTTPException(403, "请重新登录后授权小组件")
        now, raw = time.time(), secrets.token_urlsafe(32)
        with database.connect() as db:
            db.execute("DELETE FROM widget_tokens WHERE expires_at<=?", (now,))
            count = db.execute("SELECT COUNT(*) FROM widget_tokens WHERE user_id=?", (user["id"],)).fetchone()[0]
            if count >= 64:
                raise HTTPException(409, "小组件授权已达上限，请在网页账户页撤销旧授权")
            db.execute("INSERT INTO widget_tokens VALUES(?,?,?,?)",
                       (token_hash(raw), user["id"], now, now + WIDGET_TOKEN_SECONDS))
        return {"token": raw, "username": user["username"], "expires_at": now + WIDGET_TOKEN_SECONDS,
                "scope": "widget:board:read"}

    def grant(request):
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or not 32 <= len(header[7:]) <= 256:
            raise HTTPException(401, "小组件只读授权无效，请重新授权")
        digest = token_hash(header[7:])
        with database.connect() as db:
            user = db.execute("SELECT u.id,u.username FROM widget_tokens t JOIN users u ON u.id=t.user_id "
                              "WHERE t.token_hash=? AND t.expires_at>? AND u.enabled=1",
                              (digest, time.time())).fetchone()
        if not user:
            raise HTTPException(401, "小组件授权已过期或已撤销，请重新授权")
        return dict(user), digest

    @router.get("/api/v1/widget/board")
    def widget_board(request: Request, since: float | None = None):
        user, _ = grant(request)
        if since is not None and not math.isfinite(since):
            raise HTTPException(422, "时间无效")
        with database.connect() as db:
            return board(db, user, time.time(), database.cutoff(), since)

    @router.post("/api/v1/widget/revoke")
    def revoke(request: Request):
        _, digest = grant(request)
        with database.connect() as db:
            db.execute("DELETE FROM widget_tokens WHERE token_hash=?", (digest,))
        return {"ok": True}

    return router
