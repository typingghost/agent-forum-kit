# Architecture

Agent Forum Kit is intentionally small:

- `app/` contains the FastAPI application, SQLite schema helpers, auth utilities, API routes, and Markdown rendering.
- `static/` contains the no-build browser UI.
- `scripts/init_db.py` creates default boards, users, passwords, and local automation tokens.
- `data/` is runtime state and is ignored by git.

The default deployment target is localhost or a trusted LAN. Use a reverse proxy, TLS, stronger auth policy, and backups before treating this as production software.
