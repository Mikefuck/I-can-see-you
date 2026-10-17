import time
from fastapi.testclient import TestClient
from server.app.security import token_hash
from test_server import client, PASSWORD, add_member, batch, hidden, login, seed_device, send, upload_key
from test_management import desktop_login


def authorize(client):
    headers = desktop_login(client)
    response = client.post("/api/v1/management/widget-token", json={}, headers=headers)
    assert response.status_code == 200
    grant = response.json()
    assert grant["scope"] == "widget:board:read"
    assert 179 * 86400 < grant["expires_at"] - time.time() <= 180 * 86400
    return grant["token"]


def test_widget_grant_reads_same_members_and_colors_as_web_without_login(client):
    login(client)
    add_member(client, "private_member")
    own = seed_device(client, "admin", "Phone", 1, usage=[(120, 1)])
    other = seed_device(client, "private_member", "Laptop", 1, usage=[(60, 1)])
    web = client.get("/api/web/board").json()
    token = authorize(client)
    client.cookies.clear()
    assert client.get("/api/web/board").json()["people"] == []
    response = client.get("/api/v1/widget/board", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert {d["id"] for p in payload["people"] for d in p["devices"]} == {own, other}
    assert payload["app_colors"] == web["app_colors"]
    assert payload["apps"] == web["apps"]
    assert response.headers["cache-control"] == "no-store"
    with client.app.state.database.connect() as db:
        row = db.execute("SELECT * FROM widget_tokens").fetchone()
        assert row["token_hash"] == token_hash(token)
        assert token not in tuple(row)


def test_widget_upload_and_management_authority_are_separate(client):
    login(client)
    upload = upload_key(client)
    token = authorize(client)
    client.cookies.clear()
    auth = {"Authorization": "Bearer " + token}
    assert client.get("/api/v1/widget/board", headers={"Authorization": "Bearer " + upload}).status_code == 401
    assert send(client, token, batch()).status_code == 401
    assert client.get("/api/v1/management/users", headers=auth).status_code == 401
    assert client.post("/api/v1/management/token", json={}, headers=auth).status_code == 401
    assert client.post("/api/v1/management/widget-token", json={}, headers=auth).status_code == 401
    assert client.get("/api/web/board", headers=auth).json()["authenticated"] is False
    assert client.get("/api/v1/widget/board", headers=auth, params={"since": "nan"}).status_code == 422


def test_widget_authorization_needs_csrf_and_revocation_is_immediate(client):
    headers = desktop_login(client)
    assert client.post("/api/v1/management/widget-token", json={}).status_code == 403
    first = client.post("/api/v1/management/widget-token", json={}, headers=headers).json()["token"]
    second = client.post("/api/v1/management/widget-token", json={}, headers=headers).json()["token"]
    client.cookies.clear()
    assert client.post("/api/v1/widget/revoke", json={}, headers={"Authorization": "Bearer " + first}).status_code == 200
    assert client.get("/api/v1/widget/board", headers={"Authorization": "Bearer " + first}).status_code == 401
    assert client.get("/api/v1/widget/board", headers={"Authorization": "Bearer " + second}).status_code == 200
    login(client)
    assert "1 份有效只读授权" in client.get("/settings").text
    assert client.post("/settings/widgets/revoke").status_code == 403
    assert client.post("/settings/widgets/revoke", data={"csrf": hidden(client.get("/settings").text)}).status_code == 200
    assert client.get("/api/v1/widget/board", headers={"Authorization": "Bearer " + second}).status_code == 401


def test_expiry_disabled_accounts_and_password_changes_revoke_widget_grants(client):
    token = authorize(client)
    auth = {"Authorization": "Bearer " + token}
    with client.app.state.database.connect() as db:
        db.execute("UPDATE widget_tokens SET expires_at=?", (time.time() - 1,))
    assert client.get("/api/v1/widget/board", headers=auth).status_code == 401
    token = authorize(client)
    client.post("/settings/password", data={"csrf": hidden(client.get("/settings").text), "old_password": PASSWORD,
                "new_password": "new-widget-test-password-123"})
    assert client.get("/api/v1/widget/board", headers={"Authorization": "Bearer " + token}).status_code == 401
    with client.app.state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM widget_tokens").fetchone()[0] == 0


def test_disabling_member_destroys_grants_even_after_reenable(client):
    login(client)
    add_member(client, "reader")
    member = TestClient(client.app)
    member_headers = desktop_login(member, "reader")
    token = member.post("/api/v1/management/widget-token", json={}, headers=member_headers).json()["token"]
    admin_headers = desktop_login(client)
    identity = next(row["id"] for row in client.get("/api/v1/management/users").json()["users"] if row["username"] == "reader")
    for enabled in (False, True):
        assert client.patch(f"/api/v1/management/users/{identity}", json={"enabled": enabled}, headers=admin_headers).status_code == 200
        assert member.get("/api/v1/widget/board", headers={"Authorization": "Bearer " + token}).status_code == 401
