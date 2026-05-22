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
