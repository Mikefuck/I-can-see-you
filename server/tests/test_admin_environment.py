"""Deployment credential changes must work without losing persisted account data."""
import pytest
from fastapi.testclient import TestClient

from server.app.config import Settings
from server.app.database import Database
from server.app.main import create_app
from server.app.security import verify_password
from test_server import PASSWORD, add_member, batch, hidden, login, send, upload_key


CHANGED = "changed-compose-password-456"


def settings(path, password=PASSWORD, username="admin"):
    return Settings(path, admin_username=username, admin_password=password)


def test_compose_password_change_preserves_data_and_revokes_only_admin_sessions(tmp_path):
    path = tmp_path / "focus.sqlite3"
    with TestClient(create_app(settings(path))) as first:
        assert "data-board" in login(first).text
        add_member(first, "member")
        key = upload_key(first)
        assert send(first, key, batch()).json()["inserted"] == 1
        member = TestClient(first.app)
        assert "data-board" in login(member, "member").text
        admin_cookies, member_cookies = dict(first.cookies), dict(member.cookies)
        database = first.app.state.database
        database.initialize()
        assert first.get("/settings").status_code == 200
        with database.connect() as db:
            users_before = [tuple(row) for row in db.execute(
                "SELECT id,username,is_admin,enabled,upload_hash,shared,created_at FROM users ORDER BY id")]
            events_before = [tuple(row) for row in db.execute("SELECT * FROM events")]

    with TestClient(create_app(settings(path, CHANGED))) as restarted:
        restarted.cookies.update(admin_cookies)
        assert restarted.get("/settings").status_code == 401
        restarted.cookies.clear()
        restarted.cookies.update(member_cookies)
        assert restarted.get("/settings").status_code == 200
        restarted.cookies.clear()
        assert "用户名或密码错误" in login(restarted).text
        assert "data-board" in login(restarted, password=CHANGED).text
        with restarted.app.state.database.connect() as db:
            assert [tuple(row) for row in db.execute(
                "SELECT id,username,is_admin,enabled,upload_hash,shared,created_at FROM users ORDER BY id")] == users_before
            assert [tuple(row) for row in db.execute("SELECT * FROM events")] == events_before
        assert send(restarted, key, batch()).status_code == 200


def test_unchanged_compose_keeps_a_password_changed_on_the_website(tmp_path):
    path = tmp_path / "focus.sqlite3"
    website_password = "changed-on-website-password-789"
    with TestClient(create_app(settings(path))) as first:
        login(first)
        response = first.post("/settings/password", data={
            "csrf": hidden(first.get("/settings").text),
            "old_password": PASSWORD, "new_password": website_password,
        }, follow_redirects=False)
        assert response.status_code == 303
    with TestClient(create_app(settings(path))) as restarted:
        assert "用户名或密码错误" in login(restarted).text
        assert "data-board" in login(restarted, password=website_password).text
    with TestClient(create_app(settings(path, CHANGED))) as reconfigured:
        assert "data-board" in login(reconfigured, password=CHANGED).text


def test_upgrade_of_old_database_adopts_configured_password(tmp_path):
    path = tmp_path / "focus.sqlite3"
    database = Database(settings(path))
    database.initialize()
    with database.connect() as db:
        # Previous releases have no record of the last environment password.
        db.execute("DROP TABLE admin_environment")
    with TestClient(create_app(settings(path, CHANGED))) as upgraded:
        assert "用户名或密码错误" in login(upgraded).text
        assert "data-board" in login(upgraded, password=CHANGED).text
        with upgraded.app.state.database.connect() as db:
            stored = db.execute("SELECT password_hash FROM admin_environment").fetchone()[0]
            assert CHANGED not in stored and verify_password(CHANGED, stored)


@pytest.mark.parametrize("password", ["", "123456789", "x" * 257])
def test_invalid_environment_password_fails_clearly_without_changing_credentials(tmp_path, password):
    path = tmp_path / "focus.sqlite3"
    database = Database(settings(path))
    database.initialize()
    with pytest.raises(ValueError, match="ADMIN_PASSWORD.*12–256"):
        Database(settings(path, password)).initialize()
    with database.connect() as db:
        assert verify_password(PASSWORD, db.execute("SELECT password_hash FROM users").fetchone()[0])
        assert verify_password(PASSWORD, db.execute("SELECT password_hash FROM admin_environment").fetchone()[0])


@pytest.mark.parametrize("username,disable", [("member", False), ("missing", False), ("admin", True)])
def test_configuration_cannot_promote_rename_or_reenable_an_account(tmp_path, username, disable):
    path = tmp_path / "focus.sqlite3"
    with TestClient(create_app(settings(path))) as client:
        login(client)
        add_member(client, "member")
        database = client.app.state.database
        with database.connect() as db:
            if disable:
                db.execute("UPDATE users SET enabled=0 WHERE username='admin'")
            before = [tuple(row) for row in db.execute("SELECT * FROM users ORDER BY id")]
        with pytest.raises(ValueError, match="existing enabled administrator"):
            Database(settings(path, CHANGED, username)).initialize()
        with database.connect() as db:
            assert [tuple(row) for row in db.execute("SELECT * FROM users ORDER BY id")] == before


def test_existing_database_can_start_without_environment_credentials(tmp_path):
    path = tmp_path / "focus.sqlite3"
    Database(settings(path)).initialize()
    with TestClient(create_app(Settings(path))) as client:
        assert "data-board" in login(client).text
