"""Separate, in-memory management session; no administrator password is persisted."""
import http.cookiejar
import json
import urllib.error
import urllib.request

from .network import NoRedirect


class ManagementSession:
    def __init__(self, config):
        self.base_urls = config.connection_urls
        self.base_url = self.base_urls[0]
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf = ""
        self.user = None

    def request(self, path, body=None, method=None):
        # Cookies and CSRF tokens belong to the logged-in origin. A fresh login can
        # choose either route; an established management session stays on its origin.
        urls = (self.base_url,) if self.user else self.base_urls
        for index, base_url in enumerate(urls):
            try:
                result = self._request(base_url, path, body, method, 3 if len(urls) > 1 else 10)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if isinstance(exc, urllib.error.HTTPError):
                    exc.close()
                if index + 1 < len(urls):
                    self.cookies.clear()
                    continue
                if isinstance(exc, urllib.error.HTTPError):
                    raise RuntimeError(f"服务端返回 HTTP {exc.code}") from None
                raise RuntimeError("无法连接服务端，请检查两个地址或重新登录以切换地址" if len(self.base_urls) > 1
                                   else "无法连接服务端，请检查地址、端口、网络和证书") from exc
            self.base_url = base_url
            return result

    def _request(self, base_url, path, body, method, timeout):
        headers = {"Content-Type": "application/json", "X-FocusLedger-Client": "desktop"}
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(base_url + "/api/v1/management" + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise RuntimeError("服务器响应过大")
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise RuntimeError("服务器管理响应无效，请升级服务端")
                return result
        except urllib.error.HTTPError as exc:
            if exc.code >= 500:
                raise
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
