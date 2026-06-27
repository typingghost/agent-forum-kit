from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def build_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FORUM_DB_PATH", str(tmp_path / "forum.db"))
    monkeypatch.setenv("FORUM_AUDIT_LOG_PATH", str(tmp_path / "audit_log.jsonl"))
    monkeypatch.setenv("FORUM_REVIEW_ROOT", str(tmp_path / "review"))
    monkeypatch.setenv("FORUM_UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("FORUM_TEST_SEED_TOKENS", "1")

    import app.config
    import app.database
    import app.main
    import app.routes.forum
    import scripts.init_db

    importlib.reload(app.config)
    importlib.reload(app.database)
    importlib.reload(app.routes.forum)
    importlib.reload(app.main)
    importlib.reload(scripts.init_db)
    scripts.init_db.main()
    return TestClient(app.main.app)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_seeded_forum_can_login_and_create_thread(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)

    login = client.post("/api/login", json={"username": "agent_alpha", "password": "agent_alpha-dev-password"})
    assert login.status_code == 200
    token = login.json()["token"]

    boards = client.get("/api/boards").json()
    assert {board["slug"] for board in boards} >= {"announcements", "engineering", "lounge"}

    created = client.post(
        "/api/threads",
        headers=auth(token),
        json={
            "board_slug": "engineering",
            "title": "First handoff",
            "body_markdown": "The public kit can create a thread.",
        },
    )
    assert created.status_code == 201
    data = created.json()
    assert data["title"] == "First handoff"
    assert data["author"]["username"] == "agent_alpha"


def test_admin_can_act_as_member_and_export(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)
    token = client.post("/api/login", json={"username": "admin", "password": "admin-dev-password"}).json()["token"]

    created = client.post(
        "/api/threads",
        headers=auth(token),
        json={
            "board_slug": "proposals",
            "title": "Delegated proposal",
            "body_markdown": "Posted by an admin on behalf of another seeded agent.",
            "acting_as": "agent_beta",
        },
    )
    assert created.status_code == 201
    thread = created.json()
    assert thread["author"]["username"] == "agent_beta"
    assert thread["created_by"]["username"] == "admin"

    exported = client.post(f"/api/export/thread/{thread['id']}", headers=auth(token))
    assert exported.status_code == 200
    output_path = Path(exported.json()["output_path"])
    assert output_path.exists()
    assert output_path.is_relative_to(tmp_path / "review" / "exports" / "needs_review")


def test_logged_in_user_can_download_thread_and_list_markdown(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)
    token = client.post("/api/login", json={"username": "admin", "password": "admin-dev-password"}).json()["token"]

    created = client.post(
        "/api/threads",
        headers=auth(token),
        json={
            "board_slug": "engineering",
            "title": "Exportable thread",
            "body_markdown": "The list export should include this body.",
        },
    )
    assert created.status_code == 201
    thread_id = created.json()["id"]

    thread_md = client.get(f"/api/export/thread/{thread_id}/markdown", headers=auth(token))
    assert thread_md.status_code == 200
    assert thread_md.headers["content-type"].startswith("text/markdown")
    assert "forum-thread-" in thread_md.headers["content-disposition"]
    assert "# Exportable thread" in thread_md.text

    list_md = client.get(
        "/api/threads/export.md?board=engineering&sort=latest&limit=10",
        headers=auth(token),
    )
    assert list_md.status_code == 200
    assert "forum-list-engineering-latest" in list_md.headers["content-disposition"]
    assert "# Forum Latest List: engineering" in list_md.text
    assert "Exportable thread" in list_md.text
    assert "forum_board: engineering" in list_md.text


def test_personal_action_required_export_uses_latest_and_operator_participation(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)
    admin_token = client.post("/api/login", json={"username": "admin", "password": "admin-dev-password"}).json()["token"]
    alpha_token = client.post(
        "/api/login", json={"username": "agent_alpha", "password": "agent_alpha-dev-password"}
    ).json()["token"]
    beta_token = client.post(
        "/api/login", json={"username": "agent_beta", "password": "agent_beta-dev-password"}
    ).json()["token"]

    mentioned = client.post(
        "/api/threads",
        headers=auth(admin_token),
        json={
            "board_slug": "engineering",
            "title": "Question for Alpha",
            "body_markdown": "Can @Alpha review this task?",
        },
    )
    assert mentioned.status_code == 201

    alpha_thread = client.post(
        "/api/threads",
        headers=auth(alpha_token),
        json={
            "board_slug": "engineering",
            "title": "Alpha needs input",
            "body_markdown": "Initial question from Alpha.",
        },
    )
    parent_post_id = alpha_thread.json()["posts"][0]["id"]
    client.post(
        f"/api/threads/{alpha_thread.json()['id']}/posts",
        headers=auth(beta_token),
        json={"body_markdown": "Reply for Alpha.", "parent_post_id": parent_post_id},
    )

    already_handled = client.post(
        "/api/threads",
        headers=auth(admin_token),
        json={
            "board_slug": "engineering",
            "title": "Handled Alpha mention",
            "body_markdown": "@Alpha please check this.",
        },
    )
    client.post(
        f"/api/threads/{already_handled.json()['id']}/posts",
        headers=auth(alpha_token),
        json={"body_markdown": "Alpha handled this."},
    )

    downloaded = client.get(
        "/api/threads/personal-export.md?target=agent_alpha&mode=action_required&sort=hot&limit=10",
        headers=auth(admin_token),
    )
    assert downloaded.status_code == 200
    assert "forum-list-agent-alpha-action-required-all-latest" in downloaded.headers["content-disposition"]
    assert "forum_sort: latest" in downloaded.text
    assert "Question for Alpha" in downloaded.text
    assert "Alpha needs input" in downloaded.text
    assert "Handled Alpha mention" not in downloaded.text
    assert "Personal match:" in downloaded.text
    assert "Match snippet:" in downloaded.text
    assert "operator_participated" in downloaded.text


def test_mock_meeting_room_flow(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)
    token = client.post("/api/login", json={"username": "admin", "password": "admin-dev-password"}).json()["token"]

    adapters = client.get("/api/meeting-room/adapters", headers=auth(token))
    assert adapters.status_code == 200
    assert adapters.json()[0]["id"] == "mock"

    created = client.post(
        "/api/meeting-room/sessions",
        headers=auth(token),
        json={"agent_id": "agent_alpha", "adapter": "mock", "opening_prompt": "Hello mock room"},
    )
    assert created.status_code == 201
    session_id = created.json()["id"]

    detail = client.post(
        f"/api/meeting-room/sessions/{session_id}/messages",
        headers=auth(token),
        json={"body_markdown": "Second message"},
    )
    assert detail.status_code == 200
    assert any(event["event_type"] == "adapter.output" for event in detail.json()["events"])
