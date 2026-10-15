"""Separate, in-memory management session; no administrator password is persisted."""
import http.cookiejar
import json
import urllib.error
import urllib.request

from .network import NoRedirect


class ManagementSession:
    def __init__(self, config):
        self.base_url = config.base_url
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf = ""
        self.user = None

    def request(self, path, body=None, method=None):
        headers = {"Content-Type": "application/json", "X-FocusLedger-Client": "desktop"}
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(self.base_url + "/api/v1/management" + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=10) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise RuntimeError("服务器响应过大")
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise RuntimeError("服务器管理响应无效，请升级服务端")
                return result
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read(65536)).get("detail")
            except (ValueError, AttributeError):
                detail = None
            if isinstance(detail, str):
                raise RuntimeError(detail) from None
            messages = {401: "管理会话已失效，请重新登录；HTTP 部署请检查安全 Cookie 设置",
                        403: "需要管理员权限或管理会话已失效", 404: "服务端不支持管理功能，请升级服务端",
                        422: "提交的字段无效，请检查用户名、密码长度或天数"}
            raise RuntimeError(messages.get(exc.code, f"服务端返回 HTTP {exc.code}")) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError("无法连接服务端，请检查地址、端口、网络和证书") from exc
        except (ValueError, UnicodeError):
            raise RuntimeError("服务端管理响应无效，请升级服务端") from None

    def login(self, username, password):
        self.user = self.request("/login", {"username": username, "password": password})
        self.csrf = self.user.get("csrf", "")
        if not self.csrf or not any(cookie.name == "focus_session" and
                (self.base_url.startswith("https:") or not cookie.secure) for cookie in self.cookies):
            raise RuntimeError("登录会话无法使用：HTTPS 部署请使用 HTTPS；内网 HTTP 请关闭 SECURE_COOKIES")
        return self.user

    def overview(self):
        return {"users": self.request("/users")["users"], "settings": self.request("/settings")}

    def close(self):
        self.cookies.clear()
        self.csrf, self.user = "", None
