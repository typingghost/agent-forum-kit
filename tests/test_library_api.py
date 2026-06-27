from __future__ import annotations

import importlib
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient


def build_client(tmp_path: Path, monkeypatch):
    library_root = tmp_path / "library"
    monkeypatch.setenv("FORUM_DB_PATH", str(tmp_path / "forum.db"))
    monkeypatch.setenv("FORUM_AUDIT_LOG_PATH", str(tmp_path / "audit_log.jsonl"))
    monkeypatch.setenv("FORUM_REVIEW_ROOT", str(tmp_path / "review"))
    monkeypatch.setenv("FORUM_UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENT_LIBRARY_ROOT", str(library_root))
    monkeypatch.setenv("FORUM_TEST_SEED_TOKENS", "1")

    import app.config
    import app.database
    import app.main
    import app.routes.forum
    import app.routes.library
    import app.services.audit
    import scripts.init_db

    importlib.reload(app.config)
    importlib.reload(app.database)
    importlib.reload(app.routes.forum)
    importlib.reload(app.routes.library)
    importlib.reload(app.services.audit)
    importlib.reload(app.main)
    importlib.reload(scripts.init_db)
    scripts.init_db.main()
    seed_library(library_root)
    return TestClient(app.main.app)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def seed_library(library_root: Path) -> None:
    now = time.time()

    project_dir = library_root / "projects" / "forum_kit"
    project_dir.mkdir(parents=True)
    (project_dir / "local_library_note.md").write_text(
        """---
title: Local library integration note
visible_to:
  - all_agents
---

# Local library integration note

needle-index is a unique keyword for search tests.
""",
        encoding="utf-8",
    )
    (project_dir / "sort_old.md").write_text("sorting keyword", encoding="utf-8")
    (project_dir / "sort_new.md").write_text("sorting keyword", encoding="utf-8")
    (project_dir / "token_note.md").write_text("hidden names are not exposed", encoding="utf-8")

    private_dir = library_root / "notes" / "private" / "agent-alpha"
    private_dir.mkdir(parents=True)
    (private_dir / "private_note.md").write_text(
        """---
title: Agent Alpha private note
visible_to:
  - persona:agent-alpha
---

private-alpha-signal should only be visible to Agent Alpha and admins.
""",
        encoding="utf-8",
    )

    inbox_alpha_dir = library_root / "inbox" / "cloud" / "agent_alpha"
    inbox_alpha_dir.mkdir(parents=True)
    (inbox_alpha_dir / "alpha_drop.md").write_text("recipient-inbox-signal alpha-only", encoding="utf-8")
    inbox_beta_dir = library_root / "inbox" / "cloud" / "agent_beta"
    inbox_beta_dir.mkdir(parents=True)
    (inbox_beta_dir / "beta_drop.md").write_text("recipient-inbox-signal beta-only", encoding="utf-8")

    old_mtime = now - (72 * 60 * 60)
    new_mtime = now - (60 * 60)
    os.utime(project_dir / "sort_old.md", (old_mtime, old_mtime))
    os.utime(project_dir / "sort_new.md", (new_mtime, new_mtime))
    os.utime(inbox_alpha_dir / "alpha_drop.md", (new_mtime, new_mtime))
    os.utime(inbox_beta_dir / "beta_drop.md", (new_mtime, new_mtime))


def test_library_status_search_and_file(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)

    status = client.get("/api/library/status", headers=auth("admin-dev-token"))
    assert status.status_code == 200
    assert status.json()["exists"] is True
    slugs = {scope["slug"] for scope in status.json()["scopes"]}
    assert {"inbox", "projects", "notes", "handoffs", "reports", "forum", "archive"}.issubset(slugs)

    searched = client.get(
        "/api/library/search",
        headers=auth("admin-dev-token"),
        params={"q": "needle-index", "scope": "projects"},
    )
    assert searched.status_code == 200
    body = searched.json()
    assert body["total"] == 1
    assert body["results"][0]["path"] == "projects/forum_kit/local_library_note.md"
    assert "needle-index" in body["results"][0]["excerpt"]

    fetched = client.get(
        "/api/library/file",
        headers=auth("admin-dev-token"),
        params={"path": "projects/forum_kit/local_library_note.md"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Local library integration note"
    assert "<h1>Local library integration note</h1>" in fetched.json()["body_html"]


def test_library_rejects_path_escape_and_denied_names(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)

    escaped = client.get(
        "/api/library/file",
        headers=auth("admin-dev-token"),
        params={"path": "../outside.md"},
    )
    assert escaped.status_code == 400

    hidden = client.get(
        "/api/library/search",
        headers=auth("admin-dev-token"),
        params={"q": "hidden", "scope": "projects"},
    )
    assert hidden.status_code == 200
    assert hidden.json()["total"] == 0


def test_library_private_visibility(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)

    beta_search = client.get(
        "/api/library/search",
        headers=auth("agent_beta-dev-token"),
        params={"q": "private-alpha-signal", "scope": "notes"},
    )
    assert beta_search.status_code == 200
    assert beta_search.json()["total"] == 0

    alpha_search = client.get(
        "/api/library/search",
        headers=auth("agent_alpha-dev-token"),
        params={"q": "private-alpha-signal", "scope": "notes"},
    )
    assert alpha_search.status_code == 200
    assert alpha_search.json()["total"] == 1


def test_library_sort_pagination_recent_and_subpath(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path, monkeypatch)

    newest = client.get(
        "/api/library/search",
        headers=auth("admin-dev-token"),
        params={"q": "sorting", "scope": "projects", "sort": "newest", "limit": 1},
    )
    assert newest.status_code == 200
    assert newest.json()["results"][0]["path"] == "projects/forum_kit/sort_new.md"
    assert newest.json()["has_more"] is True

    second_page = client.get(
        "/api/library/search",
        headers=auth("admin-dev-token"),
        params={"q": "sorting", "scope": "projects", "sort": "newest", "limit": 1, "offset": 1},
    )
    assert second_page.status_code == 200
    assert second_page.json()["results"][0]["path"] == "projects/forum_kit/sort_old.md"

    recent = client.get(
        "/api/library/recent",
        headers=auth("admin-dev-token"),
        params={"scope": "projects", "hours": 24},
    )
    assert recent.status_code == 200
    paths = {result["path"] for result in recent.json()["results"]}
    assert "projects/forum_kit/sort_new.md" in paths
    assert "projects/forum_kit/sort_old.md" not in paths

    children = client.get(
        "/api/library/children",
        headers=auth("admin-dev-token"),
        params={"scope": "inbox", "subpath": "cloud"},
    )
    assert children.status_code == 200
    assert {child["path"] for child in children.json()["children"]} == {"cloud/agent_alpha", "cloud/agent_beta"}

    alpha_only = client.get(
        "/api/library/search",
        headers=auth("admin-dev-token"),
        params={"q": "recipient-inbox-signal", "scope": "inbox", "subpath": "cloud/agent_alpha"},
    )
    assert alpha_only.status_code == 200
    assert alpha_only.json()["total"] == 1
    assert alpha_only.json()["results"][0]["path"] == "inbox/cloud/agent_alpha/alpha_drop.md"
